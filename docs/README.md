# AwanaGIS — development handoff (excluding completed translation)

This archive consolidates the three *unfinished* workstreams for **AwanaGIS**, the independent QGIS plugin maintained under Awana Digital. The earlier Brazilian Portuguese localization work is **already done**, so **no translation specification, plan or prompt is included**. Preserve and regression-test the current translations.

## How to use

Start with **[`AGENT_PROMPT.md`](../AGENT_PROMPT.md)** at the root of this ZIP. It tells the developer agent to use three separate worktrees, prioritize the branding-only uploadable build, integrate the other worktrees, and create a **single final PR in our own AwanaGIS repository**. This is the only orchestration/PR policy; if the older individual feature instructions conflict, this document and `AGENT_PROMPT.md` win.

## Feature directories

| Feature | Canonical files | Extra binding references |
|---|---|---|
| [`branding/`](./branding/) | `spec.md`, `plan.md`, `prompt.md` | `brand-guide.md`, `brand-tokens.json` |
| [`gisbr-indigenous-data/`](./gisbr-indigenous-data/) | `spec.md`, `plan.md`, `prompt.md` | `indigenous-sources.md` |
| [`comapeo-smp/`](./comapeo-smp/) | `spec.md`, `plan.md`, `prompt.md` | — |

## Product-wide constraints

- Product and plugin identity: **AwanaGIS**, Python package/folder **`awanagis`**. Do not use the discarded working name.
- Treat AgenticGIS, GISBR and CoMapeo Map Builder as **upstream codebases/attributions** where they appear. No PRs to their repositories as part of this work.
- The branding baseline is a dependency for integration; coordinate code ownership of shared modules (`plugin.py`, `core/tools.py`, `core/toolkit.py`, provider lifecycles, settings, MCP).
- Licenses: AgenticGIS GPL-2.0-or-later, GISBR GPL-3.0, CoMapeo SMP plugin MIT; preserve all notices and distribute any combined GPLv3-derived bundle compliantly.
- The upstream AgenticGIS `.gitignore` ignores `docs/`, `tests/` and most Markdown by default. Fix its ignore rules deliberately and check that all these handoff files are **tracked in the final PR**. The runtime QGIS plugin ZIP may exclude development docs where appropriate; the Git repo must retain them.
- No fabricated tests, live endpoint claims, render performance estimates or approvals. Explicit owner approval is required for public release/QGIS directory publication.

## Suggested start

Read the root prompt, then give each worktree its own directory. Branding should produce the **first installable release candidate**, while GISBR and SMP proceed independently behind narrow interfaces. Integrate into the branded base, test, then open one final PR into the correct repository.
