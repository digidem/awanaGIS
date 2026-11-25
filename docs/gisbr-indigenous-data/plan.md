> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# PLAN — Implement GISBR and curated Indigenous data tools in our AgenticGIS fork

**Status:** Executable developer plan / gates and sequencing  
**Scope:** Our own fork and releases only. **Do not open an upstream AgenticGIS PR.**  
**Companions:** [`spec.md`](./spec.md) is authoritative for behavior; [`indigenous-sources.md`](./indigenous-sources.md) is binding for curated Indigenous sources, restrictions and evidence; [`prompt.md`](./prompt.md) is the developer-agent kickoff.  
**Prepared:** 2026-11-23

## Operating rules for the developer agent

- **Implement, test, package, and report**, not just propose an architecture. Make small inspectable commits/PRs **inside our fork** as appropriate; never submit to `ultramenid/AgenticGIS`.
- Start by inspecting **the actual current fork/worktree**, existing PT-BR i18n changes, config, tests, and CI. These documents were based on AgenticGIS upstream SHA `1e4f70b...` and GISBR SHA `06d84dfa...`; don't force the fork back to an old commit. Pin the exact GISBR source revision actually used.
- Preserve existing AgenticGIS API/CLI/MCP tools and QGIS workflows. Keep changed paths focused; avoid unrelated UI changes, broad PyQGIS refactors, or an extra full GISBR panel.
- Honor separate QGIS main-thread versus background-task constraints; do not call long-running GISBR load functions blindly from a GUI or worker thread.
- Record commands and outcomes. **Never mark a QGIS/Qt integration test “passed” if no matching QGIS installation was available.**
- No unreviewed external Python dependencies, no silent `pip install`, no auth bypass or TLS bypass, no forced remote downloads of the whole country.
- **Respect the Indigenous source policy:** a documented public portal is not automatically a supported GIS loader. Sensitive isolated-peoples presence records must not be harvested, inferred or exposed. Village/Indigenous-locality points remain discovery-only unless real cross-tool privacy enforcement is demonstrated.
- **Do not silently shrink scope back to GISBR-only:** the merged curated overlay, FUNAI TI/DSEI and INPE source adapters, named-TI area resolution, and safe ISA/Mapi/RAISG discovery are explicit project requirements.
- Resolve minor implementation details autonomously; document deviations from `spec.md`. If a blocker would violate security, license or one-plugin packaging requirements, stop that feature path rather than quietly weakening it.

## Cross-cutting Indigenous data delivery contract

Read `indigenous-sources.md` **before implementing the catalog**. Maintain a source-by-source manifest recording: `documented`, `terms_checked`, `machine_access_verified`, `loader_state`, `last_checked_at`, `source_year`, `publisher/origin_class`, `sensitivity`, `verification_evidence`. Valid loader states: `loadable`, `pending_probe`, `portal_only`, `discovery_only`, `blocked_sensitive`, `manual_required`, `unavailable`.

**Required first-party source paths:** (1) FUNAI TI polygon(s) and legal-stage metadata, (2) FUNAI-published DSEI operational **area polygons** (not TI polygons), and (3) INPE TerraBrasilis PRODES **or** DETER polygons. Registry presence is necessary but not sufficient; fixture-run connector logic and actual QGIS loading/provenance must be demonstrated. Do not invent a DSEI WFS layer name or assert access when the remote service is unreachable. Complement with restricted/catalog entries for FUNAI villages, IBGE Indigenous localities, ISA TI portal, Mapi, RAISG and MapBiomas Alerta.

**Release status:** Full `READY` requires live tested official FUNAI TI + DSEI polygon + one INPE PRODES/DETER path, correct named-TI resolver and all security gates, in at least one supported QGIS runtime; unavailable endpoints or unrun checks force `READY WITH LIMITATIONS` or `NOT READY` with clear evidence. External service downtime does **not** justify faked success or bypassing safety gates.

