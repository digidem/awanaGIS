"""Focused unit and integration tests for ci/check_plugin.py."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci import check_plugin  # noqa: E402

VALID_METADATA = """[general]
name=AgenticGIS
qgisMinimumVersion=3.22
qgisMaximumVersion=4.99
description=An in-QGIS agentic chat assistant.
version=0.4.6
author=Test Author
email=author@example.invalid
icon=resources/icon.png
"""

VALID_INIT = """def classFactory(iface):
    return None
"""


def _write_zip_entry(
    zf: zipfile.ZipFile,
    name: str,
    data: bytes,
    unix_mode: int = stat.S_IFREG | 0o644,
) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = unix_mode << 16
    zf.writestr(info, data)


def _build_valid_zip(dest: Path, extra_entries: list[tuple[str, bytes, int]] | None = None,
                     omit_members: set[str] | None = None,
                     metadata_override: bytes | None = None) -> Path:
    omit = omit_members or set()
    base_entries: list[tuple[str, bytes, int]] = [
        ("AgenticGIS/__init__.py", VALID_INIT.encode("utf-8"), stat.S_IFREG | 0o644),
        ("AgenticGIS/metadata.txt", metadata_override or VALID_METADATA.encode("utf-8"), stat.S_IFREG | 0o644),
        ("AgenticGIS/plugin.py", b"class AgenticGisPlugin:\n    pass\n", stat.S_IFREG | 0o644),
        ("AgenticGIS/resources/icon.png", b"\x89PNG\r\n\x1a\n", stat.S_IFREG | 0o644),
        ("AgenticGIS/i18n/AgenticGIS_pt_BR.ts", b"<TS version='2.1'></TS>", stat.S_IFREG | 0o644),
        ("AgenticGIS/i18n/AgenticGIS_pt_BR.qm", check_plugin.QM_MAGIC + b"\x00\x00", stat.S_IFREG | 0o644),
    ]
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data, mode in base_entries:
            if name not in omit:
                _write_zip_entry(zf, name, data, mode)
        for name, data, mode in extra_entries or []:
            _write_zip_entry(zf, name, data, mode)
    return dest


def _has_usable_git_repo() -> bool:
    if shutil.which("git") is None:
        return False
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0 and probe.stdout.strip() == "true"


class ArchiveCheckTests(unittest.TestCase):
    def test_valid_zip_passes_and_excludes_dev_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = _build_valid_zip(tmp_dir / "AgenticGIS.zip")
            extract_dir = tmp_dir / "extracted"

            report = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
            self.assertTrue(report["ok"], report["blocking_errors"])
            self.assertEqual(report["blocking_errors"], [])
            self.assertEqual(report["file_findings"], [])
            self.assertTrue((extract_dir / "AgenticGIS" / "metadata.txt").is_file())
            self.assertFalse((extract_dir / "AgenticGIS" / "tests").exists())
            self.assertFalse((extract_dir / "AgenticGIS" / "ci").exists())

    def test_real_git_archive_exports_clean_plugin_only(self):
        if not _has_usable_git_repo():
            self.skipTest("usable git checkout required")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / "AgenticGIS.zip"
            proc = subprocess.run(
                ["git", "archive", "--format=zip", "--prefix=AgenticGIS/", "--output", str(zip_path), "HEAD"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            extract_dir = tmp_dir / "extracted"
            report = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
            self.assertTrue(report["ok"], report["blocking_errors"])
            plugin_root = extract_dir / "AgenticGIS"
            for excluded in ("tests", "ci", "docs", ".github", ".flake8", ".gitattributes", ".gitignore"):
                self.assertFalse((plugin_root / excluded).exists(), f"{excluded} must not ship")

    def test_missing_qm_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = _build_valid_zip(
                tmp_dir / "missing_qm.zip",
                omit_members={"AgenticGIS/i18n/AgenticGIS_pt_BR.qm"},
            )
            extract_dir = tmp_dir / "extracted"
            report = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
            self.assertFalse(report["ok"])
            self.assertTrue(any("Missing compiled catalog" in e for e in report["blocking_errors"]))
            self.assertFalse(extract_dir.exists())

    def test_corrupt_qm_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = _build_valid_zip(
                tmp_dir / "bad_qm.zip",
                omit_members={"AgenticGIS/i18n/AgenticGIS_pt_BR.qm"},
                extra_entries=[("AgenticGIS/i18n/AgenticGIS_pt_BR.qm", b"not-a-qm-file", stat.S_IFREG | 0o644)],
            )
            report = check_plugin.validate_and_extract_archive(zip_path, tmp_dir / "extracted")
            self.assertFalse(report["ok"])
            self.assertTrue(any("QM catalog header" in e for e in report["blocking_errors"]))

    def test_duplicate_normalized_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = _build_valid_zip(
                tmp_dir / "dup.zip",
                extra_entries=[
                    ("AgenticGIS/Plugin.py", b"x = 1\n", stat.S_IFREG | 0o644),
                ],
            )
            report = check_plugin.validate_and_extract_archive(zip_path, tmp_dir / "extracted")
            self.assertFalse(report["ok"])
            self.assertTrue(any("Duplicate normalized member" in e for e in report["blocking_errors"]))

    def test_unsafe_members_are_rejected_before_extraction(self):
        unsafe_cases = [
            ("AgenticGIS/../escape.py", b"x = 1\n", stat.S_IFREG | 0o644),
            ("/etc/passwd", b"root:x:0:0\n", stat.S_IFREG | 0o644),
            ("OtherRoot/plugin.py", b"x = 1\n", stat.S_IFREG | 0o644),
            ("AgenticGIS/link.py", b"/etc/passwd", stat.S_IFLNK | 0o777),
        ]
        for member_name, data, mode in unsafe_cases:
            with self.subTest(member=member_name):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_dir = Path(tmp)
                    zip_path = _build_valid_zip(
                        tmp_dir / "unsafe.zip",
                        extra_entries=[(member_name, data, mode)],
                    )
                    extract_dir = tmp_dir / "extracted"
                    extract_dir.mkdir()
                    report = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
                    self.assertFalse(report["ok"])
                    self.assertEqual(list(extract_dir.iterdir()), [])

    def test_forbidden_leaks_are_rejected(self):
        forbidden = [
            "AgenticGIS/.git/config",
            "AgenticGIS/.env",
            "AgenticGIS/id_rsa",
            "AgenticGIS/core/__pycache__/x.cpython-312.pyc",
            "AgenticGIS/tests/test_x.py",
            "AgenticGIS/nested.zip",
        ]
        for member_name in forbidden:
            with self.subTest(member=member_name):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_dir = Path(tmp)
                    zip_path = _build_valid_zip(
                        tmp_dir / "leak.zip",
                        extra_entries=[(member_name, b"secret", stat.S_IFREG | 0o644)],
                    )
                    report = check_plugin.validate_and_extract_archive(zip_path, tmp_dir / "extracted")
                    self.assertFalse(report["ok"])
                    self.assertTrue(any("Forbidden" in e for e in report["blocking_errors"]))

    def test_malformed_metadata_and_missing_icon_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            bad_meta = b"[general]\nname=AgenticGIS\nqgisMinimumVersion=4.0\nqgisMaximumVersion=3.22\n"
            zip_path = _build_valid_zip(tmp_dir / "bad_meta.zip", metadata_override=bad_meta)
            report = check_plugin.validate_and_extract_archive(zip_path, tmp_dir / "extracted")
            self.assertFalse(report["ok"])
            self.assertTrue(any("exceeds qgisMaximumVersion" in e for e in report["blocking_errors"]))

            zip_no_icon = _build_valid_zip(
                tmp_dir / "no_icon.zip",
                omit_members={"AgenticGIS/resources/icon.png"},
            )
            report2 = check_plugin.validate_and_extract_archive(zip_no_icon, tmp_dir / "extracted2")
            self.assertFalse(report2["ok"])
            self.assertTrue(any("icon target not found" in e for e in report2["blocking_errors"]))

    def test_executable_hidden_suspicious_and_unusual_mode_are_reported_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = _build_valid_zip(
                tmp_dir / "findings.zip",
                omit_members={"AgenticGIS/resources/icon.png"},
                extra_entries=[
                    ("AgenticGIS/resources/icon.png", b"\x89PNG\r\n\x1a\n", stat.S_IFREG | 0o755),
                    ("AgenticGIS/.hidden_note", b"note", stat.S_IFREG | 0o644),
                    ("AgenticGIS/helper.sh", b"echo hi\n", stat.S_IFREG | 0o4644),
                ],
            )
            extract_dir = tmp_dir / "extracted"
            report = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
            self.assertTrue(report["ok"], report["blocking_errors"])
            categories = {(f["category"], f["path"]) for f in report["file_findings"]}
            self.assertIn(("FILE_EXECUTABLE", "AgenticGIS/resources/icon.png"), categories)
            self.assertIn(("FILE_HIDDEN", "AgenticGIS/.hidden_note"), categories)
            self.assertIn(("FILE_SUSPICIOUS", "AgenticGIS/helper.sh"), categories)
            self.assertIn(("FILE_UNUSUAL_MODE", "AgenticGIS/helper.sh"), categories)
            # Extracted files must not inherit executable or setuid bits.
            extracted_mode = (extract_dir / "AgenticGIS" / "helper.sh").stat().st_mode
            self.assertEqual(extracted_mode & (stat.S_ISUID | stat.S_IXUSR), 0)


class ScannerAdapterTests(unittest.TestCase):
    def _make_target(self, tmp: str) -> Path:
        target = Path(tmp) / "AgenticGIS"
        target.mkdir()
        (target / "plugin.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
        return target

    def test_bandit_adapter_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._make_target(tmp)

            # Pass
            ok_proc = subprocess.CompletedProcess([], 0, json.dumps({"errors": [], "results": []}), "")
            with patch("ci.check_plugin.subprocess.run", return_value=ok_proc):
                res = check_plugin._run_bandit(target)
            self.assertTrue(res["ok"])

            # Nonzero due to medium/high findings -> blocking
            med_payload = {
                "errors": [],
                "results": [{
                    "filename": str(target / "plugin.py"),
                    "line_number": 1,
                    "test_id": "B602",
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "issue_text": "subprocess shell=True",
                }],
            }
            med_proc = subprocess.CompletedProcess([], 1, json.dumps(med_payload), "")
            with patch("ci.check_plugin.subprocess.run", return_value=med_proc):
                res = check_plugin._run_bandit(target)
            self.assertFalse(res["ok"])
            self.assertEqual(len(res["blocking_findings"]), 1)

            # Low severity only -> informational, passes
            low_payload = {
                "errors": [],
                "results": [{
                    "filename": str(target / "plugin.py"),
                    "line_number": 1,
                    "test_id": "B110",
                    "issue_severity": "LOW",
                    "issue_confidence": "HIGH",
                    "issue_text": "try_except_pass",
                }],
            }
            low_proc = subprocess.CompletedProcess([], 1, json.dumps(low_payload), "")
            with patch("ci.check_plugin.subprocess.run", return_value=low_proc):
                res = check_plugin._run_bandit(target)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["informational_findings"]), 1)

            # Missing tool -> error
            with patch("ci.check_plugin.subprocess.run", side_effect=FileNotFoundError()):
                res = check_plugin._run_bandit(target)
            self.assertFalse(res["ok"])
            self.assertTrue(res["errors"])

            # Invalid JSON -> error
            bad_json = subprocess.CompletedProcess([], 0, "{not-json", "")
            with patch("ci.check_plugin.subprocess.run", return_value=bad_json):
                res = check_plugin._run_bandit(target)
            self.assertFalse(res["ok"])
            self.assertTrue(res["errors"])

            # Hardcoded credential message in B105 must be redacted from report and summary
            secret_literal = "BANDIT_" + "CREDENTIAL_VALUE_42"
            b105_payload = {
                "errors": [],
                "results": [{
                    "filename": str(target / "plugin.py"),
                    "line_number": 1,
                    "test_id": "B105",
                    "issue_severity": "LOW",
                    "issue_confidence": "MEDIUM",
                    "issue_text": f"Possible hardcoded password: '{secret_literal}'",
                }],
            }
            b105_proc = subprocess.CompletedProcess([], 1, json.dumps(b105_payload), "")
            with patch("ci.check_plugin.subprocess.run", return_value=b105_proc):
                report = check_plugin.run_scans(target, "bandit", None)
            self.assertTrue(report["ok"])
            summary = check_plugin._format_scan_summary(report)
            serialized = json.dumps(report) + "\n" + summary
            self.assertNotIn(secret_literal, serialized)
            self.assertIn("value redacted", serialized)

    def test_detect_secrets_adapter_cases_and_no_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._make_target(tmp)
            secret_hash = "deadbeef" * 5
            raw_sentinel = "FIXTURE_" + "SECRET_VALUE_98765"

            # Zero exit WITH findings -> MUST FAIL, and never emit raw/hashed secrets
            findings_payload = {
                "results": {
                    "./plugin.py": [{
                        "type": "Secret Keyword",
                        "filename": "./plugin.py",
                        "hashed_secret": secret_hash,
                        "line_number": 1,
                        "is_secret": raw_sentinel,
                    }],
                },
            }
            proc = subprocess.CompletedProcess([], 0, json.dumps(findings_payload), "")
            with patch("ci.check_plugin.subprocess.run", return_value=proc):
                report = check_plugin.run_scans(target, "secrets", None)
            self.assertFalse(report["ok"])
            summary = check_plugin._format_scan_summary(report)
            serialized = json.dumps(report) + "\n" + summary
            self.assertNotIn(secret_hash, serialized)
            self.assertNotIn(raw_sentinel, serialized)
            self.assertIn("Secret Keyword", summary)

            # Missing tool -> error
            with patch("ci.check_plugin.subprocess.run", side_effect=FileNotFoundError()):
                res = check_plugin._run_secrets(target)
            self.assertFalse(res["ok"])
            self.assertTrue(res["errors"])

            # Invalid JSON -> error
            bad_json = subprocess.CompletedProcess([], 0, "not-json", "")
            with patch("ci.check_plugin.subprocess.run", return_value=bad_json):
                res = check_plugin._run_secrets(target)
            self.assertFalse(res["ok"])
            self.assertTrue(res["errors"])

    def test_detect_secrets_baseline_comparison_is_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._make_target(tmp)
            known_hash = "1111222233334444555566667777888899990000"
            confirmed_secret_hash = "aaaabbbbccccddddeeeeffff0000111122223333"
            new_hash = "9999888877776666555544443333222211110000"

            baseline_data = {
                "results": {
                    "plugin.py": [
                        {"type": "Secret Keyword", "hashed_secret": known_hash, "is_secret": False},
                        {"type": "Secret Keyword", "hashed_secret": confirmed_secret_hash, "is_secret": True},
                        {"type": "Secret Keyword", "hashed_secret": new_hash},
                    ],
                },
            }
            baseline_path = target / ".secrets.baseline"
            baseline_bytes = json.dumps(baseline_data).encode("utf-8")
            baseline_path.write_bytes(baseline_bytes)

            # Matching baselined false-positive passes without passing --baseline or rewriting file
            scan_ok = {
                "results": {
                    "./plugin.py": [{"type": "Secret Keyword", "hashed_secret": known_hash, "line_number": 5}],
                },
            }
            with patch(
                "ci.check_plugin.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, json.dumps(scan_ok), ""),
            ) as mock_run:
                res = check_plugin._run_secrets(target)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["baselined_count"], 1)
            self.assertNotIn("--baseline", mock_run.call_args.args[0])
            self.assertEqual(baseline_path.read_bytes(), baseline_bytes)

            # Entry marked is_secret=True or unaudited (missing is_secret) still fails
            for active_hash in (confirmed_secret_hash, new_hash):
                with self.subTest(active_hash=active_hash):
                    scan_fail = {
                        "results": {
                            "plugin.py": [{"type": "Secret Keyword", "hashed_secret": active_hash, "line_number": 7}],
                        },
                    }
                    with patch(
                        "ci.check_plugin.subprocess.run",
                        return_value=subprocess.CompletedProcess([], 0, json.dumps(scan_fail), ""),
                    ):
                        res = check_plugin._run_secrets(target)
                    self.assertFalse(res["ok"])
                    self.assertEqual(len(res["blocking_findings"]), 1)

            # Malformed baseline fails with error
            baseline_path.write_text("{bad-json", encoding="utf-8")
            res = check_plugin._run_secrets(target)
            self.assertFalse(res["ok"])
            self.assertTrue(res["errors"])

    def test_flake8_and_compile_adapter_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._make_target(tmp)

            # Advisory Flake8 findings pass without failing the check
            adv_stdout = f"{target / 'plugin.py'}:1:81:E501:line too long (130 > 120 characters)\n"
            adv_proc = subprocess.CompletedProcess([], 1, adv_stdout, "")
            with patch("ci.check_plugin.subprocess.run", return_value=adv_proc):
                report = check_plugin.run_scans(target, "flake8", None)
            self.assertTrue(report["ok"])
            self.assertEqual(report["checks"][0]["counts_by_code"], {"E501": 1})

            # Missing Flake8 binary -> error
            with patch("ci.check_plugin.subprocess.run", side_effect=FileNotFoundError()):
                report = check_plugin.run_scans(target, "flake8", None)
            self.assertFalse(report["ok"])

            # Flake8 exit 1 without parseable findings -> error
            empty_fail = subprocess.CompletedProcess([], 1, "", "bad config")
            with patch("ci.check_plugin.subprocess.run", return_value=empty_fail):
                report = check_plugin.run_scans(target, "flake8", None)
            self.assertFalse(report["ok"])

            # Compile catches syntax error
            (target / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            compile_report = check_plugin.run_scans(target, "compile", None)
            self.assertFalse(compile_report["ok"])


class RealScannerIntegrationTests(unittest.TestCase):
    def _require_tools(self) -> None:
        tools = ("bandit", "detect-secrets", "flake8")
        missing = [
            tool for tool in tools
            if shutil.which(tool) is None and not (Path(sys.executable).parent / tool).is_file()
        ]
        if missing:
            if os.environ.get("AGENTICGIS_REQUIRE_REAL_SCANNERS") == "1":
                self.fail(f"Required scanner binaries missing from PATH: {missing}")
            self.skipTest(f"Scanner binaries not installed in this environment: {missing}")

    def test_real_scanners_on_clean_and_synthetic_packages(self):
        self._require_tools()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            # 1. Fixed clean plugin fixture passes all scanners (decoupled from PR HEAD regressions)
            zip_path = _build_valid_zip(tmp_dir / "clean.zip")
            extract_dir = tmp_dir / "clean_ext"
            arch = check_plugin.validate_and_extract_archive(zip_path, extract_dir)
            self.assertTrue(arch["ok"], arch["blocking_errors"])
            clean_scan = check_plugin.run_scans(
                extract_dir / "AgenticGIS",
                "all",
                ROOT / ".flake8",
                include_metadata_in_secrets=True,
            )
            self.assertTrue(clean_scan["ok"], json.dumps(clean_scan, indent=2))

            # 2. Synthetic package verifying real scanners catch intended failures without leaking secrets
            synth = tmp_dir / "synth"
            synth.mkdir()
            secret_token = "ghp_" + "A1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R8"
            password_literal = "pw_" + "REAL_BANDIT_SECRET_77"
            (synth / "bad_bandit.py").write_text(
                "import subprocess\n\n"
                f'password = "{password_literal}"\n\n'
                "def run(cmd):\n    return subprocess.Popen(cmd, shell=True)\n",
                encoding="utf-8",
            )
            (synth / "leak.py").write_text(
                f'api_key = "{secret_token}"\n',
                encoding="utf-8",
            )
            (synth / "metadata.txt").write_text(
                VALID_METADATA + f'about=leaked "{secret_token}"\n',
                encoding="utf-8",
            )
            (synth / "style.py").write_text(
                "x=1+" + "2" * 130 + "\n",
                encoding="utf-8",
            )

            bandit_rep = check_plugin.run_scans(synth, "bandit", None)
            self.assertFalse(bandit_rep["ok"])
            self.assertTrue(
                any(f["test_id"] == "B602" for f in bandit_rep["checks"][0]["blocking_findings"])
            )
            bandit_text = json.dumps(bandit_rep) + "\n" + check_plugin._format_scan_summary(bandit_rep)
            self.assertNotIn(password_literal, bandit_text)

            secrets_rep = check_plugin.run_scans(synth, "secrets", None, include_metadata_in_secrets=True)
            self.assertFalse(secrets_rep["ok"])
            files_flagged = {f["file"] for f in secrets_rep["checks"][0]["blocking_findings"]}
            self.assertIn("leak.py", files_flagged)
            self.assertIn("metadata.txt", files_flagged)
            secrets_text = json.dumps(secrets_rep) + "\n" + check_plugin._format_scan_summary(secrets_rep)
            self.assertNotIn(secret_token, secrets_text)

            # Unaudited generated baseline (without is_secret=False) must still block
            ds_bin = check_plugin._resolve_tool("detect-secrets")
            baseline_proc = subprocess.run(
                [
                    ds_bin,
                    "scan",
                    "--all-files",
                    "--exclude-files",
                    r"metadata\.txt",
                    "--exclude-files",
                    r"\.secrets\.baseline",
                    ".",
                ],
                cwd=str(synth),
                check=True,
                capture_output=True,
                text=True,
            )
            baseline_payload = json.loads(baseline_proc.stdout)
            baseline_file = synth / ".secrets.baseline"
            baseline_file.write_text(json.dumps(baseline_payload, indent=2), encoding="utf-8")
            unaudited_rep = check_plugin.run_scans(synth, "secrets", None)
            self.assertFalse(unaudited_rep["ok"])

            # Only an explicitly reviewed baseline (is_secret=False) suppresses known entries read-only
            for hits in baseline_payload["results"].values():
                for hit in hits:
                    hit["is_secret"] = False
            reviewed_text = json.dumps(baseline_payload, indent=2)
            baseline_file.write_text(reviewed_text, encoding="utf-8")
            baseline_bytes = baseline_file.read_bytes()

            baselined_rep = check_plugin.run_scans(synth, "secrets", None)
            self.assertTrue(baselined_rep["ok"], baselined_rep)
            self.assertGreater(baselined_rep["checks"][0]["baselined_count"], 0)
            self.assertEqual(baseline_file.read_bytes(), baseline_bytes)

            second_secret = "AKIA" + "IOSFODNN7" + "EXAMPLENEW"
            (synth / "leak2.py").write_text(f'aws_id = "{second_secret}"\n', encoding="utf-8")
            new_secret_rep = check_plugin.run_scans(synth, "secrets", None)
            self.assertFalse(new_secret_rep["ok"])
            new_secret_text = json.dumps(new_secret_rep) + "\n" + check_plugin._format_scan_summary(new_secret_rep)
            self.assertNotIn(secret_token, new_secret_text)
            self.assertNotIn(second_secret, new_secret_text)

            flake_rep = check_plugin.run_scans(synth, "flake8", None)
            self.assertTrue(flake_rep["ok"])
            self.assertGreater(len(flake_rep["checks"][0]["advisory_findings"]), 0)


if __name__ == "__main__":
    unittest.main()
