"""Deterministic, read-only load planner for AwanaGIS Brazilian data tools."""

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .catalog import get_source
from .manifest import CATALOG_VERSION
from .policy import (
    check_source_loadable,
    external_db_descriptor,
    is_blocked_sensitive,
    is_discovery_only,
    is_portal_only,
    validate_safe_output_path,
)
from .vendor.gisbr.core import capabilities, catalog as gisbr_catalog
from .vendor.gisbr.core import constants as gisbr_constants


def _mask_provider_hosts() -> set:
    """Hosts the loader may contact to fetch a municipality/area mask (IPEA geobr + GitHub mirrors)."""
    urls = [
        gisbr_constants.METADATA_URL,
        gisbr_constants.IPEA_BASE,
        gisbr_constants.IPEA_V2_FALLBACK_BASE,
        gisbr_constants.GEOBR_V2_API_LATEST,
        gisbr_constants.GEOBR_V2_API_RELEASES,
        *gisbr_constants.GITHUB_MIRRORS,
    ]
    out = {(urlparse(u).hostname or "").lower() for u in urls}
    # GitHub release assets are served from this host after redirect.
    out.add("objects.githubusercontent.com")
    out.discard("")
    return out


# Area types whose loader mask can fall back to the remote municipality/aggregate
# boundary fetch (``loader._build_recorte``) when no usable local polygon exists.
_REMOTE_MASK_AREA_TYPES = frozenset({
    "municipality",
    "municipio",
    "metropolitan_region",
    "microregion",
    "mesoregion",
    "state",
    "macroregion",
})


def _may_fetch_remote_mask(area: Dict[str, Any]) -> bool:
    """True when the loader may download an area mask (IPEA geobr / GitHub mirrors).

    ``loader._mask_layer_from_area`` only uses a local polygon for ``geometry_wkt``
    when that WKT parses into a non-empty geometry; otherwise it falls back to the
    municipality/aggregate Recorte path, which downloads boundary polygons. A truthy
    WKT therefore does not prove the mask is local.
    """
    if not area.get("geometry_wkt"):
        return True
    atype = str(area.get("type") or "").lower()
    return atype in _REMOTE_MASK_AREA_TYPES and bool(area.get("codes"))


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
_ESCALA_MAX_RANK = {"municipio": 0, "regional": 2, "estado": 3, "macrorregiao": 4}

_PLAN_LOCK = threading.Lock()
_PLAN_STORE: Dict[str, Dict[str, Any]] = {}
_PLAN_TTL_SECONDS = 1800.0  # 30 minutes


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _existing_gpkg_layers(gpkg_path: Path) -> set:
    if not gpkg_path.exists():
        return set()
    try:
        from qgis.core import QgsVectorLayer
        vl = QgsVectorLayer(str(gpkg_path), "probe_existing", "ogr")
        if not vl.isValid():
            return set()
        names = set()
        for sub in vl.dataProvider().subLayers():
            parts = sub.split("!!::!!")
            if len(parts) > 1:
                names.add(parts[1])
        return names
    except Exception:
        return set()


def _area_suffix(area: Dict[str, Any]) -> str:
    atype = str(area.get("type") or "area").lower()
    aid = str(area.get("id") or area.get("ibge_code") or area.get("territory_id") or "custom")
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in aid.lower())
    if atype in ("municipality", "municipio"):
        return safe
    return f"{atype}_{safe}"


def _derive_output_gpkg(output_gpkg: Optional[str], area: Dict[str, Any], project_dir: Optional[str]) -> Tuple[bool, str, Optional[Path]]:
    if output_gpkg:
        return validate_safe_output_path(output_gpkg, allowed_extensions=(".gpkg",))
    if project_dir:
        pdir = Path(project_dir).expanduser().resolve()
        if pdir.is_dir():
            candidate = str(pdir / f"awanagis_br_{_area_suffix(area)}.gpkg")
            return validate_safe_output_path(candidate, allowed_extensions=(".gpkg",))
    return (
        False,
        "No output_gpkg provided and current QGIS project has not been saved to disk. "
        "Ask the user for a destination .gpkg path (or save the project first).",
        None,
    )