## Phase 0 — Audit the fork and prove the GISBR reuse strategy

**Outcome:** A short evidence-based integration decision; no speculative big copy/paste.

1. Inspect current fork HEAD, branch status, Git remotes, QGIS minimum versions, tool schema/dispatch in `core/tools.py`, toolkit and `plugin.py`, MCP tool mirroring, project state, QGIS task runner, permissions, existing tests and i18n. Capture a git baseline.
2. Clone or fetch **GISBR at pinned SHA** and inspect: `gisbr/core/sources.py`, `diagnostico.py`, `recorte.py`, `provider.py`, `algorithms/`, `core/connectors/`, `core/ssl_support.py`, any absolute `gisbr.*` imports, data files, optional Parquet path, and QGIS 3/4 compatibility.
3. Build a **source-coverage inventory** from the actual GISBR registry (not only `fontes-detalhe.md`) **and** the curated Indigenous overlay: source ID, category, protocol, publisher, official/mirror/non-government, UF limits, supported geographic scope, `indisponivel`/manual/Parquet, reference year, license/provenance, connector/runtime capability, sensitivity and `loader_state`. Count GISBR entries automatically and keep the counts/version-specific; independently assert overlay ID uniqueness and required fields.
4. Check license/attribution/redistribution implications of mixing GPL-2.0-or-later AgenticGIS with GPL-3.0 GISBR. Identify any third-party assets, certificate bundles, source data/attribution, and non-code licenses. Define the combined distribution license and NOTICE content. This is a release gate, not post-hoc documentation.
5. Make a **throwaway spike** in a clean QGIS profile: instantiate/relocate GISBR's source engine and provider under a namespaced integration, without relying on an installed `gisbr` plugin. Verify one geobr algorithm, one source metadata lookup, one tiny filtered load, one unload/reload. Confirm how `carregar_fontes` interacts with `QgsProject`, QGIS tasks, GeoPackage writer and nested `processing.run()`.
6. Detect and list hardcoded `gisbr:` algorithm references and absolute `gisbr.` Python imports; map required patches. Test coexistence when official GISBR is separately installed.
7. **Indigenous source feasibility spike:** inspect FUNAI official GeoServer/download documentation, enumerate the actual TI and DSEI layer IDs via `GetCapabilities` when reachable, verify public polygon geometry/CRS and status/portaria fields, and test small bounded download; test an INPE PRODES or DETER source/temporal filter. Prefer existing GISBR WFS connector where compatible; build a small adapter only if necessary. Record real HTTP/error responses, source correction/date, whether any access requires user login. **The research-time FUNAI link was documented but its live endpoint was not verified; do not assume success.**
8. Inspect IBGE Indigenous-locality correction notices, ISA terms/API permissions, RAISG per-theme citations/licenses and WMS-vs-vector, MapBiomas Alerta API registration requirements, and Mapi platform governance. Classify portal-only/blocked sources before writing a downloader.
9. Document chosen adapter packaging with evidence; use a unique internal provider ID (`agenticgis_br`) and track all patches. A temporary external-GISBR PoC is allowed for diagnosis, **not** as the final install dependency.

**Artifacts:** `docs/gisbr-indigenous-data/architecture.md` (or an equivalent tracked path), **merged source/attribution/sensitivity inventory with documented-vs-live states**, pinned SHA, initial smoke script/report, a source feasibility report for FUNAI/DSEI/INPE with timestamped results.  
**Gate G0:** One-plugin vendoring path is technically demonstrable; license plan is acceptable; no collision with `gisbr` provider. If not, fix spike before building LLM tools.

## Phase 1 — Package and isolate GISBR runtime

**Outcome:** Self-contained Brazilian data runtime with a stable internal facade.

