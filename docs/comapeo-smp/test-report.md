# CoMapeo SMP Export — Test & Benchmark Report

**Branch:** `feat/comapeo-smp`  
**Status Classification (Spec Criterion J):** `READY WITH LIMITATIONS`  
**Reason:** All automated unit, security, planning, headless QGIS rendering/export, cancellation, and Node `styled-map-package/reader` validation checks passed on QGIS 3.34.4 / Qt 5.15.13. Live CoMapeo Mobile/Desktop client import and QGIS 4 / Qt6 runtime testing are `NOT RUN` because neither is installed in this Linux headless environment, and the installed `/home/luandro/.bun/bin/smp` CLI (`styled-map-package@3.0.0`) does not expose a `validate` subcommand (`download`, `view`, `mbtiles` only).

---

## 1. Test Environment & Hardware

| Component | Measured Value |
|---|---|
| OS / Kernel | Linux `7.2.15-76070215-generic` (`QT_QPA_PLATFORM=offscreen`) |
| CPU | `Intel(R) Core(TM) i7-8650U CPU @ 1.90GHz` (8 logical CPUs) |
| Memory | 23 GiB RAM |
| QGIS / Qt / Python | QGIS `3.34.4-Prizren` / Qt `5.15.13` / Python `3.12.3` |
| External SMP Package | `styled-map-package@3.0.0` (`/home/luandro/.bun/bin/smp`), Node.js `v22.22.3` |
| Vendored Renderer | `digidem/qgis-smp-plugin` commit `34715788e94718d036a58f9992d7ef69b9ecf3d5` (`0.9.0`, MIT) |

---

## 2. Real Headless QGIS Benchmark Table (3 Exports)

**Test Project:** `AwanaGIS Amazon Field Map` in `EPSG:4674` (SIRGAS 2000), containing:
1. Styled polygon layer (`territory_poly`)
2. Styled river line layer with PAL text labels (`rivers`)
3. Styled point layer with PAL text labels (`monitoring_sites`)
4. Sensitive polygon layer (`isolated_zone`, `awanagis/sensitivity = "isolated_peoples"` — verified excluded from all manifests and rendered tile pixels)

| Scenario | Format (Q) | Tiles (`W / R / L = Total`) | Rough Likely (B) | Sample Size (`n`) | Sampled Bytes (`low / likely / high`) | Actual Bytes | Sampled Time (s) | Actual Time (s) | `smp_validate_file` + Node `Reader` |
|---|---|---|---|---:|---|---:|---|---:|---|
| 1. Tiny Local-only (`tests/fixtures/smp/sample_local_only.smp`, z10–11) | PNG | `0 / 0 / 2 = 2` | `102,400` | `2` (0 blank) | `17,722 / 24,360 / 32,102` | `22,958` | `0.03 – 0.20` (likely `0.12`) | `0.062` | **PASS** (2 PIL tiles + `Reader`) |
| 2. Region + Local (Reg z6–9, Loc z10–13) | JPG (80) | `0 / 4 / 15 = 19` | `291,840` | `10` (0 blank) | `53,006 / 77,630 / 107,745` | `64,595` | `0.06 – 0.12` (likely `0.08`) | `0.183` | **PASS** (19 PIL tiles + `Reader`) |
| 3. World + Region + Local (W z0–2, Reg z6–9, Loc z10–13) | PNG | `21 / 4 / 15 = 40` | `2,048,000` | `12` (3 blank) | `40,888 / 244,968 / 406,248` | `139,926` | `0.28 – 0.55` (likely `0.38`) | `0.323` | **PASS** (40 PIL tiles + `Reader`) |

### Sample Calibration Takeaways
- Uncalibrated fixed per-tile guesses (`50 KiB` PNG, `15 KiB` JPG) overestimated these styled vector maps by **4.4x–14.6x**.
- Stratified sampling (`sample=True`) placed **100% (3/3)** of actual `.smp` byte sizes inside the `[low, high]` interval and correctly flagged `3/12` blank world ocean tiles in Scenario 3.
- **Mid-export cancellation** (`test_mid_export_cancellation_leaves_no_corrupt_final_file`): cancelled a >20-tile export after 50 ms; job terminated cleanly in state `cancelled`, with `0` final `.smp` files and `0` leftover `.smp.tmp` staging files.

---

## 3. External SMP CLI & Reader Validation Output

