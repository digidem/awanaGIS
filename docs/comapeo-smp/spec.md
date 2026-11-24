> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# SPEC — Agent-guided CoMapeo SMP exports from QGIS

**Status:** Developer-ready specification (implementation and runtime verification still required)  
**Target:** Our independently distributed AgenticGIS fork, alongside PT-BR localization and Brazilian/Indigenous data integration. **Do not submit this integration to `ultramenid/AgenticGIS`.**  
**Prepared:** 2026-11-23  
**Companions:** [`prompt.md`](./prompt.md) is the agent kickoff; [`plan.md`](./plan.md) is the execution sequence.  
**Primary objective:** A user asks the AgenticGIS chat assistant to create a CoMapeo offline map from their *current, styled QGIS project*. The agent proposes practical World/Region/Local coverage and zoom ranges, estimates size and runtime before export, obtains approval, renders the map, and returns a validated `.smp` file path.

## 1. Inspected baselines and source of truth

| Project | Reference / inspected baseline | Role |
|---|---|---|
| AgenticGIS | <https://github.com/ultramenid/AgenticGIS> (`main` SHA `1e4f70b488824982a835c89c202454ec92dafae7`) | Agent chat, tool schemas/dispatch, PyQGIS, cancellation, MCP |
| CoMapeo Map Builder | <https://github.com/digidem/qgis-smp-plugin> (`main` commit `34715788e94718d036a58f9992d7ef69b9ecf3d5`; plugin metadata version `0.9.0`) | Existing reference implementation / raster tile renderer / `.smp` writer |
| SMP format | <https://github.com/digidem/styled-map-package/blob/main/spec/1.0/README.md> (`main` commit `7d69969b47ac09ed7d4d182e3ebf7c2b6b648169`) | SMP 1.0 specification **draft** / validation expectations |
| CoMapeo map consumer | <https://github.com/digidem/comapeo-map-server> (`main` commit `ad14ea8e3d261eddfb0fb99f85e69c5c9fcf0c22`) | Real offline map consumer / compatibility test target |
| Existing fork handoff | `docs/gisbr-indigenous-data/{prompt,spec,plan,indigenous-sources}.md` | Preserve GISBR, Indigenous data policy and tool contracts if integrated |

**Pre-development rule:** Inspect the actual fork/worktree HEAD and newest selected SMP repository revision. These SHAs document the review, not permission to downgrade or overwrite newer work. Pin the exact imported renderer version and record local adaptations. Read `digidem/qgis-smp-plugin/AGENTS.md` and its tests before altering internals.

**Verified implementation facts:** The CoMapeo Map Builder source contains `SMPGenerator` in `comapeo_smp_generator.py`, `ComapeoMapBuilderAlgorithm` in `comapeo_smp_algorithm.py`, and a Processing provider. `SMPGenerator.generate_smp_from_canvas(...)` accepts Local extent/zoom, optional World (0..world max), optional Region extent/zoom, PNG/JPG/WebP, quality, cache directory, workers, and a precomputed `export_plan`. `_build_export_plan` computes per-source tile ranges/counts. Existing size estimates use fixed per-tile guesses (PNG ~50 KiB, JPEG ~15 KiB, WebP ~11 KiB), **not actual measurements**, and no calibrated time forecast exists. Rendering uses EPSG:3857 and 256px XYZ tiles. The exporter currently has ZIP32/dedup paths; do not assume all large archives or all ZIP readers are compatible.

## 2. User stories / acceptance scenarios

