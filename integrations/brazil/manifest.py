"""Source metadata manifest and curated Indigenous/territorial overlay registry.

Preserves all 76 pinned GISBR entries without mutating ``vendor/gisbr/core/sources.py``,
adds normalized provenance/policy enrichment, and defines the separately
curated Indigenous & territorial overlay registry per ``docs/gisbr-indigenous-data/indigenous-sources.md``.
"""

from typing import Any, Dict, List, Optional, Tuple

CATALOG_VERSION = "awanagis-br-2026.11.23+gisbr-06d84dfa"
GISBR_PINNED_SHA = "06d84dfab9942e4e840637bb8d8f96af173330ad"

ORIGIN_CLASSES = ("official_direct", "official_mirror", "non_government")

PUBLISHER_TYPE_MAP = {
    "official": "official_direct",
    "official_mirror": "official_mirror",
    "non_government": "non_government",
}

LOADER_STATES = (
    "loadable",
    "pending_probe",
    "portal_only",
    "discovery_only",
    "blocked_sensitive",
    "manual_required",
    "unavailable",
)

LOAD_POLICIES = (
    "allowed_public_polygon",
    "requires_terms_check",
    "requires_review_and_opt_in",
    "discovery_only",
    "blocked_sensitive",
)

SENSITIVITY_LEVELS = (
    "public",
    "territory_boundary",
    "administrative_point",
    "restricted_locality_point",
    "blocked_isolated_peoples",
)

# Mapping from GISBR Portuguese axis names to normalized English/bilingual axis tags
AXIS_EN_MAP = {
    "transportes": "transport",
    "saneamento": "sanitation_hydrology",
    "ambiental": "environment",
    "urbano": "urban",
    "pol-admin": "administrative",
    "demografia": "demography",
    "educacao": "education",
    "saude": "health",
    "agropecuaria": "agriculture",
    "contexto": "context",
    "indigenous_territories": "indigenous_territories",
}

