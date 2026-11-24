# AwanaGIS

**AwanaGIS** (by **Awana Digital**) is an independent in-QGIS conversational geospatial assistant, derived from [AgenticGIS](https://github.com/ultramenid/AgenticGIS). Type a request in Portuguese or English and an LLM agent carries it out inside the running QGIS session — driving **PyQGIS**, **Processing** (GDAL / GRASS / SAGA / native), **Google Earth Engine**, and **installed plugins**.

**Zero dependencies.** The plugin runs entirely on QGIS's bundled Python standard library — no `pip`, no `conda`, no external font binaries, no Python upgrade. Drop it in, enable it, and connect.

## What it can do

- **Analyse** — field statistics, category breakdowns, missing-value scans, and bounded layer summaries that stay fast on large datasets. Raster band statistics (min/max/mean/std/sum/range) via `analyze_raster`.
- **Visualise** — inline tables, charts (bar / pie / hbar / line / scatter / sankey), and stat cards rendered straight in the chat dock. Style layers by attribute with `set_layer_style` (categorized, graduated, rule-based, single-symbol, heatmap).
- **Process** — run native / GDAL / GRASS / SAGA algorithms (buffer, clip, dissolve, heatmap, …) and add the derived layer to the project. Discover algorithm parameters with `get_algorithm_parameters` before calling `run_processing`.
- **Select** — `select_by_attribute`, `select_by_expression`, `select_within`, `invert_selection`, and `clear_selection` for full feature-selection workflows.
- **Reproject & CRS** — `reproject_layer` and `set_project_crs` without writing PyQGIS.
- **Edit fields** — `field_calculator` adds calculated fields from QGIS expressions (permanent or virtual).
- **Layouts & export** — `create_layout` builds a print layout with map items; `export_layout` exports to PDF or PNG.
- **Remote sensing** — drive Google Earth Engine for satellite imagery, spectral indices, cloud-masked mosaics, and land-cover work (requires the optional `ee_plugin` installed and authenticated separately).
- **Fetch** — pull a public URL or API endpoint with `web_fetch` when a task needs outside reference data (gated behind explicit user permission).

## How it works

Your message enters a **think → call tool → observe** loop. The LLM picks a tool, it runs inside QGIS, the result feeds back — repeating until the task is done. One message can chain many tools without further prompting.

```
QGIS session
 ├─ Chat dock ................. you type here; results stream back
 ├─ Backend (pluggable)
 │    • API key    → Anthropic / OpenAI / Groq / Gemini / DeepSeek / Ollama / …
 │    • Custom URL → any OpenAI- or Anthropic-compatible endpoint
 │    • CLI Agent  → installed local agent CLIs such as Claude Code, Codex, Gemini, OpenCode
 └─ Tools (heavy work runs on a worker thread; project/canvas/UI calls stay on the main thread)
      run_pyqgis                arbitrary PyQGIS — layers, canvas, plugins, console
      run_processing            GDAL / GRASS / SAGA / native algorithms
      gee_*                     Google Earth Engine imagery & indices
      get_project_state         layer list, CRS, extent, field schemas
      set_layer_style           categorized / graduated / rule-based / heatmap symbology
      select_*                  select by attribute, expression, within; invert; clear
      reproject_layer           reproject to a target CRS
      set_project_crs           set the project CRS
      analyze_raster            raster band statistics
      get_algorithm_parameters  discover processing algorithm parameter schemas
      field_calculator          add calculated fields from QGIS expressions
      create_layout             print layout with map items
      export_layout             export layout to PDF / PNG
      web_fetch                 pull a public URL or API response
      ask_user                  ask the user a clarifying question
```

## Connection modes (Settings → Connection)

1. **API key** — a built-in provider (Anthropic, OpenAI, Groq, OpenRouter, Google Gemini, DeepSeek, Mistral, xAI, Ollama) using its key or the matching env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, …).
2. **Custom endpoint** — any OpenAI-compatible or Anthropic-compatible base URL (self-hosted, proxy, or another provider).
3. **CLI Agent** — use an installed local agent CLI as the model connection. AwanaGIS scans for supported CLIs, lets you test the selected agent, runs QGIS tools itself, and never reads or copies CLI-owned OAuth tokens.

### CLI Agent guide

