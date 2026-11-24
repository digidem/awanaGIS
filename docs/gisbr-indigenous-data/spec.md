> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# SPEC — Brazilian and Indigenous Public Geospatial Data in AgenticGIS (GISBR + curated sources)

**Status:** Final reviewed developer-agent specification — Indigenous dataset expansion incorporated  
**Target:** Our independently distributed AgenticGIS fork. **Do not submit this feature upstream.**  
**Language:** User-facing behavior in PT-BR where QGIS is PT-BR, English otherwise, consistent with the existing internationalization work.  
**Prepared:** 2026-11-23

## 0. Authority, baselines, and boundaries

This specification is authoritative for *what* the integration must accomplish. `plan.md` defines the execution order; `prompt.md` initiates the coding agent; `indigenous-sources.md` is the **required evidence and data-source policy matrix**.

Reference repositories as inspected on 2026-11-23:

- AgenticGIS upstream: <https://github.com/ultramenid/AgenticGIS>, `main` commit `1e4f70b488824982a835c89c202454ec92dafae7` (2026-10-05). **Our actual fork/worktree may already be ahead**, especially for PT-BR: inspect and preserve its current commits. Do not reset to this upstream SHA.
- GISBR: <https://github.com/d-camargo/gisbr>, `main` commit `06d84dfab9942e4e840637bb8d8f96af173330ad` (2026-11-18). Pin an exact GISBR commit in the shipped integration; record any subsequent selected revision and why.
- GISBR implemented catalog: <https://github.com/d-camargo/gisbr/blob/main/gisbr/core/sources.py> (authoritative *implemented source IDs/metadata*, not a guarantee of current endpoint health).
- Detailed source hardening notes: <https://github.com/d-camargo/gisbr/blob/main/docs/diagnostico-plano-diretor/fontes-detalhe.md>. **This document enumerates 18 WFS/ArcGIS source entries, not the full implemented catalog.** Other protocols/sources appear in `sources.py` and accompanying docs.
- GISBR architecture: <https://github.com/d-camargo/gisbr/blob/main/docs/diagnostico-plano-diretor/ARQUITETURA.md>; diagnostic engine: `gisbr/core/diagnostico.py`; geographic scopes: `gisbr/core/recorte.py`; Processing provider: `gisbr/provider.py`.
- GISBR reference docs: <https://gisbr.dcamargo.com.br/>.
- **Indigenous-data evidence and implementation inventory:** [`indigenous-sources.md`](./indigenous-sources.md), including FUNAI, DSEI/SESAI, IBGE Indigenous localities, INPE PRODES/DETER, ISA, Mapi, RAISG and MapBiomas Alerta. This inventory records documentation, NOT confirmed endpoint availability or permission to bulk download.

**Important**: The repository advertises **75 thematic data sources across nine axes**, plus a satellite basemap entry in the source registry (76 `id` entries at inspected commit). Its Processing provider advertises **57 algorithms**. These numbers describe the inspected version, not guaranteed counts across future updates. Never treat an entry as live, official, freely redistributable, up-to-date, or universally available solely because it appears in the registry.

**Integration boundary:** GISBR supplies its own source knowledge, connectors, geographic filtering, diagnostic loading, and selected geobr/censobr algorithms. A **small, separately maintained Indigenous/territorial overlay source registry** covers high-priority official and non-government sources absent from GISBR. AgenticGIS supplies intent interpretation, orchestration, approval, conversational progress, project state, and subsequent GIS operations. Reuse established connectors where compatible; create only narrowly-scoped tested adapters for missing protocols, not another full GISBR panel.

## 1. Product goal

From a natural-language request in AgenticGIS, a QGIS user can:

1. **Discover** relevant Brazilian geospatial sources by subject, publisher, dataset, place, time, and scale, even before downloading.
2. **Inspect** a source's authoritative origin, geographic and temporal coverage, spatial resolution (where known), protocol, license/terms, reliability, limitations, and expected cost/size (only if measured).
3. **Resolve** an unambiguous Brazilian geographic scope (municipality by 7-digit IBGE code, UF, supported regional aggregate, or an existing QGIS geometry layer); disambiguate place names before loading.
4. **Preview/plan** which layers can be loaded for that scope, which must be skipped, what files will be written, and where permissions or optional capabilities are needed.
5. **Fetch, filter/clip, persist, and add** eligible layers to QGIS with documented provenance, safe controls, cancellation, partial-result handling, and status reports.
6. **Operate on approved, non-sensitive layers** using AgenticGIS's existing QGIS tools: spatial/attribute filtering, selections, joins, intersections, buffers, statistics, styling, tables, charts, layouts, and export. A loaded layer must be usable by its *actual returned layer ID* on the next tool call.

**Illustrative requests (must be demonstrated, not hardcoded):**

- “Busque terras indígenas, unidades de conservação e processos minerários na área de São Félix do Xingu (PA), adicione ao QGIS e identifique sobreposições.”
- “Quais bases oficiais de hidrografia e saneamento existem para este município? Mostre a fonte, o ano dos dados e quais estão disponíveis antes de baixar.”
- “Baixe a malha municipal de Alto Paraíso de Goiás e filtre as rodovias estaduais para o recorte.”
- “Encontre fontes de cobertura/uso da terra e explique se representam desmatamento recente ou apenas classes de cobertura em determinado ano.”
- “Compare a distribuição de unidades de conservação por tipo no meu projeto e exporte o resultado como GeoPackage.”
- “Encontre os polígonos oficiais da FUNAI para uma terra indígena e os limites operacionais dos DSEIs que a atendem; mostre onde as áreas se intersectam e a proveniência de cada base.”
- “Quais são os dados públicos da FUNAI, IBGE, ISA, RAISG e Mapi sobre terras indígenas? Separe as camadas vetoriais realmente disponíveis dos portais para consulta e das fontes sensíveis que não devem ser importadas automaticamente.”
- “Mostre os polígonos públicos de PRODES/DETER que cruzam esta TI e explique a diferença entre supressão anual e alerta de monitoramento, sem inferir automaticamente ilegalidade.”

