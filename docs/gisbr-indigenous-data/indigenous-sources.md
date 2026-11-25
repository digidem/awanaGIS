> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# Indigenous and territorial data source inventory — AgenticGIS Brazil integration

**Date reviewed:** 2026-11-23  
**Status:** Evidence-based implementation inventory, **not** a claim of live endpoint availability.  
**Companions:** `spec.md` (requirements), `plan.md` (execution), `prompt.md` (developer instructions).  
**Rule:** Implement from primary-source documentation and successful runtime probes; never invent WFS layer names, years, exact coordinates, licenses, or API capabilities.

## 1. Why this inventory is separate

The existing GISBR `gisbr/core/sources.py` contains `geobr_terras_indigenas` and related mining/conservation datasets but **does not provide a complete official FUNAI, SESAI/DSEI, Indigenous Census, or isolated-peoples workflow**. The `fontes-detalhe.md` linked in our initial brief lists only a subset of GISBR WFS/ArcGIS sources. Add a **curated, versioned, auditable overlay registry** alongside the pinned GISBR catalog. Share the same discover/details/resolve/plan/load tools; **do not fork GISBR's original source IDs or add a tool for every dataset**.

`documented` means an institutional page names the resource. `machine_access_verified` means the development agent **actually exercised** a stable, permitted endpoint or official download in its target QGIS environment. Documentation alone never implies `reachable`, `loadable`, `complete`, or `up_to_date`.

## 2. Priority source matrix

| Proposed stable overlay ID | Publisher / authority | What it contributes | Public evidence | Initial delivery status | Sensitivity / integration gate |
|---|---|---|---|---|---|
| `funai_ti_boundaries` | FUNAI / CGGEO — **official direct** | TI polygons; identify legal recognition stage when field supported | FUNAI GeoServer and geospatial downloads | **P0**: implement after WFS/download verification | Territorial polygon; read-only discovery and planned load permitted. Preserve full status/portarias, vintage and attribution. |
| `funai_ti_studies` | FUNAI / CGGEO — **official direct** | Areas under study and associated administrative context | FUNAI download list | P1: discovery now; load only after exact geometry type/meaning reviewed | **Do not call a point an officially delimited territory polygon**; avoid exposing sensitive study points by default. |
| `funai_dsei_areas` | FUNAI-published DSEI operational polygons, SESAI thematic authority — **official direct** | DSEI service-area polygons, distinct from TI legal boundaries | FUNAI GeoServer lists “Área de Atuação ... DSEI (polígono)” | **P0**: implement after capabilities and source year check | Territorial/administrative area; describe DSEI boundaries as health-service coverage, not demarcation or population census. |
| `funai_dsei_headquarters` | FUNAI-published DSEI locations / SESAI — **official direct** | DSEI headquarters as point features | FUNAI GeoServer lists “Localização da Sede ... DSEI (ponto)” | P1: optional | Public administrative office points only; do not infer health outcomes or individual locations. |
| `funai_regional_offices` | FUNAI / CGGEO — **official direct** | CR/CTL public administrative locations | FUNAI GeoServer/download page | P1: optional | Use only public official office points, preserving precise agency role. |
| `funai_villages` | FUNAI / CGGEO — **official direct** | Publicly published village points | FUNAI download page and GeoServer catalog | **Discovery-only by default** | **Sensitive potential harm**: exact locations may reveal community access or vulnerability. No automated ingestion into remote LLM-visible project until explicit opt-in and end-to-end egress enforcement is proven; otherwise omit the loader. |
| `ibge_indigenous_localities_2022` | IBGE — **official direct** | 2022 Indigenous localities and contextual Census geographies/statistics | IBGE Localidades do Brasil / Censo 2022 | **P1**: discover; implement bounded load only with protections | Distinguish 2022 census locality points from FUNAI/SIASI/SESAI registries. IBGE has published replacement files after corrections; use current corrected package and provenance. Locality points get restricted-by-default handling. |
| `inpe_prodes` | INPE / TerraBrasilis — **official direct** | Annual deforestation/suppression maps by monitored biome/year | INPE TerraBrasilis downloads and WFS FAQ | **P0**: proof-of-concept official disturbance layer | **Annual**, methodology/biome-specific, not daily alerts. Bound by TI or municipality; validate exact published layer. |
| `inpe_deter` | INPE / TerraBrasilis — **official direct** | DETER monitoring alerts for supported biomes/periods | INPE TerraBrasilis downloads/FAQ | **P1**: first official alert feed after source validation | DETER alerts are monitoring signals, **not** evidence of crime, nor identical to annual PRODES rates. Respect publication periods, caveats, and geometry/area thresholds. |
| `isa_territories` | Instituto Socioambiental (ISA) — **civil society** | Complementary TI registry, status, historical context, sources | `terrasindigenas.org.br/pt-br/brasil` | **Discovery/link-out and metadata only** until permission/API established | Do not assume site's web page or embedded map is a public bulk-download API; no automated crawling/scraping without verified permission and terms. Compare differing polygon versions instead of silent substitutions. |
| `mapi_isolated_peoples` | COIAB + OPI, in collaboration with OPAN — **civil society** | Context about territorial pressures/vulnerabilities of peoples in voluntary isolation | Mapi platform methodology and OPI publication | **Metadata/documentation only (P0)** | **High sensitivity**: no automated collection, reconstruction, export, map overlay, or remote-model exposure of presence points/routes/sighting-level locations. Show only authorized, public, coarse-scale territorial context; do not build a “find isolated groups near X” workflow. |
| `raisg_indigenous_territories` | RAISG / mixed original contributors — **civil-society network / mixed provenance** | Pan-Amazon territorial shapefiles, WMS, regional context | RAISG 2026 downloads/WMS page | P1: load only after per-layer terms/attribution verification | WMS is **view-only**, not a queryable feature layer. Prefer permitted shapefile/feature source for manipulations; observe per-theme citations. |
| `raisg_pressures` | RAISG / mixed original contributors | Protected areas, roads, mining and other pressure layers | RAISG maps/downloads | P2/optional | Source-specific reference years vary (some historical). Don't imply current logging/mining solely from mapped historical layers. |
| `mapbiomas_alerts` | MapBiomas Alerta — **civil society** | Validated deforestation alerts, published Shapefile/API | MapBiomas Alerta FAQ/API docs | P1: discovery/link-out; conditional API adapter | API may require a registered account and terms; no unattended account creation/auth bypass. Distinguish from GISBR's `mapbiomas_cobertura` land-cover COG. |

