# PLAN.md — Implementation plan for AgenticGIS pt_BR/i18n PR

> **Status (2026-11-25):** implemented and merged. The repository moved to
> `digidem/awanaGIS`, and both handoff documents now live in-tree under
> `docs/pt-br-i18n/`. Kept for reference.

**Follow:** `SPEC.md` (normative feature requirements and acceptance criteria).  
**Repository:** https://github.com/ultramenid/AgenticGIS  
**Reviewed baseline:** `main` at `1e4f70b488824982a835c89c202454ec92dafae7` (version `0.4.6` on 2026-10-05).  
**Deliverable:** Tested code and catalogs on a feature branch of a fork, followed by a targeted upstream PR.  
**Audience:** Autonomous developer agent. Proceed through every phase; verify outputs and report blockers instead of guessing. Do not create a PR until acceptance gates pass. These documents request actual implementation and a PR after passing gates; no code changes have yet been made by the author of this handoff.

## Operating instructions for the developer agent

1. Read `SPEC.md` in full. Treat **all acceptance criteria** as required. Work with current upstream HEAD, not only the reviewed baseline. If the code has changed substantially, update the audit/plan before editing. **Handoff precondition:** these two documents are supplied separately and are **not present in the upstream repository**. Ensure both files are accessible after cloning (copy them into the checkout root or reference their absolute paths); verify with `test -s SPEC.md && test -s PLAN.md` before starting. Do not substitute assumptions for a missing document.
2. Do not ask for decisions already resolved in `SPEC.md`. Make narrow, documented decisions for implementation details; prioritize upstream maintainability.
3. Protect user data, tool/CLI/MCP compatibility, stable internal identifiers, and existing English behavior. Avoid changing AI prompting or inferring translated language from free-form content.
4. Run tests after each phase and finish each phase with the gate below. Do not mark tests as passed if not executed; explicitly report QGIS versions not available.
5. Keep commits small and thematic. Use a fork for the branch unless upstream grants write access. Do not force-push, edit upstream `main`, or publish a draft PR with broken acceptance tests.
6. Restrict the PR to feature code, translations, tests and a small README change. `SPEC.md` and `PLAN.md` are handoff documents; upstream tracking is optional and **they are ignored by this repository's current `.gitignore`**.
7. **Security-critical PR gate:** AgenticGIS currently compares exact English permission `choice` labels in `core/toolkit.py::confirm_external_access()`. Follow SPEC FR-04A and do not merge or propose a PR that changes permission outcomes or the raw option payloads.

## Phase 0 — Prepare branch, inspect, and complete the string audit

**0.1 Synchronize and baseline**

```bash
git clone https://github.com/ultramenid/AgenticGIS.git
cd AgenticGIS
git remote -v
git rev-parse HEAD
git status --short
# Fork on GitHub if necessary, and set an appropriate remote/branch:
git switch -c feat/qgis-i18n-pt-br
# The two supplied handoff Markdown files are NOT part of the upstream clone.
# If they are stored elsewhere, copy them here from their actual location first:
# cp /actual/handoff/path/SPEC.md /actual/handoff/path/PLAN.md .
test -s SPEC.md && test -s PLAN.md  # both must be available to the agent
python3 -m compileall -q .
```

Check `metadata.txt` version, Qt5/Qt6 constraints, QGIS minimum versions, `.gitignore`/`.gitattributes`, release/archive conventions. Record current HEAD SHA and any differences from the baseline in your implementation notes. Do not change version metadata simply to add translations.

**0.2 Establish a reproducible inventory**

Run `rg` across all `.py` and `.txt` for strings that reach users, not merely `QLabel`/`QPushButton`. Search constructor arguments, `setText`, `setToolTip`, placeholders, `QMessageBox`, `QFileDialog`, rich text, status helpers, f-strings, session labels, errors, menu/context-menu actions, CLI `credential_style`/`warning`, backend `validate()`, chart/stats captions, and tool result helpers.

Suggested commands (illustrative, tune as needed):