Never invent a source or assert coverage based on the model's general knowledge. In the last example, if the loaded data are not sufficient for the requested statistics, explain the limitation.

## 2. Non-goals and exclusions

- No PR or feature work submitted to **ultramenid/AgenticGIS** as part of this project.
- No deployment of a separate web app or server, remote GIS service, LLM search engine, or autonomous browser scraper.
- No general-purpose arbitrary-web geospatial scraper or connector for every Brazilian portal. **v1 merges the pinned GISBR catalog with the explicitly scoped, versioned Indigenous/territorial registry** in `indigenous-sources.md`. The overlay adds specifically verified FUNAI/DSEI/INPE capabilities; ISA/Mapi and other sources with unverified machine access remain discovery/metadata-only. Future expansions require their own source review.
- No claim that *MapBiomas land-cover collection* is a live deforestation alert or that historical layers are current; PRODES/DETER are **not presumed to be included** in GISBR unless separately validated and explicitly added in a future scope.
- No automatic bypass of gov.br login or scraping of protected INCRA/SIGEF; manual-file import is offered with clear instructions when permitted.
- No automatic downloading of the entire country, large states, all 75 sources, or costly rasters without a size-aware plan and explicit approval.
- No silent installation of `pyarrow`, GISBR, other system Python packages, or QGIS plugins.
- No automatic alteration of project CRS, deletion of preexisting files, replacement of user layers, or publishing/exporting sensitive local project data.
- No automatic collection, extrapolation, export or pinpointed reporting of **isolated peoples’ presence/sighting sites**, nor blanket automated loading of village/locality points just because an official portal publishes them. No unauthorized scraping of ISA/Mapi maps.
- No duplicate GISBR diagnostic dock or extra unrelated preferences UI unless essential.

## 3. Verified technical context and integration constraints

### 3.1 AgenticGIS, at inspected upstream baseline

- `core/tools.py` holds **static tool specifications**, maps tool names to toolkit methods, and `dispatch` chooses execution strategy.
- `core/toolkit.py` is the QGIS capability layer; it already implements `run_processing`, `run_processing_background`, `get_algorithm_parameters`, `list_processing_algorithms`, `list_layers`, `add_layer`, analysis and styling operations; `core/processing_tasks.py` uses a cancellable QGIS Processing runner.
- `core/executor.py` routes GUI/project operations to the main thread; `backends/*`, `server/mcp_server.py` and MCP stdio mirror depend on consistent tool contracts. New tools must work across **API, CLI and MCP**, not only inside one chat backend.
- `plugin.py` owns lifecycle, config, toolkit, dock and backend; it must register and release any packaged GISBR provider without leaving live duplicates after reload/unload.
- AgenticGIS `metadata.txt` declares QGIS **3.22+** and QGIS 4.x. Use the fork's actual supported matrix if it changes.
- AgenticGIS has an existing external-access permission pathway; new download tools must be classified appropriately and must not silently bypass it.
- The upstream `.gitignore` excludes `tests/`, `docs/`, and `*.md` except README. Ensure new tests/docs and development specs are tracked intentionally in our fork with narrowly scoped `.gitignore` exceptions. The release ZIP must contain **runtime code/data/licenses/translations**, not necessarily implementation-only specs/tests.

### 3.2 GISBR, at inspected baseline

- `gisbr/core/sources.py`: declarative source dictionaries, fields such as `id`, `eixo`, `nome`, `protocolo`, `endpoint` / URLs, `filtro`, `escala_max`, `ufs`, `licenca`, and protocol-specific options. It contains national **and UF-limited** sources, plus manual, derived, OSM, raster and basemap sources.
- `gisbr/core/diagnostico.py`: `carregar_fontes(source_ids, code_muni, nome_muni, bbox, gpkg_path, ..., recorte=..., censo_ano=..., mapbiomas_ano=...)`. It returns grouped `ok`, `falhou`, `pulou` status lists; it can directly create GeoPackage outputs and add layers to the current project. Treat this as a mutable **internal function**, not a guaranteed version-stable public API. Inspect runtime behavior and thread assumptions before adoption.
- `gisbr/core/recorte.py`: `Recorte.de_municipio`, `de_rm`, `de_agregado`, and layer resolution; supports municipality, RM, micro/meso, UF, macro and related aggregate types. **It contains an absolute `from gisbr.core.constants` import and calls literal `gisbr:<algorithm>` IDs**; relocating it requires audited import/provider namespace changes.
- `gisbr/provider.py`: `QgsProcessingProvider` currently IDs itself `gisbr`; its algorithms include geobr v1 GeoPackage and v2 Parquet, censobr join and GISBR operations. The provider must not collide with an independently enabled official GISBR plugin.
- `gisbr/core/connectors/*`: WFS, ArcGIS REST, OSM, remote ZIP, manual local file, IBGE Agregados, COG raster, and other supported connectors. Some use QGIS network stack and license/SSL helpers. Keep existing truncation detection and HTTP-200-with-error parsing.
- **Output/CRS:** GISBR generally targets **SIRGAS 2000 / EPSG:4674**; individual inputs may have other CRSs, including raster sources. Validate CRS transforms, WFS axis order, spatial predicates and clip geometry. Do not reproject the QGIS project automatically.
- **Data age:** Source-specific *reference year/vintage* is distinct from extraction timestamp. For GISBR v2 Parquet, GDAL Parquet/Arrow or optional `pyarrow` is needed; v1 workflows must continue without it.
- **Manual access:** SIGEF/INCRA certified parcels require authenticated manual download; GISBR intentionally does not collect credentials.
- **Licensing:** AgenticGIS declares **GPL-2.0-or-later**; GISBR declares **GPL-3.0**. Distributing adapted GISBR code within our fork requires GPL-3-compatible distribution of the combined work, keeping the respective authorship, license texts and required notices. Verify per-file provenance and any bundled certificate/data licenses; do not use a misleading GPL-2-only license label. If uncertain, stop release packaging until reviewed.

