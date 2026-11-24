# AwanaGIS Brazil + Curated Indigenous Data — Verification & Test Report

**Date:** 2026-11-23 / 2026-11-24 UTC  
**Branch:** `feat/gisbr-indigenous-data`  
**Environment:** Linux, `/usr/bin/python3` (Python 3.12), PyQt5, QGIS `3.34.4-Prizren` (`QT_QPA_PLATFORM=offscreen`)  
**GISBR Pinned Upstream SHA:** `06d84dfab9942e4e840637bb8d8f96af173330ad` (GPL-3.0; provider ID `awanagis_brazil`)

## 1. Automated Test Results

### Brazil Integration Suites (`test_brazil_catalog`, `test_brazil_safety`, `test_brazil_qgis`)
Command:
```bash
PYTHONPATH=/home/luandro/Dev/digidem/worktrees/awanagis-gisbr-data QT_QPA_PLATFORM=offscreen \
  /usr/bin/python3 -m unittest tests.test_brazil_catalog tests.test_brazil_safety tests.test_brazil_qgis tests.test_permissions -v
```
Result: **25 / 25 PASS** (19 Brazil tests + 6 Permission tests)
- `tests.test_brazil_catalog`: 5 / 5 PASS (merged 76 GISBR + 14 curated Indigenous = 90 unique sources; offline PT-BR/EN synonym search; `publisher_type` / UF / sensitivity filtering; read-only >32 KB WFS `GetCapabilities` probe; 7-digit IBGE validation & multi-UF disambiguation; named-TI resolution + TI vs DSEI concept mismatch; 5-tool schema & `humanize_tool_name` parity).
- `tests.test_brazil_safety`: 5 / 5 PASS (synthetic non-real coordinates; `mapi_isolated_peoples`, `ibge_indigenous_localities_2022`, `funai_indigenous_villages`, `funai_ti_studies`, `isa_territories`, `raisg_indigenous_territories`, `mapbiomas_alerta` blocked across probe, plan, and forged-plan execution; URL allowlist & no TLS bypass; path traversal & zip-slip; CQL literal/identifier sanitization; credential & synthetic coordinate redaction; `QgisToolkit.confirm_external_access` Deny & localized-label wire-value protection; pre-cancellation).
- `tests.test_brazil_qgis`: 9 / 9 PASS (vendor relative imports & zero `sys.path` mutation; `awanagis_brazil` 57-algorithm registration & coexistence with external `gisbr` provider; `AgenticGisPlugin` `initGui`/`unload` lifecycle; `project_layer` polygon validation; fixture-driven headless QGIS loading & `exact_polygon_clip` of `funai_ti_boundaries`, `funai_dsei_areas`, `inpe_prodes`, `inpe_deter`; `awanagis/*` provenance properties & export policy; chaining `layer_ids` into `get_layer_fields`, `select_by_expression`, and `run_processing` (`native:intersection`); reuse/skip vs safe replacement; partial failure; WFS HTTP-200 error & truncation detection; MCP `tools/list` & `tools/call` parity; write-time no-overwrite checks on GeoPackage & sidecar; refusal to persist uncut data on clip failure; atomic raster staging/cancellation/no-overwrite; actual loaded year provenance for MapBiomas & INPE PRODES; `geobr_terras_indigenas` named-TI attribute filtering; off-GUI-thread `QgsTask`/worker dispatch with main-thread-only `QgsProject` registration).

### Existing Worktree Regression Suites
- `tests.test_permissions`: **6 / 6 PASS** (`PYTHONPATH=/home/luandro/Dev/digidem/worktrees/awanagis-gisbr-data QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest tests.test_permissions -v`)
- `tests.test_i18n`: **8 / 8 PASS** when `AgenticGIS` module alias is mapped to `awanagis` (verifying updated `i18n/AgenticGIS_pt_BR.ts` + compiled `i18n/AgenticGIS_pt_BR.qm` with 352 finished translations and `AgenticGisPlugin` lifecycle).
- `tests.test_presentation`: **4 / 5 PASS** directly; `test_generated_chart_titles_preserve_wire_values` errors on `ModuleNotFoundError: No module named 'AgenticGIS'` when run directly in the `awanagis` worktree (outside Lane B scope).
- `unittest discover -s tests -v`: **25 / 27 PASS, 2 ERROR** (`test_i18n` and `test_generated_chart_titles_preserve_wire_values` fail to import `AgenticGIS` because the worktree directory is named `awanagis`, handled by the branding track).
- **QGIS 4 / Qt6:** **NOT RUN** (not installed in this environment).

## 2. Live Endpoint Probes & Headless QGIS Live Loads

Read-only probes and bounded headless QGIS loads executed on 2026-11-23 / 2026-11-24 UTC:

