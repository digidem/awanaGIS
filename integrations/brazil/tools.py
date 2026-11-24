"""Agent-facing Brazilian & Indigenous geospatial data tool contracts (``br_*``).

Exposes exactly five stable tools shared identically across API, CLI, and MCP:
- ``br_search_sources``
- ``br_source_details``
- ``br_resolve_area``
- ``br_plan_load``
- ``br_execute_load``
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .catalog import search_sources, source_details
from .loader import (
    commit_load_results,
    execute_load,
    prepare_load_context,
    run_load_worker,
)
from .planner import clear_plans, get_frozen_plan, plan_load
from .policy import redact_sensitive_text
from .resolver import resolve_area

BRAZIL_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "br_search_sources",
        "method": "br_search_sources",
        "description": (
            "Search the merged Brazilian geospatial catalog (76 GISBR sources plus 14 "
            "curated Indigenous/territorial sources: FUNAI TI, FUNAI/SESAI DSEI, INPE "
            "PRODES/DETER, IBGE 2022 Indigenous localities, ISA, Mapi, RAISG, MapBiomas "
            "Alerta) offline by Portuguese or English keywords/synonyms, theme, UF, "
            "publisher_type, scope_type, or sensitivity. Inspect sources before planning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Portuguese or English search query/synonyms (e.g. 'terras indígenas', "
                        "'PRODES', 'DSEI', 'mineração', 'conservation units')."
                    ),
                },
                "theme": {
                    "type": "string",
                    "description": (
                        "Optional theme/axis filter (e.g. 'indigenous_territories', "
                        "'environment', 'transport', 'sanitation_hydrology', 'administrative')."
                    ),
                },
                "uf": {
                    "type": "string",
                    "description": "Optional 2-letter Brazilian state UF code (e.g. 'PA', 'AM', 'RR').",
                },
                "publisher_type": {
                    "type": "string",
                    "enum": ["official", "official_mirror", "non_government", "any"],
                    "description": (
                        "Origin filter: 'official' (direct government), 'official_mirror' "
                        "(official-origin mirror e.g. IPEA/geobr), 'non_government' "
                        "(ISA/RAISG/MapBiomas/OSM), or 'any'."
                    ),
                },
                "scope_type": {
                    "type": "string",
                    "description": (
                        "Optional geographic scope (municipality, state, indigenous_territory, "
                        "metropolitan_region, microregion, mesoregion, macroregion)."
                    ),
                },
                "loadable_only": {
                    "type": "boolean",
                    "description": (
                        "If true, exclude portal_only, discovery_only, manual_required, "
                        "unavailable, and blocked_sensitive entries."
                    ),
                },
                "sensitivity": {
                    "type": "string",
                    "description": (
                        "Optional sensitivity filter (public, territory_boundary, "
                        "administrative_point, restricted_locality_point, blocked_isolated_peoples)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of sources to return (default 25, max 100).",
                },
            },
        },
    },
    {
        "name": "br_source_details",
        "method": "br_source_details",
        "description": (
            "Return detailed provenance, publisher, origin_class, reference year vs "
            "extraction status, license, caveats, and access policy for specific Brazilian "
            "source IDs. Set probe=true for a bounded read-only endpoint capability check "
            "(never downloads datasets and never probes blocked_sensitive or portal_only sources)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of source IDs (e.g. ['funai_ti_boundaries', 'inpe_prodes']).",
                },
                "probe": {
                    "type": "boolean",
                    "description": "Run bounded read-only metadata/GetCapabilities probe (default false).",
                },
            },
            "required": ["source_ids"],
        },
    },
    {
        "name": "br_resolve_area",
        "method": "br_resolve_area",
        "description": (
            "Resolve a Brazilian area of interest to an authoritative identifier or polygon "
            "mask: municipality (7-digit IBGE code or name+UF with disambiguation), state, "
            "metropolitan_region, microregion, mesoregion, macroregion, project_layer "
            "(valid QGIS polygon layer), or indigenous_territory (FUNAI terrai_cod or TI "
            "name+UF, explicitly distinct from DSEI operational health areas)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "municipality",
                        "state",
                        "metropolitan_region",
                        "microregion",
                        "mesoregion",
                        "macroregion",
                        "project_layer",
                        "indigenous_territory",
                    ],
                    "description": "Type of geographic area to resolve.",
                },
                "name": {"type": "string", "description": "Place, region, layer, or TI name."},
                "uf": {"type": "string", "description": "2-letter UF code for disambiguation."},
                "ibge_code": {"type": "string", "description": "7-digit IBGE municipality or regional code."},
                "layer_id": {"type": "string", "description": "QGIS project layer ID for project_layer or loaded TI layer."},
                "territory_id": {"type": "string", "description": "FUNAI terrai_cod identifier for indigenous_territory."},
                "source_id": {"type": "string", "description": "Optional source context (e.g. 'funai_ti_boundaries')."},
                "allow_live_lookup": {
                    "type": "boolean",
                    "description": "Allow optional read-only IBGE API fallback if code is absent offline (default false).",
                },
            },
            "required": ["type"],
        },
    },
    {
        "name": "br_plan_load",
        "method": "br_plan_load",
        "description": (
            "Build a deterministic, read-only load plan (no network retrieval or disk writes). "
            "Validates source policies, scope/UF/scale, years, destination GeoPackage path, "
            "reuse/overwrite behavior, and returns an opaque short-lived plan_id plus warnings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Canonical source IDs to plan.",
                },
                "area": {
                    "type": "object",
                    "description": "Resolved area object returned by br_resolve_area.",
                },
                "output_gpkg": {
                    "type": "string",
                    "description": "Destination .gpkg file path (optional if current QGIS project is saved).",
                },
                "years": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                    "description": "Optional mapping of source_id -> integer reference year.",
                },
                "replace_existing": {
                    "type": "boolean",
                    "description": "Overwrite matching existing tables/rasters instead of reusing (default false).",
                },
                "include_non_government": {
                    "type": "boolean",
                    "description": "Allow reviewed non-government sources after explicit opt-in (default false).",
                },
            },
            "required": ["source_ids", "area"],
        },
    },
    {
        "name": "br_execute_load",
        "method": "br_execute_load",
        "description": (
            "Execute a frozen load plan by plan_id after user confirmation. Fetches "
            "allowlisted sources with cancellation, clips to polygon mask when available, "
            "persists atomically to GeoPackage/GeoTIFF, tags awanagis/* provenance properties, "
            "and adds valid layers to QGIS. Accepts ONLY plan_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "string",
                    "description": "Opaque plan_id issued by br_plan_load.",
                },
            },
            "required": ["plan_id"],
            "additionalProperties": False,
        },
    },
]

BRAZIL_TOOL_NAMES = frozenset(spec["name"] for spec in BRAZIL_TOOL_SPECS)


def _current_project_dir() -> Optional[str]:
    try:
        from qgis.core import QgsProject

        proj = QgsProject.instance()
        home = proj.homePath()
        if home and Path(home).is_dir():
            return home
        file_name = proj.fileName()
        if file_name:
            parent = Path(file_name).parent
            if parent.is_dir():
                return str(parent)
    except Exception:
        pass
    return None


def br_search_sources(
    query: Optional[str] = None,
    theme: Optional[str] = None,
    uf: Optional[str] = None,
    publisher_type: Optional[str] = None,
    scope_type: Optional[str] = None,
    loadable_only: Optional[bool] = None,
    sensitivity: Optional[str] = None,
    limit: int = 25,
) -> Dict[str, Any]:
    """Search merged GISBR + curated Indigenous catalog offline."""
    try:
        return search_sources(
            query=query,
            theme=theme,
            uf=uf,
            publisher_type=publisher_type,
            scope_type=scope_type,
            loadable_only=loadable_only,
            sensitivity=sensitivity,
            limit=limit,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": redact_sensitive_text(f"br_search_sources failed: {exc}", redact_coordinates=True),
            "sources": [],
            "count": 0,
        }


def br_source_details(source_ids: List[str], probe: bool = False) -> Dict[str, Any]:
    """Inspect detailed source metadata and optionally run bounded read-only probes."""
    try:
        return source_details(source_ids, probe=bool(probe))
    except Exception as exc:
        return {
            "ok": False,
            "error": redact_sensitive_text(f"br_source_details failed: {exc}", redact_coordinates=True),
            "sources": [],
        }


def br_resolve_area(
    type: str,  # noqa: A002
    name: Optional[str] = None,
    uf: Optional[str] = None,
    ibge_code: Optional[str] = None,
    layer_id: Optional[str] = None,
    territory_id: Optional[str] = None,
    source_id: Optional[str] = None,
    allow_live_lookup: bool = False,
) -> Dict[str, Any]:
    """Resolve a Brazilian municipality, region, QGIS polygon layer, or Indigenous Territory."""
    try:
        return resolve_area(
            type,
            name=name,
            uf=uf,
            ibge_code=ibge_code,
            layer_id=layer_id,
            territory_id=territory_id,
            source_id=source_id,
            allow_live_lookup=bool(allow_live_lookup),
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": redact_sensitive_text(f"br_resolve_area failed: {exc}", redact_coordinates=True),
            "candidates": [],
        }


def br_plan_load(
    source_ids: List[str],
    area: Dict[str, Any],
    output_gpkg: Optional[str] = None,
    years: Optional[Dict[str, int]] = None,
    replace_existing: bool = False,
    include_non_government: bool = False,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a deterministic read-only load plan without downloads or file writes."""
    try:
        effective_project_dir = project_dir if project_dir is not None else _current_project_dir()
        return plan_load(
            source_ids,
            area,
            output_gpkg=output_gpkg,
            years=years,
            replace_existing=bool(replace_existing),
            include_non_government=bool(include_non_government),
            project_dir=effective_project_dir,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": redact_sensitive_text(f"br_plan_load failed: {exc}", redact_coordinates=True),
        }