### 3.3 Why `fontes-detalhe.md` alone is not sufficient

That Markdown file currently covers 18 WFS/ArcGIS metadata rows and records measurements from 2026-06-29. It is useful as a **source validation reference**, not the entire source list, not a live status oracle and not machine-executable policy. Use the pinned implemented `SOURCES` registry as a base; **merge a separate curated Indigenous/territorial registry** for absent sources (see `indigenous-sources.md`). Enrich missing provenance/reference-year/availability fields via a small sidecar manifest and per-source live checks, without editing upstream GISBR source entries unnecessarily.

## 4. Architecture: one installable AgenticGIS fork

**Required final distribution:** one self-contained installable fork of AgenticGIS providing Brazilian data tools out of the box, **without requiring the end user to install the separate GISBR plugin**. Internal optional `pyarrow` is allowed for v2-only functionality; unsupported optional functions degrade transparently.

Recommended structure (adapt names to the actual fork):

```text
AgenticGIS/
  plugin.py
  core/tools.py                 # new tool contracts, shared across API/CLI/MCP
  core/toolkit.py               # dispatch facade; existing QGIS tool reuse
  integrations/brazil/
    catalog.py                  # merged GISBR + curated overlay metadata
    indigenous_sources.py       # validated Indigenous source definitions/policies
    connectors_ext.py           # minimal audited adapters for non-GISBR data
    scope.py                    # IBGE geographic resolution and validation
    planner.py                  # plan, quotas and warnings
    service.py                  # source loading/orchestration, structured results
    provenance.py               # layer/project metadata and audit
    runtime.py                  # QGIS provider registration/lifecycle
  vendor/gisbr/                 # pinned, auditable GISBR runtime snapshot
    LICENSE                     # GISBR GPL-3.0 and notices alongside source
    ...                         # source catalog/connectors/core/provider components
  resources/brazil_sources.*    # GISBR enrichment manifest and overlay registry snapshot
  docs/gisbr-indigenous-data/     # include Indigenous source evidence & policy
  tests/                        # tracked in fork
  docs/                         # tracked in fork
```

**Architecture decision A1 — preserve GISBR, adapt its boundaries:**

- Bundle a **pinned, reproducible copy** of the *needed GISBR runtime implementation*. Do not copy docs/test/dev scripts into runtime by default. Preserve source attribution, licensing and a `GISBR_UPSTREAM.md` with source SHA, file inventory and changes. Avoid ad hoc code scraping at runtime.
- First run a concrete compatibility spike to confirm that the selected GISBR modules can be imported and their Processing algorithms can run when relocated under the fork's package. Where GISBR has absolute `gisbr.*` imports, replace them **only in the forked/vendor-maintained snapshot**, with a documented patch. Favor relative imports or a well-defined wrapper, not monkeypatching `sys.path` or `sys.modules` globally.
- Keep a **unique bundled Processing provider ID**, e.g. `agenticgis_br`, if registering one inside our plugin. Change *all* internal GISBR literal `gisbr:<alg>` calls accordingly. Do not overwrite the provider ID `gisbr` used by the separately installed official plugin. Detection by `QgsApplication.processingRegistry().providerById()` must be explicit.
- Give our QGIS plugin ownership of this bundled provider; on reload/unload remove **only our provider** and disconnect any callbacks. A separately installed GISBR continues to work normally. Never replace, unregister or mutate the official provider.
- **Merge** pinned GISBR sources with a namespaced, versioned overlay (see `indigenous-sources.md`). Deduplicate *display choices* only when metadata justify it; **never overwrite an upstream GISBR ID or silently equate FUNAI primary boundaries, geobr mirrored boundaries, and ISA interpretations**. Validate all new source endpoints via read-only metadata/live tests before enabling their loaders. Prefer using bundled GISBR connectors where they actually support a protocol; add focused, separately testable official-source adapters otherwise.
- Prefer using the bundled GISBR sources and source engine internally; do **not** expose every internal GISBR implementation detail as a new LLM tool. Expose a small, stable agent-facing API and delegate heavy QGIS manipulation to existing AgenticGIS tools.
- Preserve GISBR's source-specific constraints (`escala_max`, UF coverage, `indisponivel`, `requer_parquet`, separate transport/OSM scope rules, support for metadata fields). Do not silently offer unsupported scopes.
- **If the compatibility spike finds blockers**, fix the adapter/vendor isolation or, as an explicitly documented temporary *development-only* diagnostic, use an external installed GISBR plugin. The **final acceptance gate remains a one-plugin install**; never silently ship an external GISBR requirement.

**Architecture decision A2 — separation of concerns:**

```text
User in PT-BR / EN
  -> AgenticGIS chat agent
  -> br_search_sources / br_source_details / br_resolve_area
  -> br_plan_load (deterministic preflight, no writes)
  -> existing external-access approval + br_execute_load(plan_id)
  -> merged GISBR + Indigenous registry and policy gate
  -> GISBR bundled source engine, connectors, geobr algorithms
     + narrowly-scoped validated FUNAI/DSEI/INPE adapters
  -> QGIS task/main-thread orchestration, cached GeoPackage/COG
  -> QgsProject real layer IDs, standardized provenance/status
  -> existing AgenticGIS run_processing / run_pyqgis / stats / styles / export
```

Do not create a new chatbot, external model or backend integration. QGIS project/map canvas mutation must be on the GUI thread. Long-running network/processing work must be cancellable and must not block the chat dock. GISBR's current diagnostic loader may mutate QGIS during loading; split or schedule safe stages if necessary rather than invoking it indiscriminately in a worker.

## 5. Stable agent tool contracts (v1)