### Direct `/home/luandro/.bun/bin/smp validate` Execution
```text
$ /home/luandro/.bun/bin/smp --help
Usage: smp [options] [command]

Options:
  -h, --help      display help for command

Commands:
  download        Download a map style to a styled map package file
  view            Preview a styled map package in a web browser
  mbtiles         Convert a MBTiles file to a styled map package file
  help [command]  display help for command

$ /home/luandro/.bun/bin/smp validate tests/fixtures/smp/sample_local_only.smp
(exit code 1) error: unknown command 'validate'
```

### `styled-map-package/reader` (`styled-map-package@3.0.0`, Node.js `v22.22.3`)
Executed automatically by `smp_validate_file(..., run_external=True)` (`Reader.opened()`, `Reader.getStyle()` with `@maplibre/maplibre-gl-style-spec`, and `Reader.getResource(...)` streaming a sample tile):
- **Fixture 1 (`sample_local_only.smp`):** `{"ok":true,"sources":["mbtiles-source"],"tileCheck":{"contentType":"image/png","contentLength":12111,"bytesRead":12111}}`
- **Export 2 (`region_local.smp`):** `{"ok":true,"sources":["region-detail","local-detail"],"tileCheck":{"contentType":"image/jpeg","contentLength":4880,"bytesRead":4880}}`
- **Export 3 (`world_region_local.smp`):** `{"ok":true,"sources":["world-overview","region-detail","local-detail"],"tileCheck":{"contentType":"image/png","contentLength":7689,"bytesRead":7689}}`

---

## 4. Acceptance Criteria A–J Reconciliation

| Criterion | Status | Evidence & Notes |
|---|---|---|
| **A.** Conversational inventory + Region/Local bounds & zoom recommendations with provenance | `PASS` | `smp_inspect_map` & `smp_suggest_regions` derive WGS84/3857 bounds from selection, layer, canvas, or explicit bounds (`tests/test_smp_planner.py`, `tests/test_smp_security.py`). |
| **B.** Exact generator tile math + sample-calibrated size/time intervals (unknown when unsampled) | `PASS` | `estimate_plan` delegates exact counts to `SMPGenerator._build_export_plan`; `sample=False` reports `calibration="uncalibrated_rough"` and `runtime.calibration="unknown"`; `sample=True` reports stratified measured ranges (`test_exact_xyz_tile_math_matches_generator`, `test_uncalibrated_vs_sampled_estimation`). |
| **C.** Fixed slots, zoom order, containment, CRS transforms, >85° clamping & antimeridian rejection | `PASS` | Verified across `EPSG:4674`, `EPSG:31983`, `EPSG:4326`, clamped `85.0511`, pure polar rejection (`polar_extent_unsupported`), antimeridian rejection (`antimeridian_crossing`), and containment checks (`tests/test_smp_planner.py`). |
| **D.** Immutable non-stale plan approval, disclosures, overwrite & path safety | `PASS` | Server-side `PlanRegistry` (`smp_*` HMAC-salted IDs), project fingerprint staleness rejection, restricted-layer approval gate, `blocked_sensitive` refusal, path traversal/symlink rejection, and `overwrite=False` refusal (`test_approval_staleness_path_traversal_and_overwrite_gates`). |
| **E.** Progress/status/cancel, cleanup, stale cache avoidance, atomic output, single-plugin packaging | `PASS` | `QgsTask` background execution (`_SmpExportTask`), cooperative cancel with `.smp.tmp` cleanup, `cache_safe=False` for in-memory/edited/online layers, atomic `os.replace`, `plugin.unload()` cleanup, and zero duplicate `comapeo_smp` provider (`tests/test_smp_qgis_export.py`, `test_no_duplicate_comapeo_smp_provider`). |
| **F.** Internal ZIP/JSON/PIL validation + independent SMP tooling + CoMapeo open | `PARTIAL / UNTESTED` | Internal ZIP/JSON/PIL validator and `styled-map-package@3.0.0` `Reader` passed on all 3 generated archives. `/home/luandro/.bun/bin/smp validate` does not exist in CLI `3.0.0`, and **CoMapeo Mobile/Desktop app open is `NOT RUN`** (no CoMapeo client available in this environment). |
| **G.** Styled/labeled local vectors, remote failure cleanup, multi-source export, sensitive data & PT-BR intact | `PASS` | Local styled/labeled polygon+river+point exports passed; blocked sensitive layer (`awanagis/sensitivity="isolated_peoples"`) verified absent from manifest and rendered tile PNG pixels; remote render failure cleans `.smp.tmp` (`test_remote_render_failure_cleans_partial_output`); PT-BR tool labels verified (`test_api_cli_mcp_schema_parity_and_i18n_tool_names`). |
| **H.** QGIS 3.22+/Qt5 and QGIS 4/Qt6 compatibility matrix | `PARTIAL` | QGIS `3.34.4-Prizren` / Qt `5.15.13` **PASS**. QGIS 4 / Qt6 **`NOT RUN`** (not installed on host). |
| **I.** Attribution, tests, fixture, docs, no upstream PR | `PASS` | `integrations/smp/VENDOR_ATTRIBUTION.md`, `integrations/smp/vendor/LICENSE`, `tests/fixtures/smp/sample_local_only.smp` (22,958 B), and `docs/comapeo-smp/test-report.md` included on `feat/comapeo-smp`. |
| **J.** Readiness gate (`READY` vs `READY WITH LIMITATIONS` vs `NOT READY`) | `PASS` (`READY WITH LIMITATIONS`) | Marked `READY WITH LIMITATIONS` pending live CoMapeo Mobile/Desktop import test and QGIS 4 / Qt6 runtime verification. |