```bash
rg -n 'QLabel\(|QPushButton\(|QMessageBox|QFileDialog|setText\(|setToolTip\(|setPlaceholderText\(|setWindowTitle\(|setStatusTip\(' --glob '*.py' .
rg -n 'Ready|Failed|Done|Cancel|Save|Search|Delete|Current|just now| ago|item|Connected|Connecting|Error|Warning|Permission|Access|Allow|Deny|Download|Copy' --glob '*.py' .
rg -n 'QCoreApplication\.translate|\.tr\(|QTranslator|QLocale|overrideFlag|userLocale' .
```

**0.3 Create the audit table** in a dev note/PR description (not required as a shipped file):

| Module / location | English source | Category | Target context | Decision |
|---|---|---|---|---|
| `gui/chat_dock.py` composer | `Ask AgenticGIS… (↑ for history)` | UI placeholder | `ChatDock` | Translate |
| `gui/settings_dialog.py` tabs | `API key`, `CLI Agent` | UI labels; stable internal modes | `SettingsDialog` | Translate display only |
| `gui/session_popup.py` | `No matching sessions` | UI empty state | `SessionPopup` | Translate |
| `gui/formatting.py` | `just now`, `Xm ago` | UI generated messages | `AgenticGIS` | Translate/format |
| `gui/stats_widget.py` | `Features`, `Distinct`, `Mean` | UI metrics | `StatsWidget` | Translate |
| `backends/base.py` | `No API key set for {label}...` | User-facing validation vs backend data | `AgenticGIS` | Translate at display boundary; preserve returned wire behavior |
| `backends/base.py` / server | `tool_use`, JSON schema keys | Protocol | — | Never translate |
| `core/toolkit.py::confirm_external_access` | `Allow once`, `Always allow`, `Deny`, GEE session option | **Security-critical mixed UI and identity** | Presentation only | Keep canonical English `choice` values; translate distinct display fields and question |

Capture all other first-party display strings with the same discipline. Flag any dynamically built strings not easily extractable, and decide how to represent them with literal messages and placeholders. Record which categories explicitly do **not** translate.

**Phase 0 gate:** Baseline compiles; a comprehensive inventory and exclusion rationale exist. No guesses about whether a string is protocol- or user-facing remain unresolved.

## Phase 1 — Implement the locale resolver and translator lifecycle

**1.1 Add minimal i18n infrastructure**

- Implement `resolve_qgis_locale(settings=None, system_locale=None)` or equivalent pure/testable function. Read `QgsSettings().value('locale/overrideFlag', False, bool)`; use `locale/userLocale` when valid override; otherwise use `QLocale.system().name()`. Normalize locale names; avoid process-global locale changes.
- Add `candidate_catalogs(locale)` and a simple translator loader. Candidate order: exact (`pt_BR`), then language (`pt`) **only if `AgenticGIS_pt.qm` exists**; otherwise English source strings. Do not silently load `pt_BR` on `pt_PT`.
- Keep no redundant plugin-specific locale setting. Avoid hardcoded special-case branches for Portuguese beyond resource naming.
- Use `qgis.PyQt.QtCore.QTranslator`, `QCoreApplication`, `QLocale` and standard-library `os`/`pathlib` only.

**1.2 Wire startup/unload**

- In `plugin.py` initialize the translator before first translatable menu action, dock, dialog, or startup status; hold `self._translator` strongly.
- Ensure that `classFactory` and `initGui` behaviors remain correct; no translator is installed multiple times. `unload()` should remove it and clear the reference **after widgets/actions are removed** so teardown is consistent.
- Failed translator load returns no translator and English fallback; do not crash QGIS and do not emit hard-failing startup dialogs.
- Avoid translator side effects on the MCP stdio proxy (which may run outside QGIS) and on non-Qt pure Python modules.

**1.3 Unit tests**

