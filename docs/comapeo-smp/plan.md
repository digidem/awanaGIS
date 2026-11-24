> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# PLAN — Implement Agent-guided CoMapeo SMP exports in our AgenticGIS fork

**Status:** Executable phased plan / quality gates  
**Scope:** Our fork only; no upstream AgenticGIS PR, and no unapproved deployment.  
**Companions:** [`spec.md`](./spec.md) is authoritative for requirements; [`prompt.md`](./prompt.md) instructs the implementing agent.  
**Prepared:** 2026-11-23

## Execution rules

- Do the implementation, tests and packaging; do not end after creating another design document. Use small reviewable commits, clear verification notes and a final status of `READY`, `READY WITH LIMITATIONS`, or `NOT READY`.
- Inspect current fork HEAD, branch, existing i18n, GISBR and Indigenous-data modifications **before editing**. Do not reset to any upstream SHA recorded in the SPEC.
- Read `digidem/qgis-smp-plugin/{README.md,AGENTS.md,comapeo_smp_generator.py,comapeo_smp_algorithm.py,test/test_generator.py,scripts/test-qgis-headless.py}` and its MIT license, plus SMP 1.0 draft specification and CoMapeo map-server. Pin the exact imported reference commit.
- Do not accidentally ship two complete plugin UIs or require installing the original CoMapeo Map Builder. Do not invent a downloader; reuse its actual generator, cache, style and archive code.
- **Non-negotiable gates:** human approval, QGIS thread safety, correct generated tile ranges, no false file/time guarantees, restrictive sensitive-layer handling, atomic output, validated archive, reproducible packaging and truthful test status.
- Tests requiring QGIS are never considered passed based on pure Python stubs. The SMP plugin's `make test-legacy` can exit successfully even when tests fail; do **not** use it as a release gate.

## Phase 0 — Baselines, architecture spike and acceptance fixtures

**Tasks**

1. Inventory actual fork and existing `br_*` tools, QGIS project model, `core/tools.py`, `core/toolkit.py`, `core/processing_tasks.py`, `core/executor.py`, `plugin.py`, chat progress events, cancellation, QSettings, packaging rules, API/CLI/MCP schema propagation and PT-BR translation catalogs.
2. Clone/fetch `digidem/qgis-smp-plugin`, pin a specific commit, read `AGENTS.md`, inspect `SMPGenerator.generate_smp_from_canvas`, `_build_export_plan`, `estimate_tile_storage_bytes`, cache fingerprint, zip creation and `comapeo_smp_algorithm.py` parameter ID meanings. Record any new changes since the referenced tree SHA.
3. Inspect `digidem/styled-map-package/spec/1.0/README.md`, `smp validate` usage and CoMapeo map-server tests. Determine exact lowest-supported importer for our intended CoMapeo release; do not assume SMP draft spec support is uniform across clients.
4. Make a clean QGIS spike (prefer disposable QGIS profile): import renderer in a distinct namespace and generate tiny Local-only `.smp` from an in-memory vector layer, preserving styles and CRS. Test independently with Python ZIP/JSON checks, then try `smp validate`; document QGIS/Qt version and actual result.
5. **Thread-safety spike:** test whether generation via the existing AgenticGIS background `run_processing_background` path is safe with the pinned renderer (it spawns a `ThreadPoolExecutor` and locks `QgsMapRendererCustomPainterJob`). Confirm QGIS GUI stays responsive, cancel works, map is not altered, and a failed remote layer does not wedge a thread. If not safe, define a QGIS-native task/cooperative-main-thread scheduler and prove it works before proceeding. Do not call the entire generator inside a long `MainThreadExecutor.run_sync` job.
6. Inspect how the original plugin packages MIT headers, relative imports and any embedded assets; choose minimum vendored files, update script and NOTICE. Verify single-plugin package and coexistence if the original CoMapeo Map Builder is separately installed.
7. Build reference fixtures: one QGIS project with colored vector polygons and text labels in SIRGAS 2000, one with a selected focus polygon, one with 2–3 differently styled layers, one fake remote provider failure, one extreme/high zoom plan, and one restricted-layer metadata sample.
8. Create a source behavior matrix for QGIS 3.22+/Qt5 and QGIS 4/Qt6, plus platform Linux/Windows/macOS if accessible. Establish which tests are local vs pending.