Implement these in `core/tools.py` / toolkit facade, all available to API-key, CLI-agent and MCP callers using the same names and JSON schemas. `br_*` is a proposed namespace; preserve these names unless a collision is discovered and documented. Each tool returns a JSON-serializable dict; no raw Qt/QGIS object is returned to the agent.

### T1 — `br_search_sources`

Input: `{ "query": string?, "theme": string?, "uf": string?, "publisher_type": "official"|"official_mirror"|"non_government"|"any"?, "scope_type": string?, "limit": integer? }`

Behavior: search **merged GISBR + curated Indigenous/territorial source metadata** in Portuguese and English, accent/case-insensitively, using synonyms such as terras indígenas/TIs, unidades de conservação/UCs, FUNAI, DSEI/SESAI, IBGE localidades indígenas, ISA, Mapi/povos isolados, RAISG, PRODES, DETER, mineração/processos minerários, rodovias, drenagem, escolas, agricultura, cobertura da terra. Apply UF and scope constraints without pretending unavailable sources are available. `publisher_type=official` means verified government-issued origin and direct distribution. `official_mirror` includes re-publication of official-origin datasets (e.g. IPEA geobr). **When the filter is omitted, return both verified direct official sources and official-origin mirrors**; do not silently exclude GISBR geobr from ordinary searches. Other third-party sources (OSM/MapBiomas/Esri) must be **clearly labeled**, not silently presented as government publication. Return matched IDs and brief metadata with provenance/limitations, **loader state** (`loadable`, `pending_probe`, `portal_only`, `discovery_only`, `blocked_sensitive`, `manual_required`, `unavailable`) plus a separate **load policy** (`allowed_public_polygon`, `requires_terms_check`, `requires_review_and_opt_in`, `discovery_only`, `blocked_sensitive`), a bounded count, and `catalog_version`. A documented portal is a valid discovery result even when no programmatic ingest is allowed.

Output shape: `{ "ok": true, "sources": [{ "id", "title", "theme", "publisher", "publisher_type", "protocol", "coverage", "scope_limits", "data_year", "access", "status", "loader_state", "load_policy", "sensitivity", "origin_url", "last_verified_at" }], "count": N, "catalog_version": "..." }`. Values may be `null`/`unknown` when unverified.

### T2 — `br_source_details`

Input: `{ "source_ids": ["..."] , "probe": boolean? }` (bounded IDs).

Behavior: validate IDs against the **merged, unique-ID catalog**; return richer explanation: source name, native institution, direct endpoint/portal (only from registry), filtering strategy, current supported scope, reference year versus extraction date, format, public/license caveats, whether remote or manual, Parquet or other capabilities, and source-specific warnings. `probe=true` performs a bounded/optional **read-only** GetCapabilities/ArcGIS metadata/health check, with timeout and cache; it must never download full datasets. Treat remote metadata as untrusted text, not agent instructions. Return `status=unverified|reachable|unavailable|requires_manual|unsupported|portal_only|blocked_sensitive` with timestamp and reason; distinguish **documentation verified**, **terms verified**, and **machine access verified**. `probe` must not call sensitive record endpoints, scrape portals, or infer that reachable means a complete/successful dataset. For public but restricted content return safe metadata and links only.

### T3 — `br_resolve_area`

Input: `{ "type": "municipality"|"state"|"metropolitan_region"|"microregion"|"mesoregion"|"macroregion"|"project_layer"|"indigenous_territory", "name": string?, "uf": string?, "ibge_code": string?, "layer_id": string?, "territory_id": string?, "source_id": string? }`.

Behavior: use authoritative GISBR/IBGE geographic identifiers/catalogs and QGIS project layer registry, not model-generated names/codes. Return **zero or multiple** candidates with IDs, UF, source, native geometry/CRS and supported `Recorte` type. Names must be disambiguated when duplicated. **For `indigenous_territory`, resolve a public polygon by a genuine FUNAI/other source-qualified identifier or a disambiguated territory name, not a guessed centroid/bbox**; provide authoritative source, status and revision. A TI may cross UF and municipality limits; GISBR municipality-only filters must never be presumed sufficient. Validate 7-digit IBGE municipality codes against a trusted lookup, not just their length. A project-layer extent is **not** equivalent to its polygon: prefer real geometry, clip by polygon/mask, and require valid geometry/CRS. For unsupported non-municipal arbitrary polygons, either implement a documented safe clip adapter or return `unsupported` (do not pretend GISBR `Recorte` supports it automatically). If authoritative TI geometry is not already cached or loaded, do **not** make a hidden large download: return `needs_reference_data` with an approved, bounded way to obtain it, or complete an explicitly authorized read-only public lookup that cannot mutate the project.

### T4 — `br_plan_load`

Input: `{ "source_ids": ["..."], "area": { ...resolved_area... }, "output_gpkg": string?, "years": {"source_id": integer}?, "replace_existing": boolean?, "include_non_government": boolean? }`.

Behavior: **read-only** and deterministic. Validate source IDs against **both registries**, native availability and applicability; validate official/third-party choices, **sensitivity category and access policy**, scope/UF/scale, prerequisites, geometry, CRS, requested years, file path, overwrite behavior, destination permissions, estimated size when measurable, and likely disk/network impact. If source is `portal_only` or `blocked_sensitive`, no executable plan is produced for it, even with blanket permission. For village/locality points, default to discovery-only unless a separate reviewed protection path demonstrably prevents model/MCP/tool-output exposure. Default is **skip/reuse existing outputs**, not replacing; accept verified government-origin sources **including official-data mirrors** by default, while non-government sources require an explicit user request/opt-in. Warn about large, statewide, multiprotocol, raster and manual-download tasks. If output location is absent and cannot be derived from a saved project/user-chosen output directory, request location before execution (do not write to an arbitrary home or system path). Return a short-lived opaque `plan_id`, exact `source_ids`, area ID, destination, per-source readiness (`ready|skipped|blocked|manual|unverified`), confirmation requirements, and warnings. Plans are invalidated if key context/selection changes. No fetch/download or project mutation at this stage, apart from optional small metadata checks explicitly labeled as such.

