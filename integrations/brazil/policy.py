"""Hard-enforced safety, Indigenous data governance, URL allowlist, and provenance tagging.

Security and governance boundaries are enforced in Python across discovery,
details/probing, planning, execution, and layer provenance tagging — never
delegated to LLM prompt instructions.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple
from urllib.parse import urlparse

from .manifest import LOADER_STATES, LOAD_POLICIES, ORIGIN_CLASSES, SENSITIVITY_LEVELS

# Custom QGIS layer property keys (checked by downstream tools and SMP export)
PROP_SENSITIVITY = "awanagis/sensitivity"
PROP_EXPORT_POLICY = "awanagis/export_policy"
PROP_PROVENANCE_JSON = "awanagis/provenance_json"

# Hard-blocked IDs that can NEVER be planned, probed for records, or auto-loaded
BLOCKED_SENSITIVE_IDS: Set[str] = {
    "mapi_isolated_peoples",
    "mapi_povos_isolados",
}

# Discovery-only exact-point datasets blocked from automatic ingestion in v1
DISCOVERY_ONLY_IDS: Set[str] = {
    "ibge_indigenous_localities_2022",
    "funai_indigenous_villages",
    "funai_villages",
    "funai_ti_studies",
}

NON_EXECUTABLE_LOADER_STATES: Set[str] = {
    "blocked_sensitive",
    "discovery_only",
    "portal_only",
    "unavailable",
}

NON_EXECUTABLE_POLICIES: Set[str] = {
    "blocked_sensitive",
    "discovery_only",
}

_ALLOWED_SCHEMES: Set[str] = {"https", "http"}

# Redaction patterns for error messages, traces, and tool responses
_SECRET_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|api[_-]?key|secret|authorization|bearer)"
    r"\s*([:=]\s*|\s+)([^\s,;\"'&]+)"
)
_URL_CREDS_RE = re.compile(r"(https?://)([^/@:\s]+):([^/@\s]+)@")
_COORD_PAIR_RE = re.compile(
    r"(-?\d{1,3}\.\d{3,})\s*[,\s]\s*(-?\d{1,3}\.\d{3,})"
)


def is_blocked_sensitive(source: Dict[str, Any]) -> bool:
    """Return True if the source represents blocked isolated-peoples data."""
    sid = str(source.get("source_id") or source.get("id") or "")
    return (
        sid in BLOCKED_SENSITIVE_IDS
        or source.get("loader_state") == "blocked_sensitive"
        or source.get("load_policy") == "blocked_sensitive"
        or source.get("sensitivity") == "blocked_isolated_peoples"
    )


def is_discovery_only(source: Dict[str, Any]) -> bool:
    """Return True if the source is restricted to discovery-only metadata."""
    sid = str(source.get("source_id") or source.get("id") or "")
    return (
        sid in DISCOVERY_ONLY_IDS
        or source.get("loader_state") == "discovery_only"
        or source.get("load_policy") == "discovery_only"
    )


def is_portal_only(source: Dict[str, Any]) -> bool:
    """Return True if the source is portal-only (no automated scraping/ingest)."""
    return (
        source.get("loader_state") == "portal_only"
        or source.get("protocol") == "portal_only"
    )


def check_source_loadable(
    source: Dict[str, Any],
    *,
    include_non_government: bool = False,
) -> Tuple[bool, str, str]:
    """Evaluate whether ``source`` may be planned/executed for QGIS loading.

    Returns ``(allowed, status_code, reason)``.
    """
    if not isinstance(source, dict):
        return False, "invalid_source", "Invalid source entry."

    sid = str(source.get("source_id") or source.get("id") or "unknown")
    loader_state = source.get("loader_state", "")
    load_policy = source.get("load_policy", "")
    origin_class = source.get("origin_class", "")

    if is_blocked_sensitive(source):
        return (
            False,
            "blocked_sensitive",
            (
                f"Source '{sid}' is blocked_sensitive: exact isolated-peoples "
                "presence, routes, or sighting coordinates cannot be ingested, "
                "probed, or exported. Only public institutional metadata is available."
            ),
        )

    if is_discovery_only(source):
        return (
            False,
            "discovery_only",
            (
                f"Source '{sid}' is discovery_only in v1: exact village/locality "
                "point features are not auto-loaded without proven end-to-end "
                "egress protection across all agent tools."
            ),
        )

    if is_portal_only(source):
        portal = source.get("portal_url") or ""
        return (
            False,
            "portal_only",
            (
                f"Source '{sid}' is portal_only (no automated scraping/ingest). "
                f"Consult official/civil-society portal directly: {portal}"
            ).strip(),
        )

    if loader_state == "unavailable" or source.get("unavailable_reason"):
        reason = source.get("unavailable_reason") or "upstream service marked unavailable"
        return False, "unavailable", f"Source '{sid}' is unavailable: {reason}"

    if loader_state == "manual_required" or source.get("protocol") == "arquivo":
        return (
            False,
            "manual_required",
            (
                f"Source '{sid}' requires manual authenticated download "
                f"({source.get('requires_login') or 'portal login'}) from "
                f"{source.get('portal_url') or 'official portal'}."
            ),
        )

    if origin_class == "non_government" and not include_non_government:
        return (
            False,
            "requires_non_government_opt_in",
            (
                f"Source '{sid}' is a non-government source ({source.get('publisher')}). "
                "Set include_non_government=true after reviewing license and attribution."
            ),
        )

    if load_policy in NON_EXECUTABLE_POLICIES:
        return False, load_policy, f"Source '{sid}' blocked by load_policy={load_policy}."

    if load_policy == "requires_terms_check" and not source.get("terms_checked"):
        return False, "requires_terms_check", f"Source '{sid}' requires terms and attribution check before loading."

    if loader_state not in ("loadable", "pending_probe"):
        return False, loader_state or "unsupported", f"Source '{sid}' cannot be loaded (state={loader_state})."

    return True, "ready", ""


def validate_catalog_entry(entry: Dict[str, Any]) -> None:
    """Validate normalized catalog metadata enums and required keys."""
    required = (
        "source_id",
        "name",
        "name_pt",
        "axis",
        "origin_class",
        "loader_state",
        "load_policy",
        "sensitivity",
        "publisher",
        "protocol",
        "uf_scope",
    )
    for key in required:
        if key not in entry or entry[key] in (None, ""):
            raise ValueError(f"Catalog entry missing required field {key!r}: {entry.get('source_id')}")
    if entry["origin_class"] not in ORIGIN_CLASSES:
        raise ValueError(f"Invalid origin_class {entry['origin_class']!r} for {entry['source_id']}")
    if entry["loader_state"] not in LOADER_STATES:
        raise ValueError(f"Invalid loader_state {entry['loader_state']!r} for {entry['source_id']}")
    if entry["load_policy"] not in LOAD_POLICIES:
        raise ValueError(f"Invalid load_policy {entry['load_policy']!r} for {entry['source_id']}")
    if entry["sensitivity"] not in SENSITIVITY_LEVELS:
        raise ValueError(f"Invalid sensitivity {entry['sensitivity']!r} for {entry['source_id']}")


def allowed_catalog_hosts(catalog_entries: Iterable[Dict[str, Any]]) -> Set[str]:
    """Return lowercase hostnames reviewed in the merged catalog."""
    hosts: Set[str] = set()
    for entry in catalog_entries:
        if is_blocked_sensitive(entry) or is_portal_only(entry) or is_discovery_only(entry):
            continue
        for key in ("service_url",):
            raw = entry.get(key) or ""
            if not raw:
                continue
            parsed = urlparse(raw)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    # IPEA/GitHub geobr mirrors used internally by vendored GISBR algorithms
    hosts.update({"www.ipea.gov.br", "ipea.gov.br", "github.com", "raw.githubusercontent.com", "objects.githubusercontent.com"})
    # IBGE localidades API for area disambiguation
    hosts.add("servicodados.ibge.gov.br")
    return hosts


def validate_allowlisted_url(
    url: str,
    allowed_hosts: Set[str],
    *,
    require_https: bool = False,
) -> Tuple[bool, str]:
    """Validate that ``url`` uses a safe HTTP(S) scheme and an allowlisted host."""
    if not url or not isinstance(url, str):
        return False, "Empty or non-string URL rejected."
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False, f"Disallowed URL scheme '{scheme}'; only HTTPS/HTTP allowlisted endpoints are permitted."
    if require_https and scheme != "https":
        return False, "Only HTTPS URLs are permitted for this endpoint."
    if parsed.username or parsed.password:
        return False, "Embedded credentials in URL are prohibited."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL missing hostname."
    if host not in allowed_hosts:
        return False, f"Host '{host}' is not in the reviewed catalog allowlist."
    return True, ""


def validate_safe_output_path(path_str: str, *, allowed_extensions: Tuple[str, ...] = (".gpkg", ".tif", ".tiff")) -> Tuple[bool, str, Optional[Path]]:
    """Validate an output file path against path traversal and unexpected extensions."""
    if not path_str or not isinstance(path_str, str):
        return False, "Output path must be a non-empty string.", None
    if "\x00" in path_str:
        return False, "Null byte in output path.", None
    raw_parts = Path(path_str).parts
    if ".." in raw_parts:
        return False, "Path traversal ('..') is not permitted in output path.", None
    resolved = Path(path_str).expanduser().resolve()
    if allowed_extensions and resolved.suffix.lower() not in allowed_extensions:
        return (
            False,
            f"Unsupported output extension '{resolved.suffix}'; expected one of {allowed_extensions}.",
            None,
        )
    return True, "", resolved


def validate_archive_member_path(member_name: str, dest_dir: Path) -> Tuple[bool, Optional[Path]]:
    """Reject zip-slip / absolute / traversal archive member paths."""
    if not member_name or "\x00" in member_name:
        return False, None
    member_path = Path(member_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        return False, None
    dest_root = dest_dir.resolve()
    target = (dest_root / member_path).resolve()
    try:
        target.relative_to(dest_root)
    except ValueError:
        return False, None
    return True, target


def sanitize_cql_literal(value: Any) -> str:
    """Safely escape a textual value for CQL / ArcGIS ``where`` string literals."""
    text = str(value if value is not None else "")
    # Reject control characters / statement terminators
    text = re.sub(r"[\x00-\x1f\x7f;]", "", text)
    return text.replace("'", "''")


def validate_cql_identifier(field_name: str) -> str:
    """Ensure a CQL/SQL field name contains only safe identifier characters."""
    if not isinstance(field_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field_name):
        raise ValueError(f"Unsafe CQL field identifier: {field_name!r}")
    return field_name


def redact_sensitive_text(text: Any, *, redact_coordinates: bool = False) -> str:
    """Redact credentials, URL userinfo, and optionally coordinate pairs from text."""
    s = str(text or "")
    s = _URL_CREDS_RE.sub(r"\1[REDACTED]:[REDACTED]@", s)
    s = _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", s)
    if redact_coordinates:
        s = _COORD_PAIR_RE.sub("[REDACTED_COORDS]", s)
    return s


def export_policy_for_source(source: Dict[str, Any]) -> str:
    """Determine ``awanagis/export_policy`` tag for a loaded layer."""
    sensitivity = source.get("sensitivity", "public")
    if sensitivity in ("blocked_isolated_peoples", "restricted_locality_point"):
        return "restricted_no_export"
    if source.get("origin_class") == "non_government" or sensitivity == "territory_boundary":
        return "allow_with_attribution"
    return "allow_export"


def build_provenance_record(
    source: Dict[str, Any],
    area: Dict[str, Any],
    *,
    clip_mode: str,
    extracted_at: str,
    output_path: str,
    source_crs: str = "unknown",
    output_crs: str = "unknown",
    feature_count: Optional[int] = None,
    truncated: bool = False,
    catalog_version: str = "",
    data_reference_year: Any = None,
) -> Dict[str, Any]:
    """Build a JSON-serializable provenance dictionary for layer metadata."""
    ref_year = (
        data_reference_year
        if data_reference_year is not None
        else (source.get("source_year") if source.get("source_year") is not None else "unknown")
    )
    return {
        "source_id": source.get("source_id"),
        "title": source.get("name"),
        "title_pt": source.get("name_pt"),
        "publisher": source.get("publisher"),
        "distributor": source.get("distributor"),
        "origin_class": source.get("origin_class"),
        "origin_url": source.get("service_url") or source.get("portal_url") or "",
        "portal_url": source.get("portal_url") or "",
        "catalog_origin": source.get("catalog_origin"),
        "catalog_version": catalog_version,
        "data_reference_year": ref_year,
        "extracted_at": extracted_at,
        "area_scope": {
            "type": area.get("type"),
            "id": area.get("id"),
            "name": area.get("name"),
            "ufs": area.get("ufs"),
        },
        "clip_mode": clip_mode,
        "source_crs": source_crs,
        "output_crs": output_crs,
        "feature_count": feature_count,
        "truncated": bool(truncated),
        "license": source.get("license") or "unknown",
        "attribution": source.get("attribution") or "",
        "sensitivity": source.get("sensitivity", "public"),
        "export_policy": export_policy_for_source(source),
        "output_path": output_path,
    }


def tag_layer_provenance(
    layer: Any,
    source: Dict[str, Any],
    area: Dict[str, Any],
    *,
    clip_mode: str,
    extracted_at: str,
    output_path: str,
    feature_count: Optional[int] = None,
    truncated: bool = False,
    catalog_version: str = "",
    data_reference_year: Any = None,
) -> Dict[str, Any]:
    """Attach AwanaGIS sensitivity, export policy, and provenance custom properties to ``layer``."""
    source_crs = source.get("srs") or "unknown"
    output_crs = "unknown"
    try:
        if layer is not None and layer.crs().isValid():
            output_crs = layer.crs().authid()
    except Exception:
        pass

    provenance = build_provenance_record(
        source,
        area,
        clip_mode=clip_mode,
        extracted_at=extracted_at,
        output_path=output_path,
        source_crs=source_crs,
        output_crs=output_crs,
        feature_count=feature_count,
        truncated=truncated,
        catalog_version=catalog_version,
        data_reference_year=data_reference_year,
    )
    if layer is not None and hasattr(layer, "setCustomProperty"):
        layer.setCustomProperty(PROP_SENSITIVITY, provenance["sensitivity"])
        layer.setCustomProperty(PROP_EXPORT_POLICY, provenance["export_policy"])
        layer.setCustomProperty(PROP_PROVENANCE_JSON, json.dumps(provenance, ensure_ascii=False))
        # GISBR-compatible properties
        layer.setCustomProperty("data_extracao", extracted_at[:10])
        layer.setCustomProperty("fonte", str(source.get("publisher") or source.get("source_id")))
    return provenance


def check_layer_export_allowed(layer: Any) -> Tuple[bool, str]:
    """Check whether a QGIS layer is eligible for export based on its AwanaGIS tags."""
    if layer is None or not hasattr(layer, "customProperty"):
        return True, ""
    sensitivity = str(layer.customProperty(PROP_SENSITIVITY) or "")
    export_policy = str(layer.customProperty(PROP_EXPORT_POLICY) or "")
    if sensitivity in ("blocked_isolated_peoples", "restricted_locality_point") or export_policy == "restricted_no_export":
        return False, "Layer is tagged with restricted Indigenous sensitivity and cannot be exported."
    return True, ""


_PROTOCOL_DEFAULT_HOSTS: Dict[str, str] = {
    "geobr": "www.ipea.gov.br",
    "ibge_tabular": "servicodados.ibge.gov.br",
    "osm": "overpass-api.de",
}


def resolve_external_host(source: Dict[str, Any]) -> str:
    """Return the primary hostname for an external Brazilian geospatial source."""
    for key in ("service_url", "portal_url"):
        raw = (source.get(key) or "").strip()
        if raw:
            host = (urlparse(raw).hostname or "").strip().lower()
            if host:
                return host
    proto = str(source.get("protocol") or "").strip().lower()
    return _PROTOCOL_DEFAULT_HOSTS.get(proto, "external")


def classify_external_service_error(error_text: Any) -> Tuple[str, str]:
    """Classify an external DB failure into a machine code and human explanation."""
    cleaned = redact_sensitive_text(error_text or "", redact_coordinates=True)
    low = cleaned.lower()
    if "timeout" in low or "timed out" in low:
        return "offline_timeout", "External database timed out and may be temporarily offline."
    if any(tok in low for tok in ("ssl", "tls", "certificate", "handshake")):
        return "offline_tls", "External database TLS/certificate verification failed."
    if any(
        tok in low
        for tok in (
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "no route to host",
            "getaddrinfo",
        )
    ):
        return "offline_dns_or_network", "External database host is unreachable (DNS or network failure)."
    if any(
        tok in low
        for tok in (
            "http 5",
            "http error 5",
            "502",
            "503",
            "504",
            "500",
            "404",
            "serviceexception",
            "pagina de erro html",
            "excecao wfs",
            "erro no servico",
        )
    ):
        return "offline_http_error", "External database returned an upstream server/service error."
    return "offline_unavailable", "External database is currently offline or returned an invalid response."


def external_db_descriptor(
    source: Dict[str, Any],
    *,
    status: str,
    reason: str = "",
) -> Dict[str, Any]:
    """Build a structured external-database status record for explicit user signaling."""
    sid = str(source.get("source_id") or source.get("id") or "unknown")
    publisher = str(source.get("publisher") or source.get("distributor") or sid)
    distributor = str(source.get("distributor") or publisher)
    host = resolve_external_host(source)
    proto = str(source.get("protocol") or "")
    origin_class = str(source.get("origin_class") or "")
    norm_status = str(status or "unknown")
    is_offline = norm_status.startswith("offline_") or norm_status == "unavailable"
    fallback = "geobr_terras_indigenas" if (sid == "funai_ti_boundaries" and is_offline) else None
    safe_reason = redact_sensitive_text(reason, redact_coordinates=True).strip()

    if is_offline:
        signal = f"External DB OFFLINE ({publisher} @ {host}, status={norm_status})"
        if fallback:
            signal += f" — fallback available: {fallback}"
        if safe_reason:
            signal += f": {safe_reason}"
    elif norm_status in ("online", "reachable"):
        signal = f"External DB ONLINE ({publisher} @ {host})"
    elif norm_status == "planned_external":
        signal = f"Will contact external DB {publisher} ({host}) — subject to upstream availability"
    else:
        signal = f"External DB [{norm_status}] ({publisher} @ {host})"

    return {
        "source_id": sid,
        "publisher": publisher,
        "distributor": distributor,
        "host": host,
        "protocol": proto,
        "origin_class": origin_class,
        "status": norm_status,
        "is_offline": is_offline,
        "fallback_source_id": fallback,
        "user_signal": signal,
    }