1. **One request, guided execution.** “Transforme meu mapa atual em um SMP para usar offline no CoMapeo.” The agent inspects the live project, proposes coverage, reports cost/time estimates, requests approval, exports and gives the file path.
2. **Medium and maximum detail regions.** “Quero toda a TI em zoom médio, mas alta resolução só nas trilhas e aldeias que selecionei.” The agent derives a *Region* extent covering the broader territory and a smaller *Local* extent covering an explicit selected focus; avoids excessive area at maximum zoom. Sensitive coordinates are neither inferred nor published by default.
3. **Budget optimization.** “Faça um mapa de no máximo ~500 MB para os celulares.” The agent compares candidate Region/Local ranges and formats, prioritizes a feasible plan with an uncertainty interval and explains what will be lost at lower zoom.
4. **Existing layer workflow.** “Carreguei camadas FUNAI, rios e estradas com GISBR. Gere o SMP das camadas visíveis.” The exporter respects the chosen visible layers, rendering order, styles, labels and provenance restrictions without requiring GISBR at runtime when not present.
5. **Failure or interruption.** If remote source tiles are inaccessible, the QGIS project changes, disk space is insufficient, the job is canceled, or the package does not validate, return a clear failure; never claim a usable SMP or leave a corrupt final file.
6. **PT-BR and English.** The interface and status/error messages follow QGIS's locale; internal tool names, parameter keys and saved plan IDs remain stable English identifiers.

## 3. Scope and non-goals

**In scope:** Conversational planning, QGIS project inventory, geographic extent choices, zoom suitability, exact tile counts, sampled size/time estimates, explicit confirmation, locally saved raster SMP exports, progress/cancellation, resumable cache where safe, integrity checks, example import guidance, honest limitations, offline tests and QGIS/CoMapeo smoke tests.

**Out of scope (first release):** Vector-tile generation, automatic creation of separate detail tiles for arbitrarily many disjoint AOIs within *one* SMP, editing maps inside CoMapeo, mobile app automatic import, uploading/publishing SMP to an external server, fetching arbitrary tile URLs supplied by the LLM, automatically installing dependencies, changing the SMP file specification, changing CoMapeo's importer, auto-identifying confidential areas, or developing a new rendering engine.

**Distinction:** “Download SMP” in the conversation means *generate and save a rendered offline map package on the user's QGIS machine*. Network fetching of source imagery may occur during rendering, but the agent must not imply that CoMapeo itself downloads an SMP from QGIS automatically.

## 4. UX: minimal guided planning, no separate complex panel

### 4.1 Default conversation

1. **Inspect:** live project CRS, current canvas extent, visible layers (provider/format, label scale visibility, online/offline), selected features/layers, layer extents, current map theme/render order, project name, available drive space; never mutate project on inspection.
2. **Resolve coverage:** suggest a *Region* (medium zoom) and *Local* (highest zoom) area using actual selected geometry or chosen layer, current canvas, explicit polygon, project AOI, or validated GISBR/Indigenous territory boundary. Display the actual rectangle and provenance of each proposed extent; do not silently substitute a municipality for a TI.
3. **Offer 2–3 choices:** e.g. `Compact`, `Balanced` (preferred), `Detailed`; each has World/Region/Local extents, zoom bands, tile count, size interval, estimated time interval and warnings. Values must be computed for this project, not copied from generic examples.
4. **Explain compromises:** higher zoom increases tile counts fast; region covers navigation/context, local covers detailed fieldwork; the map is flattened to raster; source labels/legends remain as currently rendered, and data may be stale.
5. **Approval:** show exact output path, file name, layer selection, coverage, zoom, encoding, estimated storage/time, any remote-source/license/privacy warnings. Ask before starting any substantial render and before replacing a file; allow explicit smaller preflight sampling, not automatic expensive rendering.
6. **Run:** report preparation/rendering/packaging/validation steps and progress, allow cancel and status checks without blocking the chat/MCP indefinitely.
7. **Complete:** return real output path, actual archive size, effective extents/zoom/format, per-source tile counts, validation result, source list, notes for import via CoMapeo's Background Map screen, and any difference from estimates. Never claim a completed download before validation.

### 4.2 Coverage choices

