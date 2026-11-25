> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# plan.md — Rebrand and establish AwanaGIS using Awana Digital’s design system

**Project:** AwanaGIS (confirmed product name) — AI-assisted, extensible geospatial work in QGIS  
**Purpose:** Rebrand and separate our AgenticGIS-derived development into a self-contained, separately installable and maintainable plugin.  
**Companions:** [`prompt.md`](./prompt.md), [`brand-guide.md`](./brand-guide.md), [`brand-tokens.json`](./brand-tokens.json). This is a rebranding/foundation milestone, **not** a request to reimplement the GISBR and SMP feature specifications.  
**Target:** Our own repository and release artifacts; **no PR against `ultramenid/AgenticGIS`**.  
**Status:** Development-ready handoff, confirmed name. Validate actual working repository and brand assets before editing code.

## 0. Confirmed name, product identity and brand authority

**AwanaGIS is the chosen product name, not a placeholder.** Do not ask the owner to choose a name again or carry forward references to the previously proposed name. The name can be used for implementation immediately; public trademark/domain/repository publication still needs a normal release check. AwanaGIS is a product of **Awana Digital**, not a rename of the Awana Digital organization or its parent logo.

**Visual source of truth:** [Awana Digital Branding Guidelines in Notion](https://app.notion.com/p/3341b08162d580a38611ce745e372f45) (retrieved 2026-11-23). This handoff includes [`brand-guide.md`](./brand-guide.md), a self-contained, cited extraction of the exact colors, font roles and asset choices, and [`brand-tokens.json`](./brand-tokens.json), a machine-readable palette. If the Notion guideline is later updated, reconcile changes deliberately rather than overriding them with invented styles.

| Surface | Confirmed or required value | Contract |
|---|---|---|
| Product display name | **AwanaGIS** | Exact capitalization in all new user-visible surfaces |
| Positioning | **AwanaGIS by Awana Digital** | Parent-organization credit; independent GIS product |
| Description | Conversational geospatial analysis in QGIS, with public-data discovery and offline-map preparation as implemented | Do not advertise unfinished GISBR/SMP integration as shipped |
| Repository slug | `awanagis` | Use actual agreed owner/repository; never invent URLs |
| Python/QGIS plugin directory | `awanagis` | Lowercase ASCII, discoverable by QGIS |
| Main plugin class | `AwanaGisPlugin` | Implementation can retain internal alias if compatibility requires it; keep QGIS `classFactory(iface)` |
| QSettings group | `AwanaGIS` | New isolated state; never touch old group by default |
| Session key | `AwanaGIS/sessions_json` | No silent adoption of previous chats |
| MCP logical server name | `awanagis` | Stable client name; MCP protocol/tool IDs stay valid |
| MCP discovery | `~/.awanagis/mcp.json` | Separate from AgenticGIS and historical rebrand attempts |
| Discovery env var | `AWANAGIS_MCP_DISCOVERY` | New environment namespace |
| MCP port default | `0` (OS-assigned) | Publish actual bound port in discovery, loopback only |
| Translations | `awanagis_<locale>.ts/.qm` | PT-BR and English behavior preserved |
| Plugin log label | `AwanaGIS` | Except for third-party provenance and historical messages |
| Brand fonts | Tomorrow / Public Sans / Space Grotesk | Use according to roles in `brand-guide.md`; safe OS/QGIS fallback |
| Brand palette | Colors defined in `brand-tokens.json` | Exact source HEX values, accessibility tested |
| First independent version | `0.1.0` candidate | A new product version, not inherited from upstream |
| Credits and licenses | AgenticGIS, GISBR, CoMapeo SMP, Awana Digital | Preserve appropriate existing authorship and third-party notices |

**Boundary of authority:** the exact hex values, font names/roles and Awana Digital logo asset variants are **documented brand facts**. AwanaGIS-specific palette application, chat-layout adjustments, plugin symbol design and semantic color mapping are **product proposals** that require visual review. Do not pass a screenshot/mockup off as an approved logo.

**Before any public release:** verify naming collisions in the QGIS plugin directory, GitHub, relevant domains and trademark registries; do not buy a domain, register a mark, create a public repo or publish a release without authorization. This does **not** block local implementation of the confirmed name.

## 1. Scope and sequencing across the three existing development tracks

The repository may contain any subset of: (a) baseline AgenticGIS, (b) the PT-BR/i18n work, (c) GISBR + Indigenous public-data integrations, (d) CoMapeo SMP planner/exporter. The agent must inventory the **actual fork HEAD**, not assume all prior handoff specifications have been implemented.

The preferred dependency order for new work is:

1. **Rebrand foundation and isolated plugin identity** (this plan).
2. Preserve the **already implemented PT-BR localization**; only adapt rebranded UI contexts, compile catalogs and verify behavior. Do not create a separate translation workstream.
3. Integrate **GISBR and Indigenous data** per their separate `prompt.md`/`spec.md`/`plan.md`/`indigenous-sources.md` handoff.
4. Integrate **CoMapeo SMP** per its separate `prompt.md`/`spec.md`/`plan.md` handoff.
5. Run a single unified packaging and cross-feature regression gate.

If the current fork has already implemented (2)–(4), **do not undo them**. Preserve existing functionality, adapt only the brand/namespace-sensitive pieces and run the corresponding acceptance tests. This rebranding plan is authoritative for **product identity**, not for redefining those feature contracts.

## Phase 0 — Repository and legal audit (must pass before editing)

**Tasks**

- Inspect current Git status, branch, remotes, latest commits, Python package root, QGIS `classFactory`, metadata, docs and packaging pipeline. Preserve uncommitted changes; make a new work branch.
- Inventory **all** exact/case-insensitive references to `AgenticGIS`, `agenticgis`, `AgenticGis`, `.agenticgis`, `AGENTICGIS_*`, `mcp__agenticgis__`, and paths under `AgenticGIS/`. Classify each reference: visible branding, persisted identity, protocol/client namespace, historical attribution, code class/function, tests, user content, external upstream links.
- Inventory integration presence: `br_*`, `smp_*`, GISBR `gisbr:` Processing provider, CoMapeo SMP provider, third-party vendored folders, locale catalogs. Inventory existing runtime and test requirements.
- Confirm original AgenticGIS metadata is **GPL-2.0-or-later** and source header retains its author. GISBR is **GPL-3.0**, SMP plugin is **MIT**. Record exact upstream SHA for each copied dependency. Preserve their copyright/license headers and source obligations.
- Avoid creating a new repo/pushing to an unknown owner or mutating existing hosted repositories without explicit destination authorization.

**Gate 0:** Produce `REBRAND_AUDIT.md` (tracked), with the actual SHA, current feature inventory, planned identifier table, licensing obligations and a search baseline. Do not claim a clean starting tree when it is not clean.

## Phase 1 — Establish clean independent Git/repository identity

**Tasks**

- Create a dedicated local feature branch. If creating the separate repository: **preserve source commit history and upstream attribution**, preferably by retaining history and setting `upstream` to the original repository. Do not rewrite the old repository or force-push.
- Rename the QGIS plugin root directory to `awanagis` and ensure Python `__init__.py` exports `classFactory(iface)` returning the correct class.
- Change the user-visible plugin name in `metadata.txt` and QGIS menu/toolbar/dock/status settings. Update plugin description/about text to cover AI tools, official data discovery and offline-map export **only when implemented**; do not market unfinished features as shipped.
- Add new distinct project identity and README introduction. Replace upstream issue/release/homepage URLs **only when our actual URLs are known**; use explicit TODO metadata in a development build rather than inventing URLs or leaving misleading upstream support links in public release metadata.
- Build an **AwanaGIS-specific** icon and lockup *from the approved Awana Digital visual language*; use the parent logo's approved proportions rather than stretching or recoloring its artwork. Prefer an approved square/circle master asset as a visual reference, but do **not** simply rename the Awana Digital logo to AwanaGIS or claim a new variant is approved without design review. Keep a traceable source/authorization record in `resources/BRANDING_ASSET_PROVENANCE.md`. Include crisp QGIS plugin-manager and toolbar sizes and verify against both light and dark QGIS themes. Do not bundle unlicensed fonts or redistribute protected design assets outside the project.
- Update packaging scripts/docs/CI/plugin installation instructions so the ZIP contains a single **`awanagis/`** plugin directory, not `AgenticGIS/` or a nested double directory.
- Revisit `.gitignore`: baseline ignores `docs/`, `tests/` and most `*.md`. Explicitly track essential architecture, specs, tests, notices, and release scripts; update ignore rules rather than accidentally omitting these from Git or a release archive. Review `.gitattributes` export-ignore patterns independently.

**Gate 1:** A clean QGIS profile discovers `awanagis` by the new title **AwanaGIS**, imports `classFactory`, loads/unloads without exceptions, and displays only intended new branding. Old AgenticGIS can be separately installed.

## Phase 2 — Rename runtime identity without breaking protocols

**Tasks**

- Move `config.py` QSettings group to `AwanaGIS`; update session-store key, cached paths, temporary directories and debug logs to independent namespaces.
- Update `server/discovery.py`, `server/mcp_stdio.py`, `server/mcp_server.py`, CLI backend instructions, adapter configuration and README examples to use `awanagis`, `AWANAGIS_MCP_DISCOVERY`, and `~/.awanagis/mcp.json`.
- Default to loopback MCP port 7318 (AgenticGIS uses 7317); `mcp_port=0` selects a dynamic port. Discovery publishes the bound port. Handle port-in-use errors without stealing an old instance.
- Keep **MCP JSON-RPC and tool schemas stable**. New server name affects client registration/prefix, but established tool operations such as `run_processing`, `run_pyqgis`, `br_search_sources`, `smp_suggest_regions`, `smp_estimate`, `smp_start_export`, etc. must **not** be mechanically renamed; preserve working method dispatch and remote clients. Update first-party CLI text that explicitly references `mcp__agenticgis__*` to the correct new client registration name; do not alter third-party tool call payloads or user transcripts.
- Update QGIS dock object names only where the old brand leaks or where they could conflict with the simultaneously installed original plugin. Avoid broad CSS/style refactoring.
- Maintain QGIS 3/Qt5 and QGIS 4/Qt6 compatibility as in the actual fork.

**Gate 2:** Original AgenticGIS and new AwanaGIS both run within the same QGIS profile, with separate toolbar entries, settings, sessions, MCP discovery, CLI client configurations and no default-port collision. A working MCP `tools/list` / `tools/call` smoke test passes for the new name.

## Phase 3 — Safe migration (optional, explicit opt-in only)

**Tasks**

- New installs start in an empty/new `AwanaGIS` settings namespace. Never silently copy or overwrite `AgenticGIS/` values, credentials, sessions or old discovery registrations.
- Offer a small **Import from AgenticGIS** workflow only if it adds practical value (may be deferred with a documented manual export path). It must be opt-in, read-only against the old profile, idempotent and merge-safe.
- Separate import of chat sessions vs. non-secret preferences. Preserve session IDs, titles, histories and schema only after compatibility validation; avoid writing into the original settings group. Handle duplicated/corrupt schemas and rollback/new-session fallback without data loss.
- **Never migrate API keys, tokens, external-access approval, `auto_run`, dangerous-call bypass, unrestricted network access approvals, MCP enabled state or privileged settings automatically.** Re-consent and explicitly set secure defaults for the new plugin.
- Protect against accidental cross-project leakage of sensitive community/geospatial data via migration preview and logs. No old session content used for training or transmitted externally by migration itself.

**Gate 3:** Import is skipped by default; opt-in import is safe, reversible and tested. Old data remains untouched before and after the process.

## Phase 4 — Apply the real Awana Digital brand across AwanaGIS

This is **not** a cosmetic rename, but it is also not a mandate for an unnecessary full UI rewrite. Build a restrained, accessible brand system on top of QGIS native interactions. **Read [`brand-guide.md`](./brand-guide.md) and [`brand-tokens.json`](./brand-tokens.json) before styling any widget.** When online and authorized, open the linked Notion source and verify the image/logo assets directly; preserve their provenance. Do not claim unseen assets were inspected.

**Design-system implementation**

1. Create a central theme module (`gui/brand.py` or equivalent) with named semantic tokens rather than scattered hard-coded HEX values. Keep official colors separate from product-specific semantic assignments. Add a quick contrast test or automated token-validation script.
2. Use **Tomorrow** for high-level titles/large display elements *where appropriate and available*; **Public Sans** for primary readable chat/UI text; **Space Grotesk** for short labels/captions. Do not turn every technical dialog into display typography. Preserve QGIS default font fallback, accessibility font scaling, Qt5/Qt6 font APIs, and localization with Portuguese accents. Verify font licensing and install/embed requirements before shipping files; use native fallbacks if missing.
3. Preferred **light-theme recommendation**: Awana Cream `#FDF7EF` surfaces, Dark Burgundy `#6B0030` for main emphasis and high-contrast text, Burgundy `#8D003E` for important actions, Earth `#932D00` as an occasional accent. Secondary brand colors accent data categories, chips, map legends and statuses only when semantic meaning is clear; never use color alone to convey meaning.
4. Keep QGIS dark-theme support, system/QGIS palette harmony, screen-reader names, keyboard navigation, selected/focus state, readable text, minimum hit targets, visible permission warnings and reduced-motion behavior. Avoid sweeping global QSS selectors that recolor QGIS dialogs or maps outside our plugin.
5. Distinguish **GIS map symbology** from plugin chrome. Do not recolor user-defined layers, legends, classification ramps, satellite imagery or SMP raster outputs to fit the branding. Only brand the UI that manages those workflows. Provide color-blind-safe status and legend labeling.
6. Produce an **AwanaGIS-specific icon and product lockup proposal** using the authorized Awana Digital logo assets as reference. Do not modify the parent organization's source logo without design signoff. Keep placeholder marked `DRAFT` until approved. Verify 16, 24, 32, 64, 128 and 256 px renderings; plugin manager metadata, toolbar and dock labels. Ensure accessible alt/tooltips.
7. Rebrand the welcome/onboarding, settings, sessions, prompts, tool-result status, error messages, source discovery, territorial data notices, SMP planning/export cards and About/Credits page **where present**. Retain simple navigation and short accessible names. Do not invent new GISBR/SMP screens if those integrations have not yet been built.
8. Prepare a compact screenshot/design-review sheet covering (a) QGIS light mode, (b) dark mode, (c) pt-BR, (d) English, (e) permission confirmation, (f) long running task, (g) small-height dock, (h) focused/keyboard-only state. Request design-team review if brand/logo implementation cannot be confidently validated.
9. Preserve translations and QGIS locale detection. Re-extract contexts changed by renaming, compile and package `.qm`. Translate display strings only; **never** translate MCP identifiers, permission grant/deny codes, cache keys or saved tool payloads.

**Automated contrast examples** (WCAG normal text target ≥4.5:1; values calculated from the documented hexes): Dark Burgundy on Cream ≈**11.83:1**; Burgundy on Cream ≈**8.96:1**; Earth on Cream ≈**7.54:1**; River on Cream ≈**5.98:1**. Bright Pink on Cream ≈**2.57:1** and Orange on Cream ≈**2.18:1**: **do not use these combinations for ordinary body text**. Forest on Cream ≈4.31:1; avoid for normal-size text. Recompute if tokens change.

**Gate 4:** Brand tokens are centralized; exact documented colors and font roles are honored with fallback; a reviewed AwanaGIS product icon exists; light/dark, pt-BR/English, permission, focus and contrast tests pass. Product-specific styling is labelled as proposed until brand/design approval. The map render is not altered by the UI theme.

## Phase 5 — Feature and provider integration checks

**Tasks**

- Run existing API, CLI, native MCP and PyQGIS tool tests. `core/tools.py`, `core/toolkit.py`, and `server/mcp_server.py` must continue to expose the same functional tools and schema.
- If GISBR was bundled, validate provider registration/unregistration, import path fixups (`gisbr.*` absolute imports) and QGIS Processing algorithm resolution. If a separate GISBR plugin can coexist, use a **namespaced provider ID** where necessary; update internal references **atomically** and test all calls. Do not rename unrelated stable `br_*` agent tools.
- If SMP code was bundled, validate Processing registration, exporter file paths, zip generation, CoMapeo SMP validation and `smp_*` tool availability. Avoid conflicts with a separately installed `comapeo_smp` provider. Verify path renames don't invalidate tile caches without detection.
- Maintain explicit sensitive-layer export protections; the rebrand must not re-enable permissive export of protected Indigenous locations or bypass approval gates.
- If these integrations are **not yet implemented**, mark them `NOT PRESENT` rather than fabricating passing tests. Their implementation belongs to their dedicated handoff documents.

**Gate 5:** Every *present* integration passes its original acceptance suite. Missing integrations are explicitly scheduled and described as such in UI and docs.

## Phase 6 — Legal notices, documentation, and independent packaging

**Tasks**

- Preserve the original author's notices, LICENSE terms, source provenance, git history, and visible project credit: “Based on AgenticGIS by Muhammad Alichamdan,” with accurate upstream link and modification statement. A separate `NOTICE.md` / `THIRD_PARTY_LICENSES/` / `UPSTREAM_SOURCES.md` is preferred.
- For **base-only rebranding**, the original GPL-2.0-or-later terms remain applicable. Once **GPL-3.0 GISBR code is combined and distributed**, confirm overall distribution under **GPLv3** (the AgenticGIS “or later” grant is compatible); retain per-component GPL-3.0, GPL-2.0-or-later and MIT notices. Do not misleadingly describe a GISBR-bundled artifact as MIT-only or GPL-2-only. Have the release owner review exact license wording if uncertain.
- Include the SMP project's MIT attribution to Awana Digital if it is incorporated. Keep each vendored dependency's SHA, adaptation notes, license and upgrade policy. Do not delete author history during replacement.
- Rewrite README, install, FAQ, screenshots, CLI/MCP examples and developer docs to use the new plugin directory, settings, server name, feature claims and actual repository URLs. Keep historical upstream references as attribution, not as the current support destination.
- Define a version/release policy for this **new project**, without conflating it with AgenticGIS version `0.4.6`, GISBR `1.3.0`, or CoMapeo SMP `0.9.0`.
- Build a deterministic ZIP, inspect its contents and run a clean-profile install from that ZIP. Validate QGIS plugin repository metadata when distribution there is planned. Ensure no secret tokens, developer datasets, internal logs or local absolute paths appear in artifacts.

**Gate 6:** Legal attribution, versioning, package contents and installation are validated. ZIP can be installed as a self-contained plugin without requiring AgenticGIS or second plugin.

## Phase 7 — Comprehensive regression and coexistence tests

Test the following in **headless + live QGIS**, as applicable:

| Check | Expected |
|---|---|
| Fresh QGIS install | `awanagis` loads, AwanaGIS display name, toolbar/dock/sidebar brand correct |
| Brand consistency | Exact palette and font-role snapshot; theme tokens; high-contrast UI, own AwanaGIS icon; nothing changes existing map symbology |
| Accessibility | WCAG AA contrast, focus/keyboard, light/dark themes, font fallback and pt-BR accents |
| Co-install original AgenticGIS | Both independently enabled; no shared settings, sessions, discovery or menu collisions |
| Unload/reload | No dangling translator, provider, QGIS task, thread, action or port |
| Translation | QGIS `pt_BR` → Portuguese; unsupported language → English; permission semantics unchanged |
| CLI/MCP | `tools/list`, a safe `tools/call`, renamed setup docs and dynamic-port discovery work |
| Agent tools | Existing stable tool IDs unchanged and executable |
| Old settings | No automatic migration; optional import read-only and no credential transfer |
| GISBR (if present) | Source search, load, process, provenance, providers and Indigenous safeguards remain working |
| SMP (if present) | Plan → approval → render → package → validation works; no data-sensitivity bypass |
| Package | `awanagis/metadata.txt`, `classFactory`, resources, licenses, `.qm` files, vendored runtime in ZIP |
| Cross-Qt support | QGIS 3/Qt5 and QGIS 4/Qt6 where available; otherwise clearly mark untested |
| No regression | Error handling, cancellation, session save/restore, config, data layers and runtime speed consistent with baseline |

Prefer unit tests for identifier/config/migration logic and live QGIS tests for plugin manager behavior. Also scan all tracked files for old-brand strings and classify **each** remaining hit as (a) necessary attribution, (b) deliberate backwards-compatibility, (c) fixture, (d) accidental leakage to fix. Zero raw hits is not the criterion; **zero unintended hits** is.

**Gate 7:** Test summary with `PASS` / `FAIL` / `UNTESTED` and evidence, no unreported regressions. Do not claim Qt6 or device tests passed when unavailable.

## Phase 8 — Delivery, design acceptance and rollout

**Deliverables**

- A reviewable AwanaGIS rebranding branch (or a new independent repo after destination approval), with small cohesive commits.
- `REBRAND_AUDIT.md`, product identity table, changeset summary and namespaced settings/MCP migration notes.
- Updated README, plugin metadata, AwanaGIS icon/assets, `gui/brand.py` tokens, pt-BR catalogs, licenses/notices and tests.
- A distributable `awanagis-<version>.zip` and SHA-256 checksum, only if building a release candidate is authorized.
- A report that clearly distinguishes **rebranding complete**, **design reviewed/awaiting signoff**, **integrations present**, and **integrations planned**, with tests actually run, screenshots, contrast checks and blockers.

**Do not:** submit to `ultramenid/AgenticGIS`, erase old installations/profiles, auto-import API keys, silently install proprietary font files, register a domain, force-push, claim an unreviewed logo is approved, or create a public release without explicit destination/release approval.

### Definition of done

AwanaGIS is independently identifiable and installable, has isolated state and MCP discovery, follows the official Awana Digital brand tokens and typography hierarchy, retains existing functionality and translations, preserves original-author and vendor attribution, and works alongside AgenticGIS. Its user interface is accessible in light/dark QGIS themes, has an approved or explicitly draft-labeled product icon, makes only accurate feature claims, and passes the ZIP installation test in real QGIS. A production-ready public release requires actual design approval and release authorization.

### Reference repositories (review against current HEAD)

- Original baseline: <https://github.com/ultramenid/AgenticGIS> — previously reviewed `main` SHA `1e4f70b488824982a835c89c202454ec92dafae7`.
- GISBR (only if integrated): <https://github.com/d-camargo/gisbr> — previously reviewed SHA `06d84dfab9942e4e840637bb8d8f96af173330ad`.
- CoMapeo SMP renderer (only if integrated): <https://github.com/digidem/qgis-smp-plugin> — reviewed SHA `34715788e94718d036a58f9992d7ef69b9ecf3d5`.

**Do not assume these old baseline SHAs are the current local implementation.** They are orientation references; the checked-out fork is the source of truth.