Use pytest only as a dev/test dependency if available; simple `unittest` is also acceptable and may fit the zero-dependency spirit. Mock QGIS settings and Qt where necessary so resolver unit tests need no running QGIS. Test flags, missing overrides, normalization, exact/language fallback, invalid files, lifecycle (install once, remove once, strong ref), and English defaults.

**Phase 1 gate:** Resolver tests pass; instrumentation demonstrates the translator is installed before UI creation and removed at unload; no new runtime package is needed.

## Phase 2 — Convert core GUI surfaces to extractable translations

Implement **all** audited UI messages with literal `self.tr('…')` (for QObject subclasses) or `QCoreApplication.translate('StableContext', '…')`. Keep contexts fixed and ensure PyQt lupdate can extract everything. Do not create a `tr(text_variable)` wrapper that breaks extraction.

**2.1 Dock and sessions**

- `gui/chat_dock.py`: labels, tooltips, status text, session selector, all new/rename/delete dialogs, progress/compaction/cancellation, errors, composer hints.
- `gui/session_popup.py`, `core/session_store.py`, `gui/formatting.py`: search, `+ New`, current indicator, relative dates, size warnings, empty state, required snapshot naming policy from SPEC §FR-05: supply a localized default title to all new-session creation paths without changing the persistence schema. Keep historical session payloads unchanged.
- Explicitly test the `settings/sessions` top-row buttons and custom dialogs at minimum widths and font scales.

**2.2 Settings**

- `gui/settings_dialog.py`: `SettingsDialog`, `_PAGES`, `_MODE_LABELS`, `_FORMAT_LABELS`, helper `_group_header`, connection modes, model search, API/custom/CLI, scan/auth/test status, provider warning, MCP and appearance descriptions, footer buttons, tooltips.
- Preserve each mode's `config_mod.MODE_*` value and each CLI adapter/provider ID. Where `_PAGES` and `_MODE_LABELS` are constant pairs, keep value as stable ID and resolve translated label at display time. Never use a translated label in a comparison or config write.
- Include uncommon statuses: CLI scan missing results, binary not found, auth unsupported, connection failure, no model, selection/prefill and credential hints.

**2.3 Permissions and answer controls**

- `gui/ask_user_card.py`: prompt chrome, free-text hint, buttons, cancel, permission descriptions/risks.
- **Mandatory permission wiring (SPEC FR-04A):** inspect `core/toolkit.py::confirm_external_access()` and `_external_access_reason()`, `ask_user()` / `_normalize_ask_user_options()`, `gui/ask_user_card.py::_on_option()`, and `gui/chat_dock.py::_resolve_ask_user()`. Preserve the exact original English `choice` values while introducing localized first-party `display_label`, `display_description`, permission question and display-only reason (or an equivalent typed presentation contract). **The current normalization drops all keys except `label` and `description`: explicitly ensure trusted display metadata survives normalization, or route it separately.** Do not let untrusted agent-generated options impersonate privileged display metadata. The visible `Permitir sempre` must return **`Always allow`**, *not* `Permitir sempre`, and must preserve current security effects. Do not translate arbitrary agent-generated `ask_user` questions/options. Preserve `cancelled` semantics and any fallback Cancel option.
- `gui/agent_turn_bubble.py`, `gui/message_bubble.py`: tool row labels, `User chose: {choice}`, cancellation, detailed result/copy/download/menu wording; do not translate user-provided choice content or generated response text. Localize permission decision summaries only at display time.

**Phase 2 gate:** All above strings are in extraction inventory; screenshots of dock, Settings every tab and permission/session dialogs show meaningful `pt_BR` coverage; English still renders exactly. Verify live mocked permission choices return original English payload values before proceeding.

## Phase 3 — Complete remaining UI, messages and formatting

**3.1 Remaining widgets**

Work through `gui/chart_widget.py`, `gui/stats_widget.py`, `gui/download_card.py`, `gui/downloadable.py`, `gui/gif_widget.py`, `gui/typing_indicator.py` and other GUI files uncovered by Phase 0. Translate save dialogs and filter descriptions, chart/card fallback, `Animation no longer available`, metric names, tooltips. Preserve raw values and file suffixes.