**P0 means essential to the Indigenous workflows of this release, P1 means candidate expansion / permitted staged gate, P2 means optional follow-up.** The user-visible source catalog must still discover every documented source, including `portal_only` / `restricted`; **a claim of successful load requires real live or fixture-backed implementation**. If FUNAI's endpoint cannot be reached during development, retain `funai_*` as discoverable but `unverified/unavailable`, and offer the user a transparently labeled alternative `geobr_terras_indigenas` without silently replacing FUNAI boundaries.

## 3. Primary references and verification notes

### FUNAI — official land and DSEI services

- [GeoServer catalog page](https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geoserver-funai): FUNAI lists TI polygons, TI polygons with Portarias/dates, studied territories as points, village points, CR and CTL points, **DSEI service-area polygons and headquarters**.
- [Official download page](https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geprocessamento): describes periodic updates, SHP/KML/XLSX/CSV/ODS resources, and an attribution notice; **check dataset-specific exceptions**.
- Official page links to `https://geoserver.funai.gov.br/geoserver/Funai/ows` and advertises e.g. `Funai:tis_poligonais` as a WFS downloadable layer. **This URL is a documented candidate, not a confirmed successful runtime probe:** automated retrieval in the research environment encountered upstream errors. `GetCapabilities` must validate available layer names, supported filter/CRS, response types, page limits, and actual download. Never assume DSEI layer IDs based on the page wording.
- Separate legal TI status (em estudo, delimitada, declarada, homologada, reservada, etc.) from polygon completeness and from DSEI health-administration areas. Do not conflate agency jurisdiction or public-service coverage with entitlement or residence.