**Artifacts:** `docs/comapeo-smp/architecture.md` (or tracked equivalent), pinned SHA/patch manifest, `tests/fixtures/smp/`, spike script and real results, known compatibility gaps.  
**Gate G0:** Renderer can be imported safely inside our fork; a tiny `.smp` file passes independent validation; a responsive/cancellable QGIS scheduling approach is proven. If not, **do not implement a fake export tool.**

## Phase 1 — Vendor and isolate the renderer

**Tasks**

1. Add `integrations/smp/` service boundary and `integrations/smp/vendor/` containing minimum needed code from `digidem/qgis-smp-plugin`, **not** the full standalone GUI/provider unless proven necessary. Preserve MIT notice and copyright, record exact revision and changes. No dynamic code download or auto-install.
2. Adapt relative imports and QGIS 3/Qt5 vs QGIS 4/Qt6 enum/dialog calls without conflicting `comapeo_smp` provider. Keep original generator source methods stable except for a **mandatory ordered render-layer allowlist/snapshot seam**, proven to exclude restricted or omitted layers at actual tile rendering time. Changes should be narrow and well tested. If separate `agenticgis_smp` provider is used, register/unregister once and verify other installed SMP/GISBR providers keep working.
3. Add a typed internal facade, e.g. `SmpService.inspect(...)`, `suggest_regions(...)`, `build_plan(...)`, `start_export(...)`, `status(...)`, `cancel(...)`, `validate_file(...)`. No QGIS objects appear directly in JSON tool results.
4. Integrate with QGIS cleanup/unload and source change notifications. No orphan threads, duplicated providers, stale QGIS pointer dereferences or leaked temp files after plugin reload.
5. Ensure all needed vendor data/files end up in ZIP; upstream `.gitignore` excludes Markdown files by default so track runtime README/licenses/manifest intentionally and verify package with a file-list check.

**Tests:** import under both Qt bindings when available; provider no-collision, one plugin reload, license manifest completeness, release ZIP zipfile list.  
**Gate G1:** One installed fork is sufficient; imported renderer retains behavior and can be replaced from a pinned upstream snapshot reproducibly.

## Phase 2 — Read-only map inspection and candidate region selection

**Tasks**

1. Implement `smp_inspect_map`: actual canvas bounds/CRS, visible layer order, selected features/layer extents, renderer source types and attribution hints, available output codecs and QGIS version. Avoid exposing credentials hidden in URL/provider URIs; handle unsaved and empty projects.
2. Implement `smp_suggest_regions` with explicit user area references: canvas; current/selected layer; selected features; validated WGS84 bounding box; pre-resolved `br_resolve_area` territory/municipality where the GISBR component exists. If `br_*` is absent, return capability unavailable rather than crashing.
3. Resolve labels and bounds from actual QGIS geometry, with optional buffer; compute actual WGS84 and EPSG:3857 bounds and ensure region contains local. Never silently use a different named TI/municipality; disambiguate territory names through existing resolver, not an LLM guess.
4. Build candidate plans (`Compact`, `Balanced`, `Detailed`) by applying 2–3 practical zoom/extent/encoding combinations. Use user constraints (archive cap, time cap, intended device storage, desired detail, raster resolution) and show each plan's tradeoffs.
5. Add layer/export-policy inventory. Restricted Indigenous layers (from prior integration metadata) require suppression/denial, not merely a chat-level warning. Unknown rights → warning/confirmation and opt-in subset; do not export embedded proprietary XYZ imagery without authorization.
6. Add scale/detail reasoning based on pixel resolution at latitude, project rendering behavior and source-native resolution. Detect blank/offline missing tiles and unusual layer-scale visibility where possible; preview sample renders on demand and flag opaque/nodata/white tiles.

**Tests:** extent from canvas vs selection, transformations for EPSG:4674, EPSG:4326 and UTM; invalid CRS, empty selection, giant rectangle, near-polar location, antimeridian; hidden layers and restricted layers; project with no meaningful World imagery; no implicit project mutation.  
**Gate G2:** The region recommendations are spatially grounded, displayed bounds are correct, and the user can see why medium and maximum detail cover different extents.

## Phase 3 — Deterministic export planning and calibrated preflight

**Tasks**