# Known source years / publishers / portal URLs for GISBR entries where documented
GISBR_ENRICHMENT: Dict[str, Dict[str, Any]] = {
    "dnit_snv": {
        "name": "DNIT — National Highway System (SNV)",
        "publisher": "DNIT",
        "source_year": 2025,
        "portal_url": "https://servicos.dnit.gov.br/dnitcloud/index.php/s/oSciESFAszfYBoP",
        "keywords": ["rodovias", "estradas", "highways", "roads", "federal", "dnit", "snv"],
    },
    "minfra_ferrovias": {
        "name": "Ministry of Infrastructure — Railways",
        "publisher": "MInfra / ANTT",
        "portal_url": "https://geoservicos.inde.gov.br/",
        "keywords": ["ferrovias", "railways", "railroads", "trens", "minfra"],
    },
    "icmbio_uc": {
        "name": "ICMBio — Federal Conservation Units",
        "publisher": "ICMBio",
        "portal_url": "https://www.gov.br/icmbio/pt-br/assuntos/dados_geoespaciais",
        "keywords": ["unidades de conservacao", "uc", "ucs", "conservation units", "protected areas", "parques", "icmbio"],
    },
    "icmbio_embargos": {
        "name": "ICMBio — Environmental Embargoes",
        "publisher": "ICMBio",
        "portal_url": "https://www.gov.br/icmbio/pt-br/assuntos/dados_geoespaciais",
        "keywords": ["embargos", "icmbio", "ambiental", "infracoes"],
    },
    "sicar_imoveis": {
        "name": "SICAR — Rural Environmental Registry (CAR) Parcels",
        "publisher": "SFB / MMA (SICAR)",
        "portal_url": "https://consultapublica.car.gov.br/",
        "keywords": ["car", "sicar", "imoveis rurais", "rural parcels", "cadastro ambiental rural", "fazendas"],
    },
    "anm_sigmine": {
        "name": "ANM / SIGMINE — Mining Claims and Processes",
        "publisher": "ANM",
        "portal_url": "https://geo.anm.gov.br/",
        "keywords": ["mineracao", "processos minerarios", "mining", "mining claims", "anm", "sigmine", "garimpo"],
    },
    "incra_sigef_parcelas": {
        "name": "INCRA / SIGEF — Certified Rural Parcels (Manual gov.br Download)",
        "publisher": "INCRA",
        "portal_url": "https://certificacao.incra.gov.br/csv_shp/export_shp.py",
        "keywords": ["sigef", "incra", "parcelas certificadas", "land tenure", "gov.br"],
        "attribution": "INCRA / SIGEF — requires authenticated gov.br manual download",
    },
    "sgb_rios": {
        "name": "SGB/CPRM — Rivers (BC250)",
        "publisher": "SGB / CPRM",
        "portal_url": "https://geosgb.sgb.gov.br/",
        "keywords": ["rios", "rivers", "hidrografia", "hydrography", "drenagem", "sgb", "cprm"],
    },
    "sgb_bacias": {
        "name": "SGB/CPRM — Hydrographic Basins",
        "publisher": "SGB / CPRM",
        "portal_url": "https://geosgb.sgb.gov.br/",
        "keywords": ["bacias", "watersheds", "basins", "hidrografia", "hydrography"],
    },
    "ana_hidrografia": {
        "name": "ANA — National Hydrography",
        "publisher": "ANA",
        "portal_url": "https://metadados.snirh.gov.br/",
        "keywords": ["hidrografia", "hydrography", "agua", "water", "ana", "snirh", "rios"],
    },
    "ibge_bc250_drenagem": {
        "name": "IBGE — BC250 Drainage Lines (2025)",
        "publisher": "IBGE",
        "source_year": 2025,
        "portal_url": "https://www.ibge.gov.br/geociencias/cartas-e-mapas/bases-cartograficas-continuas/15759-brasil.html",
        "keywords": ["drenagem", "drainage", "hidrografia", "hydrography", "bc250", "ibge"],
    },
    "ibge_bc250_rodovias": {
        "name": "IBGE — BC250 Roads (2025)",
        "publisher": "IBGE",
        "source_year": 2025,
        "portal_url": "https://www.ibge.gov.br/geociencias/cartas-e-mapas/bases-cartograficas-continuas/15759-brasil.html",
        "keywords": ["rodovias", "roads", "highways", "bc250", "ibge"],
    },
    "mapbiomas_cobertura": {
        "name": "MapBiomas — Land Cover and Land Use (Collection 9 COG)",
        "publisher": "MapBiomas",
        "distributor": "MapBiomas / Google Cloud Storage",
        "origin_class": "non_government",
        "source_year": 2023,
        "portal_url": "https://brasil.mapbiomas.org/",
        "license": "CC-BY-SA",
        "attribution": "MapBiomas Collection 9 (1985-2023 annual land cover/use; NOT real-time deforestation alerts)",
        "keywords": ["cobertura", "uso da terra", "land cover", "land use", "mapbiomas", "collection 9", "raster"],
        "verification_evidence": "Historical annual land-cover raster (1985-2023); not a current deforestation alert feed.",
    },
    "geobr_terras_indigenas": {
        "name": "Indigenous Lands (FUNAI via IPEA/geobr mirror)",
        "publisher": "FUNAI (republished via IPEA/geobr)",
        "distributor": "IPEA / geobr",
        "origin_class": "official_mirror",
        "portal_url": "https://ipeagit.github.io/geobr/",
        "license": "MIT (geobr package) / Public official origin geometry",
        "attribution": "Original geometry: FUNAI; mirror package: IPEA/geobr",
        "sensitivity": "territory_boundary",
        "load_policy": "allowed_public_polygon",
        "keywords": ["terras indigenas", "ti", "tis", "indigenous land", "indigenous territories", "funai", "geobr"],
        "verification_evidence": "Dated IPEA/geobr v1.7.0 GeoPackage mirror; check vintage vs direct FUNAI WFS.",
    },
    "geobr_ucs": {
        "name": "Conservation Units (ICMBio/MMA via IPEA/geobr mirror)",
        "publisher": "ICMBio / MMA (republished via IPEA/geobr)",
        "distributor": "IPEA / geobr",
        "origin_class": "official_mirror",
        "portal_url": "https://ipeagit.github.io/geobr/",
        "keywords": ["unidades de conservacao", "uc", "ucs", "conservation units", "geobr"],
    },
    "geobr_municipio": {
        "name": "Municipal Boundaries (IBGE via IPEA/geobr mirror)",
        "publisher": "IBGE (republished via IPEA/geobr)",
        "distributor": "IPEA / geobr",
        "origin_class": "official_mirror",
        "portal_url": "https://ipeagit.github.io/geobr/",
        "keywords": ["municipio", "municipality", "malha municipal", "limites", "ibge", "geobr"],
    },
    "geobr_saude": {
        "name": "Health Facilities (CNES/MS via IPEA/geobr mirror)",
        "publisher": "Ministério da Saúde / CNES (via IPEA/geobr)",
        "distributor": "IPEA / geobr",
        "origin_class": "official_mirror",
        "portal_url": "https://ipeagit.github.io/geobr/",
        "keywords": ["saude", "health", "hospitais", "ubs", "estabelecimentos de saude", "cnes", "geobr"],
    },
    "geobr_escolas": {
        "name": "Schools (INEP via IPEA/geobr mirror)",
        "publisher": "INEP (via IPEA/geobr)",
        "distributor": "IPEA / geobr",
        "origin_class": "official_mirror",
        "portal_url": "https://ipeagit.github.io/geobr/",
        "keywords": ["escolas", "schools", "educacao", "education", "inep", "geobr"],
    },
    "osm_vias": {
        "name": "OpenStreetMap — Road Network (Overpass / Pre-built RM)",
        "publisher": "OpenStreetMap contributors",
        "distributor": "Overpass API / GISBR Releases",
        "origin_class": "non_government",
        "license": "ODbL / OpenStreetMap contributors",
        "keywords": ["osm", "openstreetmap", "vias", "ruas", "roads", "street network"],
    },
    "osm_pois": {
        "name": "OpenStreetMap — Points of Interest (Overpass)",
        "publisher": "OpenStreetMap contributors",
        "distributor": "Overpass API",
        "origin_class": "non_government",
        "license": "ODbL / OpenStreetMap contributors",
        "keywords": ["osm", "openstreetmap", "pois", "equipamentos"],
    },
    "basemap_satelite": {
        "name": "Esri World Imagery Satellite Basemap (Display Only)",
        "publisher": "Esri",
        "distributor": "Esri ArcGIS Online",
        "origin_class": "non_government",
        "loader_state": "portal_only",
        "load_policy": "requires_terms_check",
        "license": "Esri Terms of Use",
        "keywords": ["basemap", "satelite", "satellite", "esri", "imagery"],
    },
}


