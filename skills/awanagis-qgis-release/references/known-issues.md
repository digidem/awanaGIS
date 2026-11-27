# Known release and verification facts

## AwanaGIS 1.1.0 security rejection

QGIS rejected `1.1.0` for two Bandit `B110` findings:

- `gui/chat_dock.py:1398` — `try/except Exception/pass`
- `gui/chat_dock.py:1408` — `try/except Exception/pass`

The old CI adapter only blocked medium/high Bandit findings, so both low-severity
release blockers passed CI. The fix made every Bandit finding blocking and added
mocked plus real-scanner `B110` regressions.

## AwanaGIS 1.1.1 verified release

- Merge commit: `de6b5bb31f9a543c8fc9a9ae3de321e229562795`
- GitHub Release: https://github.com/digidem/awanaGIS/releases/tag/v1.1.1
- Release ZIP: `awanagis-1.1.1.zip`
- Release ZIP SHA-256: `653ab7ed4cb01ca91ff619735e0f151ec69cfb2aac86b0bab7088d39e69e8275`
- QGIS version: https://plugins.qgis.org/plugins/awanagis/version/1.1.1/
- QGIS automated scan: all checks passed; 0 issues, 0 warnings, 0 critical.
- QGIS state on 2026-11-27: `Approved: no`, awaiting staff approval. The public
  JSON still listed `1.0.0` as latest.

## Local QGIS suite baseline

On local QGIS 3.34.4, the full suite has three pre-existing onboarding failures
that reproduce on untouched `v1.1.0`:

- `test_env_key_allows_test_and_idle_status`
- `test_stale_result_ignored`
- `test_unconfigured_shows_onboarding_then_chat`

Do not attribute those to an unrelated change without a baseline comparison.
The pinned QGIS 3.44/Qt 5 and QGIS 4.4/Qt 6 release jobs passed for `1.1.1`.

## Tooling dead ends

- Multiple git remotes made implicit `gh` commands target upstream
  `ultramenid/AgenticGIS`; use `--repo digidem/awanaGIS`.
- Protected environment approval rejected string IDs sent through `gh api -f`;
  send a JSON body with numeric IDs through `--input -`.
- A fresh agent-browser Chrome profile was not logged into QGIS; the user's
  Brave profile held the valid `plugins.qgis.org` session cookies.
- Background browser commands with short timeouts were killed; use a long timeout
  and clean up both the wrapper and browser child PIDs.
- QGIS management UI can show a newly scanned version while the public JSON still
  lists only approved versions.
