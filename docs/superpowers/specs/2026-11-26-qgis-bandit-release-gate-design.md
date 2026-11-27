# QGIS Bandit Release Gate Design

## Goal

Resolve the two Bandit `B110` findings that blocked AwanaGIS `1.1.0`, prevent any Bandit finding from passing release CI, and prepare version `1.1.1` for upload.

## Root Cause

`gui/chat_dock.py::_discard` contains two `try/except Exception/pass` blocks at the exact lines reported by the QGIS plugin check. Bandit classifies `B110` as low severity, but the QGIS repository treats the findings as release-blocking. `ci/check_plugin.py::_run_bandit` only blocks medium and high findings, so the existing CI policy explicitly allowed both release blockers through.

## Design

### Source handling

Replace both broad silent handlers in `_discard` with explicit handling of Qt's expected deleted-object `RuntimeError`:

- If `layout.indexOf(widget)` raises `RuntimeError`, treat the first lookup as not found and the final attachment lookup as still attached. This preserves the existing safe behavior for already-deleted widgets without calling `deleteLater` on them.
- Continue hiding and detaching live widgets.
- Let unexpected exception types propagate instead of silently hiding programming errors.

No user-visible strings or runtime dependencies are added.

### CI policy

Treat every Bandit result as blocking, regardless of Bandit severity. Keep the existing report fields for compatibility, but leave `informational_findings` empty. Update the summary to report total blocking findings rather than medium/high versus low.

The package job will run Bandit against the extracted packaged plugin before uploading the artifact. The existing dedicated Bandit job remains as a second check on the downloaded, manifest-verified artifact. Release publishing already depends on the complete reusable CI workflow.

### Regression coverage

- Adapter test: a low-severity `B110` result must make `run_scans(..., "bandit", ...)` fail and appear in `blocking_findings`.
- Real Bandit test: a synthetic `try/except/pass` file must produce a blocking `B110` finding.
- Widget cleanup tests: deleted-layout lookups must not raise or schedule deletion of an already-deleted widget; a live detached widget must still receive `deleteLater`.

### Release metadata

Bump `metadata.txt` to `1.1.1` and add a changelog entry describing the QGIS security-check fix and fail-closed pre-upload Bandit gate.

## Verification

- `QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest discover -s tests`
- `AWANAGIS_REQUIRE_REAL_SCANNERS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_ci_checks.py -v`
- `bandit -r gui/chat_dock.py`
- `flake8 --config=.flake8 gui/chat_dock.py ci/check_plugin.py tests/test_chat_discard.py tests/test_ci_checks.py`
- Package and scan the exact ZIP with `scripts/package_plugin.py` and `ci/check_plugin.py`.

## Scope

No changes to the eval branch, provider credentials, permissions, QGIS runtime behavior outside failed-row cleanup, or release publishing credentials.
