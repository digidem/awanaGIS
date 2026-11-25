# SPEC.md — AgenticGIS internationalization and Brazilian Portuguese

**Project:** [ultramenid/AgenticGIS](https://github.com/ultramenid/AgenticGIS)  
**Feature:** QGIS-native internationalization (i18n) framework and complete Brazilian Portuguese (`pt_BR`) translation of first-party user-facing plugin text  
**Target:** Small, maintainable upstream pull request  
**Repository baseline reviewed:** `main` at commit [`1e4f70b488824982a835c89c202454ec92dafae7`](https://github.com/ultramenid/AgenticGIS/commit/1e4f70b488824982a835c89c202454ec92dafae7), `metadata.txt` version `0.4.6`, QGIS minimum `3.22`, maximum `4.99`  
**Companion document:** `PLAN.md`  
**Status:** Final-reviewed developer handoff; developer must verify against current upstream HEAD before changing code. Repository HEAD was rechecked on 2026-11-23 and still matched the reviewed baseline.
**Implementation status (2026-11-25):** implemented and merged in `digidem/awanaGIS`; kept in-tree for reference.

## 1. Problem and intended outcome

AgenticGIS is a Python-based, zero-extra-runtime-dependency QGIS plugin with a custom Qt/PyQt chat dock, settings dialog, sessions, permission prompts, tool activity, charts, stats, downloads, multiple LLM/CLI backends, and a local MCP bridge. The reviewed tree has no translation resources, translator initialization, or `.tr()`/`QCoreApplication.translate()` usage in the reviewed GUI modules. First-party user-visible English messages are scattered through widgets, helpers, configuration/connection feedback, and some backend-facing code.

A user running QGIS in Brazilian Portuguese should see the **plugin's own interface and plugin-produced feedback in Brazilian Portuguese** without changing AgenticGIS settings. Users running QGIS in English or an unsupported language must continue to see the original English. The implementation must also establish a conventional, extendable workflow for additional languages, not a one-off set of conditional `if locale == 'pt_BR'` branches.

Examples that must translate: `Settings`, `Sessions`, `Ready`, `Send`, `Cancel`, `Save`, `Search sessions…`, `New session`, `Copy response as Markdown`, `Features`, `Distinct`, `just now`, `5m ago`, `Failed`, permission descriptions, connection tests and status messages. User/LLM data, identifiers, command names, and unstructured third-party errors are different categories and must be handled correctly (section 5).

**Upstream-first:** Do not introduce a plugin-specific branding fork, a proprietary translation service, a new mandatory package, or unrelated refactoring. Preserve the existing design, behavior, and English source text as far as practical.

## 2. Repository findings and constraints

The following paths and implementation details were verified against the baseline:

| Path | Relevant behavior / translation surface |
|---|---|
| `__init__.py` | QGIS `classFactory()` plugin load path; imports `plugin.AgenticGisPlugin`. |
| `plugin.py` | `AgenticGisPlugin` lifecycle, `initGui()`, `unload()`, QGIS menu/toolbar action, dock creation, settings dialog creation, backend/MCP state. Ideal translator owner. |
| `config.py` | `Config` wraps `QSettings` using `AgenticGIS/`; currently no language preference. |
| `gui/chat_dock.py` | `ChatDock(QgsDockWidget)`, settings/sessions controls, composer, statuses, session dialogs, errors, progress, permission flow. |
| `gui/settings_dialog.py` | `SettingsDialog(QDialog)`, connection modes, provider/model selectors, CLI agent scanner, auth/testing, MCP settings, appearance; `_MODE_LABELS` and `_PAGES` currently English constants. |
| `gui/ask_user_card.py` | Interactive choices, free-text submission, `Cancel`, permission/confirmation UX. |
| `gui/session_popup.py` | Session actions/search, relative date, empty state, status and tips. |
| `gui/agent_turn_bubble.py`, `gui/message_bubble.py` | Tool progress/results, completion/cancellation, copying, code/table context menus. |
| `gui/formatting.py` | `format_relative_time`, `humanize_tool_name`, `summarize_tool_result`; currently pure-Python display helpers with English labels. |
| `gui/chart_widget.py`, `gui/stats_widget.py`, `gui/download_card.py`, `gui/downloadable.py`, `gui/gif_widget.py`, `gui/typing_indicator.py` | Captions, metric labels, save dialogs, tooltips, errors, empty/animation states. |
| `backends/base.py`, `backends/cli_backend.py`, `backends/adapters.py`, `backends/*` | Some messages shown in the UI; also contain protocol identifiers, provider content, status strings, agent prompts, and CLI metadata requiring careful classification. |
| `core/toolkit.py`, `core/tools.py`, `core/*`, `server/*` | Tool schemas, results, operational errors, MCP messages; **do not translate machine-readable protocol or model-facing material indiscriminately**. |
| `core/session_store.py` | Session JSON stored in `QSettings` (`AgenticGIS/sessions_json`), `SCHEMA_VERSION = 1`, default English name `New session`; must not migrate/rewrite existing saved user data just for translation. |
| `metadata.txt` | English metadata, plugin version `0.4.6`; QGIS supports `description[pt_BR]` / `about[pt_BR]`. |
| `.gitignore` | Excludes `tests/`, `docs/`, `*.md` other than README, and `build_release.sh`; adjust for tracked tests or explicitly force-add. Do **not** silently assume planning MDs are part of the upstream contribution. |
| `.gitattributes` | `tests/` excluded from `git archive`; ensure translation artifacts are **included** in release ZIPs. |

No existing test or CI files were visible in the baseline repository tree. These observations do not claim a full runtime audit; the developer must inventory every first-party user-facing literal and classify it before implementing.

**Critical permission behavior verified in source:** `core/toolkit.py::confirm_external_access()` constructs options labeled `Allow once`, `Always allow`, `Deny`, and (for GEE) `Allow all GEE tools for this session`. It **compares returned `choice` strings against those exact English labels** to grant/deny access and persist approval. `ask_user()` and `AskUserCard` pass the clicked option label through to `ChatDock._resolve_ask_user()` and back into the toolkit. A naïve translation of option `label` would silently change the authorization outcome. The design in FR-04A below is mandatory, not optional. The source also contains agent-generated `ask_user` questions/options, which must not be mistaken for plugin-authored text.

## 3. Goals, non-goals, and guiding rules

### Goals

1. **Automatic locale selection:** Follow the language QGIS actually uses. When QGIS has an explicit interface-language override, honor it; otherwise honor the OS/system locale. No separate AgenticGIS preference is needed.
2. **Complete `pt_BR` UI:** Translate every first-party, human-facing label, placeholder, tooltip, confirmation, status, empty state, local error explanation, activity summary, dialog, and translatable metadata string.
3. **Extensible architecture:** Support new locales by adding a `.ts` catalog and compiled `.qm` resource, without changing program logic.
4. **Safe default:** English source strings work when the catalog is absent, incomplete, invalid, or the locale is unsupported.
5. **Preserve functionality:** Sessions, authentication, agent calls, QGIS processing, generated code, MCP transport, export formats, log behavior, and CLI invocations work as before.
6. **Reviewable PR:** Minimal dependencies, clear architecture, reproducible catalog generation, tests, screenshots or UI evidence, and clean packaging.

### Non-goals for this PR

- A language dropdown inside AgenticGIS, hot language switching, or changing QGIS's global interface language. Changing QGIS's interface language is handled in QGIS Options and typically takes effect on restart.
- Translation of arbitrary LLM-generated prose/thoughts, user prompts, feature attribute values, layer names, custom model IDs, third-party error bodies, terminal output, code blocks, coordinates, SQL, URLs, or file paths.
- Changes to the agent's system prompts, reasoning language, tool descriptions/schemas, serialized event enums or model-facing protocol merely to translate the UI. The LLM remains free to reply in the user's request language; UI language is not a forced answer-language override.
- Full translation of `README.md`, all developer comments, or QGIS core UI. Do add a concise translation-contributor section to README.
- Package-management or GUI-framework changes; no dependence on external localization SDKs.

### Core engineering rules

- **Translate presentation, not identity or data.** Use immutable internal keys/IDs and translate only rendered captions.
- **Never derive logic from translated text.** E.g., an option's displayed `Permitir sempre` cannot be a logic branch that previously compared against `Always allow`.
- **English is the source-of-truth language** in code, with translations in Qt catalogs.
- **Translators must be installed before UI construction**; keep the translator alive for the lifetime of the plugin and remove it on unload.
- **Keep secrets out of translations/logs/tests.** No real API calls or credentials needed for UI verification.

## 4. Functional requirements

### FR-01 — Resolve QGIS-effective locale, with system fallback

Use QGIS's existing locale behavior rather than only `locale.getdefaultlocale()` or a hard-coded country assumption:

1. Read `QgsSettings().value('locale/overrideFlag', False, bool)` (or the equivalent QGIS-supported API on the installed version).
2. If true, read `QgsSettings().value('locale/userLocale', '')` and use the valid override.
3. If false or the overridden value is missing/invalid, use `QLocale.system().name()`.
4. Normalize common spellings (`pt-BR`, `pt_BR`, `pt_BR.UTF-8`) to Qt-style locale (`pt_BR`); handle missing/falsey values and QGIS versions gracefully.
5. Do not write or change QGIS locale settings; do not set the entire process's global default locale.

Use exact locale matching first, then language-only **only if a matching language-only catalog exists** (e.g. `pt_BR` → `pt`). **Do not silently map `pt_PT` to `pt_BR`**, as those are different variants. When no catalog is found, show English. Locale resolution should be a small independently testable function.

### FR-02 — Qt resource format and lifecycle

Use the conventional QGIS/Qt translation mechanism, via `qgis.PyQt`:

- Add `i18n/AgenticGIS_pt_BR.ts` (Qt Linguist editable source, UTF-8) and generated `i18n/AgenticGIS_pt_BR.qm` (runtime binary) to the releaseable repository.
- Add `i18n/AgenticGIS.pro` listing all translatable Python sources explicitly. Standard `pylupdate5`/`pylupdate6` extraction must find the literals. QGIS documentation notes that `pylupdate5` does not expand wildcards in `.pro` source lists.
- Implement a small `i18n` loader module, e.g. `i18n/locale.py` or a clearly named root module, that resolves locale, finds the `.qm` file, creates `QTranslator`, checks `.load()`, and calls `QCoreApplication.installTranslator()`.
- `AgenticGisPlugin` owns a strong translator reference (`self._translator`) so Python's GC cannot discard it; do not install multiple translators on repeated `initGui()`.
- Initialize before `QAction`, `ChatDock`, `SettingsDialog` or other translated UI text is created. Remove translator in `unload()` and release reference. Handle failed load quietly with English fallback (use safe optional development diagnostics, never block QGIS).
- Use compatible QGIS Qt wrappers (`qgis.PyQt.QtCore`, `qgis.PyQt.QtWidgets`) instead of hard-importing `PyQt5` or `PyQt6`.
- No `pip` dependency at runtime. Qt Linguist extraction/compilation tools are **development/build-time** tools.

Illustrative implementation contract (not a copy-paste full implementation):

```python
# In the plugin lifecycle, before initGui creates translatable widgets:
locale_name = resolve_qgis_locale()  # e.g. 'pt_BR'
translator = load_plugin_translator(locale_name, plugin_directory)
if translator is not None:
    QCoreApplication.installTranslator(translator)
    self._translator = translator
# On unload: removeTranslator(self._translator), then clear the reference.
```

### FR-03 — Extractable, stable translation calls

Prefer `self.tr("English literal")` on supported `QObject` subclasses or explicit `QCoreApplication.translate("StableContext", "English literal")` everywhere, including non-`QObject` helpers. Choose and document a consistent policy for contexts (`ChatDock`, `SettingsDialog`, `AgenticGIS`, etc.). Qt extraction must actually discover every string.

```python
# Correct: literal and context are visible to lupdate.
QCoreApplication.translate("ChatDock", "Ready")

# Correct: format only AFTER translation; never translate fragments.
QCoreApplication.translate("ChatDock", "Active session: {name}").format(name=session_name)

# Correct: Qt plural forms, with count passed as n.
QCoreApplication.translate("AgenticGIS", "%n item(s)", None, count)

# Incorrect: runtime-computed msg IDs can be invisible to Qt extractors.
QCoreApplication.translate(context_variable, source_message_variable)

# Incorrect: branching across locales throughout the UI.
"Salvar" if language == "pt_BR" else "Save"
```

If an explicit `tr()` wrapper is introduced, **prove** that the chosen extraction mechanism recognizes every string through it (or use `QT_TRANSLATE_NOOP` with verified extraction). Do not introduce a convenient wrapper that makes all messages invisible to `pylupdate`.

Preserve complete sentences and placeholders as one message. Support Qt `%n` plurals, escaped rich text, Unicode accents, long-text wrapping, translators' comments for ambiguous terminology, and stable source/context identifiers. Avoid evaluating translations into static class/module constants before the translator is installed; render labels lazily or install early and ensure controls created later are correct.

### FR-04 — Full first-party interface coverage

Audit and translate, at a minimum:

| UI / feature | Required surfaces |
|---|---|
| QGIS plugin menu/action | Translatable non-brand captions and tooltips, if any; `AgenticGIS` brand name remains unchanged. |
| Chat dock | Ready/connecting/thinking/running/error/stopped statuses; settings/sessions, composer placeholder and keyboard hint, tooltips; send/stop semantics; compaction notice. |
| Chat sessions | Search/new/rename/delete; first-run session chooser; confirmation and irreversibility warnings; empty-list state; active session metadata; size/date displays. |
| Settings | Window title, rail/pages, breadcrumb, headers/descriptions, buttons; API key/custom endpoint/CLI tabs, model picker/search; test/scan/auth feedback, MCP/security notice, appearance/help text, error dialogs. |
| Interactive ask/permissions | Built-in instructional text, allow/deny/cancel labels, custom-answer placeholder, permission warnings; first-party permission questions/reasons; display text must remain separate from exact English choice values. |
| Tool and answer cards | Tool progress, `Failed`/`Done` summaries, elapsed/relative time, count/plural, details, copied state, table/context menu, Markdown copy tooltip. |
| Visual results | Stats labels (`Features`, `Distinct`, `Null`, `Min`, `Max`, `Mean`, `Sum`, `StdDev`), empty chart notices, image/animation fallback, downloadable file labels. |
| Save/export dialogs | Save title, Markdown/PNG/CSV filter descriptions (not extensions), failure titles, source-file missing explanations. |
| CLI/backend feedback | All **first-party human-readable** status/error/credential hints presented to the UI; preserve external CLI/provider output verbatim and protocol strings unchanged. |
| Relative date/number formatting | `just now`, `Xm ago`, `Xh ago`, `Xd ago`, human-readable plural/count; use locale-aware formatting for presentation where appropriate, not protocol serialization. |
| Plugin manager metadata | `description[pt_BR]`, `about[pt_BR]`; keep plugin name, version, URLs, compatibility fields and tags valid. |

Not all English words are translation candidates: e.g. stable provider names (`Claude Code`, `Codex`, `Ollama`), API names, model IDs, filenames, layer names and CLI switches are proper nouns or data. Classify all hits rather than blindly replacing literals.

### FR-04A — Explicit permission-option display/identity separation (security-critical)

`core/toolkit.py::confirm_external_access()` currently creates the permission options and branches on **exact English choice values**. The UI flow is `confirm_external_access` → `ask_user` → `AskUserCard` → `ChatDock._resolve_ask_user` → toolkit. Preserve this functional contract:

1. Treat `Allow once`, `Always allow`, `Deny`, and `Allow all GEE tools for this session` as **stable canonical option values**, even though they happen to be English strings today. Maintain their exact spelling/capitalization for comparisons and payloads in this PR; do not translate the underlying values or persisted settings.
2. Supply separate localized presentation strings to the card: for example, keep `option['label'] == 'Always allow'` but optionally add a presentation-only `display_label == 'Permitir sempre'` and `display_description`. **Important: `QgisToolkit._normalize_ask_user_options()` currently reconstructs each option as only `{"label", "description"}`, so added display fields will be discarded unless the implementation intentionally preserves trusted presentation metadata or supplies it over a separate presentation-only channel.** Do not merely add fields to `confirm_external_access()` and assume they reach `AskUserCard`. `_OptionRow` renders the display label/description, while its click handler must return the original `label`. Other internal structures are acceptable if they are equally explicit and fully tested. For agent-generated choices without verified first-party provenance, show the supplied label and description **verbatim** and return their original values.
3. Localize the **first-party** permission question and operation reason, but keep the existing unlocalized `reason` for logging, MCP/tool error results, and other machine/LLM-facing uses. Do not translate user-generated questions or arbitrary `ask_user` options. A locale-specific display reason must not be reused as an access-control key.
4. If `ask_user()` synthesizes a fallback `Cancel` option, preserve its canonical choice value and supply a separate translated display label as appropriate. The UI's independent Cancel/dismiss control must still set `cancelled=True` rather than pretending to choose an ordinary option.
5. If displaying a selected permission in the transcript (for example, `User chose: ...`), localize the **presentation** without mutating the `choice` returned to the toolkit or rewriting stored/transmitted historical events.
6. Do not solve this by comparing against Portuguese text, translating `choice` before returning it, or altering JSON protocols. Security-critical actions must be verified with regression tests in both English and `pt_BR` (see acceptance criteria).

### FR-05 — Session compatibility and historical records

- Preserve the existing `AgenticGIS/sessions_json` structure, IDs, stored messages, transcript entries, backend histories, user-provided session titles and QSettings config.
- Do **not** rewrite old session titles or previous LLM answers into Portuguese.
- **Required minimal naming policy:** keep the canonical `DEFAULT_SESSION_NAME = 'New session'` in storage internals for backwards compatibility, but supply the localized default title **when creating new sessions from the UI** (including first-run creation). Use a narrowly scoped constructor parameter or a display/controller-level value passed into `SessionStore` so new sessions in `pt_BR` are created as `Nova sessão`, and new sessions in English keep `New session`. Saved titles are intentional **snapshots**, not live-localized tokens; after QGIS language switches, existing names remain as saved. Do not change the schema version, migrate existing titles, or guess that a user-entered `New session` is autogenerated. Ensure all new-session creation paths, including empty-store initialization and deleting the last session, receive the localized default in a safe way.
- Translate `format_relative_time` display messages without changing stored ISO 8601 values. Do not turn `humanize_tool_name()` output into a translation key that changes tool IDs.

### FR-06 — Machine protocol and security boundaries

Never translate or otherwise alter:

- `EventType` values in `backends/base.py` (`text`, `tool_use`, `done`, etc.), JSON keys, MCP tool names/parameter names, payload schemas, success/error codes or model-facing tool definitions.
- PyQGIS code, processing algorithm IDs, layer IDs, CRS codes, file paths, SQL/expressions, web URLs, response bodies, access tokens or API environment variable names.
- Provider system/developer prompts, compaction prompts, CLI JSON parsing and command construction, or the textual content of external responses as a side effect of UI localization.
- Audit logging messages relied upon by integrations, unless separately proven safe.

When a backend error currently mixes a human sentence with machine details, prefer a localized **UI wrapper** around an unchanged diagnostic detail. For permissions, preserve the exact original labels consumed by `confirm_external_access()` and display independent localized text (FR-04A). When backend-facing and UI-facing representations share a field, disentangle carefully and test the exact wire representation against baseline.

### FR-07 — Brazilian Portuguese language quality

- `pt_BR` uses natural Brazilian usage, UTF-8, and appropriate QGIS vocabulary: **camada**, **feição**, **atributos**, **processamento**, **simbologia**, **sistema de referência de coordenadas (SRC)** where suitable, **sessão**, **modelo**, **salvar**, **cancelar**, **enviar**.
- Preserve brand and technical names such as `AgenticGIS`, `QGIS`, `PyQGIS`, `MCP`, `API`, provider/CLI names, `PNG`, `CSV`, `Markdown`, and configuration identifiers.
- Ensure permissions and warnings communicate the same level of risk and negation in both languages. Do not soften dangerous-access warnings.
- Use short natural UI labels: `Settings` → `Configurações`; `Ready` → `Pronto`; `Sessions` → `Sessões`; `Save` → `Salvar`; `Cancel` → `Cancelar`; `Delete` → `Excluir`; `Send` → `Enviar`.
- Validate placeholders (`{name}`, `{provider}`, `%n`, `%1`, etc.), accelerator markers (`&`), `\n` and markup; never translate variable names or `%` formatting instructions.
- Manual review is required for truncation at 100%, 150%, and 200% font scale, narrow docks, the permission card, modal dialogs, and model/CLI selections.

### FR-08 — Translatable metadata and contributor documentation

In `metadata.txt` add QGIS-compatible localized properties inside `[general]`:

```ini
# Keep existing English description= and about= unchanged.
description[pt_BR]=Assistente de IA integrado ao QGIS para executar tarefas com PyQGIS.
about[pt_BR]=...texto completo e natural em português brasileiro...
```

Verify the Plugin Manager actually selects these with QGIS in `pt_BR` mode. Do not edit `name=AgenticGIS` or nonlocalizable machine fields.

README should briefly document: (a) how locale follows QGIS/system, (b) English fallback and restart behavior, (c) how to update `.ts`, compile `.qm`, and add another locale, (d) where translations reside. Keep the original README in English; a full pt_BR README can be a follow-up.

## 5. Implementation architecture (preferred)

```text
AgenticGIS/
├── __init__.py
├── plugin.py                   # owns and installs QTranslator
├── config.py                   # unchanged language preference model
├── i18n/
│   ├── __init__.py
│   ├── locale.py               # locale resolution + loader, or equivalent module
│   ├── AgenticGIS.pro          # explicit Python source list
│   ├── AgenticGIS_pt_BR.ts     # editable translator source (tracked)
│   └── AgenticGIS_pt_BR.qm     # compiled runtime catalog (tracked/shipped)
├── gui/                        # literal-based Qt translation calls at display sites
├── backends/                   # only human-facing status translations, as audited
├── core/                       # only human-facing presentation; protect schemas
├── metadata.txt                # localized description/about
├── README.md                   # short i18n guidance
└── tests/ or equivalent        # tracked tests; no runtime dependency added
```

The exact module spelling is flexible, but the resource names, Qt extraction compatibility, no additional mandatory runtime dependencies, and release inclusion are mandatory. A single generic `AgenticGIS` Qt translation context is acceptable if it reduces boilerplate, but stable per-class contexts may help translators; document and keep contexts consistent. Do not add a runtime JSON translations engine alongside Qt unless a genuine limitation is demonstrated.

## 6. Acceptance criteria (all required)

**Locale selection**

- [ ] `QGIS override=pt_BR`, OS `en_US` → AgenticGIS first-party UI appears in `pt_BR`.
- [ ] `QGIS override=false`, OS `pt_BR` → first-party UI appears in `pt_BR`.
- [ ] `QGIS override=en_US`, OS `pt_BR` → UI remains English.
- [ ] `QGIS override=false`, OS `en_US` → UI remains English.
- [ ] Unsupported locale, e.g. `fr_FR`, absent/invalid catalog → no error; English fallback.
- [ ] `pt_PT` does not automatically use `pt_BR` without an intentionally named fallback catalog.
- [ ] Locale setting is read at plugin startup; QGIS language changes after restart work. No global locale mutation.

**Translation and behavior**

- [ ] All **identified first-party human-visible literals** in the audited inventory have extracted Qt translation entries or an explicitly justified nontranslatable classification; `pt_BR` catalog has zero unreviewed unfinished UI entries.
- [ ] UI tested in dock, settings all tabs, CLI scan/auth states, session dialogs, permission cards, saves/errors, tool/result cards, charts/stats/empty states.
- [ ] **Permission integration:** selecting translated *Permitir uma vez* returns `choice='Allow once'` and authorizes only the current operation; *Permitir sempre* returns `choice='Always allow'` and persists the original approval config; *Negar* returns `choice='Deny'` and blocks the action; GEE session-level approval returns the original English choice and scopes the approval to the session. Cancel/dismiss returns `cancelled=True`. Compare actual results in English and `pt_BR`, including the case where an LLM supplies arbitrary `ask_user` options. No permission grant may occur via fallback/unknown values.
- [ ] LLM transcript, CLI output, user data, model IDs, tool schema/payloads, project state and saved sessions are unchanged except for carefully designed new-session presentation.
- [ ] Existing QGIS/LLM/provider functionality unaffected; no new required runtime dependency.
- [ ] Qt translator loads successfully before widgets are built, is retained, and is removed at unload. Reopening dock/settings works; no duplicate translator side effects.
- [ ] All Portuguese UI controls fit and remain accessible by keyboard at small dock widths and larger font scale.

**Build and upstream**

- [ ] `.ts` and `.qm` are committed, `.qm` passes load check; extraction and compilation commands are documented and reproducible.
- [ ] A clean QGIS plugin ZIP includes `.qm`, not just `.ts`; manual QGIS install from ZIP works.
- [ ] Automated tests cover locale precedence, normalization, fallback, translator lifetime, catalog/placeholder checks and representative UI states; manual QGIS 3/Qt5 and QGIS 4/Qt6 validation wherever environments are available, with limitations reported.
- [ ] Tests perform without real LLM API calls, external network or secrets; code compiles, baseline behavior works in English.
- [ ] PR is scoped to i18n, includes before/after evidence and test logs; no unnecessary version bump, binary churn, massive generated noise or unrelated refactor.

## 7. Edge cases and regression risks

| Risk | Required safeguard |
|---|---|
| Translator loaded too late | Install before `initGui()` builds any labels; do not cache pretranslated global constants. |
| Translator garbage-collected | Keep strong plugin-owned reference; test unload/reload. |
| Qt extractor misses strings | Extract from literal calls; explicit `.pro` source list; inspect `.ts` inventory against code audit. |
| Confusing QGIS override and OS locale | Use QGIS override flag, then system, with an explicit truth table test. |
| `pt` mistakenly handling `pt_PT` | Exact matching, then matching language-only resource if one exists; otherwise English. |
| Translating values used as IDs or access decisions | `confirm_external_access()` currently compares exact English option labels: preserve raw `choice` and translate display separately (FR-04A); test Allow once / Always allow / Deny / GEE session / cancel. |
| Tool protocol corrupted by human translation | No changes to schemas, event types, prompts, or structured payload keys. |
| Rich text/placeholders break or inject markup | Translate complete source string, format afterward, escape user-supplied values for HTML rendering. |
| Qt5 vs Qt6 tools differ | Use `qgis.PyQt`, fallback build commands `pylupdate5`/`pylupdate6`, verify runtime on both QGIS versions. |
| Session title gets mysteriously rewritten | Protect existing persisted JSON; document handling of autogenerated titles. |
| `.qm` omitted by ZIP/archive | Verify actual ZIP contents and QGIS plugin install rather than assuming source tree is enough. |
| Tests silently missing from PR | `.gitignore` currently ignores `tests/`; alter ignore rules or explicitly force-add intended tests. |

## 8. Required evidence to include with the implementation

Developer must supply a PR-ready report containing: changed file inventory, source string extraction count, translated and unfinished message counts, examples of every audited string category, actual locale behavior matrix, commands/tests and results, **permission-choice payload and grant/deny regression evidence**, QGIS 3/4 manual testing status, clean ZIP contents proof, screenshots (English and pt_BR) of dock/settings/permission and at least one session/result flow, known limitations, and an explicit confirmation that internal protocol names and system prompts were not translated.

## 9. Authoritative references

- Upstream code: https://github.com/ultramenid/AgenticGIS
- QGIS PyQGIS Developer Cookbook, **Translating plugins**: https://docs.qgis.org/testing/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#translating-plugins
- QGIS plugin installer locale behavior (`locale/overrideFlag`, `locale/userLocale`, `QLocale.system()` and localized metadata): https://github.com/qgis/QGIS/blob/master/python/pyplugin_installer/installer_data.py
- Qt `QTranslator`: https://doc.qt.io/qt-6/qtranslator.html
- Qt internationalization tools: https://doc.qt.io/qt-6/linguist-overview.html

This specification deliberately calls for the developer to verify actual repository HEAD and run the full inventory: it is based on inspected source files, **not** on an executed QGIS runtime test.
