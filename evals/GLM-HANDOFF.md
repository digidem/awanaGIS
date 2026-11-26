# GLM handoff for the AwanaGIS improvement loop

Own one complete iteration in AwanaGIS. Start by freezing the benchmark and collecting a live baseline. Use [TASK.md](../TASK.md) as the tracker and the [eval README](README.md) for runner and review details. Read the repository instructions before editing. Preserve existing work and keep commits local.

## 1. Freeze the eval and prepare an isolated runner

- Inspect the working tree and review the uncommitted harness, fixtures and tests. Run the full headless QGIS suite and Flake8. Commit the benchmark separately from agent behavior. Record the benchmark and agent SHAs in the tracker. If a required harness fix emerges later, create a new benchmark revision and repeat its baseline.
- Pin Tinfoil `deepseek-v4-1-flash`, QGIS 3.34.4 and CoMapeo Map Builder 0.9.0. Source `~/.zshrc` in the outer shell with its output suppressed. Pass the exported `TINFOIL_API_KEY` through the isolated worker environment. Keep it out of command arguments, logs, reports and Git.
- Reuse the Bubblewrap smoke launcher at `/tmp/awanagis-live.QN7QI4/launch.py` if available. Parameterize its checkout snapshot, case, variant, repeat count, output path and timeout. A fresh container or VM also works. Give the worker only the system dependencies, a read-only clean checkout snapshot and pinned plugin, a fresh home/profile, a writable reports directory, and the eval credential. Keep developer logging off and use synthetic inputs. Use the same setup for baseline and candidate.
- Verify provider-side spend limits or obtain an explicit run budget before launching the cohort. Set a total wall-clock limit and a per-run timeout. The SMP smoke took about 12–15 seconds per case execution. Other cases may be slower. Identify the PT-BR and Desktop reviewers and record any unavailable checks.

## 2. Capture the live baseline

Run each case from the runner's `--help` three times for `baseline` and three times for `heldout`. The default registry currently has 14 cases, so this is 84 executions. Keep each cohort in a distinct durable local directory outside the checkout, with a fresh output path per case. Use a normal QGIS Python environment inside the isolation boundary. For example, with the checkout mounted at `/src/awanagis`, run:

```sh
QT_QPA_PLATFORM=offscreen AWANAGIS_DEV_LOG=0 PYTHONPATH=/src \
  /usr/bin/python3 -m awanagis.evals.qgis_agent \
  --case smp_territory --variant baseline --repeat 3 \
  --provider tinfoil --model deepseek-v4-1-flash \
  --plugin-path /plugins/comapeo_smp --timeout 180 \
  --output /reports/baseline/development/smp_territory
```

Use the agreed timeout and apply the same plugin configuration on both sides. Keep failures and retries with their original reports. Check held-out runs for completion and infrastructure failures only until promotion. Record Desktop results and blocked checks as specified in the tracker. Record the revisions, environment, provider/model, run directories and sample counts.

## 3. Diagnose one gap and test one fix

Use the development reports to choose a repeatable correctness or user-control gap before optimizing tool calls or latency. The first SMP hypothesis to check is whether the agent chooses generic PyQGIS instead of the supported `run_processing` route for `smp:generatesmp`. Smoke runs ended after permission denial, with no SMP and no final reply. Prefer a narrow routing or instruction fix if the baseline reproduces this. Check whether a meaningful PT-BR reply reaches the user if export is blocked. Keep the permission gate intact.

Write the hypothesis, affected cases, expected artifacts and promotion threshold in the tracker before editing. Build the candidate in its own worktree under a separate parent with the package directory named `awanagis`. Keep the eval and its graders pinned. Run focused offline tests, then run matched baseline and candidate repetitions with the same settings. Preserve the original baseline.

## 4. Compare, decide and hand back

Use `python -m awanagis.evals.qgis_agent.compare <baseline-dir> <candidate-dir>` with QGIS Python and the package parent on `PYTHONPATH`. Compare affected development runs first. For a promising candidate, run the full development and held-out cohorts and applicable Desktop checks, then read the held-out results. Include required manual evidence before counting reviewed passes.

- **Commit** a correctness candidate if its target case improves to at least two passes out of three, the held-out cases retain their pass counts, and required Desktop gates pass. Investigate lost passes with matched reruns. For efficiency, record passing-run sample counts and median changes after quality gates pass.
- **Discard** a candidate that regresses quality or has inconclusive benefit. Leave its worktree isolated until its evidence is recorded. Preserve the baseline and report paths. A blocked check stays blocked and cannot count as a pass.

Update the iteration log in `TASK.md` with revisions, reports, the measured delta and the decision. Hand back the accepted commit or the reasons for discarding the candidate, plus any remaining blockers. Stop after one complete iteration or at the agreed budget limit.
