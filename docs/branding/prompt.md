> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# prompt.md — Developer-agent kickoff: AwanaGIS brand-aligned independent QGIS plugin

You are the engineering agent responsible for establishing **AwanaGIS**, an **independent QGIS plugin** built on the AgenticGIS codebase. The owner is creating a separate product and repository, **not** preparing a pull request to `ultramenid/AgenticGIS`.

Read [`plan.md`](./plan.md) in full, inspect the **actual current fork/worktree**, and execute the rebrand across code, runtime identity, documentation, tests and installable packaging. The rebrand must preserve all currently implemented functionality.

## Product name and project setup

**AwanaGIS is the confirmed, final development name.** Do not use the discarded working name or ask for another naming decision. Use the exact case `AwanaGIS`; canonical package/server slug is `awanagis`. This product belongs under **Awana Digital's visual identity**. Naming confirmation does not imply trademark/domain clearance or permission to publish a public repository or release; follow the rollout gate in PLAN.

Canonical AwanaGIS identity:

```yaml
product_name: AwanaGIS
plugin_display_name: AwanaGIS
qgis_plugin_folder: awanagis
python_package_name: awanagis
repository_slug: awanagis
settings_group: AwanaGIS
sessions_key: AwanaGIS/sessions_json
mcp_server_name: awanagis
mcp_discovery_path: ~/.awanagis/mcp.json
mcp_discovery_env: AWANAGIS_MCP_DISCOVERY
mcp_port_default: 0          # dynamically allocated, loopback only
translation_catalog_prefix: awanagis
initial_version_candidate: 0.1.0
release_destination: UNCONFIRMED
parent_brand: Awana Digital
brand_guidelines: https://app.notion.com/p/3341b08162d580a38611ce745e372f45
brand_snapshot: brand-guide.md
brand_tokens: brand-tokens.json
```

The names above are final for this development task. Derive all technical identifiers from an identity manifest and ensure there are no stale references to any previously proposed brand. Do not rebrand legal attribution or historical references to AgenticGIS.

## Product vision

AwanaGIS is an AI-powered geospatial assistant **inside QGIS**. A user can converse in Portuguese or English to inspect and manipulate layers, discover credible geospatial sources, create territorial analyses, and prepare offline maps for CoMapeo. The brand must remain broad enough for use beyond Brazil, beyond any single data provider, and beyond Indigenous-territory projects, while retaining careful community data governance.

Existing approved development tracks have their own developer handoffs:

- **PT-BR localization:** already completed in the current fork; preserve it and update branding contexts only. No translation spec is included here.
- **GISBR + Indigenous public data**: `prompt.md`, `spec.md`, `plan.md`, `indigenous-sources.md` from the GISBR task; no upstream AgenticGIS PR.
- **CoMapeo SMP generation**: `prompt.md`, `spec.md`, `plan.md` from the SMP task; no upstream AgenticGIS PR.

**First check which tracks are actually implemented.** Do not mistake completed specifications for existing source code. If they are absent, rebrand foundation first and leave them to their respective implementation milestones; if they are present, adapt and preserve them. This prompt is about **rebranding**, not silently claiming the other integrations are finished. **When handing those older specifications to another agent, first update their product name, package/namespace assumptions and publishing instructions to AwanaGIS.** The earlier PT-BR task contemplated an upstream pull request, but that route is explicitly superseded for our independent product.

## Execution rules