1. Install and log in to the CLI outside QGIS.
2. In AwanaGIS, open **Settings → Connection → CLI Agent**.
3. Click **Scan** or **Rescan** to detect installed CLIs.
4. Select an agent and click **Test binary** to confirm the command runs.
5. Click **Check auth** if that CLI exposes a safe status command.
6. Click **Use**, then **Save**.

Supported CLI catalog: `Claude Code`, `Codex CLI`, `Cursor Agent`, `Gemini CLI`, `Antigravity CLI`, `GitHub Copilot CLI`, `OpenCode`, `Qwen Code`, `Grok`, `Hermes`, `Kimi CLI`, `Devin for Terminal`, `DeepSeek TUI`, `Pi`, `Mistral Vibe CLI`, `Kiro CLI`, `Kilo`, `Qoder CLI`.

Notes:

- AwanaGIS does not read CLI credential files or copy OAuth tokens.
- For Claude Code, auth checks use `claude auth status`; AwanaGIS does not run interactive status commands.
- **Native tool access** — Claude Code, Codex CLI, and OpenCode get AwanaGIS tools registered as native MCP tools (via the local bridge, on while "Expose QGIS tools over MCP" is enabled), so the CLI agent calls `list_layers` / `run_pyqgis` / `run_processing` directly.

## External agent access (MCP)

While AwanaGIS is loaded and **Settings → External agents → Expose QGIS tools over MCP** is enabled, QGIS tools are exposed over a localhost MCP server:

- Listens on `127.0.0.1` using a dynamically allocated ephemeral loopback port by default (`mcp_port = 0`, never colliding with other instances or legacy plugins).
- Every running instance publishes its bound URL to `~/.awanagis/mcp.json` (override with `AWANAGIS_MCP_DISCOVERY`).
- Most CLIs speak the *stdio* MCP transport, so AwanaGIS ships a zero-dependency proxy at `server/mcp_stdio.py`.

One-time setup per CLI — replace `<plugins>` with your QGIS profile's `python/plugins` path:

```bash
# Claude Code — tools appear as mcp__awanagis__*
claude mcp add awanagis -s user -- python3 "<plugins>/awanagis/server/mcp_stdio.py"

# Codex CLI — ~/.codex/config.toml
[mcp_servers.awanagis]
command = "python3"
args = ["<plugins>/awanagis/server/mcp_stdio.py"]

# OpenCode — opencode.json
{
  "mcp": {
    "awanagis": {
      "type": "local",
      "command": ["python3", "<plugins>/awanagis/server/mcp_stdio.py"]
    }
  }
}
```

Notes:

- Localhost only, no authentication: while the toggle is on, any local process can drive the QGIS tools. Turn it off in **Settings → External agents** to disable it.
- QGIS must be running with AwanaGIS enabled — the proxy exits with a clear error when no live bridge answers.

## Isolation & Coexistence with AgenticGIS

AwanaGIS is packaged and namespaced independently so it can coexist side by side with an existing AgenticGIS installation in the same QGIS profile:

- Plugin directory & Python package: `awanagis/`
- `QSettings` group: `AwanaGIS/` (sessions stored in `AwanaGIS/sessions_json`)
- MCP discovery registry: `~/.awanagis/mcp.json` (env override `AWANAGIS_MCP_DISCOVERY`) and dynamic loopback port (`0`)
- Dock object name & title: `AwanaGisDock` / `AwanaGIS`

Fresh installs **never** automatically read, migrate, or delete `AgenticGIS/` settings, API keys, or security approvals. If legacy `AgenticGIS/` preferences or sessions exist on the machine, an **opt-in, read-only** import option is available in **Settings → Appearance → Import from AgenticGIS** (and in `core/migration.py`), which copies only non-secret preferences and chat sessions while leaving `AgenticGIS/` data untouched.

## Requirements

- **QGIS 3.22+** (including QGIS 4 / Qt6) — stdlib only, using scoped `Qgis.*` / `Qt.*` enums with Qt5/Qt6 compatibility helpers (`core/qt_compat.py`).
- **An LLM connection** — API key, custom endpoint, or local CLI agent.
- **Remote sensing (optional)** — Google Earth Engine QGIS plugin (`ee_plugin`) installed and authenticated separately.

## Install

### Option A — from a plugin ZIP