1. Create `integrations/brazil/` service boundary, choosing a clear public Python interface as described in SPEC §9.
2. Vendor the **minimum complete runtime set** needed to support catalog/connectors/diagnostic/geobr provider and required assets. Keep code provenance in `vendor/gisbr/GISBR_UPSTREAM.md`, license and upstream patch inventory. Use an auditable script or reproducible process to refresh the pinned snapshot; do not fetch code dynamically from GitHub at runtime.
3. Fix imports while preserving GISBR attribution. Eliminate global `sys.path`/`sys.modules` hacks and conflicting top-level `gisbr` package assumptions. Replace literal `gisbr:<algorithm>` lookups with our internal namespaced provider where needed.
4. Add a standalone overlay module/manifest outside `vendor/gisbr` for Indigenous/territorial sources, plus narrowly scoped validated FUNAI/DSEI/INPE connectors when GISBR lacks the source or protocol. Keep vendor updates reproducible; **do not edit GISBR source dicts to masquerade as an upstream catalog update**.
5. Register the bundled provider exactly once in `plugin.py` lifecycle, and remove it on unload/reload; verify official `gisbr` provider is not overwritten. All toolkit usage must wait until needed QGIS Processing registry setup is finished.
6. Preserve GISBR's source schema and connector behavior, including WFS/ArcGIS error parsing, truncation warnings, source limits, local/manual imports and optional Parquet checks. Do not introduce unrelated GUI components.
7. Ensure QGIS 3.22+/Qt5 and QGIS 4/Qt6 compatible imports and enums; honor QGIS's own TLS/proxy/network preferences.
8. Capture runtime dependencies accurately. Do not require `pyarrow` for GeoPackage-first paths; handle optional raster/Parquet inability as a typed capability restriction.

**Tests:** isolated catalog import, package import under QGIS with and without external GISBR enabled, provider registration/unregistration idempotency, runtime path correctness, license file presence.  
**Gate G1:** A clean QGIS can enable **our fork only**, find its bundled source inventory and execute at least one GISBR-derived capability without external GISBR installation.

## Phase 2 — Offline discovery, metadata, and geographic resolution

**Outcome:** The agent accurately knows which datasets and places exist before requesting downloads.

1. Implement `br_search_sources` using the **merged pinned GISBR registry + separate `indigenous-sources.md`-backed overlay**. Normalize accent/case, English/PT-BR keywords and aliases (TI, FUNAI, DSEI/SESAI, aldeias, localidades indígenas, ISA, Mapi/povos isolados, RAISG, PRODES, DETER); search only curated records and source IDs, not arbitrary web pages. Sort by exact source match/relevance/applicability; bound output length.
2. Add a small versioned enrichment manifest only for fields GISBR lacks: originating institution, official/official_mirror/third-party type (default discovery includes both official and official-origin mirrors), safe keywords, portal/metadata URL, data reference year, attribution/terms where verified, unsupported/capability states. Do not replace original GISBR IDs or invent source years. Entries with unknown terms remain `unknown`.
3. Make the official-vs-third-party filter correct. E.g. `funai_ti_boundaries` is official-direct, `geobr_terras_indigenas` distributes official-origin geometry, `funai_dsei_areas` is FUNAI-published DSEI operational-area data, `inpe_prodes`/`inpe_deter` are official INPE products, `isa_territories`/`mapi_isolated_peoples`/RAISG are civil-society sources, `mapbiomas_cobertura` is non-government MapBiomas, and `osm_*`/`basemap_satelite` are not Brazilian-government sources. Distinguish **publisher** from **load/access policy**: official source can still be `discovery_only` or pending probe. Don't suppress valid sources without explanation.
4. Implement `br_source_details` with `probe=false` fully offline. For `probe=true`, perform bounded metadata/capabilities checks via approved connectors, cache timestamp and failure category, and never treat a metadata response as a guaranteed full download. Verify protocol-specific layer/field names where available.
5. Implement `br_resolve_area`: validated municipality IBGE code/name+UF, supported GISBR regional `Recorte` types and reference codes, explicit `project_layer` with real geometry, **and `indigenous_territory` using a confirmed source-qualified FUNAI/other public TI polygon**. Support cross-municipal/multi-UF polygons without fabricating a GISBR municipality-only `Recorte`. Build disambiguation; determine lookup source/offline/cache behavior; refuse invented or ambiguous IDs.
6. Build typed error helpers shared by all new tools: invalid ID, unavailable, unsupported area/scale, optional capability missing, manual access needed, no network, service failure, and ambiguous location.
7. Use translatable UI messages consistent with completed PT-BR work, while keeping source IDs/payload keys invariant.