1. **Audit first.** In the checked-out working tree, inspect `git status`, remotes, `__init__.py`, `plugin.py`, `config.py`, `core/session_store.py`, `server/discovery.py`, `server/mcp_stdio.py`, `server/mcp_server.py`, `backends/cli_backend.py`, `metadata.txt`, GUI, tests, docs, ignore rules and packaging. Keep uncommitted work safe. Create a rebrand branch. Document the initial SHA and integration state.
2. **Preserve history, authorship and licenses.** The original AgenticGIS is **GPL-2.0-or-later**; GISBR is **GPL-3.0**; the CoMapeo SMP plugin is **MIT**. Retain original copyright notices, attribution and provenance; a combined distributable with GISBR must meet GPLv3 obligations. Change copyright/author metadata to accurately identify new maintainers without erasing upstream authorship. Don't rewrite repo history or force-push.
3. **Rebrand comprehensively.** Adopt the new `awanagis` Python plugin folder, Qt menu/toolbar/dock labels, QGIS plugin manager metadata, splash/help/onboarding and project docs, CLI/MCP examples, log tags, icon/assets, release/CI names. Continue to expose a working `classFactory(iface)` and valid ZIP layout. Read the **Awana Digital brand guidelines** and the included `brand-guide.md` and `brand-tokens.json` before any visual work. Create an AwanaGIS-specific product icon (draft until reviewed), and apply the actual brand typography and colors to all first-party UI without repainting the user's GIS layers. Do not re-label an existing organization's logo as a new approved AwanaGIS logo.
4. **Isolate persistence.** Use `AwanaGIS/` QSettings group and `AwanaGIS/sessions_json`. A default install must not read, overwrite, migrate or delete old `AgenticGIS/` user data. If an optional import is implemented, require opt-in, maintain rollback and keep original data unchanged; **never silently transfer API keys, authorization flags or security approvals**.
5. **Isolate the bridge.** Use `awanagis` MCP name, `~/.awanagis/mcp.json` discovery, `AWANAGIS_MCP_DISCOVERY` and dynamically allocated localhost port by default. Fix startup/client instructions and the CLI model-facing tool names so external agents find the new namespace. Verify it does not conflict when old and new plugins are installed together.
6. **Keep protocols stable.** Do not rename tool names like `run_processing`, `run_pyqgis`, `br_*` or `smp_*` just to satisfy an all-text search. Do not change MCP method names, payload JSON fields, QGIS algorithm IDs in-use, session schemas, permission choice IDs or model-visible tool capabilities unless absolutely necessary and tested. Renaming bundled Processing providers to avoid collision **is** a targeted technical change requiring exact import/algorithm-reference updates and migration tests.
7. **Implement brand design tokens and accessibility.** Use documented **Tomorrow** for display titles, **Public Sans** for general text, **Space Grotesk** for captions/small labels, with safe QGIS font fallback and licensing review. Centralize the palette: Dark Burgundy `#6B0030`, Burgundy `#8D003E`, Earth `#932D00`, and the secondary colors listed in `brand-tokens.json`. Prefer Cream `#FDF7EF` for light-mode surfaces and Dark Burgundy/Burgundy for high-contrast emphasis. The Notion guideline is authoritative for exact brand values; these specific UI semantic roles are recommendations. Test readability, focus, light/dark QGIS, PT-BR accents, and warning states. **Do not globally modify map symbology or color maps to fit brand UI.**
8. **Preserve translations.** Keep English and PT-BR catalogs, build scripts and QGIS locale behavior; update class contexts and metadata translations for the new brand. Permission-choice display text can be translated, but canonical grant/deny values must remain unchanged.
9. **Track important files.** The upstream `.gitignore` excludes `docs/`, `tests/` and `*.md` other than README. Change it deliberately to track needed documents and tests; verify `.gitattributes` and archive content separately.
10. **Test real QGIS.** Test load/unload, both QGIS plugins side by side, toolbar/dock and branding, settings and session isolation, dynamic MCP discovery plus a safe `tools/call`, CLI backend, English/PT-BR, all already-implemented GISBR/SMP paths, ZIP install and GPL/MIT attribution. Validate QGIS 3/Qt5 and QGIS 4/Qt6 where available and mark missing runtime checks as `UNTESTED`.
11. **Deliver, don't fabricate.** Execute PLAN phases, create logical commits, run tests, produce an installable release candidate and summarize actual results. Never mark integration tests as passing unless you ran them. Do not publish or deploy to an unapproved destination or submit a PR to upstream AgenticGIS.

## Visual design requirements — authoritative reference

Read these four documents, in this order, before implementation:

