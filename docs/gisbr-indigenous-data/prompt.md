> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# Developer Agent Kickoff — Integrate GISBR and Indigenous public data into our AgenticGIS fork

You are the autonomous developer responsible for implementing Brazilian geospatial data discovery and loading in **the AwanaGIS fork (derived from AgenticGIS)**. This is a product feature of our fork; **do not submit a pull request to `ultramenid/AgenticGIS`**.

Read the accompanying files in full, in this order:

1. [`spec.md`](./spec.md) — authoritative feature, architecture, safety, licensing and acceptance specification.
2. [`plan.md`](./plan.md) — phased implementation and quality gates to execute.
3. [`indigenous-sources.md`](./indigenous-sources.md) — **binding, reviewed source matrix** for FUNAI TI polygons, DSEI/SESAI jurisdiction, IBGE Indigenous localities, INPE PRODES/DETER, ISA, Mapi, RAISG and MapBiomas Alerta, including data governance restrictions.
4. The current fork's actual repository, tests and release workflows; the upstream sources listed below.

## Goal

A user chatting with AgenticGIS inside QGIS should be able to ask, in Portuguese or English, for **official Brazilian spatial datasets**, discover the available sources, inspect their provenance and reference years, resolve a municipality/UF/region or compatible project area, preview a bounded download plan, authorize loading, and have real, correctly filtered and clipped **GISBR-backed plus separately curated FUNAI/DSEI/INPE** data layers added to the QGIS project when those sources are actually loadable. The same agent then uses normal existing AgenticGIS tools to filter, intersect, join, summarize, style, map and export those loaded layers.

Example request:

> "Busque as terras indígenas, UCs federais e processos minerários na região de São Félix do Xingu (PA), me diga quais fontes e anos encontrou, adicione as camadas disponíveis ao projeto e identifique sobreposições."

This must be implemented as real tool use, not a hardcoded demo, manual browser flow, or an LLM-only answer.

**Equally critical Indigenous examples:**

> “Encontre a base oficial da FUNAI de uma TI pelo nome (confirmando o identificador e a situação jurídica), os polígonos de abrangência dos DSEIs e dados de PRODES ou DETER; traga as camadas públicas permitidas ao QGIS, calcule a interseção e documente instituição, período de referência e data de extração.”

> “Quais fontes estão disponíveis na FUNAI, IBGE, ISA, Mapi e RAISG para compreender a situação desta terra indígena? Separe as camadas que podem ser carregadas de portais apenas para consulta e de dados sensíveis que não devem ser importados automaticamente.”

## Critical reference facts / starting points

- AgenticGIS upstream: <https://github.com/ultramenid/AgenticGIS>, inspected `main` SHA `1e4f70b488824982a835c89c202454ec92dafae7`. Use **our fork/worktree HEAD** as the actual development base; preserve existing changes, including PT-BR localization if present.
- GISBR: <https://github.com/d-camargo/gisbr>, inspected `main` SHA `06d84dfab9942e4e840637bb8d8f96af173330ad`. Pin and record exact source revision used.
- Main GISBR implemented source list: `gisbr/core/sources.py`; source research: `docs/diagnostico-plano-diretor/fontes-detalhe.md` (only a subset of the live catalog); diagnostic implementation: `gisbr/core/diagnostico.py`; geographic scopes: `gisbr/core/recorte.py`; Processing provider: `gisbr/provider.py`.
- GISBR reports 75 thematic sources across 9 axes, with additional basemap registry entry, and ~57 Processing algorithms. Its code is GPL-3.0 and includes optional Parquet support; some entries are manual/download-restricted, geographically limited, third-party or possibly unavailable. **Do not treat the entire catalog as guaranteed currently available or officially government-published.**
- GISBR `recorte.py` has absolute `gisbr.*` imports and literal `gisbr:<algorithm>` references; **a self-contained bundled integration must adapt those carefully**. AgenticGIS already has `core/tools.py`, `core/toolkit.py`, `run_processing`, `run_processing_background`, `get_algorithm_parameters`, QGIS task handling and MCP tool exposure. Reuse these mechanisms.
- Our desired final deliverable is **one installable AgenticGIS fork ZIP** with the needed GISBR engine bundled, properly licensed and attributed, not a two-plugin install requirement.
- The earlier GISBR catalog does **not cover all requested Indigenous sources**. Maintain a **separate overlay catalog** based on `indigenous-sources.md`, rather than claiming official FUNAI/DSEI and INPE data are already implemented by GISBR. The published FUNAI download/GeoServer page lists TI and DSEI polygons, but the service endpoint still requires runtime verification; never invent type names, vector layers, API support or data years.