def _area_ufs(area: Dict[str, Any]) -> List[str]:
    ufs = list(area.get("ufs") or [])
    if not ufs and area.get("uf"):
        ufs = [str(area["uf"]).upper()]
    return sorted({u.upper() for u in ufs if u})


def _clip_mode_for_source(source: Dict[str, Any], area: Dict[str, Any]) -> str:
    proto = source.get("protocol", "")
    filtro = source.get("filtro") or {"tipo": "bbox"}
    atype = str(area.get("type") or "").lower()
    has_polygon_mask = bool(area.get("geometry_wkt")) or atype in (
        "municipality", "metropolitan_region", "microregion", "mesoregion", "state", "macroregion"
    )
    if proto == "ibge_tabular":
        return "attribute_join_to_municipality_polygon"
    if proto == "raster_cog":
        return "exact_polygon_clip" if has_polygon_mask else "bbox_filter_only"
    if proto == "geobr":
        raw = source.get("_raw_gisbr") or {}
        if raw.get("recorte", "code") == "code" and atype in ("municipality", "metropolitan_region", "microregion", "mesoregion", "state", "macroregion"):
            return "server_attribute_filter"
        return "exact_polygon_clip" if has_polygon_mask else "bbox_filter_only"
    if filtro.get("tipo") in ("cql_codigo", "cql_nome") and atype in ("municipality", "state", "macroregion"):
        return "server_attribute_filter"
    return "exact_polygon_clip" if has_polygon_mask else "bbox_filter_only"


def _validate_requested_year(source: Dict[str, Any], requested_year: Optional[int]) -> Optional[str]:
    if requested_year is None:
        return None
    try:
        year_int = int(requested_year)
    except (TypeError, ValueError):
        return f"Invalid year '{requested_year}' for {source['source_id']}; must be an integer."

    sid = source["source_id"]
    proto = source.get("protocol", "")
    if sid == "geobr_setores":
        try:
            avail = list(gisbr_catalog.available_years("census_tract"))
        except Exception:
            avail = [2000, 2010, 2020, 2022]
        if year_int not in avail:
            return f"Year {year_int} is not supported for '{sid}'. Supported years: {avail}"
    elif source.get("available_years"):
        avail = list(source["available_years"])
        if year_int not in avail:
            return f"Year {year_int} is not supported for '{sid}'. Supported years: {avail[0]}..{avail[-1]}"
    elif proto in ("ibge_tabular", "wfs", "arcgis", "zip_remoto") and sid != "inpe_prodes":
        return f"Source '{sid}' (protocol '{proto}') does not support year filtering; omit 'years' for this source."
    elif proto == "geobr" and not (source.get("_raw_gisbr") or {}).get("supports_year", True):
        return f"Source '{sid}' does not support year filtering; omit 'years' for this source."
    return None


def _estimate_size_category(source: Dict[str, Any], area: Dict[str, Any]) -> str:
    atype = str(area.get("type") or "").lower()
    proto = source.get("protocol", "")
    if proto == "raster_cog":
        return "large_raster_unknown_bytes"
    if atype in ("state", "macroregion"):
        return "large_regional_or_statewide_unknown_bytes"
    if proto in ("geobr", "wfs", "arcgis"):
        return "moderate_bounded_unknown_bytes"
    return "unknown"