1. Introduce immutable normalized `ExportPlan` containing project/source fingerprint, rendered layer IDs and settings, World/Region/Local extents, effective zooms, tile codec/quality, output preferences, warning set and creation timestamp. Generate an opaque `plan_id`; reject caller-forged/expired plans.
2. Use the pinned generator's `_build_export_plan` to calculate per-source/per-zoom XYZ tile counts. Do not implement an independent off-by-one tile counter. Normalize auto-adjusted Local zoom, surface changes and require approval of effective settings.
3. Apply strict zoom ordering, Region containment and Web Mercator CRS limits. Treat a bounding polygon as a *rectangle of tiles*, not polygon-clipped coverage. Reject or explicitly split highly disjoint areas; detect source slots if World or Region omitted.
4. Implement `smp_estimate(sample_mode=none|small)`. `none` returns exact tile counts and clearly low-confidence rough size/time. `small` runs a bounded representative sample of (e.g.) 8–30 tiles across role, zoom and different imagery/labels/blank zones; it must not create a full package.
5. Measure tile file byte sizes for selected supported format and quality, local rendering and encoding times. Estimate low/likely/high ranges and stage-time breakdown; report `method`, sample size and uncertainty, not unjustified exact sizes or minutes. Use `SMPGenerator.estimate_tile_storage_bytes` **only as fallback**, label the method.
6. Validate available memory/disk on scratch/cache and destination volumes; account for temp tile contents + archive simultaneously, margin/reserve, possible duplicated output, ZIP32/dedup issues and consumer-specific size constraints. Offer a smaller alternative when over budget.
7. Guard network assumptions: an online provider may cause variable download time or fail. No remote downloads during a read-only estimate; bounded sampling only after approval, and return `unknown` when necessary.
8. Build a single clear user-facing approval summary with layer list, each source's extent/zoom/tile counts, likely/low/high archive size, runtime interval, output location, overwrite status, source rights and uncertainty.

**Tests:** mocked generator tile ranges, 1-tile/edge cases, world 0–3 count, world upper bound sanity, Region/Local no overlap, generator auto-adjust handling, invalid format/quality, zero available disk, cache vs clean build, RGB/JPG vs transparent/PNG, sample variance, unstated runtime time must show unknown.  
**Gate G3:** A user can compare valid plans and understand size/runtime *before* any full render; automated tests establish estimates never masquerade as actual outcomes.

## Phase 4 — Agent tools, permissions and asynchronous job state

**Tasks**

1. Register `smp_inspect_map`, `smp_suggest_regions`, `smp_estimate`, `smp_start_export`, `smp_export_status`, `smp_cancel_export`, `smp_validate_file` using existing `core/tools.py`/toolkit dispatch. Ensure API tool list, CLI tool prompts and external MCP exposure share exact names/schemas; update backend capability descriptions.
2. Use the existing `ask_user` flow for explicit approval, including *stable choice IDs independent of translated labels*. Approve a specific immutable plan and destination, not vague future exports. Request separate explicit approval for replacing a file or export of online layers requiring user-held rights.
3. `smp_start_export` returns a `job_id` quickly, then progress/status/cancel are usable even from an external MCP caller. One job at a time by default; queue/busy behavior deterministic. No blocking an HTTP/MCP request for many hours.
4. Implement state machine: `queued -> preparing -> rendering -> archiving -> validating -> completed` and failure/cancellation paths. Status carries exact tile count progress and revised elapsed/remaining intervals when enough evidence is available.
5. Keep only safe thread-owned QGIS objects on their correct threads; use verified scheduling from Phase 0. `QgsProject` or canvas API access must never happen on unapproved background threads. Keep QGIS UI interactive and process cancellation cooperatively. Ensure the renderer gets **only the explicitly approved layers**, in correct order, independent of other layers visible in QGIS.
6. Clear stale `plan_id` after project/style/visibility/order change, after preset source selection changes, and on significant layer changes. Compare fingerprint again before render start **and while producing the tile set**. Unsaved in-memory edits and remote updates may evade upstream cache fingerprints; disable cache reuse unless consistency can be proved.
7. Update session/cache lifecycle: preserve completed file history without dumping sensitive coordinates/provider tokens into transcripts and logs. Do not treat failed/canceled jobs as successful.

**Tests:** real tool dispatch, invalid JSON, unknown tools, no-approval denied, modified project invalidation, replay and second-start prevention, cancelled job, MCP polling, CLI handoff, PT-BR labels vs immutable permission values, concurrent job rejection, QGIS unload/reload.  
**Gate G4:** Any backend can plan/start/check/cancel; permission tests show no export without approval; UI and MCP remain responsive.

## Phase 5 — Render, package and validate

**Tasks**

