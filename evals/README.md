# AwanaGIS QGIS agent evaluation

The [eval design](../docs/superpowers/specs/2026-11-25-qgis-agent-eval-design.md) records the target workflow and what counts as success. Start with synthetic data and one fixed provider, model, QGIS version, and plugin revision.

## Run the eval

Place each checkout at a path such as `<separate-parent>/awanagis`. From that checkout, run with the Python that imports QGIS. Run live models in a disposable environment with access to synthetic inputs and only the eval credential. QGIS tools can execute PyQGIS inside the runner process. Set the provider credential in the environment and select the exact model.

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m "${PWD##*/}.evals.qgis_agent" \
  --case style --provider "$AWANAGIS_EVAL_PROVIDER" --model "$AWANAGIS_EVAL_MODEL" \
  --repeat 3 --output $HOME/.local/state/awanagis-eval/baseline/style
```

Use a new output path for every invocation. For SMP cases, supply `--plugin-path` pointing to the unpacked, trusted `comapeo_smp` directory from the pinned [0.9.0 release](https://plugins.qgis.org/plugins/comapeo_smp/version/0.9.0/). This loads its Processing provider for the benchmark. Use a disposable profile for the interactive installer acceptance below.

Use `--variant heldout` for held-out baseline and promotion runs. Each repetition has its own process and a default 900-second deadline, configurable through `--timeout`. The runner records missing credentials, timeouts, and check failures in `run.json`.

The report captures first visible text, elapsed time, detected tool failures, and exact repeated tool-argument fingerprints. SMP exports through the Processing tool also record export duration and file bytes. Review the trace for whether feedback was useful and clarification was warranted. Unavailable metrics, including model request count, stay null.

Unattended runs deny external basemap requests at the permission prompt. Verify the Google Satellite default, explicit alternatives, and unavailable-source behavior in QGIS Desktop. A synthetic raster provides repeatable imagery for PDF and SMP cases.

An unattended run stands in for a user who approves work on the run's own files. The runner approves without a prompt: a layer loaded from the run's `inputs` or `outputs` folder with any provider; Processing parameters and PyQGIS code whose absolute paths stay inside the run directory. It still sends to the normal permission prompt, which unattended runs deny: URLs, network, subprocess and environment access, and absolute paths outside the run directory. A run that asks for permission records a `permission` check with status `blocked`.

Two session cases replay the shape of instructions people sent in a workshop session, with synthetic data. `camps_merge` merges the camps of two layers into a derived file, applies a rule the user states, then removes the points inside one named area while a similarly named area must stay. `layer_keep` saves a derived file the user wants kept, then removes its layer from the project. After each turn the runner records what the derived file holds, which project layers are loaded from it, and the workspace state sent to the model, so every instruction is graded against the state the earlier ones left. `camps_saved`, `camps_final` and `kept_saved` grade the points and types in the file. `kept_file` fails when the file disappears with its layer. `workspace_state` fails when the state sent to the model lists a layer that is no longer in the project, or a feature count the layer no longer has.

For Desktop basemap acceptance, use a disposable profile with [QuickMapServices 1.5.5](https://plugins.qgis.org/plugins/quick_map_services/version/1.5.5/) and verify the resulting layer against [Google Satellite, QMS service 678](https://qms.nextgis.com/geoservices/678/). Installing QuickMapServices supplies the catalog and layer actions. AwanaGIS still needs an integration to invoke that action from the chat. Record the plugin version and whether the basemap rendered.

Run the candidate into a different directory, then compare collections of `run.json` reports.

```sh
PYTHONPATH=.. /usr/bin/python3 -m "${PWD##*/}.evals.qgis_agent.compare" \
  $HOME/.local/state/awanagis-eval/baseline $HOME/.local/state/awanagis-eval/candidate