| Coverage role | Geographic extent | Zoom use | Rules |
|---|---|---|---|
| World *(optional)* | Whole world | Low zoom context (e.g. 0–3) | **Default off in agent-generated plans** unless meaningful globally styled data/basemap exists and it can legally be packaged. Avoid blank/worldwide high-zoom exports. |
| Region *(optional; suggested for larger field territories)* | Larger geographic rectangle around the project AOI: TI, protected area, catchment, routes, neighboring settlements as explicitly selected | Medium zoom (e.g. 4–8) | Must contain Local. Bound by need and available imagery rather than always using a whole state. |
| Local *(required)* | Focus rectangle: selected sites/routes/trails, canvas, or selected geometry buffered appropriately | Highest detail (e.g. 9–15) | Minimum/maximum zoom chosen by desired physical detail, imagery/native data resolution, map readability and budget. |

The example zoom ranges are *illustrative*, not fixed defaults. The plugin's actual hard rules: `World.max < Region.min <= Region.max < Local.min <= Local.max`; with Region disabled, `World.max < Local.min`. Zooms are 0..24. The existing generator may auto-adjust Local minimum when filling World gaps/avoiding overlaps; **show the effective adjusted plan and re-confirm it** rather than silently executing different settings. Coverage gaps must be detected and explained (or corrected explicitly).

**Important constraint:** The current generator supports one rectangular Region and one rectangular Local extent per SMP. For long rivers or disjoint hotspots, first release should suggest multiple SMP files or one bounding box with an explicit cost warning; no claim of polygon-exact tile coverage. Geometry-derived polygons are used to propose bounds, but XYZ tile coverage is rectangular. A source with sparse content in its bounding rectangle may produce blank tiles; check in preview.

### 4.3 Recommendation logic

- Prefer selected project geometry when explicit, otherwise known AOI layers, then current visible map extent; ask a concise targeted question only when multiple plausible regions need user choice.
- Give extent candidates as `[west,south,east,north]` in EPSG:4326 plus project CRS original and transformed EPSG:3857, using QGIS transform context and proper antimeridian handling. Confirm a valid transform, clamp Web Mercator latitude only with warning; never silently distort or transform without a valid CRS.
- Suggest Local max zoom using approximate equatorial 256px Web Mercator resolution `156543.03392804097 / 2^z` m/px and local-ground resolution approximately multiplied by `cos(latitude)`; warn that renderer QGIS styles/scales and output quality are also relevant. **Do not imply zoom beyond native raster resolution creates more real detail.** Sample complex labels/styles at recommended zoom levels.
- Use cached/static offline layers preferentially; identify remotely fetched XYZ/WMS/WMTS layers and warn that missing tiles, network speeds, provider restrictions or expiry may affect output. Never bypass attribution/licensing, token restrictions, or access controls.
- Calculate how large the Region and Local boxes need to be based on actual AOI and user-provided buffer/context. Do not autonomously guess exact aldeia locations or expand sensitive bounds.
- Prefer JPG for opaque imagery and WebP (if encoder/consumer tested) for mixed content; PNG for sharp linework/labels/alpha. Validate format support at runtime. Recommend based on measured tile samples and clarity, not solely theoretical compression.
- The `Compact / Balanced / Detailed` variants must all be valid, comparable plans. When the user's strict budget is infeasible, say so; do not present a falsely compliant plan.

## 5. Proposed AgenticGIS tool contracts

**Names may be adjusted only if justified and consistently propagated through API/CLI/MCP, tests and docs.** Use structured, deterministic JSON responses; keep tool descriptions concise. Reuse `core/tools.py` dispatch, `core/toolkit.py`, QGIS main-thread executor, agent state/permission gate, CLI and MCP mirrors. Expose the same functionality on all backends.

### `smp_inspect_map`

**Input** `{}` or optional `{include_hidden:false}`. **Output:** `ok`, `project_name`, `project_crs`, `canvas_extent`, `visible_layers:[{id,name,source_type,provider,crs,extent,scale_visibility,online,attribution,export_policy}]`, `selected_layer_ids`, `selection_extent` (when known), `warnings`, `qgis_version`, `smp_capabilities:{formats,can_render,reason}`. No expensive remote fetch. No leaking credentials in URI/report.