1. Build or obtain an `awanagis-<version>.zip` archive (for local builds, run `/usr/bin/python3 scripts/package_plugin.py`).
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Browse to the ZIP and click **Install Plugin**.
4. Enable **AwanaGIS** in the Plugins dialog.
5. Click the AwanaGIS toolbar icon to open the chat dock, then **Settings** to configure a connection.

### Option B — manual folder install

1. Locate your QGIS profile's `python/plugins` folder:
   - **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
2. Copy or clone this directory there as `awanagis` (the folder must be named exactly `awanagis`).
3. Restart QGIS and enable **AwanaGIS** in **Plugins → Manage and Install Plugins**.

## Localization (EN / PT-BR)

AwanaGIS honors the QGIS interface language override when set and valid, falling back to the system locale and then English. Brazilian Portuguese (`pt_BR`) is included and compiled at `i18n/awanagis_pt_BR.qm`.

Use literal English messages in `QCoreApplication.translate("Context", "Message")` and add each new source module to `i18n/awanagis.pro`. Compile updated `.ts` catalogs with `lrelease`:

```sh
cd i18n
/usr/lib/qt5/bin/lrelease awanagis_pt_BR.ts -qm awanagis_pt_BR.qm
```

## Development & Tests

Run the headless QGIS/Qt test suite from the parent directory of an `awanagis` checkout:

```sh
PYTHONPATH=.. QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -v
```

## Continuous Integration & Local Checks

Pull requests run [`.github/workflows/qgis-ci.yml`](.github/workflows/qgis-ci.yml) with read-only permissions, `persist-credentials: false`, SHA-pinned GitHub Actions, and digest-pinned containers.

### Checks and blocking rules

| Check name | Blocking? | What it verifies |
|---|---|---|
| `Package & Validate Archive` | Blocking | Packages `HEAD` with `TZ=UTC git archive`, runs `tests/test_ci_checks.py`, validates ZIP CRC (`testzip()`), 25 MB upload limit, `LICENSE`, `metadata.txt` (`about`/`tracker`/`repository`/`author`/URLs), `classFactory`, icon, `.qm` headers, path safety, forbidden leaks, and gates artifact upload with `detect-secrets --include-metadata`. |
| `Security Scan (Bandit)` | Blocking on medium/high or errors | Verifies manifest SHA-256 and runs Bandit recursively on the extracted plugin ZIP (`LOW` findings remain visible as informational; credential literals redacted). |
| `Secrets Scan (detect-secrets)` | Blocking on any finding or error | Verifies manifest SHA-256 and runs `detect-secrets scan --all-files` read-only against any reviewed `.secrets.baseline` (`is_secret: false` required). |
| `Code Quality (Compile & Flake8)` | Compile, AST guards, CI linters blocking; plugin Flake8 advisory | Compiles all packaged `.py` files against Python 3.9 syntax, enforces zero unexpected third-party dependencies and Qt 5/6 compatibility (`qgis.PyQt`, no `.exec_()`), reports plugin Flake8 drift without blocking, and runs `py_compile`/`flake8`/`zizmor`/`actionlint` on `ci/`, `tests/test_ci_checks.py`, and `.github/workflows/*.yml`. |
| `QGIS 3 / Qt 5` | Blocking | Representative QGIS 3 (`3.44.16` / Qt `5.15.13`) container: manifest SHA-256 check, `pylupdate5` + `lrelease` QM parity, `unittest discover`, and unattended `pt_BR` desktop ZIP smoke (all packaged module imports, `QIcon`, `QgsMessageLog` Critical/Python-warning guard, unload fallback). |
| `QGIS 4 / Qt 6` | Blocking | Representative QGIS 4 (`4.4.0` / Qt `6.8.2`) container: manifest SHA-256 check, `pylupdate6` + `lrelease` QM parity, `unittest discover`, and unattended `pt_BR` desktop ZIP smoke. |

The runtime matrix tests two representative pinned QGIS Desktop releases (`3.44.16` and `4.4.0`), not every minor version across `3.22`–`4.99`, and runs completely offline (live LLM provider, CLI, and Earth Engine calls are excluded).

### Alignment with QGIS Plugin Repository scanning