| Check | Endpoint / Scope | Outcome | Details |
|---|---|---|---|
| `inpe_prodes` (live probe + QGIS load) | `https://terrabrasilis.dpi.inpe.br/geoserver/ows` (`prodes-legal-amz:yearly_deforestation`), PA synthetic AOI `POLYGON((-52.5 -7.5, -51.5 -7.5, -51.5 -6.5, -52.5 -6.5, -52.5 -7.5))` | **PASS** | `GetCapabilities` HTTP 200 (172,063 bytes); live QGIS `br_execute_load` loaded **3,988** clipped features into GeoPackage (`exact_polygon_clip`, geometry repaired via `native:fixgeometries` fallback). |
| `inpe_deter` (live probe + QGIS load) | `https://terrabrasilis.dpi.inpe.br/geoserver/ows` (`deter-amz:deter_amz`), same bounded PA AOI | **PASS** | `GetCapabilities` HTTP 200; live QGIS `br_execute_load` loaded **5,279** clipped features into GeoPackage (`exact_polygon_clip`). (Note: unbounded `count=1` GetFeature without bbox timed out at 15s; bounded bbox queries succeeded.) |
| `geobr_municipio` + `geobr_terras_indigenas` (live QGIS load) | Vendored GISBR `awanagis_brazil:read_municipality` + `read_indigenous_land`, São Félix do Xingu (`1507300`, PA) | **PASS** | Live QGIS `br_execute_load` loaded `geobr_municipio` (1 feature) and `geobr_terras_indigenas` (6 clipped TI polygons inside São Félix do Xingu) into GeoPackage with provenance tags. |
| IBGE Localidades API | `https://servicodados.ibge.gov.br/api/v1/localidades/municipios/1507300` | **PASS** | HTTP 200 (`São Félix do Xingu`). |
| `funai_ti_boundaries` | `https://geoserver.funai.gov.br/geoserver/Funai/ows` | **UNAVAILABLE** | `URLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate`. Strict TLS kept enabled (no bypass). Verified via fixture in `test_brazil_qgis.py`; dated mirror `geobr_terras_indigenas` verified live. |
| `funai_dsei_areas` | `https://geoserver.funai.gov.br/geoserver/Funai/ows` | **UNAVAILABLE** | Same FUNAI GeoServer missing intermediate CA TLS error; DSEI `typename` remains `pending_probe`. Verified via fixture in `test_brazil_qgis.py`. |

## 3. Indigenous & Territorial Overlay Status Matrix

| Source ID | Publisher / Origin Class | Live / Fixture / Policy State | Status Label | Notes |
|---|---|---|---|---|
| `funai_ti_boundaries` | FUNAI / CGGEO (`official_direct`) | Fixture PASS; live FUNAI WFS TLS failed | **PASS_WITH_LIMITATIONS** | Missing intermediate CA on `geoserver.funai.gov.br`; TLS bypass prohibited. `geobr_terras_indigenas` offered transparently as dated mirror. |
| `funai_dsei_areas` | FUNAI / SESAI (`official_direct`) | Fixture PASS; live FUNAI WFS TLS failed | **PASS_WITH_LIMITATIONS** | Explicit concept distinction enforced against TI boundaries (`concept_mismatch` on TI resolver). |
| `inpe_prodes` | INPE / TerraBrasilis (`official_direct`) | Live WFS + QGIS clip PASS + Fixture PASS | **PASS** | Verified live (`3,988` features in PA AOI) and via fixture. Annual suppression methodology. |
| `inpe_deter` | INPE / TerraBrasilis (`official_direct`) | Live WFS + QGIS clip PASS + Fixture PASS | **PASS** | Verified live (`5,279` features in PA AOI) and via fixture. Requires bounded bbox; indicative alerts only. |
| `geobr_terras_indigenas` | FUNAI via IPEA/geobr (`official_mirror`) | Live QGIS load PASS | **PASS** | Loaded 6 TI polygons for São Félix do Xingu (`1507300`). |
| `ibge_indigenous_localities_2022` | IBGE (`official_direct`) | `discovery_only` (auto-load blocked) | **BLOCKED (policy)** | Revised 2022 census files noted; exact locality points blocked across probe/plan/execute. |
| `funai_indigenous_villages` | FUNAI / CGGEO (`official_direct`) | `discovery_only` (auto-load blocked) | **BLOCKED (policy)** | Exact village point locations blocked from auto-load in v1. |
| `funai_ti_studies` | FUNAI / CGGEO (`official_direct`) | `discovery_only` (auto-load blocked) | **BLOCKED (policy)** | Study points blocked so they are not conflated with delimited polygons. |
| `isa_territories` | ISA (`non_government`) | `portal_only` (link-out only) | **BLOCKED (portal_only)** | No bulk scraping/API verified. |
| `mapi_isolated_peoples` | COIAB + OPI / OPAN (`non_government`) | `blocked_sensitive` (metadata only) | **BLOCKED (policy)** | Hard-blocked across search/probe/plan/execute/export; zero exact coords ingested or exposed. |
| `raisg_indigenous_territories` | RAISG (`non_government`) | `portal_only` (terms review required) | **BLOCKED (portal_only)** | WMS display-only disclaimer; per-theme citations required. |
| `mapbiomas_alerta` | MapBiomas Alerta (`non_government`) | `portal_only` (registered API) | **BLOCKED (portal_only)** | Account-gated API; distinct from GISBR `mapbiomas_cobertura` COG. |

## 4. Release Readiness Assessment

- **Status:** **READY WITH LIMITATIONS**
- **Verified:** One-plugin vendored GISBR runtime (`awanagis_brazil`, 57 algorithms, 76 GISBR + 14 curated Indigenous sources), 5 `br_*` tools across API/CLI/MCP, hard-enforced Indigenous safety & permission gates, named-TI & IBGE area resolution, live INPE PRODES/DETER + live GISBR `geobr` QGIS loading, and fixture-driven FUNAI TI/DSEI validation in QGIS 3.34.4/Qt5.
- **Limitations:**
  1. Direct FUNAI GeoServer (`geoserver.funai.gov.br`) failed strict TLS certificate chain verification from this environment (`unable to get local issuer certificate`); therefore `funai_ti_boundaries` and `funai_dsei_areas` live endpoints remain unverified without an official intermediate CA bundle, and `funai_dsei_areas` `typename` remains `pending_probe`.
  2. QGIS 4 / Qt6 runtime was not tested (unavailable in environment).
  3. Two pre-existing tests (`tests/test_i18n.py`, `tests/test_presentation.py`) hardcode `AgenticGIS` package imports while this worktree directory is named `awanagis` (handled by the branding track).