### `smp_suggest_regions`

**Input:** `{area_reference:{type:"canvas|layer|selection|bounds|br_resolved_area",id?,bounds?,crs?}, local_reference?, region_buffer_km?, local_buffer_km?, include_world?, constraints?:{target_size_mb?,max_time_minutes?,preferred_format?,device_profile?}}`. **Output:** `ok`, `candidates:[{name,reason,coverage:{region?,local,world?},recommended_zooms,format,quality,provisional_estimate}],selection_requirements`, `warnings`. Local/Region computed from actual geometry or explicit bounds; `br_resolved_area` only when the GISBR feature is installed/active. No network rendering in this tool.

### `smp_estimate`

**Input:** complete *normalized* candidate config (coverage, per-role zooms, format/quality), `{sample_mode:"none|small"}`, optional size/time budget. **Output:** `ok`, `plan_id`, `project_fingerprint`, `source_revision`, `effective_config`, `tile_counts:{world,region,local,total,by_zoom}`, `estimated_archive_bytes:{low,likely,high,method}`, `estimated_runtime_seconds:{low,likely,high,method}`, `scratch_disk_bytes`, `free_disk_bytes`, `coverage_gaps`, `remote_layer_warnings`, `privacy_licensing_warnings`, `confidence`, `requires_confirmation`. A plan is immutable and has a short TTL; recalculation required if project/styles/layers change. `sample_mode:small` is an explicitly approved, bounded preflight that renders representative tiles without creating an SMP.

### `smp_start_export`

**Input:** `{plan_id,output_path,confirm:true,overwrite:false}`. Only starts a job after explicit human approval for the exact normalized plan. **Output:** `{ok,job_id,status:"queued|running",output_path_pending,plan_summary}`. Validate output is an authorized local file with `.smp`; never overwrite without separate approval. Check fingerprint, free disk, unsupported layers, source/policy checks immediately before start. One concurrent export per QGIS process by default. No arbitrary shell execution, unknown URLs, or external upload.

### `smp_export_status` / `smp_cancel_export`

**Status input:** `{job_id}`; **output:** `state`, per-role stage/progress (`preparing/rendering/archiving/validating/completed/failed/cancelled`), completed/total tiles, time elapsed and revised remaining-time range when supported, warnings, error, completed artifact info only on success. **Cancel input:** `{job_id}`; cancels cooperatively, cleans partial final output, returns state, allows safe cache resume when fingerprint matches. Idempotent behavior; expose via MCP too.

### `smp_validate_file`

**Input:** `{file_path}` limited to local output and authorized accessible files. **Output:** `{ok,valid,archive_size_bytes,tile_count,sources,zoom_ranges,issues,consumer_test_status}`. Pure-Python ZIP/style validator should work without Node; optional independent `smp validate` and CoMapeo map server/device test as release gates, not a mandatory end-user runtime dependency.

`plan_id`/`job_id` are opaque and non-forgeable across sessions; never accept arbitrary caller-generated plans as already approved. Expire stale plans and clear jobs on unload safely; serialize only minimal resumable state (not source secrets, caches or sensitive coordinates) to persistent settings.

## 6. Estimation: accuracy and honesty

**Exact mathematical part:** Reuse the renderer's `_build_export_plan` / `_calculate_tiles_at_zoom`; count inclusive XYZ x/y ranges per source, per zoom, and total, after all automatic min-zoom adjustments. Handle WGS84 vs project CRS correctly and validate Region contains Local. No raster data downloading needed for exact tile count.

**Approximate output size:** Existing renderer's `estimate_tile_storage_bytes()` is a *coarse fallback*, not a real SMP-size prediction. When `sample_mode:small` is authorized, render a bounded, geographically and zoom-stratified sample (e.g. 8–30 tiles total, configurable maximum), measure actual bytes for PNG/JPG/WebP at selected quality and include a sensible ZIP overhead range. Stratify by imagery/labels/blank areas rather than only empty corners. Extrapolate low/likely/high using per-stratum counts and variance; include `method`, `sample_size`, uncertainty and note that transparent/identical tiles, complexity and compression vary. Treat ZIP dedup as an optional bounded optimization, not a guaranteed saving. Never report estimates as exact final size.