**3.2 User-facing backend/status feedback**

Audit `backends/base.py`, `backends/cli_backend.py`, `backends/adapters.py`, other backends, `core/` and `server/` for first-party text the chat dock renders. For each string, decide explicitly whether it is UI-only, protocol-only, source data, or mixed. UI-only may be translated at display time; mixed strings should be split into stable error IDs/diagnostic data and localizable UI descriptions **only when needed**, without breaking MCP clients or existing CLI adapters. Do not bulk-translate `core/toolkit.py` errors that are used as LLM tool observations or structured responses.

**3.3 Formatting and safety**

- Convert `format_relative_time` to localizable units/messages (or a UI adapter) without touching ISO storage. Plurals and counts must be correct (`%n` or verified natural phrase design). `format_elapsed` may retain measurement symbols when locale-neutral.
- Translate dynamic templates *before* inserting data. Keep HTML-escaping for all untrusted content. Preserve `%`, `&`, braces, tags and keyboard shortcuts.
- Ensure translated labels do not change logic for permissions, session choices, connection modes, or agent actions.

**Phase 3 gate:** Complete first-party text inventory marked translated/nontranslatable with reasons; source-level protocol and saved-data diff review passes; no hidden English plugin UI in common paths.

## Phase 4 — Generate, translate, compile and document catalogs

**4.1 Extraction config**

Create `i18n/AgenticGIS.pro` with **explicit relative paths** for every Python module containing extractable Qt calls; include UI, plugin, and any audited presenter/backend sources. If generation is scripted, script must remain optional build-time tooling and be documented. Do not use glob patterns relying on `.pro` expansion.

**4.2 Generate source catalog**

Use the Qt tooling installed in the QGIS build environment. Example (adapt for Qt5/Qt6 and project layout):

```bash
cd i18n
pylupdate5 AgenticGIS.pro
# On a Qt6-only environment, use the corresponding compatible Qt6 extraction tool.
lrelease AgenticGIS_pt_BR.ts
cd ..
```

Do **not** populate `.ts` by naïve regex replacement without running extraction. Preserve source context and comments. Qt Linguist is acceptable for editing. Review each translation for native Brazilian Portuguese usage and operational correctness, especially dangerous permissions, negations and errors. Ensure every extracted first-party UI message has a finished `pt_BR` translation; no accidental empty/unfinished entries for the audited scope.

**4.3 Verify catalog and metadata**

- Check `.qm` is compiled and `QTranslator.load()` returns true.
- Commit both `.ts` and `.qm`; verify catalog is distributed in the actual ZIP (not merely present locally). Inspect ZIP/archive generated from tracked content.
- Add localized metadata `description[pt_BR]` and `about[pt_BR]` while keeping English values and all machine fields.
- Add concise README section with locale precedence, restart behavior, exact extraction/compile steps and how to add a new language.

**Phase 4 gate:** `.ts` extraction is reproducible, catalogs are complete, compilation passes, QGIS loads the `.qm`, and clean ZIP includes translations.

## Phase 5 — Tests, manual UX matrix and regression review

**5.1 Automation**

Implement the test suite according to `SPEC.md`. Required focused tests:

1. Locale resolver: QGIS explicit override > system locale; missing invalid QGIS preference falls back; `pt-BR`, `pt_BR.UTF-8`, `en_US`, `fr_FR`, `pt_PT`; no global setting mutation.
2. Qt translator lifecycle: install before UI; strong lifetime; no duplicate install; remove on unload; missing/bad catalog returns English without crash.
3. Extraction/coverage: every audited UI source string is extractable, catalog has no placeholder mismatches or invalid `%n`, no unfinished `pt_BR` UI entries. Static-check for new unwrapped first-party literals as feasible; allow documented exceptions.
4. Stable internal behavior: mode IDs, stored settings, schema keys, MCP tool names, serialized events, permissions and CLI command arguments unchanged. **Explicit integration assertions**: pt_BR display of Allow once → raw `Allow once` and one-time grant; Always allow → raw `Always allow` and persisted approval; Deny → raw `Deny` with denial; GEE session option → raw `Allow all GEE tools for this session` with only session-scoped approval; Cancel → `cancelled=True`; arbitrary agent-provided option labels remain unchanged in both display and payload.
5. Session regression: pre-existing JSON session, user-assigned names, restored transcript and current session survive; only intended default-title display changes.
6. Presentation: dynamic template substitution, HTML escaping, Qt pluralization, relative-time formatting, save dialogs/format filters, empty states.