1. Generate SMP using the bundled `SMPGenerator` and effective plan, preserving 256px XYZ Web Mercator and current styled QGIS layer order. Do not use a generic XYZ downloader or the shell script's hardcoded bounds. Show useful per-source and total progress.
2. Render into an isolated staging/cache directory; use content+renderer fingerprint. Reuse cache only on exact match and exclude `_cache_meta.json` and stale extra tiles from the archive. Re-test output when user changed imagery, labels, vector content, encoding or source extents.
3. Check before writing that proposed tile count, file size and ZIP entries are feasible; select a portable ZIP mode. Resolve the `smp:bounds` edge case: pinned exporter uses Local bounds; SMP draft recommends union of source bounds. Check a multi-source archive with the actual CoMapeo importer before altering that metadata, and record the chosen compatible behavior. **Default to standard archive construction, without nonstandard central-directory dedup aliases.** ZIP64 is permitted only after the actual CoMapeo importer has been tested for it; otherwise stop with a clear size limit.
4. Write to a protected `.partial` file on destination filesystem; validate ZIP entries, `VERSION`, root `style.json`, MapLibre v8, WGS84 bounds, SMP URIs, matching tile paths/byte signatures, source zooms and no unwanted external URLs; then finalize atomically. No partial final file on cancel/fail.
5. Validate against independent `smp validate` CLI in CI/test environment and with `@comapeo/map-server` using fixture and actual generated file. Do not make Node/npm a runtime prerequisite for QGIS.
6. Verify real rendering of labels, transparency/imagery, **approved layer allowlist exclusions**, layer render order, and that World/Region tiles are **not blank where context is promised**. Mark or block incomplete packages; never hide provider failures behind blank fallback images.
7. Confirm final file exists and report actual bytes, hash/checksum if appropriate, total tiles, effective zooms, sources, validated state and import instructions. File path is not a download link to a hosted server.

**Tests:** local raster/vector QGIS project to SMP, Local-only and World+Region+Local, PNG/JPG/WebP supported codecs, cache resume/cancel, corrupt/stale tile rejection, unsafe ZIP names, 4 GiB/65k limit mocks and ZIP64/consumer acceptance, output overwrite refusal, ZIP integrity and independent reader.  
**Gate G5:** A real sample can be generated, validated and re-opened; unsafe/incomplete output does not appear as success.

## Phase 6 — UX, localization and source-policy integration

**Tasks**

1. Keep existing AgenticGIS chat UX simple; integrate text comparison of recommendations plus optional compact preview of extents/tiles if existing GUI components support it. Do **not** add a new complex dock just for SMP.
2. Add all new human UI/status/error strings to existing Qt translation mechanism; native Portuguese (PT-BR) and English fallbacks, no translated internal IDs or payload keys.
3. Document how GISBR/Indigenous layers can be included after loading, and how protected sensitive-source metadata is enforced at exporter entry points. No automatic inclusion of restricted layers or inferred community locations.
4. Show caveats for online tiles/Mapbox/OSM imagery licensing, user passwords in provider URIs, incomplete satellite imagery, no elevation/vector editability, and remote WMS latency.
5. Update fork README, release docs and examples: request in PT-BR and English, how to select Region and Local, budget guidance, output location, CoMapeo Mobile/Desktop Background Map import, offline validation and troubleshooting.
6. Ensure no conflict with the original CoMapeo Map Builder if separately installed; include upstream MIT attribution and valid combined-license notices. Respect `.gitignore` Markdown filter and package vendor manifests explicitly.

**Tests:** PT-BR live screenshot/manual UI check, English QGIS screenshot, status/progress readable, settings no regressions, GISBR processing still available, no leaked hidden layer in SMP, no duplicate SMP provider, world tiles disclaimer when no world base.  
**Gate G6:** End-to-end workflow works naturally in PT-BR/English and respects prior data-source policies.

## Phase 7 — Validation on real CoMapeo clients and QGIS matrix

**Tasks**