def _plan_fingerprint(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "brplan_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def get_frozen_plan(plan_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Retrieve and validate a non-expired frozen plan by ``plan_id``."""
    if not plan_id or not isinstance(plan_id, str):
        return None, "Missing or invalid plan_id."
    with _PLAN_LOCK:
        record = _PLAN_STORE.get(plan_id.strip())
        if record is None:
            return None, f"Unknown or expired plan_id '{plan_id}'. Run br_plan_load first."
        if (time.monotonic() - record["created_monotonic"]) > _PLAN_TTL_SECONDS:
            _PLAN_STORE.pop(plan_id.strip(), None)
            return None, f"Plan '{plan_id}' has expired. Re-run br_plan_load to create a fresh plan."
        # Deep copy so callers cannot mutate the frozen record (or its nested area
        # inputs such as bbox/codes) and change what the same plan_id executes.
        return copy.deepcopy(record), None


def clear_plans() -> None:
    """Clear in-memory plan registry (primarily for tests)."""
    with _PLAN_LOCK:
        _PLAN_STORE.clear()


def plan_load(
    source_ids: List[str],
    area: Dict[str, Any],
    *,
    output_gpkg: Optional[str] = None,
    years: Optional[Dict[str, int]] = None,
    replace_existing: bool = False,
    include_non_government: bool = False,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a deterministic, read-only load plan without performing downloads or writes."""
    if not isinstance(source_ids, list) or not source_ids:
        return {"ok": False, "status": "invalid_input", "error": "source_ids must be a non-empty list."}
    if not isinstance(area, dict) or not area.get("type"):
        return {"ok": False, "status": "invalid_area", "error": "area must be a resolved area dict from br_resolve_area."}

    if area.get("type") == "indigenous_territory" and not area.get("geometry_wkt"):
        # Check if user is trying to load TI boundaries themselves (bootstrap) vs clipping other layers
        non_ti_requested = [s for s in source_ids if s not in ("funai_ti_boundaries", "geobr_terras_indigenas")]
        if non_ti_requested:
            return {
                "ok": False,
                "status": "needs_reference_data",
                "error": (
                    f"Resolved TI '{area.get('name')}' does not yet have polygon mask geometry loaded. "
                    "First plan/load 'funai_ti_boundaries' or 'geobr_terras_indigenas' (or pass a project_layer with the TI polygon), "
                    "then clip pressure layers against the real polygon."
                ),
                "reference_source_options": ["funai_ti_boundaries", "geobr_terras_indigenas"],
            }

    ok_dest, dest_err, gpkg_path = _derive_output_gpkg(output_gpkg, area, project_dir)
    if not ok_dest or gpkg_path is None:
        return {
            "ok": False,
            "status": "needs_destination",
            "error": dest_err,
        }

    existing_layers = _existing_gpkg_layers(gpkg_path)
    area_ufs = _area_ufs(area)
    area_rank = _SCALE_RANK.get(str(area.get("type") or "").lower(), 2)
    suffix = _area_suffix(area)
    years_map = dict(years or {})

    # Check available disk space on parent directory (or nearest existing ancestor)
    disk_free_mb: Optional[float] = None
    probe_dir = gpkg_path.parent
    while not probe_dir.exists() and probe_dir != probe_dir.parent:
        probe_dir = probe_dir.parent
    try:
        usage = shutil.disk_usage(str(probe_dir))
        disk_free_mb = round(usage.free / (1024 * 1024), 1)
    except Exception:
        disk_free_mb = None

    parquet_ok = None
    items: List[Dict[str, Any]] = []
    executable_ids: List[str] = []
    external_databases: List[Dict[str, Any]] = []
    hosts: set = set()
    warnings: List[str] = []
    disclosures: List[str] = []

    if area_rank >= 3:
        warnings.append(
            f"Large geographic scope ({area.get('type')}): downloads may be large and slow."
        )
    if replace_existing and gpkg_path.exists():
        warnings.append(
            f"replace_existing=true will overwrite matching tables in {gpkg_path.name} safely."
        )
    if disk_free_mb is not None and disk_free_mb < 250:
        warnings.append(f"Low free disk space ({disk_free_mb} MB) at destination.")

    seen = set()
    for raw_sid in source_ids[:25]:
        sid = str(raw_sid).strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)

        source = get_source(sid)
        if source is None:
            items.append({
                "source_id": sid,
                "readiness": "blocked",
                "reason_code": "unknown_source",
                "reason": f"Unknown source_id '{sid}'.",
            })
            continue

        canonical_id = source["source_id"]
        allowed, reason_code, reason_msg = check_source_loadable(
            source, include_non_government=include_non_government
        )
        if not allowed:
            readiness = "manual" if reason_code == "manual_required" else "blocked"
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "origin_class": source["origin_class"],
                "loader_state": source["loader_state"],
                "load_policy": source["load_policy"],
                "sensitivity": source["sensitivity"],
                "readiness": readiness,
                "reason_code": reason_code,
                "reason": reason_msg,
                "portal_url": source.get("portal_url", ""),
            })
            continue

        # Check UF scope
        uf_scope = [u.upper() for u in (source.get("uf_scope") or ["BR"])]
        if "BR" not in uf_scope and area_ufs and not set(area_ufs) <= set(uf_scope):
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "readiness": "blocked",
                "reason_code": "out_of_scope_uf",
                "reason": f"Source '{canonical_id}' is restricted to UF(s) {uf_scope}; area has {area_ufs}.",
            })
            continue

        # Check escala_max
        src_rank = _ESCALA_MAX_RANK.get(source.get("escala_max", "regional"), 2)
        if area_rank > src_rank:
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "readiness": "blocked",
                "reason_code": "out_of_scope_scale",
                "reason": (
                    f"Source '{canonical_id}' has escala_max='{source.get('escala_max')}' "
                    f"and is blocked at '{area.get('type')}' scale."
                ),
            })
            continue

        # Check OSM municipality/RM constraint
        if source.get("protocol") == "osm" and area.get("type") not in ("municipality", "metropolitan_region"):
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "readiness": "blocked",
                "reason_code": "out_of_scope_scale",
                "reason": "OSM sources only support municipality (and RM for osm_vias) scopes.",
            })
            continue

        # Check Parquet capability for geobr v2 sources
        if source.get("requires_parquet"):
            if parquet_ok is None:
                parquet_ok = capabilities.parquet_backend() is not None
            if not parquet_ok:
                items.append({
                    "source_id": canonical_id,
                    "title": source["name"],
                    "readiness": "blocked",
                    "reason_code": "missing_parquet",
                    "reason": (
                        f"Source '{canonical_id}' is a geobr v2 dataset requiring GDAL Parquet "
                        "driver or optional pyarrow package."
                    ),
                })
                continue

        # Check requested year validity
        req_year = years_map.get(canonical_id) or years_map.get(sid)
        year_err = _validate_requested_year(source, req_year)
        if year_err:
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "readiness": "blocked",
                "reason_code": "invalid_year",
                "reason": year_err,
            })
            continue

        # Determine target table / raster filename and reuse/skip check
        target_layer_name = f"{canonical_id}_{suffix}"
        if source.get("protocol") == "raster_cog":
            eff_year = req_year or source.get("source_year") or 2023
            tif_path = gpkg_path.parent / f"{canonical_id}_{eff_year}_{suffix}.tif"
            already_exists = tif_path.exists()
            output_target = str(tif_path)
        else:
            already_exists = target_layer_name in existing_layers
            output_target = f"{gpkg_path}|layername={target_layer_name}"

        if already_exists and not replace_existing:
            items.append({
                "source_id": canonical_id,
                "title": source["name"],
                "readiness": "skipped",
                "reason_code": "already_exists",
                "reason": f"Output '{target_layer_name}' already exists; reusing existing data (replace_existing=false).",
                "output_target": output_target,
                "table_name": target_layer_name,
            })
            continue

        clip_mode = _clip_mode_for_source(source, area)
        if clip_mode == "bbox_filter_only":
            warnings.append(
                f"{canonical_id}: only bbox filtering is available for this area (no exact polygon clip)."
            )

        svc_url = source.get("service_url") or ""
        if svc_url:
            parsed = urlparse(svc_url)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())

        src_warnings: List[str] = []
        if source["loader_state"] == "pending_probe":
            src_warnings.append(
                "Endpoint machine access is pending_probe; execution will verify TLS/endpoint and fail cleanly if unreachable."
            )
        if canonical_id == "funai_dsei_areas":
            src_warnings.append(
                "DSEI polygons are SESAI operational health districts, NOT TI legal demarcation boundaries."
            )
        if canonical_id == "mapbiomas_cobertura":
            src_warnings.append(
                f"MapBiomas Collection 9 is historical land cover (year={req_year or source.get('source_year')}), NOT live deforestation alerts."
            )
        if canonical_id == "inpe_deter":
            src_warnings.append("DETER alerts are monitoring indicators, not proof of illegal activity.")

        disclosures.append(
            f"{canonical_id}: publisher={source['publisher']} ({source['origin_class']}), "
            f"license={source.get('license', 'unknown')}, sensitivity={source['sensitivity']}"
        )

        ext_desc = external_db_descriptor(source, status="planned_external")
        if ext_desc.get("host"):
            hosts.add(ext_desc["host"])
        external_databases.append(ext_desc)

        items.append({
            "source_id": canonical_id,
            "title": source["name"],
            "origin_class": source["origin_class"],
            "protocol": source["protocol"],
            "loader_state": source["loader_state"],
            "load_policy": source["load_policy"],
            "sensitivity": source["sensitivity"],
            "readiness": "ready",
            "table_name": target_layer_name,
            "output_target": output_target,
            "clip_mode": clip_mode,
            "requested_year": req_year or source.get("source_year"),
            "estimated_size": _estimate_size_category(source, area),
            "external_db": ext_desc,
            "warnings": src_warnings,
        })
        executable_ids.append(canonical_id)

    can_execute = len(executable_ids) > 0
    if can_execute and _may_fetch_remote_mask(area):
        # Loader fetches an area mask from IPEA/GitHub mirrors when no usable polygon is supplied.
        hosts.update(_mask_provider_hosts())
    external_db_notice = (
        "External databases to contact: "
        + ", ".join(f"{d['source_id']} ({d['publisher']} @ {d['host']})" for d in external_databases)
        + ". External government/public geoportals may go offline intermittently."
    ) if external_databases else ""
    # Bind the ID to every execution input carried by the area (bbox, WKT, terrai_cod, ...).
    # Snapshot the area so later mutation of the caller's dict/lists cannot change this plan.
    area_snapshot = copy.deepcopy(area)
    area_fingerprint_payload = {k: area_snapshot[k] for k in sorted(area_snapshot)}
    plan_payload = {
        "catalog_version": CATALOG_VERSION,
        "executable_ids": executable_ids,
        "area": area_fingerprint_payload,
        "output_gpkg": str(gpkg_path),
        "replace_existing": bool(replace_existing),
        "include_non_government": bool(include_non_government),
        "years": years_map,
    }
    plan_id = _plan_fingerprint(plan_payload) if can_execute else None

    if can_execute and plan_id:
        frozen = {
            "plan_id": plan_id,
            "created_at": _utc_now_iso(),
            "created_monotonic": time.monotonic(),
            "catalog_version": CATALOG_VERSION,
            "executable_ids": executable_ids,
            "items": items,
            "area": area_snapshot,
            "output_gpkg": str(gpkg_path),
            "replace_existing": bool(replace_existing),
            "include_non_government": bool(include_non_government),
            "years": years_map,
            "hosts": sorted(hosts),
            "external_databases": external_databases,
            "external_db_notice": external_db_notice,
            "warnings": warnings,
            "disclosures": disclosures,
        }
        with _PLAN_LOCK:
            _PLAN_STORE[plan_id] = frozen

    return {
        "ok": True,
        "status": "ready" if can_execute else "no_executable_sources",
        "plan_id": plan_id,
        "can_execute": can_execute,
        "requires_confirmation": can_execute,
        "catalog_version": CATALOG_VERSION,
        "area": {
            "type": area.get("type"),
            "id": area.get("id"),
            "name": area.get("name"),
            "ufs": area_ufs,
            "geometry_fingerprint": area.get("geometry_fingerprint"),
        },
        "output_gpkg": str(gpkg_path),
        "replace_existing": bool(replace_existing),
        "hosts": sorted(hosts),
        "external_databases": external_databases,
        "external_db_notice": external_db_notice,
        "disk_free_mb": disk_free_mb,
        "items": items,
        "warnings": warnings,
        "disclosures": disclosures,
    }