1. **[Awana Digital Branding Guidelines](https://app.notion.com/p/3341b08162d580a38611ce745e372f45)** in Notion (if connector access is available); it contains actual logo variants, examples and font attachments.
2. **[`brand-guide.md`](./brand-guide.md)** — self-contained, evidenced color/font/logo facts, contrast guidance and practical QGIS UI mapping.
3. **[`brand-tokens.json`](./brand-tokens.json)** — exact palette/semantic proposals suitable for a theme module.
4. **[`plan.md`](./plan.md)** — implement/test gates, especially Phase 4.

Official colors: **AD Dark Burgundy `#6B0030`**, **AD Burgundy `#8D003E`**, **AD Earth `#932D00`**; secondary **Pink `#FF60C0`**, **Orange `#FF8D00`**, **Pollen `#FFE460`**, **Fungi `#00D05F`**, **Forest `#148658`**, **Cream `#FDF7EF`**, **River `#0063A1`**, **Sky `#0094FF`**, **Rain `#B4DDF9`**. No improvised official colors.

Fonts: **Tomorrow** = headings/display; **Public Sans** = body and chat; **Space Grotesk** = captions and compact metadata. Use real typefaces when available and legally distributable; otherwise retain readable QGIS-native fallbacks and document missing fonts. Do not store or commit unlicensed font files.

The brand page includes parent-company logos in rectangle, circle, square and wordmark formats, in Burgundy/Earth/Black/White variants. **These are Awana Digital brand assets, not automatically approved AwanaGIS artwork.** Create an AwanaGIS icon/wordmark *proposal* in the same visual family, trace source/derivation, mark as draft pending Awana Digital design-team signoff, and test it at small QGIS icon sizes. Preserve original logos unaltered.

Styling must cover toolbar, dock, tabs, settings, chat message bubbles, prompts, permission dialogs, source catalogs, SMP planning cards, onboarding and error/empty/loading states wherever those screens exist. Use semantic color roles and WCAG-AA contrast: normal text ≥4.5:1, key controls/graphics ≥3:1; distinguish success/warnings with icons/text too. Verify light/dark themes and keyboard navigation. **Brand should not override map symbology, geospatial layer colors or exported SMP content**.

A sensible public description **after the underlying features exist**:

> AwanaGIS is an AI-assisted mapping workspace for QGIS from Awana Digital. Explore and process map layers, discover trustworthy spatial datasets and prepare offline maps using natural language.

Use a narrower description in a baseline-only build and give upstream developers accurate credit in About/NOTICE.

## Important repository specifics to verify

At the last reviewed AgenticGIS source baseline, the hard-coded identity includes:

- `plugin.py`: action/menu label `AgenticGIS`, `AgenticGisPlugin` class.
- `config.py`: `_GROUP = "AgenticGIS"`.
- `core/session_store.py`: `SETTINGS_KEY = "AgenticGIS/sessions_json"`.
- `server/discovery.py`: `~/.agenticgis/mcp.json` and `AGENTICGIS_MCP_DISCOVERY`.
- `server/mcp_server.py`: `SERVER_INFO = {"name": "AgenticGIS", ...}`.
- `config.py`: `mcp_port` default `7317`.
- `server/mcp_stdio.py`, `backends/cli_backend.py`, and `README.md`: old MCP client-registration examples and prompt references (`mcp__agenticgis__*`).
- `metadata.txt`: `name=AgenticGIS`, upstream author's metadata/license and upstream support URLs.
- `.gitignore`: ignores `docs/`, `tests/`, and almost all `*.md`.

This is an **orientation checklist, not an exhaustive substitution script**. Search every tracked file and classify remaining brand references; preserve historical copyright and carefully handle any machine-facing keys.

## Deliverables and reporting

Deliver the reviewed branch/source tree, `REBRAND_AUDIT.md`, an identity manifest, a reusable semantic theme module based on the supplied brand tokens, AwanaGIS icon/wordmark proposal plus asset provenance, screenshots/light-dark/pt-BR checks, README/metadata changes, attribution/licenses, test additions, final ZIP, and a concise report with actual Git SHAs and command outputs. Report `PASS / FAIL / UNTESTED` for the gates in `plan.md`. Clearly distinguish work completed **now** from later GISBR/SMP/i18n milestones. End with a recommendation of `READY`, `READY WITH LIMITATIONS`, or `NOT READY` and its exact reasons.

**Definition of done:** AwanaGIS installs and operates as a separately named plugin; old AgenticGIS can coexist without settings, sessions, MCP, or package collisions; all already-implemented functions still work; user data and upstream authorship are preserved. The plugin is ready for its own repository/release process once design approval and the repository/release destination are confirmed.