### T5 — `br_execute_load`

Input: `{ "plan_id": string }` **only**. No arbitrary network URL, script string, CQL, SQL or file path in the execution call.

Behavior: enforce that the plan is current and approved under AgenticGIS external-access rules. A user request to load data authorizes executing the specific planned data retrieval, **not** arbitrary future external reads, replacing unrelated files or system-command execution. Honor large-download confirmation policy and existing guardrails. Execute per-source bounded jobs with progress, cancellation, retry/backoff policy and safe partial failures. Use GISBR's connectors and diagnostic logic for existing sources, and **only bounded, audited overlay adapters** for verified FUNAI/DSEI/INPE source protocols. No model-generated host/endpoint parameters. Recheck sensitive-source policy and effective selected feature geometry **at execution time**, not only in the catalog. Persist outputs, load valid returned layers into the project, and report stable IDs/actual names/paths. Explicitly mark `truncated`, `partial`, `empty`, `cancelled`, `skipped`, `manual_required`, and `failed` instead of treating incomplete data as success. The function is idempotent by default: existing validated table/file is reused/skipped; replacements require explicit `replace_existing=true` in the plan and a safe per-source overwrite strategy.

Output example (illustrative only):

```json
{
  "ok": true,
  "status": "partial",
  "area": { "type": "municipality", "ibge_code": "..." },
  "results": [
    { "source_id": "icmbio_uc", "status": "loaded", "layer_ids": ["<actual QGIS id>"],
      "layer_names": ["..."], "feature_count": 42, "output": "...gpkg",
      "provenance": { "publisher": "ICMBio", "data_year": null,
        "extracted_at": "<UTC ISO-8601>", "origin_url": "<source URL>" },
      "warnings": [] },
    { "source_id": "incra_sigef_parcelas", "status": "manual_required",
      "layer_ids": [], "instructions": "...", "warnings": [] }
  ],
  "cancelled": false
}
```

The example does not assert those sources are currently online or that 42 real features exist. Never supply guessed IDs/counts in production. `ok` means tool execution contract completed, not that every source succeeded; `status` and per-source results tell the truth.

**Integration note:** Existing AgenticGIS `run_processing` must continue to work. The **same five `br_*` tools** expose both GISBR and Indigenous overlay sources; no extra source-per-tool surface. Source IDs and access controls must be enforced in each transport, not just in agent instructions. Keep new source discovery/plan/load tools compact; do **not** generate 75 one-source tool schemas. Existing tools handle analysis and manipulation, including using returned IDs in `run_processing` and `get_layer_fields`.

## 6. Source coverage and data correctness

### 6.1 Initial real source workflows to support and test

| Topic | Source IDs in inspected GISBR catalog | Notes and constraints |
| --- | --- | --- |
| Territory boundaries | `geobr_terras_indigenas` | IPEA/geobr distribution of Brazilian Indigenous territory boundaries; confirm dataset year, scope and publisher of original geometry. Do not present as confidential or complete for any community. |
| Conservation | `icmbio_uc`, `geobr_ucs`, selected `*_uc_estaduais` | Distinguish federal/derived/state catalogs; UF-limited entries not offered nationally. |
| Mining claims | `anm_sigmine`, `anm_sigmine_req_pesquisa`, `anm_sigmine_licenciamento`, `anm_sigmine_concessao_lavra`, `anm_sigmine_lavra_garimpeira` | Distinguish claim stage and source vintage; don't claim legal status from spatial overlap alone. |
| Land-cover | `mapbiomas_cobertura` | Third-party MapBiomas product, COG raster, specified collection/year, not a current deforestation-alert feed. |
| Rural parcels | `sicar_imoveis`, `incra_sigef_parcelas` | SICAR scope/filters; SIGEF manual gov.br-authenticated file import only. |
| Municipal geometry / Census | `geobr_municipio`, `geobr_setores`, `geobr_ponderacao`, `geobr_favelas` | Some v2 sources need Parquet capability; `YEAR` in Processing is an **enum index**, not literal year. |
| Hydrology | `sgb_rios`, `sgb_bacias`, `ana_hidrografia`, `ibge_bc250_drenagem` | Spatial bbox server filter plus polygon clip as needed. |
| Infrastructure | `dnit_snv`, `minfra_ferrovias`, `ibge_bc250_rodovias` | Stage/status matters; verify connected network interpretation if used. |
| Health / Education | `geobr_saude`, `geobr_escolas`, `df_escolas_publicas` | Respect UF-only public school data. |

Do not hardcode only these sources. All catalog entries must be discoverable and clearly typed; runtime support is limited to connector/capability implementations proved available. Unsupported sources must be surfaced with meaningful reasons, not disappear silently.

### 6.1.1 Curated Indigenous and territorial registry (mandatory)

`indigenous-sources.md` is part of the **binding requirements**, not optional background reading. The source registry **must cover** (at minimum) FUNAI official TI polygon boundaries and recognition stages, FUNAI-published DSEI **operational area polygons** (SESAI thematic domain), the publicly indexed IBGE 2022 Indigenous localities, INPE TerraBrasilis annual PRODES and alerting DETER, and transparent reference-only entries for ISA (`isa_territories`), Mapi (`mapi_isolated_peoples`), RAISG (`raisg_indigenous_territories`) and MapBiomas Alerta (`mapbiomas_alerts`). Include FUNAI villages/administrative locations in **discovery**, but restrict automatic point ingestion as specified in §6.4.

