> **AwanaGIS integration note (2026-11-23):** AwanaGIS (`awanagis`) is the confirmed, independent QGIS plugin identity, derived from the AgenticGIS codebase. Historical references to “AgenticGIS” below describe the inherited code architecture, not the name or release destination of the new product. Use AwanaGIS in runtime names, package paths, UI, docs and MCP discovery. **The PT-BR translation feature is already implemented**: preserve, test and adjust its branding contexts but do not start a translation workstream. The root `AGENT_PROMPT.md` governs Git worktrees, sequencing, integration, PR destination and publishing authorization where older handoffs differ. Never open a PR against `ultramenid/AgenticGIS`.

# AwanaGIS — independent plugin branding and identity specification

**Authority:** [Awana Digital Branding Guidelines](https://app.notion.com/p/3341b08162d580a38611ce745e372f45), [brand-guide.md](./brand-guide.md), [brand-tokens.json](./brand-tokens.json). [plan.md](./plan.md) is the implementation checklist and [prompt.md](./prompt.md) contains developer instructions. The root [AGENT_PROMPT.md](../../AGENT_PROMPT.md) controls sequencing, worktrees and PR policy.

## Product objective

Build a separately installable **AwanaGIS** plugin from the actual existing AgenticGIS-derived fork, carrying forward its functionality and **already completed PT-BR translation**. This is the **first release milestone**; ship a QGIS-installable **brand-only release candidate** before waiting for GISBR and SMP integrations. Do not submit work to upstream AgenticGIS, publish a QGIS plugin repository entry or release publicly without owner authorization. A PR in **our** repository is requested by the root orchestrator.

## Canonical identity (binding)

| Property | Value |
|---|---|
| Display/product name | `AwanaGIS` |
| Plugin folder and Python package | `awanagis` |
| Repository slug (if available/appropriate) | `awanagis` |
| Settings prefix | `AwanaGIS/` |
| Session storage key | `AwanaGIS/sessions_json` |
| MCP server/client namespace | `awanagis` |
| MCP discovery | `~/.awanagis/mcp.json` |
| MCP discovery environment override | `AWANAGIS_MCP_DISCOVERY` |
| MCP default listen | loopback `127.0.0.1`, dynamically allocated port |
| Translation catalog prefix | `awanagis` (preserve existing translations, rebrand contexts) |
| Initial version candidate | `0.1.0` (subject to owner's release approval) |
| Parent organization / visual identity | Awana Digital |

Keep `classFactory(iface)` QGIS entrypoint. Do **not** rename machine-facing QGIS tool identifiers (`run_processing`, `run_pyqgis`, `br_*`, `smp_*`), JSON fields or permission choice values as a cosmetic exercise. Any unavoidable Processing provider ID change needs an explicit migration and tests.

## Visual design contract

Use the *exact official* palette and family roles in `brand-tokens.json` and `brand-guide.md`. The current official primary colors are Dark Burgundy `#6B0030`, Burgundy `#8D003E`, Earth `#932D00`. The official fonts are **Tomorrow** for large display/title text, **Public Sans** for body text, and **Space Grotesk** for captions. Secondary colors are defined in the JSON. Brand names, HEX codes and typography roles are official; mapping these into semantic desktop UI roles is a proposal subject to review. Use QGIS-native fallback fonts without requiring users to install font packages. Do not bundle font binaries in the handoff or commit fonts without license/source review.

Style the plugin-owned toolbar, chat, settings, confirmations, status/error states, onboarding, future GISBR and SMP controls. Do not restyle QGIS globally or alter user layers, map symbology, processing outputs or raster SMP content. Support compact Qt docks, keyboard focus, screen readers, PT-BR/English and light/dark QGIS. Validate contrast for normal text >=4.5:1, important UI graphics >=3:1, and don't rely only on color for status. Use a brand-consistent **proposed** AwanaGIS icon with 16/24/32px checks; it is not an approved product logo until design-team signoff. Use official source/approved logo assets only with authorization and provenance.

## Isolation, legal and migrations

AwanaGIS must coexist with AgenticGIS: separate QSettings/session storage, MCP discovery, runtime connection identity, menu actions and plugin ZIP identity. Optional old-data import must be opt-in and non-destructive, never copying credentials/security approvals silently. Preserve AgenticGIS GPL-2.0-or-later notices, GISBR GPL-3.0 obligations if later bundled, SMP MIT attribution and all original authors' copyrights. The merged product requires correct GPLv3-compatible distribution and source notices after GISBR inclusion. Do not misrepresent completed vs planned capabilities.

## Release acceptance gates

1. QGIS recognizes `awanagis` plugin ZIP with valid `metadata.txt`, `classFactory`, assets, bundled catalogs and attribution; install/uninstall/reload smoke tested in real QGIS.
2. Original AgenticGIS and AwanaGIS coexist without settings/session/MCP collision. Default launch never consumes old secrets or grants.
3. Current user flows and existing PT-BR locales work unchanged, including permission decision semantics.
4. Brand token use is centralized and visually checked under light/dark QGIS, small dock/high DPI, focus, permission dialogs and error/progress messages.
5. Brand-only release-candidate archive and evidence are produced as soon as branding passes. Do not block the **brand-only artifact** on other worktrees. QGIS Plugin Repository submission/public release requires separate explicit approval.
6. Automated tests plus available QGIS 3/Qt5 and QGIS 4/Qt6 checks are recorded as PASS/FAIL/NOT RUN, never invented.
7. The final PR into the authorized AwanaGIS repository is created after integration per root orchestrator, not to upstream AgenticGIS.
