# AgenticGIS Pull Request CI Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or superpowers:subagent-driven-development after the planning handoff. Steps use checkboxes.

> **Status (2026-11-25):** implemented — the PR checks ship as
> `.github/workflows/qgis-ci.yml`, with packaging and publishing in
> `release.yml`.

**Goal:** Give each pull request reproducible QGIS 3 and QGIS 4 checks, plus the security, quality, and package diagnostics that authors see during QGIS Plugin Repository upload.

**Architecture:** A GitHub Actions workflow packages the tracked commit once, scans the resulting payload, and runs the same offline smoke suite in pinned QGIS Desktop containers. Keep the status reporting rules explicit and reserve uploads and publishing for the existing release process.

**Tech stack:** GitHub Actions, official QGIS Desktop images, Python unittest, Qt Linguist, Bandit, detect-secrets, Flake8 and Python zipfile.

## Constraints and branch order

- This document is the planning handoff. Branch creation, code, commits and PR operations begin after context compaction.
- Fetch upstream `main` and confirm [PR #4](https://github.com/ultramenid/AgenticGIS/pull/4) status. Prefer a fresh fork branch `ci/qgis-plugin-checks` based on upstream `main` after #4 merges. Its tests and catalogs are prerequisites for the complete matrix. If work starts earlier, use a separate worktree based on the exact #4 head or its current replacement and keep it local until it can be rebased onto post-merge main. Review the resulting diff against upstream before pushing so PR #4 changes appear only once.
- Preserve existing workspace edits and ignored planning files. Keep the present i18n handoff byte-for-byte in `docs/pt-br-i18n/{SPEC,PLAN}.md`. Store future handoffs under `docs/<feature-name>/`. The original i18n documents describe their historical root-level handoff. For eventual tracking, make a deliberate narrow ignore exception for feature `SPEC.md` and `PLAN.md` or explicitly stage requested paths. Add `docs/ export-ignore` to `.gitattributes` before tracked docs enter a release archive. Keep these planning documents out of the CI PR unless explicitly requested.
- Preserve the plugin metadata compatibility range, QGIS 3.22–4.99, and zero extra runtime dependencies. Use one representative QGIS 3/Qt 5 release and one QGIS 4/Qt 6 release on every PR. State separately that this covers representative versions, with no implicit full-range testing claim.
- Run on `pull_request` including forks, with read-only contents permission and no credentials, provider calls, privileged containers, or release uploads. Pin third-party actions to commit SHAs and container images to manifest digests after verifying their reported QGIS and Qt versions. Use timeouts and per-PR concurrency cancellation.

## File map

| Path | Responsibility |
|---|---|
| `.github/workflows/qgis-ci.yml` | Stable check names, pinned runtimes, packaging, artifact and result wiring |
| `ci/requirements.txt` | Pinned development-only scanner dependencies |
| `ci/check_plugin.py` | Archive validation, scanner adapters and sanitized result summaries |
| `ci/qgis_zip_smoke.py` | QGIS desktop install, locale, start and unload assertions with a deterministic exit status |
| `tests/test_ci_checks.py` | Focused negative cases for archive and scanner handling |
| `.gitattributes`, `README.md` | Release exclusions and commands contributors can reproduce |

## 1. Establish the baseline and package the PR commit

- [ ] Confirm PR #4's [recorded runtime checks](https://github.com/luandro/AgenticGIS/blob/054815e9f36b95bb118656e2934b189faa6337f4/RELEASE-REVIEW.md) and inspect the release packaging actually used by upstream. If no other release path is tracked, start with `git archive --format=zip --prefix=AgenticGIS/ --output="$RUNNER_TEMP/AgenticGIS.zip" HEAD`. Save the exact tested SHA and archive checksum. Exclude CI files from release export. Deliberately decide whether the reviewed `.flake8` should also ship for QGIS's upload scanner. Use the repo config explicitly for local CI scans regardless.
- [ ] Provide `python ci/check_plugin.py archive <zip> --extract-to <empty-directory>`. Validate entries before extraction. Require a single `AgenticGIS/` root, `metadata.txt`, entry point and referenced icon, and the compiled catalog required by every shipped TS. Reject malformed metadata, duplicate normalized names, traversal and absolute paths, links and special files, and leaks such as `.git`, `.env`, private keys, cached bytecode, test outputs, or nested archives. Treat ordinary hidden files, executable permissions, suspicious suffixes, and unusual modes as findings with path and category. Allow a valid Qt `.qm` catalog and other explicitly reviewed required resources.
- [ ] Unit-test a valid ZIP, missing QM, duplicate name, unsafe member, executable resource, and a synthetic forbidden file. Confirm the valid ZIP extracts with no runtime tests or CI files shipped. Keep the package available to both matrix jobs through one artifact.

## 2. Add QGIS Plugin Repository scan previews

- [ ] At implementation time, pin the reference scanner source revision and compare its enabled rules, thresholds, config handling and file categories with the [QGIS tool guide](https://plugins.qgis.org/docs/security-scanning/tools) and [scanner implementation](https://github.com/qgis/QGIS-Plugins-Website/blob/master/qgis-app/plugins/security_scanner.py). Administrator settings can change the website results, so describe CI as a repository-aligned preview. Record differences in the README.
- [ ] Provide `python ci/check_plugin.py scan <extracted-plugin>`. Run Bandit recursively with JSON output against the exact package. Use the website fallback `-ll` for medium and high severity unless its pinned rule selection calls for a different filter. Distinguish a findings exit from a scanner error or invalid report. Treat unexplained medium and high findings as failures. Document narrowly scoped reviewed exceptions. Keep normal findings below the blocking filter visible when useful.
- [ ] Run `detect-secrets scan --all-files .` from the extracted plugin root and parse its JSON results. A successful scanner process with new findings still fails the CI check. Inspect existing false positives before adopting a reviewed, hash-only baseline. Never generate or update the baseline in a PR run. Prefer narrowly matching the specific metadata field or baseline file that creates noise over exempting unrelated content. Report file, line, detector and counts only, with no raw matches or snippets. Treat tool errors and malformed JSON as failures.
- [ ] Run Flake8 with the project's explicit config on packaged Python files. Report existing style findings without making the first CI PR a formatting cleanup. Run Python compilation separately as a blocking safety net. Classify ordinary file-analysis findings as informational, consistent with the site. Keep invalid or unsafe archive structure blocking under the separate packaging check. The [website overview](https://plugins.qgis.org/docs/security-scanning) distinguishes blocking security scanners from informational Flake8 and file findings.
- [ ] Cover scanner pass, nonzero due to findings, missing tool, invalid JSON, secret findings with zero process exit, and advisory Flake8 findings via small fake subprocess fixtures. Run real scanners on the upstream baseline and a temporary synthetic package. Confirm checks catch intended failures and do not leak fixture values into logs.

## 3. Add the QGIS and Qt runtime matrix

- [ ] Resolve a pinned official QGIS 3 Qt 5 image and the verified QGIS 4.4.0 / Qt 6.8.2 image, or equivalent version-pinned images. The previously tested QGIS 4 tag is `qgis/qgis:4.4.0-trixie` with manifest digest `sha256:54193adc74227c2d264606b721eae13cc23924aa6d23e0572e548d5d7fd1581d`. Preserve the image's QGIS Python path when adding the checkout parent, for example `PYTHONPATH=/workspace:/usr/share/qgis/python`. Log actual QGIS and Qt versions at startup and fail if they mismatch the lane. [Official images](https://github.com/qgis/qgis-docker)
- [ ] Run `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -v` from a checkout named `AgenticGIS` using a temporary profile. Mount sources read-only and disable test-container networking. Reuse the existing tests for locales, catalog integrity, permissions, MCP payload equality, session compatibility and result widgets. Keep the suite outside the packaged ZIP.
- [ ] Implement the desktop smoke that worked during #4. Launch `xvfb-run -a qgis --nologo --noversioncheck --noplugins --profiles-path <temporary-profile> --code /workspace/AgenticGIS/ci/qgis_zip_smoke.py` with a timeout. Under a clean profile set the locale override to `pt_BR`, disable the plugin MCP bridge in the fixture, install the uploaded ZIP using Plugin Manager, and assert plugin activation, translated settings text and metadata, and English fallback after unload. Exit nonzero on assertion failure, launcher failure or timeout. Require a completion marker so a premature QGIS exit cannot pass. Use a non-root desktop process when feasible. If the verified image requires a WebEngine sandbox exception, confine it to the network-disabled disposable test container.
- [ ] Use a build-time job with verified Qt Linguist tools to extract into a temporary catalog and compare context, source, and plural flags to tracked TS. Use `pylupdate5 AgenticGIS.pro` for the explicit Qt 5 project and `pylupdate6 <explicit Python sources> -ts <temporary TS>` on Qt 6. Check the tracked QM loads through each runtime. Keep full real-OS locale matrices and bilingual screenshots as optional release evidence. Require the fast automated matrix and desktop smoke on each PR.

## 4. Verify and prepare the CI-only pull request

- [ ] Run the packaging, both runtime jobs and scanner jobs on a fork PR. Verify a controlled failure is reported for each blocking class and an informational finding stays visible. Keep synthetic failing files in disposable fixture directories or commits outside the final PR. Confirm the actual upstream PR head's checks passed and that jobs consume the same packaged artifact.
- [ ] List stable check names and commands in the README. Describe what blocks and what is advisory, the runtime matrix, how to review a scanner exception, and how to regenerate the archive. Report scanner failures clearly. Avoid uploading raw security reports or credentials.
- [ ] Rebase on current upstream `main`, run `git diff --check`, inspect the exact diff and verify that branch history contains the CI work only relative to main. Push the separate fork branch and open a PR against `ultramenid/AgenticGIS:main` with gate statuses, known baseline findings and exact test evidence. Leave branch protection and release publication to maintainers.

## Acceptance

Each PR runs both runtime lanes, validates and installs the same tracked ZIP, and runs the four repository-aligned scanner categories with clear outcomes. Permission and MCP regressions fail the check. Missing scanners, malformed reports, unsafe archives and smoke failures cannot produce green status. Advisory findings are visible without blocking ordinary quality drift. The CI PR leaves plugin behavior and the i18n PR's diff independent.
