# QGIS Bandit Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two `B110` release blockers, make all Bandit findings fail CI, gate artifact upload, and prepare AwanaGIS `1.1.1`.

**Architecture:** Narrow the Qt cleanup handlers to the expected deleted-object `RuntimeError` with explicit fallback state. Make the Bandit adapter fail closed on every finding and run it on the extracted package before upload. Cover the policy with mocked and real-scanner tests and cover cleanup behavior with focused Qt tests.

**Tech Stack:** Python 3.9-compatible plugin code, PyQt through `qgis.PyQt`, `unittest`, Bandit 1.9.4, GitHub Actions.

## Global Constraints

- Keep the plugin zero-dependency at runtime.
- Import Qt through `qgis.PyQt`.
- Keep Python syntax compatible with Python 3.9.
- Follow the 120-character Flake8 limit.
- Do not add user-visible strings without translation catalogs.
- Do not touch the eval branch or credentials.

---

### Task 1: Prove the CI policy currently misses B110

**Files:**
- Modify: `tests/test_ci_checks.py:408-452`
- Modify: `tests/test_ci_checks.py:1074-1126`

**Interfaces:**
- Consumes: `ci.check_plugin.run_scans`, `ci.check_plugin._run_bandit`, `ci.check_plugin._format_scan_summary`.
- Produces: failing regression tests that require every Bandit finding, including `B110`, to block.

- [ ] **Step 1: Update the mocked low-severity test to require blocking**

Replace the low-severity `B110` assertions in `test_bandit_adapter_cases` with:

```python
self.assertFalse(res["ok"])
self.assertEqual(len(res["blocking_findings"]), 1)
self.assertEqual(res["blocking_findings"][0]["test_id"], "B110")
self.assertEqual(res["informational_findings"], [])
```

- [ ] **Step 2: Add B110 to the real-scanner synthetic fixture**

In `test_real_scanners_on_clean_and_synthetic_packages`, add:

```python
(synth / "silent.py").write_text(
    "def ignore():\n"
    "    try:\n"
    "        return 1\n"
    "    except Exception:\n"
    "        pass\n",
    encoding="utf-8",
)
```

Then extend the Bandit assertions:

