import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.qgis_agent.compare import compare


class EvalCompareTests(unittest.TestCase):
    def test_manual_review_and_configuration_match(self):
        with TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline"
            candidate = Path(directory) / "candidate"
            for root, model in ((baseline, "a"), (candidate, "b")):
                root.mkdir()
                (root / "run.json").write_text(json.dumps({
                    "case": "pdf", "variant": "baseline", "qgis_version": "test",
                    "backend": {"provider": "test", "model": model},
                    "checks": [{"id": "layout", "status": "manual", "detail": "inspect PDF"}],
                    "metrics": {"elapsed_seconds": 3},
                }), encoding="utf-8")
                (root / "manual_checks.json").write_text(json.dumps({
                    "layout": {"status": "pass", "detail": "Reviewed rendered page"},
                }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configurations differ"):
                compare(baseline, candidate)
            result, = compare(baseline, candidate, allow_backend_change=True)
            self.assertEqual(result["baseline"]["outcomes"], {"pass": 1})
            self.assertEqual(result["passing_run_metrics"]["elapsed_seconds"]["baseline_median"], 3)

    def test_keeps_failed_blocked_and_unpaired_cases_visible(self):
        with TemporaryDirectory() as directory:
            baseline = Path(directory) / "baseline"
            candidate = Path(directory) / "candidate"
            cases = [
                (baseline, "style", "pass", 5),
                (baseline, "style", "fail", 900),
                (candidate, "style", "pass", 3),
                (candidate, "style", "blocked", 800),
                (baseline, "smp_region", "manual", 600),
            ]
            for index, (root, case, status, elapsed) in enumerate(cases):
                run_dir = root / str(index)
                run_dir.mkdir(parents=True)
                (run_dir / "run.json").write_text(json.dumps({
                    "case": case,
                    "variant": "baseline",
                    "checks": [{"id": "example", "status": status}],
                    "metrics": {"elapsed_seconds": elapsed, "model_requests": None},
                }), encoding="utf-8")

            region, style = compare(baseline, candidate)
            self.assertEqual(region["baseline"]["outcomes"], {"pending_manual": 1})
            self.assertEqual(region["candidate"]["runs"], 0)
            self.assertEqual(region["missing_cohorts"], ["candidate"])
            self.assertEqual(style["baseline"]["outcomes"], {"pass": 1, "fail": 1})
            self.assertEqual(style["candidate"]["outcomes"], {"pass": 1, "blocked": 1})
            self.assertEqual(style["passing_run_metrics"], {
                "elapsed_seconds": {
                    "baseline_median": 5, "baseline_samples": 1,
                    "candidate_median": 3, "candidate_samples": 1,
                },
            })

    def test_pairs_heldout_variant_separately(self):
        with TemporaryDirectory() as directory:
            baseline, candidate = (Path(directory) / name for name in ("baseline", "candidate"))
            for root, heldout_status in ((baseline, "pass"), (candidate, "fail")):
                for variant, status in (("baseline", "pass"), ("heldout", heldout_status)):
                    run_dir = root / variant
                    run_dir.mkdir(parents=True)
                    (run_dir / "run.json").write_text(json.dumps({
                        "case": "style", "variant": variant,
                        "checks": [{"id": "style", "status": status}],
                        "metrics": {"tool_calls": 2},
                    }), encoding="utf-8")

            development, heldout = compare(baseline, candidate)
            self.assertEqual(development["variant"], "baseline")
            self.assertEqual(development["candidate"]["outcomes"], {"pass": 1})
            self.assertIn("tool_calls", development["passing_run_metrics"])
            self.assertEqual(heldout["variant"], "heldout")
            self.assertEqual(heldout["baseline"]["outcomes"], {"pass": 1})
            self.assertEqual(heldout["candidate"]["outcomes"], {"fail": 1})
            self.assertEqual(heldout["passing_run_metrics"], {})
            self.assertEqual(heldout["unpaired_metrics"]["baseline_only"], ["tool_calls"])

    def test_rejects_mismatched_version_cohorts(self):
        for qgis, plugin in (("3.40", "0.9.0"), ("3.34", "0.9.1"), (None, None)):
            with self.subTest(qgis=qgis, plugin=plugin), TemporaryDirectory() as directory:
                baseline, candidate = (Path(directory) / name for name in ("baseline", "candidate"))

                def write_run(run_dir, qgis_version, plugin_version):
                    run_dir.mkdir(parents=True)
                    (run_dir / "run.json").write_text(json.dumps({
                        "case": "smp_region", "variant": "heldout",
                        "qgis_version": qgis_version, "plugin_version": plugin_version,
                        "checks": [{"id": "smp_region", "status": "pass"}],
                    }), encoding="utf-8")

                write_run(baseline / "first", "3.34", "0.9.0")
                write_run(candidate / "first", qgis, plugin)
                with self.assertRaisesRegex(ValueError, "configurations differ"):
                    compare(baseline, candidate, allow_backend_change=True)

                write_run(baseline / "second", qgis, plugin)
                with self.assertRaisesRegex(ValueError, "mixes backend, QGIS, or SMP plugin settings"):
                    compare(baseline, candidate)