### IBGE — Indigenous locality and census geography

- [Localidades do Brasil](https://www.ibge.gov.br/geociencias/organizacao-do-territorio/estrutura-territorial/27385-localidades.html?edicao=42271): includes publicly distributed vector files, Indigenous localities and location methodologies.
- IBGE reports **revised/replaced downloads** for certain 2022 Indigenous-localities files; use the corrected published set and record the publication/revision date. The Census's spatial classification **does not replace FUNAI or SESAI administrative registries**.
- A census-locality point is not equivalent to a TI perimeter. Census figures describe the **reference year and statistical unit**, not necessarily a population today. Guard against singling out or deriving locations from small counts.

### INPE / TerraBrasilis — pressure layers

- [TerraBrasilis downloads](https://terrabrasilis.dpi.inpe.br/downloads/) and [FAQ/WFS documentation](https://terrabrasilis.dpi.inpe.br/faq/). The portal advertises PRODES and DETER datasets and WFS via `https://terrabrasilis.dpi.inpe.br/geoserver/ows`.
- Runtime must discover and validate the actual layers, temporal attributes, biome/coverage, download limitations and licensing before enabling loads. Clip/join to **public TI polygons**, not alleged positions of isolated groups. Alerts are **indicative**; comparisons must name the data/reference dates and update cadence.

### ISA, Mapi, RAISG, MapBiomas Alerta — distinguish publisher and access

- [ISA — Terras Indígenas no Brasil](https://terrasindigenas.org.br/pt-br/brasil): public browsing of registered Indigenous lands, administrative phases, and complementary context. **No bulk vector/API access or reuse license was independently verified in this review**; start as source discovery, reference and portal link-out.
- [Mapi](https://plataforma.povosisolados.org/) / [Mapi methodology](https://plataforma.povosisolados.org/metodologia) / [OPI launch description](https://povosisolados.org/no-dia-internacional-dos-direitos-humanos-coiab-e-opi-lancam-plataforma-mapi-de-monitoramento-de-ameacas-e-pressoes-a-povos-indigenas-isolados/): publicly described vulnerability/pressure analysis, not a blanket consent to reproduce fine-grained presence records. The specific user-linked `/mapa` path **could not be fetched successfully during this review**; do not assume it is a stable API or direct data endpoint. Respect provenance, consultation, terms and safety review; no automated ingestion of exact isolated-presence geodata in this project.
- [RAISG maps and downloads](https://www.raisg.org/pt-br/mapas/): publishes **2026 Indigenous territory shapefile** and other regional downloads plus WMS endpoints. The site explicitly says original data owners vary and citations are specified **per theme in metadata**. These are not automatically Brazilian-government source layers.
- [MapBiomas Alerta FAQ](https://alerta.mapbiomas.org/perguntas-frequentes/) / [API docs](https://plataforma.alerta.mapbiomas.org/api/docs/index.html): describes Shapefile downloads, a QGIS plugin, and an API for registered users. Do not add this to the default government-only results; check terms/auth before writing an adapter.

## 4. Required registry schema (overlay, **not** GISBR source dict edits)

Each candidate added to our overlay is **declarative**, versioned and validated. Suggested fields (adapt serialization to real code):

```json
{
  "id": "funai_ti_boundaries",
  "title_pt_br": "Terras indígenas — limites oficiais (FUNAI)",
  "publisher": "FUNAI",
  "origin_class": "official_direct",
  "category": "indigenous_territories",
  "protocol": "wfs",
  "portal_url": "https://www.gov.br/funai/pt-br/atuacao/terras-indigenas/geoprocessamento-e-mapas/geprocessamento",
  "access_mode": "official_wfs",
  "load_policy": "allowed_public_polygon",
  "loader_state": "pending_probe",
  "sensitivity": "territory_boundary",
  "year": null,
  "machine_access_verified": false,
  "terms_verified": false,
  "last_checked_at": null
}
```

Additional recommended fields: `original_dataset_id`, `service_url`, `typename`, `file_format`, `geometry_kind`, `default_extent`, `coverage`, `reference_period`, `extraction_date`, `license_url`, `attribution_text`, `metadata_url`, `endpoint_probe_method`, `supported_scopes`, `requires_auth`, `needs_user_file`, `cost_size_estimate`, `known_limits`, `record_corrections`, `classification_basis`, `sensitivity_reason`, `review_owner`, `reviewed_on`. **Unknown fields remain null/unknown, not guessed.** Do not serialize runtime credentials or private coordinates into this manifest. IDs may be renamed before release but must then remain stable with migration alias tests.

`access_mode` must distinguish `gisbr`, `official_wfs`, `official_download`, `third_party_download`, `portal_only`, `manual_import`, `restricted`. `load_policy` must distinguish `allowed_public_polygon`, `requires_terms_check`, `requires_review_and_opt_in`, `discovery_only`, `blocked_sensitive`. `loader_state` must distinguish `loadable`, `pending_probe`, `portal_only`, `discovery_only`, `blocked_sensitive`, `manual_required`, `unavailable`. Map the tool-facing `publisher_type="official"` to registry `origin_class="official_direct"` consistently. The example intentionally has `pending_probe`: documented endpoints are **not** automatically usable.

### Catalog merge and deduplication

1. Read GISBR's pinned `SOURCES`, then overlay validated entries. Never mask a GISBR ID; every new overlay ID must be unique. Keep original source record intact for upgradeability.
2. Normalize labels and aliases (`TI`, `terra indígena`, `território tradicional`, `FUNAI`, `DSEI`, `SESAI`, `Distrito Sanitário Especial Indígena`, `IBGE`, `PRODES`, `DETER`, `ISA`, `RAISG`, `Mapi`, `povos isolados`) for PT-BR/EN search.
3. Preserve **original publisher**, **distributor**, geometry source, measured vintage, original URL and license. FUNAI official boundary and geobr/IPEA-derived boundaries may differ and are **not** the same dataset release. Return them as alternatives rather than silently deduplicating by name.
4. No HTML scraping; portal-only sources return title/description/URL/access restrictions. A WMS raster overlay is not a vector feature download. Remote QGIS network requests use allowlisted hosts and documented resource paths, not model-supplied arbitrary URLs.
5. New official-data source loading must reuse GISBR's WFS/download connector *where technically compatible* or a narrowly scoped, tested adapter. Do not depend on installing another public plugin.

## 5. Territory selection and analysis behavior

- Add **`indigenous_territory`** as an explicit area type in `br_resolve_area`, alongside municipality, UF, region and existing QGIS polygon layers. Resolve by an actual FUNAI identifier when present, or source-qualified territory name plus UF with candidate disambiguation; use public TI polygon geometry, not a name-derived bounding rectangle. Permit source-specific name matching but **do not assume identically spelled territories are identical**.
- An Indigenous TI area may span municipalities/states; do not force a municipality-only GISBR `Recorte`. If a connector requires municipal code, plan an explicit supported multi-scope strategy or return `unsupported` with details. For publicly documented TI polygons, clip by real geometry and record exact intersection and CRS assumptions.
- Provide safe default workflows: **TI boundaries + DSEI areas**, **TI boundaries + ANM/ICMBio/SICAR**, and **TI boundaries + PRODES/DETER** if verified. A simple overlap implies **spatial intersection only**, not permission, demarcation, illegality, health outcome, or unauthorized occupation.
- Prefer a FUNAI primary dataset for official recognition status. If unavailable, offer `geobr_terras_indigenas` with **original-data vintage clearly labeled** and explicit user selection. ISA/RAISG records can be used for comparative, sourced context, never asserted to be the legal cadastral boundary without validation.
- Preserve source geometry/attributes in the original output while rendering filtered/derived layers appropriately. For user-requested DSEI/TI intersections, note that DSEI operational coverage and TI recognition polygons are different administrative concepts.
- For publicly distributed Indigenous localities and village points, the default is **discovery-only** unless explicit user opt-in, terms/rights review, a safe local workflow and **effective enforcement across all existing chat, MCP, PyQGIS and export tools** are proven. Otherwise, do not auto-load precise point features. For Mapi/isolated peoples, **only coarse, authorized public territorial context** is eligible; exact presence/sighting/location records remain blocked from automated ingestion and model output.

## 6. Privacy, safety, Indigenous data governance and abuse resistance

1. Source is public ≠ blanket permission for every secondary use. Respect source license, attribution, source corrections, Indigenous community protocols and **CARE principles** (Collective Benefit, Authority to Control, Responsibility, Ethics) where applicable; do not suggest community consent where none has been obtained.
2. Never automatically derive, reveal, query, rank, join, buffer, export or summarize precise isolated-peoples sightings, travel routes, contact sites, camp locations, or inferred locations from mosaicked datasets. Only coarse published territorial/pressure context may be described, without pinpointing locations.
3. No auto-loading a precise sensitive layer just because it is served by an official GeoServer. **Block at catalog/planner/execution**; don't rely on an LLM safety instruction or a UI warning. If a layer is conditionally allowed, the developer must prove it cannot leak coordinates/attributes through `run_pyqgis`, `get_project_state`, summaries, error traces, exports, AgenticGIS API/CLI/MCP, model transcript history or the optional local bridge. If that enforcement cannot be achieved without unsafe architectural changes, ship those sources **discovery-only**.
4. Preflight and approval cannot authorize access to Mapi's presence-record geometry in v1. Do not use network requests or scraped JS to reconstruct unavailable or fine-resolution datasets. Surface transparent source link and restrictions instead.
5. No telemetry and no implicit uploads of downloaded geodata or geometry to the configured LLM provider. Tool responses include **source IDs, names, bounded counts and general area**; sensitive fields/coordinates/GeoJSON are never included. Redact sensitive exception traces, cache paths and credentials. Make user exports explicit and respect restricted layer policies.
6. Defensively prevent **composition leakage**: if a combination of otherwise coarse layers would reveal a precise restricted location, suppress location-specific outputs and give a general territorial-pressure summary or decline that operation.
7. Include offline fixtures using **synthetic, non-real sensitive points** for negative tests. No production logs, screenshots or test fixtures should carry real isolated-peoples coordinates or other confidential Indigenous data.

## 7. Tiered deliverables / verification gates

**Required for v1:**

- **Catalog discovery:** Every source in §2 is discoverable with honest `official_direct`/`official_mirror`/`non_government` and `loadable`/`portal_only`/`blocked_sensitive` state; descriptions and portals in PT-BR/EN. GISBR preexisting source IDs remain functional.
- **Real official loading:** After source-protocol verification, demonstrate a **FUNAI TI boundary**, a **FUNAI DSEI area** and at least one **INPE PRODES or DETER pressure** source as genuine QGIS layers, filtered/clip-safe and manipulable by the existing tools. If an official service is genuinely unavailable, do not counterfeit success: include fixture-driven adapter tests and mark service-dependent release limitations. At least one non-GISBR official overlay loader must be exercised live for full readiness.
- **Territory resolver:** A real Indigenous territory name or official ID can be resolved to a unique polygon or a disambiguation list and used as a clipping area. Municipal lookup continues to work.
- **Safety:** `mapi_isolated_peoples` must remain metadata-only; FUNAI village/IBGE locality exact-point auto-load remains disabled unless the specified rigorous protection has passed. All negative tests in SPEC pass.
- **Provenance:** Layer outputs preserve original dataset, institution, distribution portal, checked/downloaded times, correction status, source revision, local clip, legal/temporal meaning and explicit attribution.

**Optional but valuable:** permitted RAISG shapefile download adapter (with source-specific attribution), MapBiomas Alerta registered-API adapter after access/terms verification, extra FUNAI CR/CTL offices and DSEI headquarters.

**Gate labels:** `PASS` (verified in runtime), `PASS_WITH_LIMITATIONS` (supported by deterministic fixture but live service not demonstrated), `BLOCKED` (access/terms/sensitivity), `NOT_RUN` (missing environment), `FAIL` (actual regression). The final release must state which Indigenous sources are real loadable features and which are only catalog/links. **No unconditional “ready” label if required FUNAI/DSEI/INPE live paths remain untested.**