**Tests:** PT-BR/EN synonyms (FUNAI, DSEI, SESAI, terras indígenas, povos isolados, PRODES, DETER); accent folding; exact IDs; merged registry uniqueness; default portal-only visibility; UF/scale classification and official-vs-civil-society checks; source policy states; offline mode; ambiguity/invalid municipality/TI IDs; TI spanning municipalities; invalid geometry; read-only probe cache/timeout and blocked remote-sighting queries.  
**Gate G2:** Discovery of **both registries** and geographic resolution work offline (where trusted cached reference data exist) except for explicitly requested live probes; no invented years, TI IDs, WFS layer names, legal classes or government classifications; restricted sources remain non-loadable by default.

## Phase 3 — Deterministic preflight and authorization

**Outcome:** Expensive data retrieval is planned and user intent is respected before any project/file mutation.

1. Implement `br_plan_load`: validate source IDs and chosen area, GISBR supported recorte, UF coverage, `escala_max`, source status, format/Parquet requirements, remote/manual URLs, output destination, existing GeoPackage tables/rasters and disk space.
2. Translate `Recorte` dimensions to GISBR loading inputs. Validate a municipality boundary and its polygon; where GISBR cannot take an arbitrary polygon, report unsupported or implement a safe wrapper that loads a supported larger scope then clips the actual layer geometry. **For a named TI, use a trusted public full polygon mask**, not a centroid, single municipality or fabricated bbox. When a TI boundary is not cached, require explicit bounded reference-data retrieval rather than hidden large downloads. **Never silently treat bbox as exact polygon.** Preserve full TI identity, source revision and cross-UF coverage.
3. Validate source-specific years against actual available values, including `YEAR` enum-index semantics for GISBR/geobr algorithms. Never substitute a different year's data without reporting it.
4. Select output path: current saved project folder or explicit user-chosen location. If neither exists, respond `needs_destination` and ask. Avoid arbitrary working-directory files, hidden output and accidental overwrite.
5. Detect existing output table/file and default to **reuse/skip**. A plan with `replace_existing=true` must include clearly scoped destructive effects and a safe replacement strategy; no unrelated project layers/files are touched.
6. Produce warnings for unknown/large size, slow endpoint, statewide or aggregate scope, many layers, raster, manual SIGEF, missing Parquet, and scope incompatibility. Implement configurable thresholds; choose conservative defaults with documentation.
7. Generate an opaque short-lived `plan_id` bound to normalized source IDs, area ID/geometry fingerprint, output path, replacement policy, years and capability state. Store in memory for current QGIS process only; detect stale/replayed plans.
8. Integrate new tools into AgenticGIS `confirm_external_access` or a dedicated equivalent authorization path. **Check permission before network retrieval/file writes**, without changing the existing stable English permission choice values. Denials do not mutate QGIS or data files.

**Tests:** preflight has no download or project writes; invalid scope/unknown IDs/restricted UF; stale plan; missing directory permissions; large-download warning; no automatic permanent allow; `replace_existing` approval; manual SIGEF prompts but cannot initiate login; **Mapi/ISA portal-only denied for execution; village/IBGE-locality points restricted; FUNAI documented-but-unverified endpoints do not get a ready plan; TI polygon plan includes exact mask geometry fingerprint.**  
**Gate G3:** The agent cannot download arbitrary endpoints, bypass permissions or overwrite user data by crafting tool JSON.

## Phase 4 — Cancellable fetch, geographic filtering, and QGIS loading

