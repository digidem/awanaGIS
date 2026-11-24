"""Merged GISBR + curated Indigenous geospatial catalog, search, and read-only probing."""

from datetime import datetime, timezone
import json
import re
import threading
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .manifest import (
    CATALOG_VERSION,
    CURATED_INDIGENOUS_SOURCES,
    GISBR_PINNED_SHA,
    PUBLISHER_TYPE_MAP,
    normalize_gisbr_entry,
)
from .policy import (
    allowed_catalog_hosts,
    classify_external_service_error,
    external_db_descriptor,
    is_blocked_sensitive,
    is_discovery_only,
    is_portal_only,
    redact_sensitive_text,
    resolve_external_host,
    validate_allowlisted_url,
    validate_catalog_entry,
)
from .vendor.gisbr.core.sources import SOURCES as GISBR_RAW_SOURCES
from .vendor.gisbr.core.ssl_support import build_python_ssl_context

# Scale ranking mirrored from GISBR Recorte/diagnostico
_SCALE_RANK = {
    "municipality": 0,
    "municipio": 0,
    "microregion": 1,
    "metropolitan_region": 1,
    "rm": 1,
    "regional": 2,
    "mesoregion": 2,
    "state": 3,
    "uf": 3,
    "macroregion": 4,
    "macrorregiao": 4,
    "indigenous_territory": 2,
    "project_layer": 2,
}

# Bilingual PT-BR <-> EN search synonym groups
_SYNONYM_GROUPS = (
    {"terra indigena", "terras indigenas", "ti", "tis", "indigenous land", "indigenous lands", "indigenous territory", "indigenous territories", "funai"},
    {"dsei", "dseis", "sesai", "saude indigena", "indigenous health", "health district"},
    {"povos isolados", "isolated peoples", "isolamento voluntario", "voluntary isolation", "mapi", "coiab", "opi", "opan"},
    {"aldeia", "aldeias", "village", "villages", "localidade indigena", "localidades indigenas", "indigenous locality", "indigenous localities"},
    {"unidade de conservacao", "unidades de conservacao", "uc", "ucs", "conservation unit", "conservation units", "protected area", "protected areas", "icmbio"},
    {"mineracao", "processo minerario", "processos minerarios", "mining", "mining claim", "mining claims", "anm", "sigmine"},
    {"car", "sicar", "imovel rural", "imoveis rurais", "rural parcel", "rural parcels"},
    {"sigef", "incra", "parcelas certificadas", "certified parcels"},
    {"desmatamento", "deforestation", "prodes", "deter", "supressao", "alerta", "alertas", "inpe", "terrabrasilis"},
    {"cobertura", "uso da terra", "land cover", "land use", "mapbiomas"},
    {"hidrografia", "hydrography", "rio", "rios", "river", "rivers", "drenagem", "drainage", "bacia", "bacias", "watershed", "saneamento", "sanitation", "sgb", "ana"},
    {"rodovia", "rodovias", "estrada", "estradas", "highway", "highways", "road", "roads", "transporte", "transport", "dnit", "ferrovia", "ferrovias", "railway", "railways"},
    {"escola", "escolas", "school", "schools", "educacao", "education"},
    {"saude", "health", "hospital", "hospitais", "estabelecimento de saude", "health facility"},
    {"municipio", "municipios", "municipality", "municipalities", "malha municipal", "ibge"},
    {"isa", "instituto socioambiental"},
    {"raisg", "amazonia", "amazon", "pan-amazon"},
)

_PROBE_CACHE: Dict[str, Dict[str, Any]] = {}
_PROBE_LOCK = threading.Lock()
_PROBE_TTL_SECONDS = 300.0
_PROBE_FAILURE_TTL_SECONDS = 30.0


def _fold_text(text: Any) -> str:
    """Lowercase and strip accents/diacritics for resilient PT-BR/EN matching."""
    raw = str(text or "").lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_merged_catalog() -> List[Dict[str, Any]]:
    """Build and validate the merged GISBR + curated Indigenous source catalog."""
    merged: List[Dict[str, Any]] = []
    seen_ids = set()

    for raw in GISBR_RAW_SOURCES:
        entry = normalize_gisbr_entry(raw)
        validate_catalog_entry(entry)
        sid = entry["source_id"]
        if sid in seen_ids:
            raise ValueError(f"Duplicate source_id in GISBR catalog: {sid}")
        seen_ids.add(sid)
        merged.append(entry)

    for raw_ind in CURATED_INDIGENOUS_SOURCES:
        entry = dict(raw_ind)
        validate_catalog_entry(entry)
        sid = entry["source_id"]
        if sid in seen_ids:
            raise ValueError(f"Curated Indigenous ID collides with existing GISBR ID: {sid}")
        seen_ids.add(sid)
        merged.append(entry)

    return merged