```

Use `--allow-backend-change` when the backend or model is the intended variable. Record completed manual checks in a `manual_checks.json` file next to the relevant `run.json`. Use the check ID from the run and include what the reviewer observed. An SMP review can look like this.

```json
{"smp_region": {"status": "pass", "detail": "The map opened offline, matched the selected area and styling, and the estimates covered the measured size and time."}}
```

The comparison applies these decisions only to pending manual checks.

| Check | Record |
| --- | --- |
| Any pending check emitted by the runner, such as `smp_region` | `manual_checks.json` next to `run.json`, using its emitted ID |
| Standalone basemap, missing plugin, visual PDF and offline SMP checks | `desktop.md` under the run directory, using the IDs in TASK.md |
| Canvas selection and territory-only coverage during Desktop SMP acceptance | Include observations under `smp_offline` in `desktop.md` |

## Compare a candidate with the baseline

1. Use separate output directories for the baseline and candidate. Run each case three times with the same settings. Keep any runs that time out or fail.
2. Compare checks per case, especially unintended edits, selected layers, project state, and artifact coverage. Record manual and blocked checks alongside failures.
3. Compare latency, QGIS tool calls, and repeated or failed calls on cases that pass in both configurations. The comparison leaves runs with pending manual checks out of performance medians. Compare export time separately from the agent's response time.
4. Repeat the full workflow and a held-back variant before promoting a change. Keep the held-back output out of the tuning session.
5. Sample PT-BR replies with a Portuguese-speaking reviewer familiar with the intended users. Check whether the reply explains what happened and makes the next action clear.

## Retain or discard a candidate

1. Start from a committed eval harness. Record its revision, the AwanaGIS revision, the fixture variant, QGIS and plugin versions, and the exact provider and model with the run reports. Capture the first live baseline before changing the agent.
2. Pick one recurring failure or source of wasted work from the baseline. Test one change in a separate worktree so the baseline remains runnable and rejected edits can stay out of the main branch.
3. Run the affected cases three times with the same inputs and configuration. For a promising change, run the full workflow and held-out fixtures. Keep Desktop evidence for cases that need it.
4. Commit a candidate when the intended improvement repeats, existing correct cases remain correct, and user control is preserved. For speed changes, compare medians from passing runs and retain the sample counts. Keep the reports and drop the candidate branch if quality regresses or the benefit is inconclusive.

The blank PDF reproduced below is a candidate to investigate. Capture a live baseline before deciding whether to correct the layout tool, the agent's choice of tool, or both.

## Desktop acceptance

Use a disposable QGIS profile and a generated synthetic fixture. Record the AwanaGIS revision, QGIS version, and CoMapeo Map Builder version. Use a local raster basemap for export comparisons.

- **Canvas selection.** Start with the entire territory visible and send “Cria um mapa para o Mapeo.” Pan and zoom to a different view before replying “pronto”. Record the canvas extent and CRS after moving the map. Check that the agent uses this view for the high-detail band and keeps the wider territory at zooms 6–11.
- **SMP offline.** Save the estimate shown before export and record actual file bytes and export duration. Import the package into CoMapeo with connectivity disabled. Inspect the world overview, the territory at zooms 6–11, and the detailed area at zoom 12 and the recommended maximum. Check basemap, visible layers, labels, and styling against the QGIS view.
- **Territory only.** Export with no specific area of interest. Verify world and territory coverage and the absence of high-detail tiles. The SMP plugin calls the required highest-detail source “Local”, so use the territory for that source and leave its optional middle source disabled. The plugin's world band includes zoom 0 when configured through zoom 5. [Upstream SMP configuration](https://github.com/digidem/qgis-smp-plugin#how-world--region--local-sources-work)
- **PDF.** Open the rendered file and inspect readability, clipping, extent, north arrow, scale bar, title, and applicable legend or credits.
- **Missing SMP plugin.** In a profile without CoMapeo Map Builder, check the PT-BR confirmation. Exercise approval, refusal, and install failure when agent-driven installation is available. For approval, verify the plugin loads and the export resumes. Record an unsupported installation flow as blocked.

For checks with a run ID, use the sidecar above. Record standalone Desktop results in `desktop.md` using the IDs in [TASK.md](../TASK.md). Review those results during promotion.

## Initial smoke findings

- With QGIS 3.34.4 and Map Builder 0.9.0, a scripted backend exercised AwanaGIS's normal Processing dispatch and generated an SMP from the post-pan view. The grader accepted the package structure and zoom coverage. Visual parity and offline CoMapeo import still require Desktop acceptance.
- On the same QGIS build, AwanaGIS's built-in `create_layout` and `export_layout` tools reported success and produced a blank PDF. The layout contained a page but no map. Keep this case in the baseline before tuning the PDF workflow.