**Outcome:** End-to-end layer loading with trustworthy structured results.

1. Implement `br_execute_load(plan_id)`: resolve the trusted frozen plan, **recheck sensitive source restrictions and actual polygon mask identity**, recheck permissions/constraints, and run per-source operations through GISBR **or the narrowly scoped, validated Indigenous overlay adapters** with explicit progress and cancellation. Do **not** expose raw URL/SQL/CQL arguments in the execute schema.
2. Study GISBR's `carregar_fontes` side effects; isolate network/processing on valid QGIS task/thread APIs and marshal `QgsProject`/GUI changes to the GUI thread. Avoid deadlocks around `processing.run()` and asynchronous callbacks; do not simply wrap the whole synchronous diagnostic loader in a Python thread.
3. Respect GISBR filters: server-side municipal code/name or BBOX, then exact polygon clip; country/state/region support only when catalog permits. Handle coordinate transforms, WFS axis-order and ArcGIS record limits; preserve `truncado` metadata. Ensure empty/timeout/HTTP-200-with-error cases stay distinct.
4. Download into a versioned cache or safe staging location, save appropriately to GeoPackage or raster (GeoTIFF when needed), then register *valid* layers. Verify per-layer output exists before adding to project. Temporary outputs must be cleaned after failure or cancel without deleting user files.
5. Apply safe reuse/overwrite behavior. Verify existing QGIS map layers pointing to a GeoPackage remain valid and intact when one table is updated; if not, use a side-by-side versioned output and explain the change instead of corrupting referenced data.
6. Populate per-layer provenance: publisher **and distributor**, original URL, GISBR pinned revision or curated-source manifest revision, year/vintage and correction notices, extraction timestamp UTC, requested scope, actual filter + polygon clip status, source CRS, output CRS, attribution, privacy/sensitivity designation and errors/truncation.
7. Return the **actual QGIS project layer ID** and file paths; mark statuses `loaded`, `reused`, `empty`, `partial`, `truncated`, `skipped`, `manual_required`, `cancelled`, `failed` accurately. `ok=true` should not erase partial failure information.
8. Register new valid layers with normal AgenticGIS project-state visibility and update invalidated caches. Test immediate subsequent `get_layer_fields`, `select_by_expression`, `run_processing`, `set_layer_style`, `create_chart`, and export.
9. Ensure cancellation stops both background source retrieval and subsequent operations where possible. Respect GISBR/Qt feedback, clean staging files, preserve completed outputs, and free tasks on unload.

**Tests:** small WFS and ArcGIS fixture or live path, geobr GPKG, **FUNAI TI polygon, DSEI area polygon and INPE PRODES/DETER fixture plus opt-in live runs**, named-TI clipping and mixed municipal boundaries, optional COG, multi-source partial failure, no features, 200 error body, truncation, geometry filtering, cancellation, re-run/replacement, provenance, layer ID chaining, QGIS UI responsiveness. No raw sensitive point fixtures—only synthetic substitutes.  
**Gate G4:** One **non-GISBR official source** demonstrably downloads live and is manipulable via a subsequent AgenticGIS tool call, with fixture-driven FUNAI TI/DSEI and INPE coverage; another protocol is fixture-tested; cancellation and partial failure are demonstrated without project corruption. Full Indigenous release READY still requires all P0 live source gates.

## Phase 5 — LLM tool discovery and all backend transports

**Outcome:** The agent actually chooses the Brazilian data tools correctly in normal conversation.

