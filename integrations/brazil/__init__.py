"""Brazilian and curated Indigenous public geospatial data integration for AwanaGIS."""

from .runtime import provider_id, register_brazil_provider, unregister_brazil_provider
from .tools import (
    BRAZIL_DISPATCH_TABLE,
    BRAZIL_TOOL_NAMES,
    BRAZIL_TOOL_SPECS,
    BrazilDataService,
    br_execute_load,
    br_plan_load,
    br_resolve_area,
    br_search_sources,
    br_source_details,
    get_brazil_service,
)

__all__ = [
    "BRAZIL_DISPATCH_TABLE",
    "BRAZIL_TOOL_NAMES",
    "BRAZIL_TOOL_SPECS",
    "BrazilDataService",
    "br_execute_load",
    "br_plan_load",
    "br_resolve_area",
    "br_search_sources",
    "br_source_details",
    "get_brazil_service",
    "provider_id",
    "register_brazil_provider",
    "unregister_brazil_provider",
]