Add a focused test suite as **tracked files**: the existing `.gitignore` ignores `tests/`. Prefer narrowly relaxing the ignore rule for tests or using `git add -f tests/...` and verifying `git ls-files tests`; don't broadly remove all internal ignore rules without a reason. No API keys, live services or external network in tests.

**5.2 Runtime smoke matrix**

Where QGIS installations are available, test clean installs at least on representative QGIS 3/Qt5 and QGIS 4/Qt6; if QGIS 4 is unavailable, clearly report unverified rather than claim support. Also check the oldest claimed QGIS 3.22 API compatibility by review or runtime test if available.

| QGIS locale override | OS locale | Expected AgenticGIS UI | Test flows |
|---|---|---|---|
| `pt_BR` enabled | `en_US` | Portuguese | Open dock/settings, session manager, permissions, chart, save, errors |
| disabled | `pt_BR` | Portuguese | Same; proves true default-from-system behavior |
| `en_US` enabled | `pt_BR` | English | Same; proves QGIS preference takes precedence |
| disabled | `en_US` | English | English baseline and unchanged spacing |
| `fr_FR` enabled | any | English fallback | Missing resource must not crash |
| `pt_PT` enabled | any | English unless an explicit `pt` catalog exists | Do not load `pt_BR` by accident |

For QGIS language changes, restart QGIS; do not promise live retranslation. Test font scale 75%, 100%, 150%, 200%, narrow dock, keyboard navigation and all modal dialogs. Simulate backend statuses and permission events locally to cover UI without contacting an LLM. Where feasible, run one stubbed agent tool event path and verify the same structured payload in English and Portuguese.

**5.3 Packaging smoke**

```bash
# Illustrative; adapt to the project's actual release procedure.
git status --short
git ls-files i18n tests
python3 -m compileall -q .
# Inspect the resulting plugin ZIP or archive:
unzip -l AgenticGIS-*.zip | grep -E 'AgenticGIS_pt_BR\.(ts|qm)'
```

If no release script exists in upstream, package the tracked plugin tree in a temp directory with `AgenticGIS/` as the top-level folder and validate ZIP install via QGIS Plugin Manager. Do not commit local release ZIPs or generated test outputs.

**Phase 5 gate:** All automated checks pass, runtime matrix is documented with honest pass/not-tested statuses, English regressions absent, package smoke passes, and a final diff audit finds no protocol or prompt changes.

## Phase 6 — Review, final cleanup, and upstream contribution

**6.1 Do the last adversarial review**

- Read every changed line; classify UI vs protocol impact. Search `QCoreApplication.translate`, `tr(`, `QTranslator`, and any newly untranslated string. Check translation contexts match `.ts` and `.qm` actually load.
- Check that all translated `SettingsDialog` labels are resolved after translator installation and none are persisted as mode keys.
- Ensure question/permission option **display** is localized without altering the `choice`, `cancelled`, `external_access_always_allowed`, or equivalent semantic payload. Inspect and test exact comparisons in `core/toolkit.py`; there must be no `if choice == "Permitir ..."` branch.
- Confirm pre-existing sessions are readable, naming policy is intentional, and no data migration occurred merely for localization.
- Ensure localized HTML does not interpolate raw user text into markup, apostrophes and accents display correctly, and QGIS core/MCP output is preserved.
- Confirm `.qm` tracked, `.ts` UTF-8, build instructions match actual commands, metadata parses, and `git diff --check` is clean.
- Verify not accidentally committing local logs, cache, ZIP, credentials, virtualenv, IDE directories, or handoff docs when upstream `.gitignore` excludes them.

