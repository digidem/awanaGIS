"""Compare two collections of QGIS eval run reports."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median


def _apply_review(path, report):
    review_path = path.with_name("manual_checks.json")
    if not review_path.exists():
        return
    review = json.loads(review_path.read_text(encoding="utf-8"))
    pending = {check["id"]: check for check in report["checks"] if check["status"] == "manual"}
    for check_id, result in review.items():
        if (check_id == "workflow" or check_id not in pending or result["status"] not in {"pass", "fail"}
                or not result["detail"].strip()):
            raise ValueError(f"{review_path}: invalid manual review for {check_id}")
        pending[check_id].update(status=result["status"], detail=result["detail"])
    if "workflow" in pending:
        components = [check for check in report["checks"] if check["id"] != "workflow"]
        pending["workflow"]["status"] = _outcome({**report, "checks": components}).replace("pending_manual", "manual")


def _group_reports(directory):
    grouped = defaultdict(list)
    for path in sorted(directory.rglob("run.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        _apply_review(path, report)
        grouped[report["case"], report["variant"]].append(report)
    if not grouped:
        raise ValueError(f"No run.json reports found in {directory}")
    return grouped


def _outcome(report):
    statuses = {check["status"] for check in report["checks"]}
    if "fail" in statuses or report.get("status") in {"failed", "error", "timeout"}:
        return "fail"
    if "blocked" in statuses or report.get("status") == "blocked":
        return "blocked"
    if "manual" in statuses:
        return "pending_manual"
    if "pass" in statuses:
        return "pass"
    return "ungraded"


def _summarize(reports):
    outcomes = Counter(_outcome(report) for report in reports)
    checks = defaultdict(Counter)
    for report in reports:
        for check in report["checks"]:
            checks[check["id"]][check["status"]] += 1
    return {"runs": len(reports), "outcomes": dict(outcomes),
            "checks": {name: dict(counts) for name, counts in sorted(checks.items())}}


def _performance(reports):
    samples = defaultdict(list)
    for report in reports:
        if _outcome(report) == "pass":
            metrics = {**report.get("timing", {}), **report.get("metrics", {})}
            for metric, value in metrics.items():
                if type(value) in (int, float):
                    samples[metric].append(value)
    return samples


def _configuration(reports):
    configurations = {
        (report.get("qgis_version"), report.get("plugin_version"))
        for report in reports
        if report.get("qgis_version") is not None or report.get("status") not in {"blocked", "error", "timeout"}
    }
    backends = {json.dumps(report.get("backend"), sort_keys=True) for report in reports}
    if len(configurations) > 1 or len(backends) > 1:
        raise ValueError("A comparison group mixes backend, QGIS, or SMP plugin settings")
    return next(iter(backends), None), next(iter(configurations), None)


def compare(baseline_dir, candidate_dir, allow_backend_change=False):
    baseline = _group_reports(baseline_dir)
    candidate = _group_reports(candidate_dir)
    result = []
    for case, variant in sorted(baseline.keys() | candidate.keys()):
        before = baseline.get((case, variant), [])
        after = candidate.get((case, variant), [])
        before_backend, before_config = _configuration(before)
        after_backend, after_config = _configuration(after)
        qgis_changed = before_config and after_config and before_config != after_config
        backend_changed = before_backend and after_backend and before_backend != after_backend
        if qgis_changed or (backend_changed and not allow_backend_change):
            raise ValueError(f"{case}/{variant}: baseline and candidate configurations differ")
        left, right = _performance(before), _performance(after)
        shared = left.keys() & right.keys()
        result.append({
            "case": case, "variant": variant,
            "baseline": _summarize(before), "candidate": _summarize(after),
            "missing_cohorts": [name for name, reports in (("baseline", before), ("candidate", after))
                                if not reports],
            "unpaired_metrics": {"baseline_only": sorted(left.keys() - shared),
                                 "candidate_only": sorted(right.keys() - shared)},
            "passing_run_metrics": {
                metric: {
                    "baseline_median": median(left[metric]), "baseline_samples": len(left[metric]),
                    "candidate_median": median(right[metric]), "candidate_samples": len(right[metric]),
                }
                for metric in sorted(shared)
            },
        })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--allow-backend-change", action="store_true",
                        help="Compare different pinned backends or models intentionally")
    args = parser.parse_args(argv)
    try:
        result = compare(args.baseline, args.candidate, args.allow_backend_change)
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
