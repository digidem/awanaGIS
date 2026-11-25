# AwanaGIS Rebrand Audit (`REBRAND_AUDIT.md`)

**Baseline commit SHA:** `51c8a79` (`fix(i18n): harden permission prompts and translator teardown`)  
**Upstream origin baseline:** `ultramenid/AgenticGIS` `main` at `1e4f70b` (`v0.4.6`) + PT-BR localization (`f0c552a`, `51c8a79`)  
**Target branch:** `feat/awanagis-branding`  
**Product identity:** `AwanaGIS` (package/plugin folder `awanagis`), by **Awana Digital**  
**Initial independent version candidate:** `0.1.0`

---

## 1. Current Feature Inventory (Baseline `51c8a79`)

### Implemented in this branch
- **Plugin lifecycle & UI:** Dockable chat assistant (`gui/chat_dock.py`), Settings dialog (`gui/settings_dialog.py`), session management (`core/session_store.py`, `gui/session_popup.py`), inline message/turn bubbles (`gui/message_bubble.py`, `gui/agent_turn_bubble.py`), permission/clarification card (`gui/ask_user_card.py`), inline charts (`gui/chart_widget.py`), statistics card (`gui/stats_widget.py`), GIF preview (`gui/gif_widget.py`), file download card (`gui/download_card.py`), typing indicator (`gui/typing_indicator.py`).
- **Core QGIS tools (`core/tools.py`, `core/toolkit.py`):**
  - Execution & project state: `run_pyqgis`, `get_project_state`, `list_layers`, `get_layer_fields`, `get_layer_summary`, `analyze_layer`, `list_plugins`, `add_layer`, `remove_layer`, `clear_layers`, `zoom_to_layer`, `save_project`, `save_project_as`, `ask_user`.
  - Processing & spatial ops: `list_processing_algorithms`, `get_algorithm_parameters`, `run_processing`, `select_by_attribute`, `select_by_expression`, `select_within`, `clear_selection`, `invert_selection`, `reproject_layer`, `set_project_crs`, `analyze_raster`, `field_calculator`, `create_layout`, `export_layout`, `set_layer_style`, `create_chart`, `get_layer_statistics`.
  - Google Earth Engine (via optional `ee_plugin`): `gee_status`, `gee_dataset_info`, `gee_add_layer`, `gee_animation`.
  - Network & caching: `web_fetch`, `configure_network_cache`, `warm_cache`, `core/network_cache.py`, `core/tile_preloader.py`.
- **LLM backends (`backends/`):** API key (`anthropic_http.py`, `openai_http.py`, `api_backend.py`, `openai_backend.py`), Custom endpoint, CLI Agent (`cli_backend.py`, `adapters.py`).
- **Local MCP server (`server/`):** HTTP streamable bridge (`server/mcp_server.py`), discovery registry (`server/discovery.py`), stdio proxy (`server/mcp_stdio.py`).
- **Localization (`i18n/`):** Brazilian Portuguese (`pt_BR`) + English fallback, permission-wire safety hardening, and regression tests (`tests/test_i18n.py`, `tests/test_permissions.py`, `tests/test_presentation.py`).

### Not present in this baseline-only branch (planned in separate lanes)
- **GISBR & Indigenous public-data integration (`br_*`, `gisbr:` provider):** `NOT PRESENT` in `51c8a79`.
- **CoMapeo SMP planning/export (`smp_*`, SMP provider/exporter):** `NOT PRESENT` in `51c8a79`.

---

## 2. Canonical Identifier Mapping Table

| Category | Legacy (`AgenticGIS`) | AwanaGIS (`awanagis`) | Notes |
|---|---|---|---|
| Display / product name | `AgenticGIS` | `AwanaGIS` | Exact casing in all UI & metadata |
| Plugin folder & Python package | `AgenticGIS` | `awanagis` | Lowercase ASCII |
| Main plugin class | `AgenticGisPlugin` | `AwanaGisPlugin` | `classFactory(iface)` preserved in `__init__.py` |
| Dock title & objectName | `"AgenticGIS"` / `"AgenticGisDock"` | `"AwanaGIS"` / `"AwanaGisDock"` | Prevents widget collision on co-install |
| QSettings group | `AgenticGIS` | `AwanaGIS` | Isolated namespace; no auto-migration |
| Session storage key | `AgenticGIS/sessions_json` | `AwanaGIS/sessions_json` | Isolated session store |
| Network cache sentinel | `agenticgis/network_cache_dirty` | `awanagis/network_cache_dirty` | Isolated cache dirty sentinel |
| Layer custom property | `agenticgis/analysis` | `awanagis/analysis` | Read-compat checks `awanagis/analysis` or `agenticgis/analysis` |
| MCP server info name | `AgenticGIS` | `AwanaGIS` | `SERVER_INFO["name"]` |
| MCP server client slug | `agenticgis` | `awanagis` | `MCP_SERVER_NAME` in `backends/adapters.py` |
| MCP discovery path | `~/.agenticgis/mcp.json` | `~/.awanagis/mcp.json` | Independent discovery file |
| MCP discovery env var | `AGENTICGIS_MCP_DISCOVERY` | `AWANAGIS_MCP_DISCOVERY` | Independent env override |
| MCP default port | `7317` | `7318` | Distinct loopback ports allow the plugins to coexist |
| MCP tool prefix normalization | `mcp__agenticgis__`, etc. | `mcp__awanagis__`, `awanagis__`, `awanagis.`, `awanagis_`, `awanagis/` | Legacy `mcp__agenticgis__*` kept as fallback |
| Translation catalog prefix | `AgenticGIS_<locale>.ts/.qm` | `awanagis_<locale>.ts/.qm` | Existing PT-BR translations preserved |
| Dev log env vars & filename | `AGENTICGIS_DEV_LOG*` / `agenticgis-dev.log` | `AWANAGIS_DEV_LOG*` / `awanagis-dev.log` | Isolated debug logging |
| Temp dirs & prefixes | `AgenticGIS/`, `agenticgis_*` | `AwanaGIS/`, `awanagis_*` | Isolated runtime temp files |
| PyQGIS exec markers | `__agenticgis__`, `<agenticgis>` | `__awanagis__`, `<awanagis>` | Internal execution markers |
| HTTP User-Agent | `AgenticGIS` | `AwanaGIS` | GEE STAC catalog requests |
| QGIS message log tag | `AgenticGIS` | `AwanaGIS` | Plugin log panel tab |