1. Add concise JSON schemas and descriptions for `br_search_sources`, `br_source_details`, `br_resolve_area`, `br_plan_load`, `br_execute_load` in `core/tools.py`; wire `TOOL_BY_NAME` and dispatch to toolkit facade.
2. Ensure dispatch logic handles authorization and task orchestration correctly. Do not route an expensive `br_execute_load` through the default `executor.run_sync` in a way that blocks QGIS. Avoid generic uncategorized `run_pyqgis` fallbacks.
3. Confirm the exact tool names and schemas appear in built-in API and CLI agent modes and in external MCP bridge (`server/mcp_server.py` / stdio). Do not maintain inconsistent independent schemas per backend.
4. Teach tool descriptions/prompt context to discover source metadata first, **distinguish government source from non-government/portal-only and high-sensitivity data**, validate geography (including a named TI), plan/approve, execute, and then manipulate results. **Never let the model infer nearby isolated-peoples locations or fall back to arbitrary `web_fetch`/`run_pyqgis` scraping**. Keep instructions compact to preserve model context; prefer actual structured tool outputs over a huge static source catalog in the system prompt.
5. Update agent state summary after load: usable layer IDs, names, relevant source/vintage and warnings. Avoid dumping whole features, GeoJSON, large raw errors, credentials **or Indigenous sensitive point coordinates** into conversations. Mapi records and restricted precise-point datasets must never become loaded agent-visible project data by default; test generic tool/MCP exposure, not only new `br_*` handlers.
6. In PT-BR QGIS, demo source search from Portuguese prompts and keep controls localized without altering internal choice IDs or algorithm names.

**Tests:** scripted/fake-model multi-tool sequence, malformed JSON, unknown source, **non-GISBR official lookup**, Mapi/ISA metadata-only returns, model trying to construct requests for isolated peoples exact locations or route around blocked load using `run_pyqgis`, user declining permission, returned TI polygon ID used for allowed pressure-layer intersections; live API/CLI/MCP smoke where setup exists.  
**Gate G5:** Same request can succeed through the AgenticGIS chat regardless of supported backend, with one stable set of tools and honest status messages.

## Phase 6 — Thorough hardening and regression testing

**Outcome:** Reliable, documented fork release behavior.

### Automated offline suite

- Catalog snapshot schema, GISBR count, **curated Indigenous overlay source registry validation**, ID uniqueness, official publisher evidence, access and sensitivity states, per-source reference-date/terms status; parent registry updates must fail loudly if shape/required enums change.
- PT-BR/English fuzzy search, official classification, UF/scale filtering, documented source restrictions, unknown-year behavior.
- Municipal resolution and duplicate place names; geometry CRS/invalid geometry, no polygon vs bbox distinction.
- WFS query/CQL escaping, ArcGIS field/where escaping, URL allowlist, read-only capabilities probe, timeouts, truncation, pagination and HTTP 200 error body; no accidental whole-country fallback.
- ZIP-slip/decompression payload, malicious metadata HTML, bad URL schemes, path traversal, TLS errors and explicitly disabled certificate bypass.
- Plan authorization, rejected replay/expiry, denied access, large request confirmation, unknown disk budget, manual gov.br behavior, no file write during plan.
- GeoPackage read/reuse/replacement failure, multi-source partial result, cancel cleanup, idempotent project layer add, safe cache behavior.
- Source metadata/provenance completeness, extraction UTC vs vintage, **FUNAI legal-status versus DSEI administrative polygon distinction, IBGE corrected 2022 files, PRODES annual vs DETER alerts vs MapBiomas land-cover/Alerta**, no false official-status or live-access claims.
- Existing AgenticGIS tool dispatch, session storage, backend selection, package imports, provider lifecycle and independent installed GISBR coexistence.
- **Sensitive-source abuse tests (synthetic data only):** Mapi blocked for direct/multi-source load and probing, no exact sighting/presence outputs, no sensitive coordinates through `run_pyqgis`, `get_project_state`, CLI/API/MCP tools, session serialization, error traces, exported charts or other generic tools. If full protection is unachievable, confirm **no precise sensitive layers are auto-loaded**.
- **Portal-only tests:** ISA/MAPI no automated scraping; RAISG WMS cannot masquerade as vector features; MapBiomas Alerta API access respects login/terms. Unsupported dataset states return safe source links.

### QGIS smoke-test matrix