## Work instructions

1. First inspect the current repo and prove the vendoring/provider strategy in an isolated QGIS smoke test. Do not assume that relocating GISBR packages and its `QgsProcessingProvider` will work automatically.
2. Implement the *small, stable* `br_*` tools specified in SPEC: `br_search_sources`, `br_source_details`, `br_resolve_area`, `br_plan_load`, `br_execute_load`. Expose them consistently to **API, CLI and MCP**. Do not add a tool for each source.
3. Discovery must merge the **pinned GISBR source catalog plus curated Indigenous registry** and be meaningful offline, PT-BR/English searchable, and honest about original institution, official vs IPEA geobr mirror vs non-government, data vintage, applicability, **sensitivity, portal-only/blocked/verified live** state and licensing caveats.
4. **Prioritize and prove source paths for FUNAI official TI polygons, FUNAI-published DSEI operational areas, and INPE PRODES or DETER**, including a named-TI polygon area resolver. Use official download/WFS metadata, validate service layer IDs/temporal meaning, reuse existing GISBR connectors when compatible and create only narrow extra adapters. Do not mark these source paths complete based on metadata-only discovery.
5. Discover IBGE 2022 Indigenous localities (noting revised downloads), ISA TI registry, RAISG data/WMS, MapBiomas Alerta (registration-dependent API) and Mapi (COIAB/OPI/OPAN) with accurate source type. ISA/Mapi are **metadata/link-out only unless access rights and an API are verified**. **Never automatically ingest or expose isolated-peoples presence/sighting geodata**. FUNAI village and census-locality exact points are discovery-only unless rigorous technical protections exist across every tool/backend; LLM text instructions are not a security boundary.
6. Loading must use validated GISBR **or curated overlay** source IDs, safe geographic boundaries and exact polygon clip, QGIS's proper task/main-thread APIs, per-source cancellation/progress, staged or safe persistence, validated layer IDs and provenance. Use planning and permissions before network/file writes. No arbitrary model-supplied URLs or shell commands.
7. Keep existing AgenticGIS user experience and general-purpose QGIS tools, session format, permissions, and current internationalization intact. Do not add a duplicate GISBR diagnostic dock or modify upstream AgenticGIS itself.
8. Ship appropriate GPLv3-compatible combined license notices, pinned vendor upstream SHA, documented adaptation patches, source attribution and a way to refresh the bundled GISBR snapshot.
9. Write offline tests, real QGIS smoke tests, **Indigenous sensitive-data egress tests across general-purpose PyQGIS, API/CLI/MCP, local session/logs and prompts**, negative security tests, PT-BR/English demos, and verify a complete flow: query → plan → approval → download → real layer → follow-up spatial processing. Run a dedicated official TI+DSEI+INPE source test matrix and report live/fixture/unverified states, not only GISBR smoke tests. Test both QGIS 3/Qt5 and QGIS 4/Qt6 if environments are available; otherwise mark untested clearly.
10. Execute every phase in `plan.md` through a release artifact and concise handoff report. Make logical, reviewable commits in **our fork** only. Do not deploy/push to an unapproved production destination.

## Priorities in case of tradeoffs

1. Correct, safe, reproducible **GISBR plus curated official Indigenous source** loading, with exact data provenance.
2. Honest provenance, reference year, spatial clip, partial/truncation handling, permissions and correct return of QGIS layer IDs.
3. One-plugin packaging, no provider collision, no extra mandatory dependencies, maintainability.
4. Broad source discovery via **both catalogs**, true geographic meaning and protection against exposure of sensitive Indigenous locations; advanced niceties only if they do not compromise 1–3.

**For full READY, live test FUNAI TI, FUNAI DSEI area and INPE PRODES/DETER layer paths in QGIS.** If service downtime prevents validation, leave those paths as unverified and report `READY WITH LIMITATIONS` or `NOT READY`; never fake completion.

Do not claim to provide “latest deforestation alerts” using historical MapBiomas land-cover alone. Do not bypass protected SIGEF/gov.br services. Never overwrite unrelated QGIS project content.

## Done means done

Your final report must state the fork branch/commits, pinned GISBR SHA and vendor patches, exact tools provided, commands and PASS/FAIL/NOT RUN results, **per-source Indigenous inventory (catalog-only vs live vs fixture vs blocked), evidence for FUNAI TI/DSEI/INPE live verification and named-TI lookup**, example QGIS layer IDs (from actual runtime, not invented), zipped plugin artifact location, licensing/sensitivity state, source caveats, and **READY / READY WITH LIMITATIONS / NOT READY**. If a required environment is missing, report the untested gate honestly. Implement the feature; do not stop after writing another plan.
