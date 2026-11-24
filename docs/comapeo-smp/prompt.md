> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# Developer Agent Kickoff — CoMapeo SMP generation inside our AgenticGIS fork

You are the engineering agent responsible for implementing **conversational, budget-aware CoMapeo SMP exports** in **the AwanaGIS fork (derived from AgenticGIS)**. This is the **third integration workstream**, complementing the earlier PT-BR translation and GISBR/Indigenous public-data integrations. **Do not open a pull request against `ultramenid/AgenticGIS`.**

## Read before editing

1. [`spec.md`](./spec.md) — **binding product/technical requirements and acceptance criteria**.
2. [`plan.md`](./plan.md) — phase-by-phase implementation and verification gates; execute it.
3. The real fork HEAD, `core/tools.py`, `core/toolkit.py`, `plugin.py`, QGIS task/processing/executor code, settings/i18n and any existing GISBR/Indigenous modules; preserve prior changes.
4. <https://github.com/digidem/qgis-smp-plugin> — particularly `README.md`, `AGENTS.md`, `comapeo_smp_generator.py`, `comapeo_smp_algorithm.py`, `test/test_generator.py` and `scripts/test-qgis-headless.py`.
5. <https://github.com/digidem/styled-map-package/blob/main/spec/1.0/README.md> and <https://github.com/digidem/comapeo-map-server> — format and actual map-consumer behavior.

## What we want

A user should be able to ask, in PT-BR or English:

> **“Tenho esse mapa aberto no QGIS. Faça um mapa offline SMP para usar no CoMapeo. Quero toda a região do território em zoom médio, mas o máximo de detalhe apenas na área que selecionei. Me mostre opções para ficar próximo de 500 MB e quanto tempo cada uma provavelmente vai demorar. Depois que eu escolher, gere o arquivo.”**

The agent must inspect the **actual current QGIS map and styles**, identify candidate medium-zoom **Region** and high-detail **Local** extents, recommend appropriate zooms using geography, rendered resolution and user constraints, calculate exact XYZ tile counts, sample representative tiles when authorized, estimate the final archive size and rendering time with uncertainty, obtain approval, render `.smp`, validate it and report the real local file path and size. Users may subsequently import the file into CoMapeo's Background Map screen.

**Do not build an LLM-only advice feature, mock export, separate standalone SMP app, or unbounded browser/download process.** This must be a real, interactive QGIS agent capability.

## Repository references verified at planning time (2026-11-23)

- AgenticGIS upstream `main`: `1e4f70b488824982a835c89c202454ec92dafae7` (baseline only; **do not reset our fork to it**).
- `digidem/qgis-smp-plugin` `main` commit: `34715788e94718d036a58f9992d7ef69b9ecf3d5`; metadata version `0.9.0`. This plugin is MIT and was developed by Awana Digital.
- `digidem/styled-map-package` spec: `spec/1.0/README.md` (SMP v1.0 **draft**), `main` tree `7d69969b47ac09ed7d4d182e3ebf7c2b6b648169`.
- `digidem/comapeo-map-server` `main` commit: `ad14ea8e3d261eddfb0fb99f85e69c5c9fcf0c22`.

The SMP generator **already has** World (optional), Region (optional), Local (required), a fixed source-slot model, EPSG:3857/256px XYZ raster rendering, PNG/JPG/WebP and exact tile counts. It does **not** have reliable file-size or time forecasts: its built-in size calculation uses fixed guesses per tile. Reuse its generator and adapt where necessary; do not reinvent the SMP file format.

## Non-negotiable architecture and behavior

1. **Single installed plugin.** Vendor a pinned, minimal SMP renderer within the fork (MIT attribution intact) and wrap it with a stable `integrations/smp/` adapter. Do not require a separately installed `comapeo_smp` plugin or duplicate its UI/provider ID. Ensure coexistence if a user happens to have the original installed.
2. **Tools across every agent backend.** Implement `smp_inspect_map`, `smp_suggest_regions`, `smp_estimate`, `smp_start_export`, `smp_export_status`, `smp_cancel_export`, `smp_validate_file` through AgenticGIS's existing tool schema/dispatch. API, CLI and MCP must agree.
3. **Practical planning.** Derive Region and Local from real canvas extent, selected features/layer(s), an explicit rectangle, or a verified `br_resolve_area` result when GISBR is installed. The Region must contain Local; zoom bands must be ordered. World is optional and off by default unless it would be meaningful. Present 2–3 valid alternatives with honest constraints.
4. **Credible preflight.** Use generator exact tile math. For size/time, bounded (permissioned) sampling and low/likely/high estimates with method, sample size and uncertainty. Where sampling is unavailable, report rough/unknown, not invented precision. Include disk needed for temp tiles and archive and limitations of remote WMS/XYZ.
5. **Explicit approval.** No full export, overwrite or sensitive data inclusion without user authorization of the exact effective plan/output path. Preserve previous permission logic, including stable IDs across translated labels. Reject stale project plans.
6. **Responsive execution.** Export as a cancellable, pollable background job with progress; thread safety is the **first technical feasibility gate**. The current renderer uses QGIS map jobs from a worker pool; do not assume that wrapping it in another worker is safe. Never freeze QGIS through a long synchronous executor call.
7. **Real CoMapeo compatibility.** Create a standards-conformant raster SMP archive (`style.json`, `VERSION`, source folders and internal `smp://maps.v1` URIs, correct 256px tileSize and EPSG:3857 tile content). Validate with internal tests, independent `smp validate`, map-server and at least one actual CoMapeo import/open when possible; record which checks actually ran.
8. **Protect the map and data.** Preserve QGIS layer order, visibility, styling, labels and project state. Respect license restrictions on online basemaps and restrictions on Indigenous community location datasets; don't silently export sensitive layers. **Adapt the generator to render only an explicit approved ordered layer list**; upstream currently reads all visible layers from the live project, so a tool-level filter is insufficient. Clean failed/cancelled output and handle cache invalidation, including unsaved feature edits, correctly.
9. **Fork integration.** Keep PT-BR translation and `br_*` tools intact, avoid changes to upstream repos unless a separate explicit upstream task exists, preserve MIT/GPL notices and versioned vendor provenance, ship a working fork ZIP with no new mandatory pip/Node install.
10. **Report truthfully.** Mark `PASS`, `FAIL` or `UNTESTED` for every gate; distinguish unit tests, headless QGIS, GUI and live CoMapeo. Never claim a test passes if the relevant environment is unavailable.

## Suggested developer execution order

Begin with **PLAN Phase 0**: inspect the actual fork, pin renderer SHA, generate and validate a tiny SMP using real QGIS, and prove safe scheduling/cancellation. Only then proceed through vendor packaging, region recommendations, sampled estimator, tool integration, rendering/validation, localization and CoMapeo acceptance testing. Use small reviewable commits and run all checks. Handle reasonable implementation choices autonomously, documenting any deviation from SPEC.

## Final deliverables

- Implementation in our own fork, ideally a distinct `integrations/smp/` module.
- Seven working `smp_*` agent tools with tests, explicit approval and asynchronous status/cancel flows.
- Deterministic tile count + calibrated, honest file-size/time planning with medium/high region choices.
- A real validated SMP export from visible QGIS layers, compatible with actual CoMapeo clients (or precisely documented pending device verification).
- One-plugin installable build, pinned upstream MIT vendor manifest/license, regression tests against PT-BR and GISBR, documentation and recorded commands/results.
- A final engineering report with blockers, tested environments and a readiness classification.

**Success is not documentation delivery; success is an approved, rendered, tested offline map file that a CoMapeo user can actually open.**
