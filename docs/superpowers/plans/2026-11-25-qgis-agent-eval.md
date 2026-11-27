# AwanaGIS QGIS Agent Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkboxes for tracking.

**Goal** Build a repeatable evaluation for completing an offline mapping workflow in AwanaGIS using everyday Brazilian Portuguese.

**Architecture** Use isolated synthetic QGIS projects, the production backend request path, deterministic checks, and a Desktop acceptance procedure. Keep the baseline configuration and input variants stable across comparisons.

**Tech stack** QGIS Python, PyQt through `qgis.PyQt`, Python standard library and unittest, and CoMapeo Map Builder 0.9.0. [QGIS Plugin Repository](https://plugins.qgis.org/plugins/comapeo_smp/)

## Global constraints

- Use synthetic data and a local raster for reproducible imagery checks.
- Baseline runs use one pinned backend and model, fresh sessions and unique output directories.
- Separate correctness, unintended changes, and Portuguese review from performance metrics.
- Desktop evidence is required for canvas interaction, rendered PDF readability, CoMapeo offline import, and the proposed plugin installation flow.

## Shared interfaces

- `build_fixture(case_id: str, run_dir: Path, variant: str = "baseline") -> Fixture`. A fixture exposes `project_path: Path`, `turns: tuple[str, ...]`, and `output_dir: Path`. Fixture-specific expectations can remain on the fixture.
- `evaluate(fixture, project, trace: dict) -> list[dict]`. Each check has `id`, `status` and `detail`, where status is `pass`, `fail`, `manual` or `blocked`.
- Trace uses `turns` entries with `prompt`, `reply`, and `events`; `artifacts` lists paths. Document fields added for Desktop evidence or timings. Report any missing instrumentation as unavailable.
- Case IDs are `basemap`, `load`, `style`, `filter_join`, `pdf`, `smp_territory`, `smp_region`, `smp_ambiguous` and `workflow`.

## Task 1 — Synthetic fixtures and oracles (Luna)

**Files** `evals/qgis_agent/{fixtures,cases,checks}.py` and `tests/test_qgis_eval_fixtures.py`.

- [ ] Create disposable projects with deterministic coordinates, generated names and a fixed project CRS. Use deliberately different source and region extents, named point features with school flags and join keys, and a keyed synthetic table with a known missing match. Keep script-generated fixture inputs apart from the run's artifact directory.
- [ ] Implement standalone starting states and the integrated conversation. Include a basemap default request, explicit alternative and unavailable-source behavior; GeoJSON load and explanation; symbol and labels; filter/join; PDF; and SMP variants. Use the exact framing instruction and follow-up pattern in the design. Include variants with different names and keys for promotion. Preserve uncertainty about field meaning and include realistic references to the preceding map or layer.
- [ ] Evaluate concrete state. Select layers by stable fixture identity, verify expected counts and example names, inspect renderer color and symbol and labeling field plus the white buffer. For join output compare expected feature IDs and joined values and check the source files/records stayed intact. Check basemap identity without requiring remote tile downloads. Put language claims that require judgment in the manual review set.
- [ ] Check PDF artifacts inside the run output folder for validity and inspect the QGIS layout map extent, mapped layers, and present layout elements. Record rendered page readability and clipping as Desktop checks. Inspect SMP metadata and actual tile indexes if present, checking band coverage and per-band limits against expected tile boundaries. Missing evidence must prevent a pass.
- [ ] Exercise check sensitivity by producing expected state, then changing a label field, deleting a join field, altering a source feature, or supplying an absent artifact. Each mutation should fail the corresponding check. Run fixture tests using the offscreen suite.

## Task 2 — Production request path and scoring (Terra)

**Files** `evals/qgis_agent/{runner,trace,__main__}.py` and `tests/test_qgis_eval_runner.py`.

- [ ] Open the fixture project in a QGIS application. Build a real backend through `backends.build_backend`, with the real toolkit and main-thread executor. Drive its request path off the GUI thread and process Qt events on the main thread, as `gui.chat_dock.ChatWorker` does. Preserve returned history only within the same run. Start every case and every repetition with a new backend and project state.
- [ ] Expose case, variant, run output location, repetition count, and exact backend/model selection in the CLI. Read credentials from the environment. If the chosen backend or required credential is absent, give a clear blocked result. Record the version and pinned model actually used. The offline tests can inject a scripted backend through the same runner.
- [ ] Collect assistant text, tool name and cleaned call/result evidence, error and completion state, monotonic times and artifact paths. Intercept toolkit questions through its ask-user emitter and record scripted action wait separately. Allowlisted trace schema should omit transport payloads, credentials, environment, raw exception tracebacks, arbitrary tool data and private reasoning. Redact exact supplied credential values in any retained free text.
- [ ] Report per-case passes across three baseline repetitions, and retain failed, blocked and manual checks. For correctly completed runs report time to first useful feedback, total elapsed, actual model request count, QGIS calls, failed/repeated calls, clarification turns, model time and export time separately. First useful feedback and unnecessary versus justified questions need explicit classification evidence. Record unavailable fields as unavailable and avoid estimating request counts from tool calls.
- [ ] Test turn order, isolation, tool event counts, unavailable metrics, artifact path filtering, credential redaction, failures and timeout handling without invoking a live model. Run the CLI help path and test the repository's package import pattern from the parent directory.

## Task 3 — Desktop acceptance and promotion (coordinator)

**Files** Benchmark README or acceptance instructions adjacent to the runner. Keep plugin references and captured run evidence in the runner's documented output format.

- [ ] Record the version of QGIS, Map Builder 0.9.0, CoMapeo, model, fixture variant, and starting project state. Run PDF layout inspection and all SMP cases from clean profiles or prepared projects.
- [ ] For world coverage inspect zooms 1–5, territory 6–11, and the selected detail region from 12 through the recommended capped zoom. Compare expected tile sets at boundaries, accounting for the fixture CRS and XYZ Web Mercator coordinates. Inspect representative rendered tiles for imagery, visible layers, styles and labels. Validate territory-only output has no detail band and ambiguous territory prompts a targeted question.
- [ ] In the region flow frame the area after the prompt, record before/after canvas bounds and visible layer IDs, and reply “pronto”. Exercise preframed area requests and a changed view or zoom range. Capture the assumptions, estimate ranges, actual artifact bytes and export elapsed time. Check that the detail band follows the updated canvas while retaining wider territory coverage.
- [ ] Open the PDFs and inspect a rendered page for readability and clipping, title, scale bar, north arrow, legend and source credits where applicable. Import the SMP in CoMapeo Desktop and verify it paints without network access.
- [ ] Test missing Map Builder in a disposable profile. Record the offer in plain PT-BR, specific package installation on approval, loaded state and resumed export. Record refusal and install-failure behavior. The design marks agent-driven installation as proposed, so missing implementation is a capability gap in the evidence.
- [ ] Have a Portuguese-speaking reviewer evaluate whether each sampled reply explains what happened and what to do next. Validate wording with intended users or facilitators. Use only baseline inputs for tuning. Record one recurring problem per change, replay affected cases on the pinned baseline configuration, then repeat promising changes across the full workflow and held-back variants. Promote only if correctness and user control hold and the intended metric shows a repeatable gain.

## Verification

Run `QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest discover -s tests` and `flake8`. Run the live baseline only with the pinned backend/model available. Treat missing live or Desktop requirements as unverified and report them per case. Review whether each oracle can fail independently of a model's success claim before accepting benchmark results.