**Approximate duration:** Time representative tile rendering and local encoding, plus packaging sample. Estimate using observed effective throughput and sample variability; report `low/likely/high`, note uncertainty for slow remote WMS/XYZ tile providers or unbounded network access. Keep sample small and abortable. If there is no calibrated sample, return `unknown` or a visibly low-confidence coarse range, never invent a precise minute count. Update projected completion once enough real tiles have rendered.

**Disk budget:** Include scratch tile files + output archive + reserve, not merely final file. Check actual target volume free space, output write permission and whether cache is on a separate volume. Revalidate on export. Large plans should fail closed or request a smaller plan at conservative thresholds, not kick off a multi-hour render unintentionally.

**Candidate comparison:** Include a tabular summary to chat: `World / Region / Local zooms`, bounds labels, exact tiles, size range, time range, recommendation, source caveats. Expose optional per-zoom tile histogram. Do not hardcode size/time claims based solely on zoom levels.

## 7. Rendering/export architecture

**Preferred:** Bundle the *minimum required* CoMapeo Map Builder renderer code (MIT) under a distinct namespace (`integrations/smp/vendor/` or equivalent), plus a thin service adapter for planning/jobs. Do not force a second QGIS plugin install, duplicate the `comapeo_smp` Processing provider, or inject global `sys.path`. Keep a vendor manifest recording exact commit, license/copyright, files included and patches. Since GISBR is GPL-3.0 and AgenticGIS GPL-2.0-or-later, preserve all licensing notices in the combined fork (MIT SMP component is compatible) and avoid implying this integration is an upstream contribution.

**Alternate acceptable design:** a distinct `agenticgis_smp` Processing provider using the original algorithm under a properly namespaced, audited module, **only if** it works on QGIS 3/4 and is safe under the chosen job scheduler. Do not rely on installed `comapeo_smp` provider or call a private plugin instance found via `qgis.utils.plugins` for the final release.

- Preserve exporter XYZ Web Mercator EPSG:3857 tile geometry, 256px `tileSize` metadata, World/Region/Local source slots (`s/0`,`s/1`,`s/2`, with legacy Local-only `s/0`), raster layer rendering, `smp://maps.v1/...` local URIs, and fixed-source non-overlap rules. Do not replace the generator with hand-built image downloads or `XYZ_SMP.md`'s older hardcoded-Javari shell script.
- Use actual QGIS visible/renderable layer order and custom layer order, symbols, labels and project styles. **Critical renderer adaptation:** the upstream implementation calls `_visible_layers_in_render_order(QgsProject.instance())`, so a tool-level warning or JSON layer filter alone cannot exclude restricted layers. Add an explicit ordered, approved `render_layers` argument or an equivalent QGIS-safe immutable render snapshot and pass it through **every** rendering path. Fail closed if that allowlist cannot be enforced; do not temporarily hide prohibited layers as a substitute. Preview map at representative zoom levels to catch blank world tiles, clipping/label artifacts, wrong CRS and online basemaps without real offline permission. A raster SMP is a frozen image map, not editable vector data.
- **Thread correctness is a hard gate.** QGIS map rendering and project mutation have strict thread ownership constraints; the generator currently calls `QgsMapRendererCustomPainterJob` under a lock from its own tile worker pool. Build a live runtime spike to establish which calls may safely run off the GUI thread on QGIS 3 and 4. Use QGIS-safe task scheduling/cooperative GUI work and queue progress; never simply call a huge synchronous render via `MainThreadExecutor.run_sync` and freeze QGIS, nor move arbitrary `QgsProject` objects across threads unchecked. Document the chosen architecture and tested cancellation path.
- Never silently mutate the user's active map, visibility, zoom, style or layer order to make an SMP. If temporarily changing any state is unavoidable for preview, restore in `finally`; prefer an approved render snapshot. Check project changes between inspection, estimation, export start **and during rendering** (including in-memory feature edits) and cancel/replan rather than mixing tiles from different project states.
- Prefer offline/cached inputs; respect source permission and attribution, especially for remote commercial raster services and Indigenous restricted data. The tool may export only layers clearly permitted by the user's authorization and project policy. No automatic export of detailed villages, isolated-peoples records or sources flagged restricted by the earlier Indigenous integration. A general-purpose PyQGIS tool cannot be assumed to enforce a total data-loss-prevention boundary; document this limitation and implement enforcement at this new export tool's own entry points.
- Use safe output staging: render into a dedicated temp/cache directory, create `.smp.partial`, run validations, atomically replace the approved final destination on the same filesystem if possible, and only then announce success. Never delete unrelated user files. On cancel/error, keep valid cache for optional resume but remove partial archive; cache must be keyed to **map content**, style, extent, zoom, format, quality, relevant source mtimes, and renderer version; stale cache tiles must not leak into a new SMP. **Do not assume the existing `_project_cache_fingerprint` catches unsaved edits to in-memory/remote layer content:** explicitly test, supplement it, or disable resume for content that cannot be reliably fingerprinted.
- Archive creation should normally use standards-compliant ZIP entries and honor ZIP64 as needed; if the pinned generator's optional dedup mode uses central-directory aliases or ZIP32 size limits, choose a compatible default and explain limits. **Do not enable nonstandard dedup by default**. Add an explicit filesize/entry-count feasibility check before rendering, and test both ZIP32 and larger-package handling when feasible.