**Source selection defaults:** Official FUNAI primary polygons take precedence for current legal/status questions **when actually validated and available**; `geobr_terras_indigenas` is a different dated distribution route. If FUNAI is unreachable, offer a source-qualified geobr alternative with its **own data vintage and attribution**, never silently replace the requested dataset. DSEI coverage polygons do **not** mean TI demarcation boundaries and must be labeled accordingly. GISBR `mapbiomas_cobertura` is land cover, while PRODES, DETER and MapBiomas Alerta have distinct annual/alert products, temporal concepts and owners.

**Release minimum (not just catalog labels):** the developer must implement and test genuine QGIS load paths for **FUNAI TI polygon, FUNAI DSEI area polygon, and one INPE PRODES/DETER polygon series**, using the actual published protocol and audited connector. If a given service is unavailable, demonstrate fixture-driven correctness, report that live dataset as *unverified*, and **do not label the Indigenous integration fully READY**. A live non-GISBR official adapter is required for full release readiness. The user should be able to choose a named TI polygon as area of interest, not only municipality/UF.

**Access categories:** The source registry `origin_class` has `official_direct`, `official_mirror`, `non_government`. Map public tool input `publisher_type="official"` to `origin_class="official_direct"`, `publisher_type="official_mirror"` to `origin_class="official_mirror"`, and `publisher_type="non_government"` to the same-named class. Keep this mapping centralized and tested; do not silently rename an API enum. Separately record access mode (`gisbr`, `official_wfs`, `official_download`, `third_party_download`, `portal_only`, `manual_import`, `restricted`), load policy (`allowed_public_polygon`, `requires_terms_check`, `requires_review_and_opt_in`, `discovery_only`, `blocked_sensitive`) and runtime loader state (`loadable`, `pending_probe`, `portal_only`, `discovery_only`, `blocked_sensitive`, `manual_required`, `unavailable`). An entry may be official **and** restricted. A public source webpage may be discoverable without machine-readable geometry. Always publish the origin URL and the check date; never manufacture live service availability.

### 6.1.2 Indigenous territory identity and source comparison

- Resolve a TI by confirmed source-qualified ID when available, or by name **plus UF and candidate disambiguation**, returning a real polygon and `source_revision`/data-date. A TI may cross municipalities and UFs. Do not convert its name to an arbitrary bbox or rely on a municipality-only filter when it crosses administrative borders.
- Keep original legal-status fields, official portaria/publication references if present, original geometry, CRS, spatial clip/mask geometry, and provenance. When interpreting overlaps, distinguish **spatial intersection** from permit/legality, possession, medical coverage or proof of illegal activity.
- Coordinate reference systems, clipping, geometry validity, source schema and temporal validity must be checked. A WMS visualization is not an editable vector layer; a portal-only record has no QGIS feature IDs. When only raster or PDF content exists, return that limitation honestly.
- Crosscheck FUNAI/geobr/ISA/RAISG polygon differences only through permitted sources. Expose each original publication date and legal meaning. Never silently merge jurisdictions or treat ISA contextual records as a current FUNAI legal registry.

### 6.2 Metadata contract

Every data layer created/loaded by this integration must have a minimum metadata record (QGIS custom properties and, when practical, a sidecar table/manifest in the output directory):

- `provider` / originating institution and official-versus-derived classification;
- `source_id`, original source URL/portal and GISBR source registry commit/version;
- `data_reference_year` or explicit `unknown` distinct from `extracted_at` in UTC;
- geographic scope type and validated ID, active filter method (municipal code/name/bbox and geometry clip), source CRS and target CRS, clip success status;
- terms/license/attribution as validated or `unknown` (never infer that `Publica` means unrestricted reuse);
- `result_status`, `truncated`/`partial` warnings, feature count when reliable, saved path and project layer ID.

User data and secret credentials must not be written to logs or metadata. Avoid labeling zero features as source failure: return `empty` after confirming successful valid query. If the endpoint is down, return `unavailable` rather than an empty dataset.

### 6.3 Correct spatial semantics

- Apply **server-side filters** by IBGE code or safe escaped name where possible; otherwise bbox in verified CRS and then **exact polygon clip** client-side. Escaped textual values must never form arbitrary unsanitized CQL or SQL.
- Multi-municipality regions must be represented by validated municipality-code sets, with GISBR's `escala_max`/state restrictions. Do not use first municipality as a proxy for whole region.
- Handle WFS axis order, ArcGIS `where`/envelope fields, pagination/record limits, HTTP-200 errors, invalid geometry, NoGeometry tables, and raster COG clipping/tiling. Preserve GISBR truncation warnings; if a request is only partially paginated, mark `partial/truncated` and do not silently compute authoritative totals.
- Reprojection must use QGIS CRS transformation API; preserve original source reference and do not assume rasters begin in EPSG:4674.
- Be explicit about remote years. When GISBR defaults to a 2023 MapBiomas collection, don't label that result “latest”. Always report the actual source year. A year unsupported for the selected source must be rejected or prompt a supported option, not quietly substituted.

### 6.4 Indigenous data sensitivity and governance — non-negotiable

1. **Public does not mean unrestricted.** Disclose originating institution, publication rights, redistribution terms, Indigenous governance/CARE considerations, version and reference year. Do not imply that community permission has been obtained from public access alone.
2. **Mapi / isolated peoples:** `mapi_isolated_peoples` is **discoverable metadata and public coarse contextual links only**. Do **not** automate ingest, extract, infer, georeference, expose, rank or export precise presence records, contact sites, routes, or sightings, including by combining layers. The linked `/mapa` web endpoint was not independently verified as an API. This restriction applies even if publicly rendered maps or downloads exist.
3. **FUNAI villages and IBGE Indigenous locality points:** discovery-only by default. An optional local import requires separate, documented user authorization **and proof** that sensitive fields/geometries are not exposed by **any** of AgenticGIS's existing API/CLI/MCP paths, project summaries, unrestricted `run_pyqgis` calls, logs, generated code and exports. If the existing generic tools cannot enforce that boundary, do **not** enable automatic loading of those precise point sources in v1. Never let an LLM instruction alone substitute for technical enforcement.
4. **Non-government sites:** ISA is for metadata/context and portal links unless a legitimate bulk access method and terms are verified. RAISG publishes shapefile/WMS but each theme needs individual attribution/terms checks; WMS is display-only. MapBiomas Alerta API may require account registration, and no login bypass or unreviewed automated bulk copy is allowed.
5. **Least data to the model:** return stable source IDs, titles, high-level scope, age, bounded counts, verified warnings and QGIS layer IDs where allowed; do not stream sensitive coordinates, raw GeoJSON, access tokens, exact sighting/locality points or local community datasets into remote chat, history, logs or MCP responses. For newly restricted layers, verify egress boundaries end-to-end before any automated use.
6. **Operational safety:** Show `portal_only`, `pending_probe`, `blocked_sensitive`, `manual_required` distinctly in search/details/plan. Plan/execute may never bypass policy via a raw model-provided source URL, TIFF/ZIP filename, changed locale, or alternate agent backend.