def br_execute_load(
    plan_id: str,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
    project=None,
    local_fixtures: Optional[Dict[str, str]] = None,
    executor=None,
    iface: Any = None,
) -> Dict[str, Any]:
    """Execute a frozen ``plan_id`` with strict policy checks and atomic layer registration."""
    if not plan_id or not isinstance(plan_id, str):
        return {
            "ok": False,
            "status": "invalid_plan",
            "cancelled": False,
            "results": [],
            "error": "plan_id must be a non-empty string issued by br_plan_load.",
        }
    try:
        return execute_load(
            plan_id,
            should_stop=should_stop,
            project=project,
            local_fixtures=local_fixtures,
            executor=executor,
            iface=iface,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "cancelled": False,
            "results": [],
            "error": redact_sensitive_text(f"br_execute_load failed: {exc}", redact_coordinates=True),
        }


class BrazilDataService:
    """Thin service facade matching SPEC §9 for AwanaGIS Brazil operations."""

    def search_sources(self, **filters) -> Dict[str, Any]:
        return br_search_sources(**filters)

    def source_details(self, source_ids: List[str], probe: bool = False) -> Dict[str, Any]:
        return br_source_details(source_ids, probe=probe)

    def resolve_area(
        self,
        type: str,  # noqa: A002
        name: Optional[str] = None,
        uf: Optional[str] = None,
        ibge_code: Optional[str] = None,
        layer_id: Optional[str] = None,
        territory_id: Optional[str] = None,
        source_id: Optional[str] = None,
        allow_live_lookup: bool = False,
    ) -> Dict[str, Any]:
        return br_resolve_area(
            type=type,
            name=name,
            uf=uf,
            ibge_code=ibge_code,
            layer_id=layer_id,
            territory_id=territory_id,
            source_id=source_id,
            allow_live_lookup=allow_live_lookup,
        )

    def plan_load(
        self,
        source_ids: List[str],
        area: Dict[str, Any],
        output_gpkg: Optional[str] = None,
        years: Optional[Dict[str, int]] = None,
        replace_existing: bool = False,
        include_non_government: bool = False,
        project_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        return br_plan_load(
            source_ids=source_ids,
            area=area,
            output_gpkg=output_gpkg,
            years=years,
            replace_existing=replace_existing,
            include_non_government=include_non_government,
            project_dir=project_dir,
        )

    def execute_load(
        self,
        plan_id: str,
        *,
        should_stop: Optional[Callable[[], bool]] = None,
        project=None,
        local_fixtures: Optional[Dict[str, str]] = None,
        executor=None,
        iface: Any = None,
    ) -> Dict[str, Any]:
        return br_execute_load(
            plan_id,
            should_stop=should_stop,
            project=project,
            local_fixtures=local_fixtures,
            executor=executor,
            iface=iface,
        )

    def shutdown(self) -> None:
        clear_plans()


_DEFAULT_SERVICE = BrazilDataService()


def get_brazil_service() -> BrazilDataService:
    """Return the shared ``BrazilDataService`` instance."""
    return _DEFAULT_SERVICE


BRAZIL_DISPATCH_TABLE: Dict[str, Callable[..., Dict[str, Any]]] = {
    "br_search_sources": br_search_sources,
    "br_source_details": br_source_details,
    "br_resolve_area": br_resolve_area,
    "br_plan_load": br_plan_load,
    "br_execute_load": br_execute_load,
}