1. Run reference exporter tests: `PYTHONPATH=. python3 test/test_generator.py` from pinned original SMP project (use adapted equivalent after vendoring), original `scripts/test-qgis-headless.py` in a supported QGIS environment, tests in our fork. Do not claim `make test-legacy` is a passing gate.
2. Test QGIS 3.22+/Qt5 and QGIS 4/Qt6 where actual installation exists; record version/OS/device and missed coverage. Verify plugin activation/unload, giant plan rejection, Worker/MCP/CLI status polling and cancellation.
3. Generate at least three files: tiny Local-only fixture, normal Region+Local fieldwork file, World+Region+Local file. Independent SMP CLI validator must accept representative output when available; do not use only `zipfile.testzip()` as proof.
4. Import at least one freshly generated file into a supported CoMapeo Mobile or Desktop client; inspect at region and local zoom, close/reopen offline, verify no blank tiles or wrong zoom/CRS, verify 256px `tileSize` and labels. Record observed app version/platform.
5. Test online tile sources with network throttled/unavailable: warnings and failure behavior must be honest and non-destructive. Test restrictive license/source metadata.
6. Compare predicted and actual tile count/size/duration across three realistic maps (simple vector, labeled mixed map, imagery/remote); capture QGIS/CPU/RAM, output codec, sample size, confidence interval and actual values. Tune assumptions based on real evidence, not wishful fixed estimates.
7. Verify standalone fork ZIP fresh install (one plugin), with and without separate GISBR and original SMP plugin, i18n and `br_*` features, Python environment dependencies, tests and release notes. No user tokens or credentials embedded.

**Artifacts:** `docs/comapeo-smp/test-report.md`, evidence/fixtures (no sensitive data), benchmark table with prediction/error, real imported SMP example, release ZIP installation report.  
**Gate G7:** Full `READY` requires CoMapeo consumer proof, end-to-end QGIS proof, security and cancel tests. `READY WITH LIMITATIONS` only for precisely documented unavailable environments/noncritical issues; never call an untested exporter fully ready.

## Phase 8 — Final code review, packaging and fork delivery

**Tasks**

1. Run complete tests/lint/security checks available to the fork; inspect changed files for unwanted SMP plugin UI, duplicate providers, accidental logging/secrets, stale cache or partial artifacts, permission bypass and regressions to generic `run_pyqgis` or GISBR tools.
2. Reconcile `spec.md` acceptance A–J; list each item as `PASS`, `FAIL`, or `UNTESTED`, with exact test command and evidence. A failure affecting security, invalid files or UI freezes is a blocker.
3. Build installable fork ZIP with documented versioning; inspect ZIP entries including `metadata.txt`, vendor renderer, license/NOTICE, translations and scripts/assets necessary at runtime. Do not push to production, publish release, or open upstream AgenticGIS PR without authorization.
4. Prepare concise developer report: implemented features, chosen architectural tradeoffs, fork commits, test matrix, size/time estimator calibration, sample SMP path/import evidence, limitations and next improvements. Note which tests were QGIS-free, headless-QGIS, full GUI and actual CoMapeo.
5. Provide suggested subsequent backlog separately (multiple nonrectangular local AOIs in one SMP, vector SMPs, map preview UI, remote download/transfer, source-specific sampling profiles), not as hidden scope creep.

**Gate G8 / Definition of done:** Feature does what real users asked—*recommend sensible medium and high zoom regions, credibly estimate output size and time, obtain consent, produce an actually usable CoMapeo SMP*—within our single AgenticGIS fork. No unsupported success claims.

## Compact stage-gate checklist

| Gate | Required evidence |
|---|---|
| G0 Spike | Tiny real QGIS SMP + threading/cancel proof |
| G1 Package | Bundled MIT renderer, no second plugin, no collisions |
| G2 Coverage | Accurate Region/Local candidates from actual project geometry |
| G3 Estimate | Exact tile math + honest, preferably sampled byte/time intervals |
| G4 Agent tools | Same behavior API/CLI/MCP, approval, job status/cancel |
| G5 Output | Valid SMP, no partial final or stale cache |
| G6 User workflow | PT-BR/English, license/privacy caveats, no regressions |
| G7 Field test | Real CoMapeo import + offline display, QGIS compatibility evidence |
| G8 Delivery | Reviewed fork ZIP, tests, attribution and documented limits |

## Example test commands (adjust paths after integration)

```bash
# From the pinned CoMapeo Map Builder source checkout:
PYTHONPATH=. python3 test/test_generator.py
QT_QPA_PLATFORM=offscreen ./scripts/test-qgis-headless.py

# From the fork: use the project's existing test/CI conventions
python3 -m compileall -q integrations/smp
python3 -m pytest -q tests/test_smp*   # only if pytest/tests are present

# From CI or a development machine with the independent SMP CLI installed:
smp validate /path/to/generated-test.smp

# Basic structural debug — never substitute for consumer validation:
python3 -m zipfile -t /path/to/generated-test.smp
```

Do not execute dangerous install/cleanup or publish commands as part of exploratory testing. Report missing tools, unavailable QGIS versions and unmet preconditions explicitly.