## 8. SMP format and real CoMapeo compatibility

A valid output is a ZIP with root `style.json`, suitable `VERSION` (SMP spec draft 1.0), only internal `smp://maps.v1/` resource URLs, a MapLibre style v8, raster sources with `scheme:"xyz"` and `tileSize:256`, correct WGS84 `bounds` and matching `{z}/{x}/{y}.{png|jpg|webp}` files. Source IDs and folders must agree with `smp:sourceFolders`; source tile ranges must match their declared min/max. **Metadata edge case:** current exporter writes `metadata["smp:bounds"]` as Local bounds even for World+Region+Local, while SMP v1.0 draft recommends union of all source bounds. Test actual CoMapeo consumer behavior before changing this to a global box, document the deliberate choice, and keep initial center/zoom meaningful for field teams. The archive entry order (`VERSION` before style) is recommended rather than mandatory. Basic validator must reject traversal/absolute ZIP paths, duplicate/path-colliding entries, missing/invalid image bytes, missing tiles for promised bounds, malformed JSON, any external resource URL, and unexpected cache artifacts. Handle antimeridian/higher latitude/CRS failures explicitly. Bound validation work to avoid unbounded memory/time on very large ZIP inventories; use streaming and safe entry limits.

**Consumer validation:** test `smp validate <file>` from `digidem/styled-map-package` *when the CLI is available in CI*, plus loading via the CoMapeo map-server and at least one actual CoMapeo Mobile/Desktop import/open test (document version/device). Until a real consumer test passes, release status is **READY WITH LIMITATIONS**, not full READY; a ZIP test alone does not prove compatibility. For very large or ZIP64 archives, specifically verify the target consumer accepts them; do not claim support from spec text alone.

## 9. Security, permissions and privacy