---

## 5. Exact Test Commands & Results

1. **SMP + Permission test suite (`tests/test_smp_*.py` + `tests/test_permissions.py`):**
   ```bash
   PYTHONPATH=/home/luandro/Dev/digidem/worktrees/awanagis-comapeo-smp QT_QPA_PLATFORM=offscreen \
     /usr/bin/python3 -m unittest tests/test_smp_planner.py tests/test_smp_qgis_export.py tests/test_smp_security.py tests/test_permissions.py -v
   ```
   - Result (after all P1/P2 review fixes): **31 ran (25 SMP + 6 permission tests), 31 PASS, 0 FAIL, 0 SKIP**.
   - Includes regression tests for:
     - Trusted interactive `_ask_user` / `approval_callback` gate (fails closed on MCP/agent self-approval)
     - Main-thread isolated `QgsProject` + cloned-layer snapshot (with unsaved edits preserved & live project mutation mid-render)
     - Atomic no-clobber publication (`os.link` / `O_CREAT|O_EXCL`) + exclusive staging manifest (`NamedTemporaryFile`)
     - Tile-count cap (`250,000`) & dual-volume disk budget enforcement
     - Refusal of unapproved `restricted` / `online` sampling (`allow_restricted_sampling` / `allow_online_sampling`)
     - Failure on `QgsMapRendererCustomPainterJob.errors()`
     - Cancellation during `validating` preventing publication
     - Missing/out-of-range tile coverage detection and `ZipInfo.file_size` bounds before decompression
     - `from __future__ import annotations` / `Optional[...]` Python 3.8/3.9 compatibility

2. **Full worktree test discovery:**
   ```bash
   PYTHONPATH=/home/luandro/Dev/digidem/worktrees/awanagis-comapeo-smp QT_QPA_PLATFORM=offscreen \
     /usr/bin/python3 -m unittest discover -s tests -v
   ```
   - Result: **37 ran — 35 PASS, 0 FAIL, 2 pre-existing `ModuleNotFoundError: No module named 'AgenticGIS'` errors** in `tests/test_i18n.py` and `tests/test_presentation.py::test_generated_chart_titles_preserve_wire_values` because this worktree directory is named `awanagis/` while those two pre-branding tests still import `AgenticGIS.*`.

3. **i18n test suite with `AgenticGIS` package symlink in `/tmp`:**
   ```bash
   TMPD=$(mktemp -d) && ln -s /home/luandro/Dev/digidem/worktrees/awanagis-comapeo-smp/awanagis "$TMPD/AgenticGIS" && \
     PYTHONPATH="$TMPD" QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s "$TMPD/AgenticGIS/tests" -p "test_i18n.py" -v
   ```
   - Result: **8 ran, 8 PASS, 0 FAIL** (`CatalogTests`, `LocaleTests`, `McpTests`, `SessionTests`).

4. **CoMapeo Mobile / Desktop client & QGIS 4 / Qt6:**
   - **NOT RUN** (unavailable in this Linux headless environment).