### Invariant Machine-Facing Identifiers (NEVER RENAME)
- **Tool IDs (`core/tools.py`):** `run_pyqgis`, `get_project_state`, `list_layers`, `get_layer_fields`, `get_layer_summary`, `analyze_layer`, `list_plugins`, `list_processing_algorithms`, `run_processing`, `add_layer`, `zoom_to_layer`, `gee_status`, `gee_dataset_info`, `gee_add_layer`, `gee_animation`, `remove_layer`, `clear_layers`, `save_project`, `create_chart`, `get_layer_statistics`, `configure_network_cache`, `warm_cache`, `web_fetch`, `ask_user`, `set_layer_style`, `select_by_attribute`, `select_by_expression`, `select_within`, `clear_selection`, `invert_selection`, `reproject_layer`, `set_project_crs`, `analyze_raster`, `get_algorithm_parameters`, `field_calculator`, `save_project_as`, `create_layout`, `export_layout`.
- **Permission wire choice values (`core/toolkit.py`):** `"Allow once"`, `"Always allow"`, `"Deny"`, `"Allow all GEE tools for this session"`, `"Cancel"`.
- **MCP JSON-RPC methods & response schemas (`server/mcp_server.py`):** `initialize`, `ping`, `tools/list`, `tools/call`, `notifications/initialized`, `notifications/cancelled`.

---

## 3. Licensing Obligations

- **Upstream AgenticGIS:** Licensed under **GPL-2.0-or-later** (`Copyright (C) 2026 Muhammad Alichamdan <malichamdan@gmail.com>`). Original `LICENSE` copyright and license text are preserved verbatim.
- **AwanaGIS branding-only distribution:** Continues under **GPL-2.0-or-later**, with derivative notices in `NOTICE`, `THIRD_PARTY_LICENSES.md`, `metadata.txt`, and `README.md`.
- **Future integrations (not in this branch):** GISBR is GPL-3.0 and CoMapeo SMP is MIT; when GISBR is integrated, the combined distributable must satisfy GPL-3.0 (compatible with AgenticGIS's "or later" grant) and retain all upstream notices.
- **Fonts & Brand Assets:** No external font binaries are bundled (native OS/QGIS font fallbacks apply). The AwanaGIS icon (`resources/icon.png`, `resources/icon.svg`) is derived from the official Awana Digital mark supplied by the maintainer, resized to `128x128` and compressed (see `resources/ASSET_PROVENANCE.md`).

---

## 4. Exhaustive Baseline Search (`51c8a79`)

Baseline `rg -n -i "agenticgis"` across non-`docs/` files at `51c8a79` produced **230 matches** across 21 files, classified as:
1. **Visible branding / UI / metadata / docs:** `metadata.txt`, `README.md`, `plugin.py`, `gui/chat_dock.py`, `gui/settings_dialog.py`, `gui/typing_indicator.py`, `i18n/AgenticGIS_pt_BR.ts`, `core/toolkit.py` (`Allow AgenticGIS to {reason}?`), `backends/openai_backend.py` (system prompt identity), `backends/cli_backend.py` (CLI system prompt).
2. **Persisted / runtime identity:** `config.py` (`_GROUP`, `mcp_port=7317`), `core/session_store.py` (`SETTINGS_KEY`), `core/network_cache.py` (`_DIRTY_KEY`), `core/toolkit.py` (`agenticgis/analysis`, manifest/snapshot/fetch temp names, exec markers, User-Agent), `core/dev_logging.py` (`AGENTICGIS_DEV_LOG*`).
3. **MCP protocol / CLI client namespace:** `server/mcp_server.py` (`SERVER_INFO`), `server/discovery.py` (`~/.agenticgis/mcp.json`, `AGENTICGIS_MCP_DISCOVERY`), `server/mcp_stdio.py`, `backends/adapters.py` (`MCP_SERVER_NAME`, `normalize_tool_name`, runtime dir, `agenticgis-mcp.json`), `gui/formatting.py` (`humanize_tool_name`).
4. **Code identifiers & logs:** `__init__.py`, `plugin.py`, `core/executor.py`, `core/processing_tasks.py`, `core/tile_preloader.py`, `gui/theme.py`, `i18n/__init__.py`, `i18n/AgenticGIS.pro`.
5. **Tests:** `tests/test_i18n.py`, `tests/test_permissions.py`, `tests/test_presentation.py`.

All categories (1)–(5) are updated in this branding milestone while retaining explicit attribution in `LICENSE`, `NOTICE`, `THIRD_PARTY_LICENSES.md`, `metadata.txt`, and `README.md`, and deliberate read-compatibility fallbacks where safe (`awanagis/analysis` + `agenticgis/analysis` read check; `mcp__awanagis__*` + `mcp__agenticgis__*` tool-name normalization; opt-in non-destructive `core/migration.py`).