_MERGED_CATALOG: List[Dict[str, Any]] = build_merged_catalog()
_BY_ID: Dict[str, Dict[str, Any]] = {e["source_id"]: e for e in _MERGED_CATALOG}
_ALIAS_TO_ID: Dict[str, str] = {}
for _entry in _MERGED_CATALOG:
    _ALIAS_TO_ID[_entry["source_id"]] = _entry["source_id"]
    for _alias in _entry.get("aliases") or []:
        _ALIAS_TO_ID[_alias] = _entry["source_id"]

_ALLOWED_HOSTS = allowed_catalog_hosts(_MERGED_CATALOG)


def get_catalog() -> List[Dict[str, Any]]:
    """Return a shallow copy of all merged catalog entries."""
    return list(_MERGED_CATALOG)


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    """Look up a source by canonical ID or documented alias."""
    if not source_id:
        return None
    canonical = _ALIAS_TO_ID.get(str(source_id).strip())
    return _BY_ID.get(canonical) if canonical else None


def get_allowed_hosts() -> set:
    """Return the reviewed allowlist of catalog service hostnames."""
    return set(_ALLOWED_HOSTS)


def _expand_query_terms(query: str) -> List[str]:
    folded = _fold_text(query)
    if not folded:
        return []
    tokens = [t for t in re.split(r"[\s,;/()\-]+", folded) if t]
    expanded = {folded}
    expanded.update(tokens)
    for group in _SYNONYM_GROUPS:
        if any(phrase == folded or phrase in folded or phrase in tokens for phrase in group):
            expanded.update(group)
    return sorted(expanded, key=len, reverse=True)


def _entry_search_blob(entry: Dict[str, Any]) -> str:
    parts = [
        entry.get("source_id", ""),
        entry.get("name", ""),
        entry.get("name_pt", ""),
        entry.get("axis", ""),
        entry.get("axis_pt", ""),
        entry.get("publisher", ""),
        entry.get("distributor", ""),
        entry.get("protocol", ""),
        entry.get("attribution", ""),
        " ".join(entry.get("keywords") or []),
        " ".join(entry.get("aliases") or []),
        " ".join(entry.get("uf_scope") or []),
    ]
    return _fold_text(" ".join(parts))


def _score_entry(entry: Dict[str, Any], folded_query: str, expanded_terms: List[str]) -> int:
    if not folded_query:
        return 1
    sid = _fold_text(entry["source_id"])
    name = _fold_text(entry["name"])
    name_pt = _fold_text(entry["name_pt"])
    blob = _entry_search_blob(entry)

    score = 0
    if folded_query == sid:
        score += 200
    elif folded_query in sid:
        score += 100
    if folded_query in name or folded_query in name_pt:
        score += 80

    # Require at least one query token or expanded synonym match
    tokens = [t for t in re.split(r"[\s,;/()\-]+", folded_query) if len(t) >= 2]
    matched_tokens = sum(1 for tok in tokens if tok in blob)
    matched_synonyms = sum(1 for term in expanded_terms if term in blob)

    if matched_tokens == 0 and matched_synonyms == 0:
        return 0

    score += matched_tokens * 25 + min(matched_synonyms, 6) * 10
    if entry.get("catalog_origin") == "curated_indigenous":
        score += 5
    if entry.get("loader_state") == "loadable":
        score += 3
    return score