| Runtime | Minimum mandatory smoke |
| --- | --- |
| QGIS 3.x / Qt5 compatible with our fork (>=3.22) | Clean plugin enable/unload/reload, tool inventory, provider uniqueness, one official dataset load, run_processing follow-up, PT-BR and English UI |
| QGIS 4.x / Qt6 | Same lifecycle/import test; provider and algorithm registration; load/clip/provenance; no Qt enum/binding errors |
| Linux | Clean-profile install, normal network/proxy and cache behavior, supported GIS workflows |
| Windows/macOS (if environment available) | ZIP layout, certificates/network, plugin loading, output paths, no hidden dependency assumption; otherwise explicitly mark unverified |
| No Parquet backend | GeoPackage v1/search/plan still work; v2-only reports actionable unsupported reason |
| With official GISBR also enabled | `gisbr` remains theirs, `agenticgis_br` remains ours, both can unload independently |
| Offline | No network attempt for catalog search and source metadata without `probe`, explicit unavailable execution results |

### Live verification policy

- **Not every source must be live during CI**. External governmental endpoints can fail or rate-limit; use deterministic fixtures for CI and an opt-in live test script for at least one verified WFS/ArcGIS/geobr path and one second protocol.
- Record test date, chosen small area, source IDs, exact endpoint/response status, feature counts (if reliable), output, elapsed time, local QGIS version, and whether the data were clipped. Do not commit API credentials, protected geodata or huge test datasets.
- For Indigenous-land/mining/UC workflows, verify **all new overlay IDs are discoverable**, source descriptions/portal links are truthful, and non-sensitive source loading works. Run opt-in live checks for **FUNAI TI, FUNAI DSEI and one INPE PRODES/DETER layer**. If a government service is down, a different official layer may satisfy the general plugin *smoke*, but **does not satisfy the Indigenous source-specific live readiness gate**; mark `READY WITH LIMITATIONS`/`NOT READY` and include fixture evidence.

**Gate G6:** All offline and Indigenous-source safety tests pass; at least one **non-GISBR official live QGIS load**, one additional protocol path, verified permission/clip/provenance and named-TI resolution pass. **Full READY requires the P0 FUNAI TI, FUNAI DSEI and INPE live gates; otherwise mark limitations explicitly**. List platform-specific untested gaps.

## Phase 7 — Documentation, packaging, final review and release

**Outcome:** One clean-installable fork artifact, no upstream submission.

1. Write user-facing docs in `docs/gisbr-indigenous-data/` (or similar): brief usage in PT-BR/EN; discover → inspect → resolve → plan → load → process examples **for named TIs, FUNAI TI/DSEI, and INPE pressure layers**; label supported source categories, `portal_only`/`blocked_sensitive` access states, license/attribution, source age/corrections; cover ISA/Mapi/RAISG restrictions, manual SIGEF, optional Parquet, budgets/cache and removal.
2. Write developer docs: exact upstream GISBR commit, vendored file inventory, patches (including absolute imports and provider ID), **Indigenous overlay manifest/evidence review and update process**, source enrichment, registry version/update commands, thread model, sensitive-data egress model, authorized host policy, test/CI commands and dependencies.
3. Update AgenticGIS fork README, metadata/version as appropriate and changelog. Preserve original project and GISBR attribution/links. Re-check the full combined GPL license/third-party notice inventory.
4. Narrowly modify upstream `.gitignore` so new `tests/**`, `docs/**`, implementation Markdown and required resources are actually tracked. Keep release archive free of unwanted dev files; include all required runtime files, assets, GPL notices, translations and certificates.
5. Build the installable QGIS ZIP from a clean checkout; **do not assume `make test` from GISBR proves runtime compatibility**. Inspect archive contents, test clean-profile installation on at least one supported QGIS, and ensure no separate GISBR plugin is required.
6. Perform a final code review focused on protocol/permission safety, unbounded downloads, GeoPackage corruption risk, CRS correctness, user-visible source provenance and backend parity. Resolve every must-fix item.
7. Produce a compact report: git branch and commits, archive path, executed tests with PASS/FAIL/NOT RUN, known limitations and service statuses, **Indigenous source matrix (FUNAI TI, DSEI, INPE, IBGE, ISA, Mapi, RAISG, MapBiomas Alerta) with catalog/fixture/live/blocked distinctions**, screenshots/logs with no credentials or sensitive coordinates, exact manual reproduction commands, release instructions. Do not push/deploy/release to a live destination unless explicitly authorized by user/project policy.