```python
self.assertTrue(
    any(f["test_id"] == "B110" for f in bandit_rep["checks"][0]["blocking_findings"])
)
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```sh
AWANAGIS_REQUIRE_REAL_SCANNERS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ci_checks.ScannerAdapterTests.test_bandit_adapter_cases tests.test_ci_checks.RealScannerIntegrationTests.test_real_scanners_on_clean_and_synthetic_packages -v
```

Expected: the mocked test fails because `B110` is informational; the real-scanner test fails because `B110` is absent from blocking findings.

### Task 2: Make Bandit fail closed

**Files:**
- Modify: `ci/check_plugin.py:610-698`
- Modify: `ci/check_plugin.py:1530-1546`

**Interfaces:**
- Consumes: Bandit JSON results.
- Produces: every result in `blocking_findings`; `informational_findings` remains an empty list; summaries count all findings as blocking.

- [ ] **Step 1: Classify every Bandit finding as blocking**

Replace the severity branch with:

```python
result["blocking_findings"].append(entry)
```

Keep credential redaction and malformed-report handling unchanged.

- [ ] **Step 2: Update the Bandit summary**

Replace the medium/high and low counts with:

```python
f"{len(check['blocking_findings'])} blocking finding(s)"
```

Keep the existing blocking-detail loop. The informational loop may remain for schema compatibility but will receive no Bandit entries.

- [ ] **Step 3: Run the focused tests**

Run:

```sh
AWANAGIS_REQUIRE_REAL_SCANNERS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ci_checks.ScannerAdapterTests.test_bandit_adapter_cases tests.test_ci_checks.RealScannerIntegrationTests.test_real_scanners_on_clean_and_synthetic_packages -v
```

Expected: PASS.

### Task 3: Remove the two silent cleanup handlers

**Files:**
- Modify: `gui/chat_dock.py:1386-1409`
- Create: `tests/test_chat_discard.py`

**Interfaces:**
- Consumes: `ChatDock._discard(widgets)`, a transcript layout, and Qt widgets.
- Produces: safe cleanup when Qt raises `RuntimeError` for deleted objects; unexpected exceptions propagate.

- [ ] **Step 1: Add focused failing cleanup tests**

Create `tests/test_chat_discard.py`:

```python
"""Regression tests for failed transcript-row cleanup."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
ChatDock = import_module(f"{ROOT.name}.gui.chat_dock").ChatDock


class FakeLayout:
    def __init__(self, indexes):
        self.indexes = iter(indexes)
        self.taken = []

    def indexOf(self, _widget):
        value = next(self.indexes)
        if isinstance(value, Exception):
            raise value
        return value

    def takeAt(self, index):
        self.taken.append(index)
        return object()


class FakeWidget:
    def __init__(self):
        self.hidden = False
        self.detached = False
        self.deleted = False

    def hide(self):
        self.hidden = True

    def setParent(self, _parent):
        self.detached = True

    def deleteLater(self):
        self.deleted = True


class ChatDiscardTests(unittest.TestCase):
    def test_deleted_widget_is_hidden_without_delete_later(self):
        widget = FakeWidget()
        layout = FakeLayout([RuntimeError("deleted"), RuntimeError("deleted")])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [widget])

        self.assertTrue(widget.hidden)
        self.assertTrue(widget.detached)
        self.assertFalse(widget.deleted)
        self.assertEqual(layout.taken, [])

    def test_detached_live_widget_is_deleted(self):
        widget = FakeWidget()
        layout = FakeLayout([-1, -1])
        dock = SimpleNamespace(transcript_layout=layout)

        ChatDock._discard(dock, [widget])

        self.assertTrue(widget.hidden)
        self.assertTrue(widget.detached)
        self.assertTrue(widget.deleted)

    def test_unexpected_layout_error_propagates(self):
        widget = FakeWidget()
        layout = FakeLayout([ValueError("unexpected")])
        dock = SimpleNamespace(transcript_layout=layout)

        with self.assertRaisesRegex(ValueError, "unexpected"):
            ChatDock._discard(dock, [widget])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify the unexpected-error case fails**

Run:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest tests.test_chat_discard -v
```

Expected: `test_unexpected_layout_error_propagates` fails because the current broad handler swallows `ValueError`; the two `RuntimeError` behavior tests pass.

- [ ] **Step 3: Replace both broad pass handlers**

Use explicit fallback state:

```python
try:
    index = layout.indexOf(widget)
except RuntimeError:
    index = -1
if index >= 0:
    layout.takeAt(index)
```

For the final lookup:

```python
try:
    attached = layout.indexOf(widget) >= 0
except RuntimeError:
    attached = True
if not attached:
    widget.deleteLater()
```

- [ ] **Step 4: Run the cleanup tests**

Run:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest tests.test_chat_discard -v
```

Expected: PASS.

- [ ] **Step 5: Verify Bandit no longer reports B110**

Run:

```sh
bandit gui/chat_dock.py
```

Expected: no issues in `_discard`.

### Task 4: Gate package upload and prepare 1.1.1

**Files:**
- Modify: `.github/workflows/qgis-ci.yml:73-87`
- Modify: `metadata.txt:7-16`
- Modify: `server/mcp_server.py:40`

**Interfaces:**
- Consumes: extracted packaged plugin, pinned Bandit dependency, release metadata validator.
- Produces: no artifact upload after a Bandit finding; plugin version `1.1.1`.

- [ ] **Step 1: Add the pre-upload Bandit step**

Insert before `Upload packaged plugin artifact`:

```yaml
      - name: Gate artifact upload with pre-upload Bandit scan
        run: |
          python3 ci/check_plugin.py scan \
            "$RUNNER_TEMP/extracted/awanagis" \
            --check bandit
```

- [ ] **Step 2: Bump release metadata**

Set `version=1.1.1` in `metadata.txt`, set `SERVER_INFO["version"]` to `1.1.1` in `server/mcp_server.py`, and prepend:

```ini
changelog=1.1.1 - Fix the QGIS plugin-check security findings in failed chat-row cleanup and make pre-upload CI reject every Bandit finding.
```

- [ ] **Step 3: Validate release metadata**

Run:

```sh
python3 ci/check_plugin.py release-meta metadata.txt --tag v1.1.1
```

Expected: PASS.

### Task 5: Verify the exact release candidate

**Files:**
- No additional source changes.

- [ ] **Step 1: Run the full QGIS test suite**

Run:

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest discover -s tests
```

Expected: PASS, allowing only pre-existing environment-dependent skips.

- [ ] **Step 2: Run all CI checker tests with real scanners**

Run:

```sh
AWANAGIS_REQUIRE_REAL_SCANNERS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_ci_checks.py -v
```

Expected: PASS.

- [ ] **Step 3: Lint changed Python files**

Run:

```sh
flake8 --config=.flake8 gui/chat_dock.py ci/check_plugin.py tests/test_chat_discard.py tests/test_ci_checks.py
```

Expected: no new findings; `gui/chat_dock.py` may retain only documented pre-existing advisory findings if present.

- [ ] **Step 4: Build and scan the exact ZIP**

Run:

```sh
python3 scripts/package_plugin.py --output /tmp/opencode/awanagis-1.1.1.zip
python3 ci/check_plugin.py archive /tmp/opencode/awanagis-1.1.1.zip --extract-to /tmp/opencode/awanagis-1.1.1-extracted
python3 ci/check_plugin.py scan /tmp/opencode/awanagis-1.1.1-extracted/awanagis --check bandit
```

Expected: archive validation and Bandit both PASS.

- [ ] **Step 5: Review the diff and move T301 to review**

Run `git diff --check`, inspect `git diff --stat` and the complete diff, then set task `301` to `review`. Do not mark it `done`; that remains the user's decision.