def _public_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Format a source entry for ``br_search_sources`` output."""
    uf_scope = entry.get("uf_scope") or ["BR"]
    ext_host = resolve_external_host(entry)
    if entry.get("loader_state") in ("loadable", "pending_probe", "unavailable"):
        ext_notice = (
            f"External online database ({entry['publisher']} @ {ext_host}) — "
            "subject to upstream availability; may go offline intermittently."
        )
    else:
        ext_notice = (
            f"External reference ({entry['publisher']} @ {ext_host}, "
            f"policy={entry['load_policy']}) — no automated download."
        )
    return {
        "id": entry["source_id"],
        "source_id": entry["source_id"],
        "title": entry["name"],
        "name": entry["name"],
        "name_pt": entry["name_pt"],
        "theme": entry["axis"],
        "axis": entry["axis"],
        "publisher": entry["publisher"],
        "distributor": entry["distributor"],
        "publisher_type": entry["origin_class"],
        "origin_class": entry["origin_class"],
        "catalog_origin": entry["catalog_origin"],
        "protocol": entry["protocol"],
        "coverage": uf_scope,
        "uf_scope": uf_scope,
        "scope_limits": {"escala_max": entry.get("escala_max"), "ufs": uf_scope},
        "data_year": entry.get("source_year") if entry.get("source_year") is not None else "unknown",
        "source_year": entry.get("source_year"),
        "access": entry["load_policy"],
        "load_policy": entry["load_policy"],
        "status": entry["loader_state"],
        "loader_state": entry["loader_state"],
        "sensitivity": entry["sensitivity"],
        "terms_checked": entry.get("terms_checked", False),
        "machine_access_verified": entry.get("machine_access_verified", False),
        "license": entry.get("license", "unknown"),
        "attribution": entry.get("attribution", ""),
        "origin_url": entry.get("portal_url") or entry.get("service_url") or "",
        "portal_url": entry.get("portal_url") or "",
        "external_host": ext_host,
        "external_service_notice": ext_notice,
        "last_verified_at": entry.get("last_checked_at"),
        "last_checked_at": entry.get("last_checked_at"),
        "requires_parquet": entry.get("requires_parquet", False),
        "verification_evidence": entry.get("verification_evidence", ""),
    }


def search_sources(
    *,
    query: Optional[str] = None,
    theme: Optional[str] = None,
    uf: Optional[str] = None,
    publisher_type: Optional[str] = None,
    scope_type: Optional[str] = None,
    loadable_only: Optional[bool] = None,
    sensitivity: Optional[str] = None,
    limit: int = 25,
) -> Dict[str, Any]:
    """Search the merged GISBR + curated Indigenous catalog offline."""
    folded_q = _fold_text(query or "")
    expanded = _expand_query_terms(query or "")
    folded_theme = _fold_text(theme or "")
    uf_norm = str(uf or "").strip().upper()
    raw_pub = str(publisher_type or "").strip().lower()
    if raw_pub in ("", "any"):
        pub_filter = None
    elif raw_pub in PUBLISHER_TYPE_MAP:
        pub_filter = PUBLISHER_TYPE_MAP[raw_pub]
    elif raw_pub in ("official_direct", "official_mirror", "non_government"):
        pub_filter = raw_pub
    else:
        return {
            "ok": False,
            "error": f"Invalid publisher_type '{publisher_type}'. Expected official, official_mirror, non_government, or any.",
            "sources": [],
            "count": 0,
            "total_matched": 0,
            "catalog_version": CATALOG_VERSION,
            "gisbr_pinned_sha": GISBR_PINNED_SHA,
        }
    scope_rank = _SCALE_RANK.get(_fold_text(scope_type or "")) if scope_type else None
    sens_filter = str(sensitivity or "").strip().lower()

    try:
        max_results = max(1, min(int(limit or 25), 100))
    except (TypeError, ValueError):
        max_results = 25

    scored: List[tuple] = []
    for entry in _MERGED_CATALOG:
        if pub_filter and entry["origin_class"] != pub_filter:
            continue
        if uf_norm:
            scope = [s.upper() for s in (entry.get("uf_scope") or ["BR"])]
            if "BR" not in scope and uf_norm not in scope:
                continue
        if folded_theme:
            axis_blob = _fold_text(f"{entry.get('axis', '')} {entry.get('axis_pt', '')}")
            if folded_theme not in axis_blob:
                continue
        if scope_rank is not None:
            src_rank = _SCALE_RANK.get(_fold_text(entry.get("escala_max") or "regional"), 2)
            if scope_rank > src_rank:
                continue
        if loadable_only:
            if entry["loader_state"] not in ("loadable", "pending_probe"):
                continue
            if is_blocked_sensitive(entry) or is_discovery_only(entry) or is_portal_only(entry):
                continue
        if sens_filter and entry["sensitivity"].lower() != sens_filter:
            continue

        score = _score_entry(entry, folded_q, expanded)
        if score <= 0:
            continue
        scored.append((score, entry["source_id"], entry))

    scored.sort(key=lambda item: (-item[0], item[1]))
    results = [_public_summary(item[2]) for item in scored[:max_results]]
    return {
        "ok": True,
        "sources": results,
        "count": len(results),
        "total_matched": len(scored),
        "catalog_version": CATALOG_VERSION,
        "gisbr_pinned_sha": GISBR_PINNED_SHA,
    }


def _probe_endpoint(entry: Dict[str, Any], *, timeout: float = 8.0) -> Dict[str, Any]:
    """Perform a bounded, read-only capability/health probe on an allowlisted endpoint."""
    sid = entry["source_id"]
    now_iso = _utc_now_iso()

    if is_blocked_sensitive(entry):
        return {
            "status": "blocked_sensitive",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": "Probing blocked_sensitive isolated-peoples sources is prohibited.",
        }
    if is_discovery_only(entry):
        return {
            "status": "discovery_only",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": "Source is discovery_only; record endpoints are not probed.",
        }
    if is_portal_only(entry):
        return {
            "status": "portal_only",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": "Portal-only source; web scraping/probing is not performed.",
        }
    if entry["loader_state"] == "manual_required":
        return {
            "status": "requires_manual",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": f"Manual authenticated download required ({entry.get('requires_login') or 'portal login'}).",
        }
    if entry["loader_state"] == "unavailable":
        return {
            "status": "unavailable",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": entry.get("unavailable_reason") or "Marked unavailable in pinned catalog.",
        }

    # Check short-lived cache (shorter TTL for offline failures so recoveries surface quickly)
    with _PROBE_LOCK:
        cached = _PROBE_CACHE.get(sid)
        if cached:
            ttl = _PROBE_TTL_SECONDS if cached.get("machine_access_verified") else _PROBE_FAILURE_TTL_SECONDS
            if (datetime.now(timezone.utc).timestamp() - cached["_ts"]) < ttl:
                return {k: v for k, v in cached.items() if k != "_ts"}

    proto = entry.get("protocol", "")
    base_url = (entry.get("service_url") or "").strip()
    if proto == "raster_cog" and "{ano}" in base_url:
        ano = entry.get("source_year") or 2023
        base_url = base_url.format(ano=ano)

    if not base_url:
        return {
            "status": "unsupported",
            "service_status": "unsupported",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": "No direct machine service URL configured for this source.",
            "external_db": external_db_descriptor(entry, status="unsupported", reason="No direct URL configured."),
        }

    ok_url, url_err = validate_allowlisted_url(base_url, _ALLOWED_HOSTS)
    if not ok_url:
        return {
            "status": "unsupported",
            "service_status": "unsupported",
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": url_err,
            "external_db": external_db_descriptor(entry, status="unsupported", reason=url_err),
        }

    probe_url = base_url
    method = "GET"
    if proto == "wfs":
        sep = "&" if "?" in base_url else "?"
        probe_url = f"{base_url}{sep}service=WFS&version=2.0.0&request=GetCapabilities"
    elif proto == "arcgis":
        layer_id = entry.get("typename") or "0"
        probe_url = f"{base_url.rstrip('/')}/{layer_id}?f=json"
    elif proto in ("zip_remoto", "raster_cog", "geobr"):
        method = "HEAD"

    result: Dict[str, Any]
    ssl_ctx = build_python_ssl_context()
    try:
        req = urllib.request.Request(
            probe_url,
            method=method,
            headers={"User-Agent": "AwanaGIS-Probe/0.1 (read-only metadata check)"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:  # strict TLS with bundled intermediates
            status_code = getattr(resp, "status", 200)
            read_limit = (8 * 1024 * 1024) if proto == "wfs" else 65536
            snippet = resp.read(read_limit).decode("utf-8", errors="replace") if method == "GET" else ""
            if proto == "wfs":
                parsed_root = None
                if "<!ENTITY" not in snippet.upper():
                    try:
                        parsed_root = ET.fromstring(snippet)
                    except ET.ParseError:
                        parsed_root = None
                root_local = parsed_root.tag.rsplit("}", 1)[-1] if parsed_root is not None else ""
                ft_lists = (
                    [el for el in list(parsed_root) if el.tag.rsplit("}", 1)[-1] == "FeatureTypeList"]
                    if root_local == "WFS_Capabilities"
                    else []
                )
                if root_local == "WFS_Capabilities" and ft_lists:
                    typename = (entry.get("typename") or "").strip()
                    ft_names = set()
                    for ft_list in ft_lists:
                        for ft_node in list(ft_list):
                            if ft_node.tag.rsplit("}", 1)[-1] == "FeatureType":
                                for child in list(ft_node):
                                    if child.tag.rsplit("}", 1)[-1] == "Name" and (child.text or "").strip():
                                        ft_names.add(child.text.strip())
                    layer_found = bool(ft_names) and ((not typename) or (typename in ft_names))
                    svc_status = "reachable" if layer_found else "offline_http_error"
                    reason_txt = (
                        "WFS GetCapabilities reachable and typename present."
                        if layer_found
                        else f"WFS GetCapabilities reachable, but typename '{typename}' not found."
                    )
                    result = {
                        "status": "reachable" if layer_found else "unavailable",
                        "service_status": svc_status,
                        "checked_at": now_iso,
                        "machine_access_verified": bool(layer_found),
                        "http_status": status_code,
                        "typename_verified": layer_found,
                        "reason": reason_txt,
                    }
                else:
                    result = {
                        "status": "unavailable",
                        "service_status": "offline_http_error",
                        "checked_at": now_iso,
                        "machine_access_verified": False,
                        "http_status": status_code,
                        "typename_verified": False,
                        "reason": "WFS GetCapabilities endpoint returned non-capabilities HTML/error response.",
                    }
            elif proto == "arcgis":
                try:
                    meta = json.loads(snippet)
                    if isinstance(meta, dict) and "error" in meta:
                        reason_txt = redact_sensitive_text(str(meta["error"])[:240])
                        result = {
                            "status": "unavailable",
                            "service_status": "offline_http_error",
                            "checked_at": now_iso,
                            "machine_access_verified": False,
                            "http_status": status_code,
                            "reason": reason_txt,
                        }
                    else:
                        result = {
                            "status": "reachable",
                            "service_status": "reachable",
                            "checked_at": now_iso,
                            "machine_access_verified": True,
                            "http_status": status_code,
                            "max_record_count": meta.get("maxRecordCount") if isinstance(meta, dict) else None,
                            "reason": "ArcGIS REST layer metadata reachable.",
                        }
                except ValueError:
                    result = {
                        "status": "unavailable",
                        "service_status": "offline_http_error",
                        "checked_at": now_iso,
                        "machine_access_verified": False,
                        "http_status": status_code,
                        "reason": "ArcGIS REST metadata returned non-JSON response.",
                    }
            else:
                ok_http = 200 <= status_code < 400
                result = {
                    "status": "reachable" if ok_http else "unavailable",
                    "service_status": "reachable" if ok_http else "offline_http_error",
                    "checked_at": now_iso,
                    "machine_access_verified": ok_http,
                    "http_status": status_code,
                    "reason": f"Endpoint responded HTTP {status_code}.",
                }
    except urllib.error.HTTPError as exc:
        raw_err = f"HTTP {exc.code}: {exc.reason}"
        svc_code, svc_reason = classify_external_service_error(raw_err)
        result = {
            "status": "unavailable",
            "service_status": svc_code,
            "checked_at": now_iso,
            "machine_access_verified": False,
            "http_status": exc.code,
            "reason": redact_sensitive_text(f"Probe failed ({svc_reason}): {raw_err}"),
        }
    except urllib.error.URLError as exc:
        raw_err = str(exc.reason)
        svc_code, svc_reason = classify_external_service_error(raw_err)
        result = {
            "status": "unavailable",
            "service_status": svc_code,
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": redact_sensitive_text(f"Probe failed ({svc_reason}): {raw_err}"),
        }
    except Exception as exc:
        raw_err = f"{type(exc).__name__}: {exc}"
        svc_code, svc_reason = classify_external_service_error(raw_err)
        result = {
            "status": "unavailable",
            "service_status": svc_code,
            "checked_at": now_iso,
            "machine_access_verified": False,
            "reason": redact_sensitive_text(f"Probe failed ({svc_reason}): {raw_err}"),
        }

    ext_desc = external_db_descriptor(entry, status=result["service_status"], reason=result["reason"])
    result["external_db"] = ext_desc
    result["user_signal"] = ext_desc["user_signal"]

    with _PROBE_LOCK:
        _PROBE_CACHE[sid] = {**result, "_ts": datetime.now(timezone.utc).timestamp()}
    return result


def source_details(source_ids: List[str], *, probe: bool = False) -> Dict[str, Any]:
    """Return detailed provenance, policy, caveats, and optional read-only probe results."""
    if not isinstance(source_ids, list) or not source_ids:
        return {"ok": False, "error": "source_ids must be a non-empty list of source IDs."}

    bounded_ids = [str(s).strip() for s in source_ids[:25] if str(s).strip()]
    details: List[Dict[str, Any]] = []
    unknown_ids: List[str] = []

    for sid in bounded_ids:
        entry = get_source(sid)
        if entry is None:
            unknown_ids.append(sid)
            continue

        item = _public_summary(entry)
        item.update(
            {
                "requested_id": sid,
                "documentation_verified": True,
                "terms_checked": entry.get("terms_checked", False),
                "machine_access_verified": entry.get("machine_access_verified", False),
                "service_url": "" if is_blocked_sensitive(entry) else entry.get("service_url", ""),
                "typename": entry.get("typename", ""),
                "srs": entry.get("srs", "EPSG:4674"),
                "available_years": entry.get("available_years"),
                "requires_login": entry.get("requires_login"),
                "unavailable_reason": entry.get("unavailable_reason"),
                "caveats": _caveats_for_entry(entry),
            }
        )

        if probe:
            probe_res = _probe_endpoint(entry)
            item["probe"] = probe_res
            item["status"] = probe_res["status"]
            item["service_status"] = probe_res.get("service_status", probe_res["status"])
            item["last_verified_at"] = probe_res["checked_at"]
            item["machine_access_verified"] = probe_res.get("machine_access_verified", False)
            ext_desc = probe_res.get("external_db") or external_db_descriptor(
                entry, status=item["service_status"], reason=probe_res.get("reason", "")
            )
            item["external_db"] = ext_desc
            item["user_signal"] = ext_desc["user_signal"]
        else:
            item["status"] = (
                "blocked_sensitive"
                if is_blocked_sensitive(entry)
                else (
                    "discovery_only"
                    if is_discovery_only(entry)
                    else (
                        "portal_only"
                        if is_portal_only(entry)
                        else (
                            "requires_manual"
                            if entry["loader_state"] == "manual_required"
                            else (
                                "unavailable"
                                if entry["loader_state"] == "unavailable"
                                else ("reachable" if entry.get("machine_access_verified") else "unverified")
                            )
                        )
                    )
                )
            )
            ext_desc = external_db_descriptor(entry, status=item["status"])
            item["service_status"] = item["status"]
            item["external_db"] = ext_desc
            item["user_signal"] = ext_desc["user_signal"]
        details.append(item)

    signals = [d["external_db"] for d in details if d.get("external_db")]
    return {
        "ok": len(details) > 0 and len(unknown_ids) == 0,
        "sources": details,
        "unknown_source_ids": unknown_ids,
        "probed": bool(probe),
        "external_db_signals": signals,
        "user_notice": "; ".join(s["user_signal"] for s in signals),
        "catalog_version": CATALOG_VERSION,
        "error": f"Unknown source IDs: {', '.join(unknown_ids)}" if unknown_ids else None,
    }


def _caveats_for_entry(entry: Dict[str, Any]) -> List[str]:
    caveats: List[str] = []
    sid = entry["source_id"]
    if entry.get("origin_class") == "official_mirror":
        caveats.append("Official-origin geometry redistributed via IPEA/geobr mirror; verify vintage against primary agency.")
    if entry.get("origin_class") == "non_government":
        caveats.append("Non-government publisher; requires explicit opt-in and attribution/license review.")
    if sid == "funai_dsei_areas":
        caveats.append("DSEI polygons represent SESAI/FUNAI operational health service districts, NOT TI legal demarcation boundaries.")
    if sid == "mapbiomas_cobertura":
        caveats.append("Annual historical land-cover/use raster (1985-2023); NOT a real-time deforestation alert feed.")
    if sid == "inpe_prodes":
        caveats.append("Annual deforestation suppression methodology by biome; distinct from DETER monitoring alerts.")
    if sid == "inpe_deter":
        caveats.append("Indicative monitoring alerts; spatial overlap alone is NOT proof of illegality.")
    if sid == "raisg_indigenous_territories":
        caveats.append("WMS is display-only, not an editable vector layer; per-theme citations apply.")
    if sid == "ibge_indigenous_localities_2022":
        caveats.append("IBGE published revised/replaced 2022 files; exact locality points are discovery_only in v1.")
    if is_blocked_sensitive(entry):
        caveats.append("Blocked sensitive dataset: exact isolated-peoples coordinates/sightings cannot be queried, loaded, or exported.")
    if entry.get("requires_parquet"):
        caveats.append("geobr v2 dataset: requires GDAL Parquet driver or optional pyarrow package.")
    return caveats