def _infer_gisbr_publisher(raw: Dict[str, Any]) -> Tuple[str, str, str]:
    """Return ``(publisher, distributor, origin_class)`` for a GISBR source."""
    sid = raw["id"]
    proto = raw.get("protocolo", "")
    nome = raw.get("nome", "")
    if sid.startswith("geobr_"):
        return ("IBGE / Official Agencies (via IPEA/geobr)", "IPEA / geobr", "official_mirror")
    if proto in ("osm", "basemap") or sid == "mapbiomas_cobertura":
        pub = "OpenStreetMap contributors" if proto == "osm" else ("Esri" if proto == "basemap" else "MapBiomas")
        return (pub, pub, "non_government")
    if "—" in nome:
        pub = nome.split("—", 1)[0].strip()
    else:
        pub = sid.split("_", 1)[0].upper()
    return (pub, pub, "official_direct")


def normalize_gisbr_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one raw GISBR ``SOURCES`` dict into the unified AwanaGIS catalog schema."""
    sid = raw["id"]
    enr = GISBR_ENRICHMENT.get(sid, {})
    pub_default, dist_default, origin_default = _infer_gisbr_publisher(raw)
    proto = raw.get("protocolo", "unknown")

    if raw.get("indisponivel"):
        loader_state = "unavailable"
        load_policy = "requires_terms_check"
    elif proto == "arquivo":
        loader_state = "manual_required"
        load_policy = "requires_terms_check"
    elif proto == "basemap":
        loader_state = "portal_only"
        load_policy = "requires_terms_check"
    else:
        loader_state = enr.get("loader_state", "loadable")
        load_policy = enr.get(
            "load_policy",
            "requires_review_and_opt_in"
            if enr.get("origin_class", origin_default) == "non_government"
            else "allowed_public_polygon",
        )

    origin_class = enr.get("origin_class", origin_default)
    portal_url = enr.get("portal_url") or raw.get("origem_url") or raw.get("endpoint") or ""
    service_url = raw.get("endpoint") or raw.get("url_template") or ""
    if not service_url and proto == "geobr":
        service_url = "https://www.ipea.gov.br/geobr/data_gpkg/"
    axis_raw = raw.get("eixo", "other")
    axis = AXIS_EN_MAP.get(axis_raw, axis_raw)

    keywords = list(enr.get("keywords", []))
    keywords.extend([sid, raw.get("nome", ""), axis_raw, axis, proto])
    if raw.get("ufs"):
        keywords.extend(raw["ufs"])

    entry = {
        "source_id": sid,
        "name": enr.get("name", raw.get("nome", sid)),
        "name_pt": raw.get("nome", sid),
        "axis": axis,
        "axis_pt": axis_raw,
        "origin_class": origin_class,
        "loader_state": loader_state,
        "load_policy": load_policy,
        "sensitivity": enr.get("sensitivity", "public"),
        "terms_checked": bool(raw.get("licenca") or enr.get("license")),
        "machine_access_verified": False,
        "last_checked_at": None,
        "source_year": enr.get("source_year", raw.get("ano_default")),
        "available_years": list(raw["anos"]) if raw.get("anos") else None,
        "publisher": enr.get("publisher", pub_default),
        "distributor": enr.get("distributor", dist_default),
        "protocol": proto,
        "license": enr.get("license") or raw.get("licenca") or "unknown",
        "attribution": enr.get("attribution") or (
            f"{enr.get('publisher', pub_default)} — {raw.get('nome', sid)}"
        ),
        "portal_url": portal_url,
        "service_url": service_url,
        "typename": raw.get("type_name") or raw.get("layer_id") or raw.get("algo") or "",
        "uf_scope": list(raw["ufs"]) if raw.get("ufs") else ["BR"],
        "escala_max": raw.get("escala_max", "regional"),
        "srs": raw.get("srs", "EPSG:4674"),
        "filtro": raw.get("filtro") or {"tipo": "bbox"},
        "requires_parquet": bool(raw.get("requer_parquet", False)),
        "unavailable_reason": raw.get("indisponivel"),
        "requires_login": raw.get("requer_login"),
        "arquivo_glob": list(raw.get("arquivo_glob") or []),
        "keywords": keywords,
        "verification_evidence": enr.get(
            "verification_evidence",
            f"Pinned GISBR catalog entry (commit {GISBR_PINNED_SHA[:8]}); live availability depends on upstream service.",
        ),
        "catalog_origin": "gisbr",
        "aliases": [],
        "_raw_gisbr": raw,
    }
    return entry


# ---------------------------------------------------------------------------
# Curated Indigenous and territorial overlay registry (separate from GISBR)
# ---------------------------------------------------------------------------

CURATED_INDIGENOUS_SOURCES: List[Dict[str, Any]] = [
    {
        "source_id": "funai_ti_boundaries",
        "name": "Indigenous Lands — Official Boundaries and Legal Status (FUNAI)",
        "name_pt": "Terras Indígenas — Limites Oficiais e Situação Jurídica (FUNAI)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "loadable",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "territory_boundary",
        "terms_checked": True,
        "machine_access_verified": True,
        "last_checked_at": "2026-11-24T20:23:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / CGGEO",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official geospatial dataset (check FUNAI attribution notice)",
        "attribution": "FUNAI / Coordenação-Geral de Geoprocessamento (CGGEO)",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geprocessamento",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "Funai:tis_poligonais",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "funai", "terra indigena", "terras indigenas", "ti", "tis",
            "indigenous territory", "indigenous territories", "indigenous land",
            "demarcacao", "homologada", "portaria", "situacao juridica", "cggeo",
            "tis_poligonais", "limites oficiais",
        ],
        "verification_evidence": (
            "Live WFS 2.0.0 verified (Funai:tis_poligonais) using bundled Sectigo Public Server "
            "Authentication CA OV R36 intermediate PEM (strict TLS preserved). Government GeoServer "
            "may go offline intermittently; offer geobr_terras_indigenas as dated mirror fallback."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["funai_tis_poligonais"],
    },
    {
        "source_id": "funai_ti_studies",
        "name": "Indigenous Lands Under Study (FUNAI — Discovery Only)",
        "name_pt": "Terras Indígenas em Estudo (FUNAI — Somente Consulta)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "discovery_only",
        "load_policy": "discovery_only",
        "sensitivity": "restricted_locality_point",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / CGGEO",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official catalog (discovery-only due to point/study sensitivity)",
        "attribution": "FUNAI / CGGEO",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "funai", "em estudo", "under study", "terra indigena", "indigenous study",
        ],
        "verification_evidence": (
            "Listed on FUNAI GeoServer catalog page as point/study layer; held discovery_only "
            "so study points are not misrepresented as officially delimited polygons."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "funai_dsei_areas",
        "name": "DSEI Operational Health Jurisdiction Areas (FUNAI / SESAI)",
        "name_pt": "Áreas de Atuação dos DSEIs — Jurisdição Operacional de Saúde (FUNAI / SESAI)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "pending_probe",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "territory_boundary",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / SESAI (Ministério da Saúde)",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official dataset (operational health district coverage)",
        "attribution": "FUNAI / SESAI — DSEI operational health coverage (NOT TI demarcation boundaries)",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "dsei", "dseis", "sesai", "saude indigena", "distrito sanitario especial indigena",
            "area de atuacao", "operational jurisdiction", "health district", "funai",
        ],
        "verification_evidence": (
            "Documented on FUNAI GeoServer page ('Área de Atuação ... DSEI (polígono)'); "
            "represents SESAI health-service coverage, NOT TI legal demarcation boundaries. "
            "Exact WFS typename requires GetCapabilities verification once FUNAI TLS chain resolves."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["sesai_dsei_areas"],
    },
    {
        "source_id": "funai_dsei_headquarters",
        "name": "DSEI Headquarters Administrative Points (FUNAI / SESAI)",
        "name_pt": "Sedes Administrativas dos DSEIs (FUNAI / SESAI)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "pending_probe",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "administrative_point",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / SESAI",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official administrative office locations",
        "attribution": "FUNAI / SESAI",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": ["dsei", "sede", "headquarters", "sesai", "funai", "escritorio"],
        "verification_evidence": "Public administrative office points listed on FUNAI GeoServer page; pending GetCapabilities probe.",
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "funai_regional_offices",
        "name": "FUNAI Regional Coordinations and Technical Units (CR / CTL)",
        "name_pt": "Coordenações Regionais e Unidades Técnicas Locais da FUNAI (CR / CTL)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "loadable",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "administrative_point",
        "terms_checked": True,
        "machine_access_verified": True,
        "last_checked_at": "2026-11-24T20:23:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / CGGEO",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official administrative office locations",
        "attribution": "FUNAI / CGGEO",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "Funai:tis_cr",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": ["funai", "cr", "ctl", "coordenacao regional", "regional offices"],
        "verification_evidence": (
            "Live WFS 2.0.0 verified (Funai:tis_cr; Funai:tis_ctl also exposed) using bundled "
            "Sectigo intermediate PEM (strict TLS preserved). Subject to intermittent upstream availability."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "funai_indigenous_villages",
        "name": "FUNAI Indigenous Village Points (Discovery Only — Auto-Load Blocked)",
        "name_pt": "Aldeias Indígenas (FUNAI — Somente Descoberta; Carga Automática Bloqueada)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "discovery_only",
        "load_policy": "discovery_only",
        "sensitivity": "restricted_locality_point",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "FUNAI / CGGEO",
        "distributor": "FUNAI GeoServer",
        "protocol": "wfs",
        "license": "Public official catalog — restricted locality point governance",
        "attribution": "FUNAI / CGGEO (discovery-only; exact village coordinates blocked from automatic ingestion)",
        "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai",
        "service_url": "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "aldeias", "aldeia", "villages", "indigenous villages", "funai",
            "funai_villages", "pontos de aldeias",
        ],
        "verification_evidence": (
            "Listed on FUNAI download/GeoServer catalog; held discovery_only in v1 because "
            "exact village point locations require end-to-end egress protection across generic PyQGIS/MCP/export paths."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["funai_villages"],
    },
    {
        "source_id": "ibge_indigenous_localities_2022",
        "name": "IBGE 2022 Census Indigenous Localities (Discovery Only — Corrected Release)",
        "name_pt": "Localidades Indígenas — Censo IBGE 2022 (Somente Descoberta; Arquivos Revisados)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "official_direct",
        "loader_state": "discovery_only",
        "load_policy": "discovery_only",
        "sensitivity": "restricted_locality_point",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": 2022,
        "available_years": [2022],
        "publisher": "IBGE",
        "distributor": "IBGE Geociências",
        "protocol": "official_download",
        "license": "IBGE Open Data (statistical census reference; restricted locality points)",
        "attribution": "IBGE — Censo Demográfico 2022 / Localidades Indígenas (arquivos revisados/substituídos)",
        "portal_url": "https://www.ibge.gov.br/geociencias/organizacao-do-territorio/estrutura-territorial/27385-localidades.html?edicao=42271",
        "service_url": "https://www.ibge.gov.br/geociencias/organizacao-do-territorio/estrutura-territorial/27385-localidades.html?edicao=42271",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "ibge", "localidades indigenas", "indigenous localities", "censo 2022",
            "census 2022", "aldeias", "comunidades", "agrupamentos indigenas",
        ],
        "verification_evidence": (
            "Documented on IBGE Localidades 2022 portal (revised/replaced files published). "
            "Distinct from FUNAI/SESAI administrative registries; exact locality points held discovery_only in v1."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "inpe_prodes",
        "name": "INPE / TerraBrasilis — PRODES Annual Deforestation Suppression",
        "name_pt": "INPE / TerraBrasilis — PRODES Desmatamento Anual (Supressão)",
        "axis": "environment",
        "axis_pt": "ambiental",
        "origin_class": "official_direct",
        "loader_state": "loadable",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "public",
        "terms_checked": True,
        "machine_access_verified": True,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": 2024,
        "available_years": list(range(2008, 2026)),
        "publisher": "INPE",
        "distributor": "INPE / TerraBrasilis",
        "protocol": "wfs",
        "license": "CC-BY-SA / INPE TerraBrasilis Open Data",
        "attribution": "INPE / TerraBrasilis — PRODES (annual deforestation suppression; not daily alerts)",
        "portal_url": "https://terrabrasilis.dpi.inpe.br/downloads/",
        "service_url": "https://terrabrasilis.dpi.inpe.br/geoserver/ows",
        "typename": "prodes-legal-amz:yearly_deforestation",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "inpe", "prodes", "terrabrasilis", "desmatamento", "deforestation",
            "supressao anual", "annual deforestation", "amazonia", "cerrado",
        ],
        "verification_evidence": (
            "Live WFS verified 2026-11-23 at terrabrasilis.dpi.inpe.br/geoserver/ows "
            "(GetCapabilities HTTP 200 + GetFeature prodes-legal-amz:yearly_deforestation EPSG:4674). "
            "Annual methodology by biome; distinct from DETER real-time alerts and MapBiomas land cover."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["terrabrasilis_prodes"],
    },
    {
        "source_id": "inpe_deter",
        "name": "INPE / TerraBrasilis — DETER Deforestation Monitoring Alerts",
        "name_pt": "INPE / TerraBrasilis — DETER Alertas de Monitoramento",
        "axis": "environment",
        "axis_pt": "ambiental",
        "origin_class": "official_direct",
        "loader_state": "loadable",
        "load_policy": "allowed_public_polygon",
        "sensitivity": "public",
        "terms_checked": True,
        "machine_access_verified": True,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": 2026,
        "available_years": None,
        "publisher": "INPE",
        "distributor": "INPE / TerraBrasilis",
        "protocol": "wfs",
        "license": "CC-BY-SA / INPE TerraBrasilis Open Data",
        "attribution": "INPE / TerraBrasilis — DETER (indicative monitoring alerts; NOT proof of illegality)",
        "portal_url": "https://terrabrasilis.dpi.inpe.br/faq/",
        "service_url": "https://terrabrasilis.dpi.inpe.br/geoserver/ows",
        "typename": "deter-amz:deter_amz",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "inpe", "deter", "terrabrasilis", "alertas", "desmatamento",
            "deforestation alerts", "monitoring alerts", "amazonia", "cerrado",
        ],
        "verification_evidence": (
            "Live GetCapabilities verified 2026-11-23 at terrabrasilis.dpi.inpe.br/geoserver/ows "
            "(layers deter-amz:deter_amz and deter-cerrado-nb:deter_cerrado). "
            "Indicative monitoring alerts only — not proof of crime or annual PRODES rate."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["terrabrasilis_deter"],
    },
    {
        "source_id": "isa_territories",
        "name": "ISA — Terras Indígenas no Brasil (Portal Only)",
        "name_pt": "ISA — Terras Indígenas no Brasil (Somente Portal para Consulta)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "non_government",
        "loader_state": "portal_only",
        "load_policy": "requires_terms_check",
        "sensitivity": "territory_boundary",
        "terms_checked": False,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "Instituto Socioambiental (ISA)",
        "distributor": "ISA Portal",
        "protocol": "portal_only",
        "license": "unknown — check ISA portal terms (no automated scraping permitted)",
        "attribution": "Instituto Socioambiental (ISA) — terrasindigenas.org.br",
        "portal_url": "https://terrasindigenas.org.br/pt-br/brasil",
        "service_url": "",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "isa", "instituto socioambiental", "terras indigenas", "ti", "tis",
            "indigenous territories", "portal", "historico",
        ],
        "verification_evidence": "Public civil-society reference portal; no bulk API/scraping license verified. Portal link-out only.",
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "mapi_isolated_peoples",
        "name": "Mapi — Monitoring of Pressures on Isolated Peoples (Blocked / Metadata Only)",
        "name_pt": "Mapi — Monitoramento de Ameaças a Povos Indígenas Isolados (Bloqueado / Somente Metadados)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "non_government",
        "loader_state": "blocked_sensitive",
        "load_policy": "blocked_sensitive",
        "sensitivity": "blocked_isolated_peoples",
        "terms_checked": True,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "COIAB + OPI (in collaboration with OPAN)",
        "distributor": "Mapi Platform",
        "protocol": "restricted",
        "license": "Sensitive Indigenous governance / CARE principles — automated geodata ingest prohibited",
        "attribution": "COIAB / OPI / OPAN — Plataforma Mapi (metadata & public methodology reference only)",
        "portal_url": "https://plataforma.povosisolados.org/",
        "service_url": "",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "mapi", "povos isolados", "isolated peoples", "coiab", "opi", "opan",
            "isolamento voluntario", "voluntary isolation", "pressoes", "ameacas",
        ],
        "verification_evidence": (
            "Blocked for any automated geodata ingest, coordinate extraction, or layer loading. "
            "Only coarse public institutional metadata and methodology link are exposed."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["mapi_povos_isolados"],
    },
    {
        "source_id": "raisg_indigenous_territories",
        "name": "RAISG — Pan-Amazon Indigenous Territories (Portal / Attribution Review)",
        "name_pt": "RAISG — Territórios Indígenas da Amazônia (Portal / Revisão de Termos)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "non_government",
        "loader_state": "portal_only",
        "load_policy": "requires_terms_check",
        "sensitivity": "territory_boundary",
        "terms_checked": False,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": 2026,
        "available_years": None,
        "publisher": "RAISG (mixed original national contributors)",
        "distributor": "RAISG Maps & Downloads",
        "protocol": "portal_only",
        "license": "Per-theme attribution and terms specified in RAISG metadata (WMS is display-only, not editable vector)",
        "attribution": "RAISG — Rede Amazônica de Informação Socioambiental Georreferenciada",
        "portal_url": "https://www.raisg.org/pt-br/mapas/",
        "service_url": "",
        "typename": "",
        "uf_scope": ["AC", "AM", "AP", "MA", "MT", "PA", "RO", "RR", "TO"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": [
            "raisg", "amazonia", "pan-amazon", "terras indigenas", "territorios indigenas",
            "indigenous territories", "wms", "shapefile",
        ],
        "verification_evidence": (
            "RAISG publishes regional shapefiles and WMS; per-theme provenance and terms vary by "
            "original contributor. WMS is display-only and never represented as editable vector."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "raisg_pressures",
        "name": "RAISG — Amazon Territorial Pressures (Portal Only)",
        "name_pt": "RAISG — Pressões na Amazônia (Somente Portal)",
        "axis": "indigenous_territories",
        "axis_pt": "terras_indigenas",
        "origin_class": "non_government",
        "loader_state": "portal_only",
        "load_policy": "requires_terms_check",
        "sensitivity": "public",
        "terms_checked": False,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "RAISG (mixed original contributors)",
        "distributor": "RAISG Maps & Downloads",
        "protocol": "portal_only",
        "license": "Per-theme attribution and terms specified in RAISG metadata",
        "attribution": "RAISG",
        "portal_url": "https://www.raisg.org/pt-br/mapas/",
        "service_url": "",
        "typename": "",
        "uf_scope": ["AC", "AM", "AP", "MA", "MT", "PA", "RO", "RR", "TO"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": None,
        "arquivo_glob": [],
        "keywords": ["raisg", "pressoes", "pressures", "amazonia", "mineracao", "estradas"],
        "verification_evidence": "Historical/mixed-vintage regional pressure layers; portal discovery only without per-theme terms check.",
        "catalog_origin": "curated_indigenous",
        "aliases": [],
    },
    {
        "source_id": "mapbiomas_alerta",
        "name": "MapBiomas Alerta — Validated Deforestation Alerts (Portal / Registered API)",
        "name_pt": "MapBiomas Alerta — Alertas Validados de Desmatamento (Portal / API com Cadastro)",
        "axis": "environment",
        "axis_pt": "ambiental",
        "origin_class": "non_government",
        "loader_state": "portal_only",
        "load_policy": "requires_review_and_opt_in",
        "sensitivity": "public",
        "terms_checked": False,
        "machine_access_verified": False,
        "last_checked_at": "2026-11-23T21:52:00Z",
        "source_year": None,
        "available_years": None,
        "publisher": "MapBiomas Alerta",
        "distributor": "MapBiomas Alerta Platform",
        "protocol": "portal_only",
        "license": "MapBiomas Alerta Terms (API requires registered account; Shapefile portal download)",
        "attribution": "MapBiomas Alerta (distinct from MapBiomas annual land-cover Collection 9)",
        "portal_url": "https://alerta.mapbiomas.org/",
        "service_url": "https://plataforma.alerta.mapbiomas.org/api/docs/index.html",
        "typename": "",
        "uf_scope": ["BR"],
        "escala_max": "macrorregiao",
        "srs": "EPSG:4674",
        "filtro": {"tipo": "bbox"},
        "requires_parquet": False,
        "unavailable_reason": None,
        "requires_login": "MapBiomas Alerta account",
        "arquivo_glob": [],
        "keywords": [
            "mapbiomas alerta", "mapbiomas_alerts", "alertas", "desmatamento",
            "deforestation alerts", "validated alerts", "laudos",
        ],
        "verification_evidence": (
            "API requires user registration and terms acceptance; no unattended auth bypass. "
            "Portal link-out and manual download guidance provided; distinct from GISBR mapbiomas_cobertura."
        ),
        "catalog_origin": "curated_indigenous",
        "aliases": ["mapbiomas_alerts"],
    },
]