## 7. Safety, privacy, performance and reliability

**Network and data trust**

1. Only load predeclared, reviewed catalog sources and approved resolved URLs. **Never allow the LLM to supply arbitrary WFS/ArcGIS URLs through `br_execute_load`**. No authenticated portal bypass; no `verify=False`, certificate-warning suppression, or blanket TLS relaxations. Respect proxy and CA chain where supported.
2. Treat remote descriptions, labels and downloaded feature attributes as untrusted data; they must not become executable tool instructions or shell/code prompts. Sanitize displayed HTML/Markdown; never run scripts embedded in downloads.
3. Keep original AgenticGIS access permissions for new network/file operations. Use stable internal IDs/choice values separately from localized labels. Never auto-set `external_access_always_allowed` as a side effect of this feature.
4. Do not publish/share local community datasets without user instruction. Data loaded from government sources can still have attribution or policy constraints. No telemetry, analytics or upload of private project geometry to third-party LLMs beyond what the existing AgenticGIS model flow explicitly sends.
5. Manual import file paths must be user-selected or restricted to a validated configured folder. Reject path traversal in archives and unsafe archive member paths; bound decompressed size and downloaded payload. Respect available disk space.

**Performance and lifecycle**

6. Offline catalog search and local project lookup must work with networking disabled. Probe/read-only metadata timeouts are bounded and cached. Download limits, per-source timeouts, retries, optional size ceilings and confirmation thresholds are configurable; unknown sizes require clear warnings. Do not hardcode a “safe” national maximum without evidence.
7. Never freeze the QGIS UI while downloading a heavy service, raster or aggregate. Use existing `QgsTask` and AgenticGIS main-thread executor appropriately, support stop/cancel, avoid background manipulation of `QgsProject` and non-thread-safe Qt objects.
8. Partial success persists valid completed layers only, with correct status; errors do not corrupt an existing GeoPackage or leave stale broken map layers. Verify replacement semantics by tests, including QGIS project layers referencing affected files. Temporary files get cleaned on cancellation and error; cache reuse is safe/versioned.
9. Avoid duplicate sources/layers on repeated natural-language requests; preserve source IDs and chosen scope. Replaced layers must not silently break layer references, styles, or the QGIS project.
10. On plugin unload/reload, no dangling processing providers, leaked tasks, stale signals or orphaned files; the separately installed GISBR plugin still functions if present.

## 8. Experience and language

- **No required new GISBR-specific panel.** Use existing AgenticGIS chat, tool-call progress, errors, and permission UI. A small source-summary card or link is optional only if it improves clarity without duplicating QGIS's layer tree.
- Tool outputs should remain concise and actionable: source/title, official/derived/third-party, checked date, provenance, scope, current stage (preparing/downloading/clipping/added), output path, and warnings. Don't stream raw megabytes of metadata, geodata or full feature attributes into the LLM context.
- Follow the existing AgenticGIS PT-BR localization approach in the fork. User-facing labels and errors should be translatable; tool identifiers, source IDs, QGIS field names, provider IDs, payload keys and saved metadata keys remain stable English identifiers. Never translate options that are used as control/permission IDs.
- A query in Portuguese should match English metadata and Portuguese aliases (and vice versa). Include Brazilian geographic vocabulary and acronyms while preserving institution names and proper nouns.
- Explain missing capability rather than silently failing: e.g. “requires GDAL Parquet driver/pyarrow”, “gov.br manual download”, “not published for selected UF”, “source endpoint currently unavailable”, “source is from OSM rather than government”, “data year unknown”.
- Never falsely describe historical MapBiomas land cover as real-time deforestation or present spatial intersection as proof of illegal activity.

## 9. Suggested code-level interface and boundaries

Use a thin `BrazilDataService` abstraction, initialized by the fork's plugin/toolkit lifecycle:

```python
class BrazilDataService:
    def search_sources(self, **filters) -> dict: ...
    def source_details(self, source_ids, probe=False) -> dict: ...
    def resolve_area(self, type, name=None, uf=None, ibge_code=None,
                     layer_id=None, territory_id=None, source_id=None) -> dict: ...
    def plan_load(self, source_ids, area, output_gpkg=None, years=None,
                  replace_existing=False, include_non_government=False) -> dict: ...
    def execute_load(self, plan_id, *, feedback, executor, cancel_token) -> dict: ...
    def shutdown(self) -> None: ...
```

Final code may choose different internals. Preserve functional contracts and keep the `br_*` tool handlers very small. Source/vendor code must not import, instantiate or depend directly on any chat backend. Any provider registration must happen in QGIS plugin lifecycle, not at module import time. Avoid global `sys.path` mutation. Use `QgsApplication.processingRegistry()` for provider checks and `run_processing` for follow-on analysis, with coherent internal/external provider IDs.

`br_execute_load` must not be implemented as a single unbounded `run_pyqgis` string. The agent must see curated source metadata before triggering expensive work; after loading, existing tools can call normal PyQGIS/Processing methods as permitted.