- Use the existing AgenticGIS permission and agent-ask flow, preserving **stable choice IDs** across PT-BR translation. Prior review found literal English comparisons in `confirm_external_access`; never translate values used for control decisions.
- Require explicit approval for exporting, output location, overwrite and provider usage (including online tile licensing). No hidden upload or automatic sharing. Tool-facing JSON returns only necessary metadata; never return or log secrets from data-source URIs or local private path credentials.
- If any visible layers have restricted/unknown export policy, stop and ask for an explicit layer subset or exclude unsafe ones with clear disclosure. Where feasible, prevent restricted layers from entering the renderer even if they are visible; no blanket assertion that all loaded public GIS layers are redistributable.
- Keep a machine-readable manifest (outside the SMP unless it is safe and necessary) documenting user-approved layer IDs/names, data reference dates, provenance, zooms, bounds, renderer commit and local checksum. Sanitize source credentials and sensitive details. Do not attach machine-sensitive exact community locations to the chat transcript or manifests when not authorized.
- Output path must be normalized, within a user-selected writable destination, with canonical path checks to prevent unsafe overwrite/symlink traversal. Resource/path fetching limited to safe allowlisted QGIS providers; reject model-generated arbitrary remote requests.
- Fail on unsafe ZIP paths, oversized archive resource exhaustion, partial downloads, stale plans, missing provider/format support, or permission denial. Preserve existing `br_*`, core agent, MCP and PT-BR behavior.

## 10. Release acceptance criteria

A. User can request an SMP entirely through the chat; the agent inventories the *current map* and recommends practical Region and Local bounds and zoom levels, showing where they came from.

B. All candidates use exact generator tile math and **sample-calibrated** file-size/time intervals when calibrated; a no-sample result is explicitly labeled rough/unknown; unit tests prove correct counts and no false precision.

C. World/Region/Local fixed slots, zoom ordering, region containment, single AOI fallback, QGIS CRS transforms and >85° / antimeridian cases are correctly handled or explicitly rejected with actionable guidance; no unreported auto-adjustments.

D. No long-running export starts without an approved, non-stale immutable plan; size/time/disk/remote source/license/privacy flags are disclosed; output overwrite and location authorization enforced.

E. Export supports progress/status/cancellation, resource cleanup, stale cache avoidance, and safe atomic output; existing chat and QGIS UI remain responsive; no second SMP plugin install is required.

F. A generated raster `.smp` passes internal ZIP/JSON/tile checks; validated with independent SMP tooling and actually imported/opened in CoMapeo or clearly labeled untested. Multi-source `smp:bounds` behavior is explicitly justified by a consumer test.

G. A real QGIS project test checks local vector styling and labels, a remote basemap failure case, and a multi-source export. GISBR and PT-BR integrations remain working and their restricted data policies honored.

H. QGIS 3.22+/Qt5 and QGIS 4/Qt6 compatibility checked where installations exist; both unrun and failed checks appear accurately in the handoff report.

I. License attribution, tests, packaging, user documentation and samples shipped with the one-plugin fork; no upstream AgenticGIS PR and no external service deployment.

J. **READY** means every applicable safety gate and a real CoMapeo consumer test passed. **READY WITH LIMITATIONS** is allowed for untestable target runtimes/consumer or documented noncritical constraints; **NOT READY** for safety violations, corrupt SMP, blocked UI, false estimates, or export without approval.

## 11. Concrete demonstrations for developer report

- **Scenario 1:** A project with local river/road/land-use layers. Agent suggests balanced World-off, Region-on and Local-on; records tile count and sampled estimates; user approves; export works; `smp_validate_file` and independent tooling agree; file opens in CoMapeo.
- **Scenario 2:** Large territory rectangle and selected small focus zone. Show two candidate packages and actual tile count differences as Local max zoom increases; enforce user storage budget and show actual vs predicted sizes/times.
- **Scenario 3:** Project includes external XYZ/WMS tiles or restricted Indigenous geographic information; the agent warns/blocks as required, never silently exports forbidden content.
- **Scenario 4:** Export canceled midway; no final corrupted file, no freeze; resume only matching cache.
- **Scenario 5:** Locale PT-BR and English, QGIS 3 and 4 (where available), API/CLI/MCP tools produce the same state transitions.

**Handoff deliverables:** fork implementation, pinned/vendor license manifest, test suites, compatibility matrix, one `.smp` fixture/example, user docs (including CoMapeo import), execution logs/benchmarks with hardware and sample sizes, exact commands run, limitations and release-ready package. No fabricated runtime test results.