**Gate G7 / Definition of done:** SPEC §10 checks are satisfied; every external platform/service limitation is disclosed and not misrepresented as passing; a verified single-plugin ZIP exists; all code is in **our fork**, not upstream; the Indigenous source and sensitivity report is complete. `READY` status is reserved for passing live P0 gates and mandatory safety tests.

## Recommended implementation commit slices

These are logical commits, not a requirement to keep exactly this structure:

1. `docs(brazil): pin GISBR source and document integration/licensing architecture`
2. `feat(brazil): vendor isolated GISBR runtime and register namespaced provider`
3. `feat(brazil): merged GISBR/Indigenous source catalog and IBGE + named-TI polygon resolver`
4. `feat(brazil): deterministic load plans and external-access policy`
5. `feat(brazil): cancellable GISBR and FUNAI/DSEI/INPE source adapters, provenance and layer registration`
6. `feat(agent): expose Brazilian data tools through API, CLI and MCP`
7. `test(brazil): protocol, permission, QGIS lifecycle and regression coverage`
8. `docs(release): bilingual usage and self-contained QGIS package`

## Stop signs — never silently downgrade these requirements

- The packaged fork requires separately installing GISBR to work.
- FUNAI TI/DSEI or INPE appears in discovery as **loadable and current** without proof of an actual legal source and valid live endpoint; public FUNAI DSEI polygons are conflated with demarcation boundaries.
- Mapi/isolated-presence geometry, or exact FUNAI village/IBGE locality points, are ingested or disclosed through an uncontrolled existing agent tool/model endpoint.
- ISA/Mapi site is scraped without terms/permission; RAISG WMS is claimed editable as vector; MapBiomas Alerta registration is bypassed.
- The official `gisbr` provider is clobbered, or GISBR absolute imports require global `sys.path` hacks.
- A data request cannot be cancelled or freezes QGIS for an unbounded time.
- Arbitrary model-supplied endpoints run through trusted GISBR fetch logic.
- Changing permission display language changes what is approved.
- Large/global downloads begin without appropriate preflight and permission.
- A source reports success after returning partial/truncated/empty/wrong-year/wrong-CRS data.
- Municipal bbox results are claimed to be municipality-clipped without a polygon clip.
- GISBR GPL-3.0 attribution or source redistribution obligations are omitted.
- CI mock tests are mislabeled as QGIS 3 / QGIS 4 runtime validation.

## Final handoff format (required)

At the end, report exactly:

```text
Implementation summary:
- Fork repo/branch/commit:
- GISBR source commit / vendored change inventory:
- New tools and working example prompts:
- Single-plugin ZIP artifact path:

Validation:
- Offline tests (command + count):
- QGIS 3/Qt5 (version, PASS/FAIL/NOT RUN):
- QGIS 4/Qt6 (version, PASS/FAIL/NOT RUN):
- Live sources tested (source ID, date, area, protocol, status):
- Indigenous overlay status table (FUNAI TI / DSEI / INPE PRODES-DETER / IBGE / ISA / Mapi / RAISG / MapBiomas Alerta; documented / fixture / live / restricted / reasons):
- Named TI polygon resolution and confidentiality/egress tests:
- Permission, cancellation, overwrite, layer-ID chaining results:

Known limitations / follow-up:
- ...

Release readiness:
- READY / READY WITH LIMITATIONS / NOT READY
- Exact blocker(s) if not READY
```