## 10. Acceptance tests (must pass before release)

### Functional

- [ ] Without network, `br_search_sources` finds `geobr_terras_indigenas`, `funai_ti_boundaries`, `funai_dsei_areas`, `ibge_indigenous_localities_2022`, `inpe_prodes`, `inpe_deter`, `isa_territories`, `mapi_isolated_peoples`, `raisg_indigenous_territories`, `icmbio_uc`, `anm_sigmine`, `sicar_imoveis` by PT-BR and English synonyms; correctly filters provenance types, UF, loadability and sensitivity policy.
- [ ] Source details show original institution, catalog origin, year or `unknown`, and an access status—not assumed live. Probe results are time-stamped and do not download full datasets.
- [ ] `br_resolve_area` validates a genuine IBGE municipality code, rejects invalid codes, and disambiguates identical names across UFs; project-layer geometry can be chosen only when supported.
- [ ] A municipal, small-data live E2E run (chosen after source availability checks) resolves place → plans → approves → downloads → clips → persists → adds at least one **official** source to QGIS, returning the exact layer ID; a follow-up `run_processing`/analysis or selection uses that ID successfully.
- [ ] At least one additional source from a **different protocol** is tested live or with a full fixture-driven connector test; WFS and ArcGIS paths are covered including truncation cases. A raster case is verified against actual CRS/clip behavior.
- [ ] The curated Indigenous registry is **separate from GISBR `SOURCES`**, has unique IDs, provenance/access/sensitivity metadata, primary verified documentation URLs, and includes all `indigenous-sources.md` priority entries. Both catalogs appear in the same five agent tools.
- [ ] A **FUNAI official TI boundary**, **FUNAI-published DSEI area polygon**, and **INPE PRODES or DETER** path pass fixture tests plus live QGIS tests whenever endpoints are available. If any service is unreachable, its live gate is marked blocked/untested; it is not reported loaded. At least **one non-GISBR official source** is loaded live to declare full feature READY.
- [ ] `br_resolve_area(type="indigenous_territory")` resolves a real polygon by trusted ID or disambiguated TI name, including cross-municipal territories; subsequent clipping works and DSEI vs TI meanings are explicitly differentiated.
- [ ] `mapi_isolated_peoples` remains discoverable **without exact presence-record ingestion or model exposure**, including attempts to request it via `br_plan_load` and `br_execute_load`; village/locality point auto-ingestion is blocked until technical end-to-end protections are proven. Synthetic security fixtures test API/CLI/MCP, generic PyQGIS and transcript/exception paths.
- [ ] ISA and Mapi portal-only sources do not claim vector/QGIS capability, RAISG WMS does not claim editable vector features, and MapBiomas Alerta registration/terms are respected; no unauthorized scraping or credentials collection.
- [ ] Existing output is reused/skipped by default; explicit replacement is safe; rerun does not duplicate registered map layers or corrupt the GeoPackage.
- [ ] Out-of-scope UF/scale sources and manual SIGEF are shown as blocked/manual; optional Parquet missing does not crash basic workflows.
- [ ] Some sources failing produces `partial` with correct per-source results, no fabricated successful data, and retained valid layers.
- [ ] Cancellation of a long remote request leaves the UI responsive and QGIS/GeoPackage consistent; reload/unload succeeds.
- [ ] Existing generic AgenticGIS tools (chat, run_processing, run_pyqgis, get_project_state, sessions, provider selection) work unchanged.
- [ ] Same new tools appear and execute consistently via **API/CLI/MCP**; internal schema, permissions and layer IDs match across transports.

### Safety and packaging

- [ ] New external access is authorized according to the existing permission path; tests prove a denied operation never downloads/writes, cannot change permanent approval, and cannot reach arbitrary URLs.
- [ ] WFS CQL/ArcGIS where text, user output paths, remote metadata, archive extraction, TLS errors and malicious payloads have negative tests.
- [ ] Registry entries are classified official/mirror/third-party honestly; unknown licenses remain unknown; data vintage and extraction time distinct.
- [ ] GISBR bundled source SHA, notices, GPLv3 compliance, attribution and source availability are documented and included in distributable ZIP. Separate official GISBR can coexist; no duplicate `gisbr` provider registration.
- [ ] One ZIP (or equivalent documented fork package) installs on a clean QGIS without separate GISBR installation. Optional Parquet absence degrades gracefully. Required runtime assets are present and import cleanly.
- [ ] QGIS 3.22+/Qt5 and QGIS 4/Qt6 import/startup/unload tests pass in available environments; any unavailable platform is reported as unverified, not “passed.”
- [ ] Human-verified PT-BR and EN chat examples match the actual returned statuses, data metadata, layers and output files.

## 11. Deliverables / definition of done

The coding agent must deliver in **our fork**:

1. A self-contained GISBR-backed integration with documented pinned GISBR source revision, patch/upgrade instructions, appropriate license/copyright notices, no standalone GISBR installation requirement.
2. Five stable `br_*` tool contracts and backend/MCP exposure, **merged GISBR + reviewed Indigenous source catalog**, deterministic search/validation, named-TI polygon resolver, plan-and-approve load, safe execution, provenance and layer chaining.
3. Functional and negative tests, preferably both offline unit/fixtures and a verified QGIS E2E smoke test; a concise test report distinguishing executed from not executed.
4. User documentation in English and Portuguese illustrating discovery, source selection, limits, data vintage, manual SIGEF, FUNAI/DSEI/INPE examples, ISA/RAISG/Mapi classification and sensitive-data restrictions, and a complete GIS operation following download.
5. A release-ready fork ZIP with a clean-install checklist; a changelog, architecture notes, and a handoff report containing remaining known limitations.

A document-only or prototype-only implementation is **not** complete. Any difference between actual GISBR APIs and this spec must be explicitly resolved in an adapter and documented with evidence, preserving the user-visible requirements above.