**6.2 Suggested commit structure**

1. `feat(i18n): load QGIS locale and Qt translator`
2. `refactor(i18n): mark plugin UI and feedback strings for translation`
3. `feat(i18n): add Brazilian Portuguese catalog and metadata`
4. `test(i18n): cover locale fallback and UI compatibility`
5. `docs(i18n): document translator workflow`

Use fewer commits if it keeps the diff reviewable; each commit should build where practical. Do not reformat whole files just because they contain translations.

**6.3 Open a PR against `ultramenid/AgenticGIS:main`**

Suggested title:

> `feat(i18n): QGIS-native localization framework and pt_BR translations`

Suggested description (fill bracketed evidence, omit untested claims):

```markdown
## Summary
- Follow QGIS's effective interface language, falling back to the OS locale and then English source strings.
- Introduce a Qt/QGIS translation pipeline (extractable strings, pt_BR TS/QM catalogs, translator lifecycle).
- Translate first-party chat/settings/session/tool feedback and plugin metadata into Brazilian Portuguese.
- Preserve internal tool IDs, provider/MCP payloads, stored sessions and LLM responses.

## Testing
- Unit / extraction checks: [commands, pass counts]
- Runtime QGIS 3 / Qt5: [version, results, screenshots]
- Runtime QGIS 4 / Qt6: [version/results or not tested]
- Locale matrix: [table]
- Clean-install ZIP: [result]

## Notes
- Unsupported locales continue to display English.
- QGIS interface-language changes take effect on restart.
- No additional runtime dependencies.

## Screenshots
[English / pt_BR: dock, settings, session/permission and result flow]
```

Ask upstream maintainers for review; respond to feedback without weakening tests or expanding scope. If modifications are required, regenerate `.ts` and `.qm`, rerun verification, update screenshots/test notes, and push the same PR branch.

**Phase 6 gate:** PR diff contains exactly the scoped changes; CI/tests and documented manual checks support the claims; PR is reviewable and offers a clear path for future locales.

## Final developer delivery checklist

Return to the requester:

- [ ] Fork/branch link, actual upstream base SHA and PR URL (if opened).
- [ ] Concise implementation summary and complete file list.
- [ ] `pt_BR` translation counts: extracted, finished, intentionally exempt, missing.
- [ ] Test commands and actual results, per QGIS version, with untested cases explicitly listed.
- [ ] Confirmations: no new runtime dependencies; English fallback; ZIP includes QM; no protocol/system-prompt changes; existing session preservation; **permission decisions and canonical raw `choice` strings unchanged in pt_BR**.
- [ ] Screenshot evidence of before/after and a small limitations/next-steps note.
- [ ] Any action required from the user (only if truly blocked), such as providing the QGIS 4 environment or GitHub fork write permission.

## Priority if unexpected complexity is discovered

1. **Do not compromise safety or backwards compatibility**: never translate protocol identifiers, command arguments, or persisted user data.
2. Meet core user experience: QGIS locale detection, main UI, permission flow, sessions, settings and complete `pt_BR` catalog.
3. Preserve maintainability: extractable Qt literals, standard `.ts`/`.qm` pipeline, no new runtime dependencies.
4. Fix or explicitly report any legitimate source string that cannot be localized without reworking protocol code; do not silently say translation is complete.
5. For environmental gaps (e.g. QGIS 4 not installed), run the strongest available tests, provide reproducible instructions and mark the gap honestly. Do not invent a passing runtime result.

---

**Reference documents:**

- `SPEC.md` in this handoff — authoritative scope and acceptance criteria.
- https://github.com/ultramenid/AgenticGIS
- https://docs.qgis.org/testing/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#translating-plugins
- https://github.com/qgis/QGIS/blob/master/python/pyplugin_installer/installer_data.py
- https://doc.qt.io/qt-6/qtranslator.html