The `bandit`, `detect-secrets`, `flake8`, archive validator, and file-analysis checks preview the checks documented in the [QGIS Security Scanning docs](https://plugins.qgis.org/docs/security-scanning) and implemented in [`QGIS-Plugins-Website` `security_scanner.py` and `validator.py`](https://github.com/qgis/QGIS-Plugins-Website/blob/e66c9281bc530256359306febbe1d41a6edea753/qgis-app/plugins/security_scanner.py) (pinned at `e66c9281bc530256359306febbe1d41a6edea753`). Because `plugins.qgis.org` administrators can toggle individual `SecurityRule` entries on the server, CI serves as a repository-aligned preview rather than an authoritative server verdict:

- CI fails on missing scanner binaries, timeouts, or invalid JSON reports (the website treats missing tools gracefully).
- `.flake8` remains `export-ignore` in release archives and is passed explicitly via `--config .flake8` in CI; `plugins.qgis.org` defaults to `--max-line-length=120` when no `.flake8` is packaged.
- Narrowly scoped exceptions use `# nosec Bxxx` with justification (Bandit), `# pragma: allowlist secret` (detect-secrets), or a reviewed `.secrets.baseline` where false positives are explicitly audited (`"is_secret": false`) — never auto-generate or update a baseline inside a PR run.

### Reproducing CI locally

```sh
# 1. Regenerate and validate the release ZIP
TZ=UTC git archive --format=zip --prefix=awanagis/ --output=/tmp/awanagis.zip HEAD
python3 ci/check_plugin.py archive /tmp/awanagis.zip --extract-to /tmp/awanagis-extracted

# 2. Install scanner tools (dev-only) and run scans + unit tests
python3 -m pip install -r ci/requirements.txt
python3 ci/check_plugin.py scan /tmp/awanagis-extracted/awanagis --flake8-config .flake8
AWANAGIS_REQUIRE_REAL_SCANNERS=1 python3 -m unittest tests/test_ci_checks.py -v
```

### Automated Releases

[`.github/workflows/release.yml`](.github/workflows/release.yml) builds and publishes a QGIS Plugin Repository-ready release package without ever rebuilding the tested ZIP:

1. Bump `version=` (and `experimental=False` for stable, or `experimental=True` for prereleases) in `metadata.txt` on `main`.
2. Push an annotated tag matching `vX.Y.Z` (or `vX.Y.Z-rc.N` / `-beta.N` / `-alpha.N`) on a commit reachable from `main` (for example `git tag -a v0.4.7 -m "Release v0.4.7" && git push digidem v0.4.7`). Triggering `Release QGIS Plugin` manually via `workflow_dispatch` runs a non-publishing dry run.
3. The workflow validates tag/metadata parity (`ci/check_plugin.py release-meta`), calls `qgis-ci.yml` once to package and test the commit, verifies the downloaded artifact matches the tested SHA-256 and commit SHA, attaches `awanagis-<version>.zip` (containing the single `awanagis/` root folder), `SHA256SUMS.txt`, `package-manifest.json`, and a GitHub build provenance attestation (`gh attestation verify awanagis-<version>.zip -R digidem/awanaGIS`). Keep a repository tag ruleset on `v*` blocking tag updates and deletions (and a `release` environment approval/branch rule) so a release tag cannot be moved to another commit during publishing.
4. Upload `awanagis-<version>.zip` from the GitHub Release to `plugins.qgis.org` manually (AwanaGIS is published under its own plugins.qgis.org listing).

## Roadmap & Planned Integrations

This branding-only baseline preserves all core QGIS, Processing, PyQGIS, GEE, CLI, MCP, and PT-BR features. Dedicated feature lanes (such as Brazilian/Indigenous public-data discovery `br_*` and CoMapeo offline map `.smp` export `smp_*`) are developed separately and are **not** bundled in this baseline release candidate.

## Attribution & License

- **License:** GNU General Public License v2.0 or later (`GPL-2.0-or-later`), see [`LICENSE`](LICENSE).
- **Upstream attribution:** Derived from [AgenticGIS](https://github.com/ultramenid/AgenticGIS) by Muhammad Alichamdan (`1e4f70b` / `v0.4.6` + PT-BR localization `51c8a79`). See [`NOTICE`](NOTICE) and [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- **Brand & visual identity:** Uses Awana Digital's official color palette, typography roles (`gui/brand.py`, `gui/theme.py`), and resized/compressed official AwanaGIS icon (`resources/icon.png`, `resources/icon.svg`; see [`resources/ASSET_PROVENANCE.md`](resources/ASSET_PROVENANCE.md)).
