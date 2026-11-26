"""Offline checks for the cases that replay a user's instructions over several turns."""

from contextlib import contextmanager
from importlib import import_module
import json
from pathlib import Path
import sys
import tempfile
import unittest

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
PACKAGE = ROOT.name
build_fixture = import_module(f"{PACKAGE}.evals.qgis_agent.fixtures").build_fixture
camps_plan = import_module(f"{PACKAGE}.evals.qgis_agent.fixtures")._camps_plan
checks = import_module(f"{PACKAGE}.evals.qgis_agent.checks")
run_case = import_module(f"{PACKAGE}.evals.qgis_agent.runner").run_case


def write_points(path, points, type_key="tipo de acampamento"):
    features = [
        {"type": "Feature",
         "properties": {type_key: kind} if kind else {},
         "geometry": {"type": "Point", "coordinates": [x, y]}}
        for x, y, kind in points
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
                    encoding="utf-8")


def load(project, path):
    layer = QgsVectorLayer(str(path), path.stem, "ogr")
    assert layer.isValid(), path
    project.addMapLayer(layer)
    return layer


def state_for(project, extra=""):
    """A workspace state text that agrees with the project, plus optional extra lines."""
    lines = ["## Workspace State", f"### Layers ({len(project.mapLayers())})"]
    for layer in project.mapLayers().values():
        count = layer.featureCount() if isinstance(layer, QgsVectorLayer) else None
        lines.append(f"- {layer.name()} (id={layer.id()}, type=vector)"
                     + (f" features={count}" if count is not None else ""))
    return "\n".join(lines + ([extra] if extra else []))


class SessionCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        cls.app.initQgis()

    @contextmanager
    def scenario(self, case_id, variant="baseline"):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            fixture = build_fixture(case_id, run_dir, variant)
            project = QgsProject.instance()
            project.clear()
            try:
                self.assertTrue(project.read(str(fixture.project_path)))
                yield fixture, project, run_dir
            finally:
                project.clear()

    def statuses(self, fixture, project, turns):
        return {check["id"]: check for check in checks.evaluate(fixture, project, {"turns": turns})}

    def test_camps_fixture_keeps_the_camps_of_the_similar_area(self):
        for variant, final_count in (("baseline", 6), ("heldout", 5)):
            with self.scenario("camps_merge", variant) as (fixture, _project, _run_dir):
                self.assertEqual(len(fixture.expected_derived), 8)
                self.assertEqual(len(fixture.expected_final), final_count)
                self.assertEqual(fixture.turns, tuple(turn for turn in fixture.turns if turn))
                self.assertEqual(len(fixture.area_names), 2)
                self.assertTrue(fixture.area_names[1].startswith(fixture.area_names[0]))
                target = tuple(value + (0.04 if variant == "heldout" else 0.0)
                               for value in camps_plan(variant)["areas"][0][1])
                inside = [point for point in fixture.expected_derived if target[0] <= point[0] <= target[2]
                          and target[1] <= point[1] <= target[3]]
                self.assertTrue(inside, "the named area must hold camps to remove")
                self.assertFalse({(x, y) for x, y, _ in inside} & {(x, y) for x, y, _ in fixture.expected_final})
                self.assertEqual({(x, y) for x, y, _ in fixture.expected_derived} - {(x, y) for x, y, _ in inside},
                                 {(x, y) for x, y, _ in fixture.expected_final})
                kinds = {kind for _, _, kind in fixture.expected_final}
                self.assertIn("demarcação", kinds)
                self.assertLessEqual(kinds, {"demarcação", "não informado", "vigilância"})
        self.assertNotEqual(camps_plan("baseline")["layer_names"], camps_plan("heldout")["layer_names"])

    def test_camps_pass_when_the_file_follows_each_instruction(self):
        for variant in ("baseline", "heldout"):
            with self.scenario("camps_merge", variant) as (fixture, project, run_dir):
                path = fixture.input_files[0].parent / fixture.derived_file
                write_points(path, fixture.expected_derived)
                layer = load(project, path)
                turns = [{}, {"observed": checks.observe_run(fixture, project, run_dir)}, {}]
                write_points(path, fixture.expected_final)
                layer.reload()
                turns.append({"observed": checks.observe_run(fixture, project, run_dir),
                              "workspace_state": state_for(project)})
                results = self.statuses(fixture, project, turns)
                self.assertEqual({name: check["status"] for name, check in results.items()}, {
                    "camps_saved": "pass", "camps_final": "pass", "camps_sources": "pass",
                    "workspace_state": "pass", "camps_merge": "pass"}, results)

    def test_camps_fail_when_the_similar_area_is_also_removed(self):
        with self.scenario("camps_merge") as (fixture, project, run_dir):
            path = fixture.input_files[0].parent / fixture.derived_file
            decoy = next(point for point in fixture.expected_final if point[2] == "vigilância")
            write_points(path, [point for point in fixture.expected_final if point != decoy])
            turns = [{}, {}, {}, {"observed": checks.observe_run(fixture, project, run_dir)}]
            final = self.statuses(fixture, project, turns)["camps_final"]
            self.assertEqual(final["status"], "fail")
            self.assertIn(f"no point at ({decoy[0]:g}, {decoy[1]:g})", final["detail"])

    def test_camps_fail_on_wrong_types_a_missing_layer_and_an_edited_source(self):
        with self.scenario("camps_merge") as (fixture, project, run_dir):
            path = fixture.input_files[0].parent / fixture.derived_file
            demarcation = next(point for point in fixture.expected_final if point[2] == "demarcação")
            wrong = [((x, y, "não informado") if kind == "demarcação" else (x, y, kind))
                     for x, y, kind in fixture.expected_final]
            write_points(path, wrong)
            source = fixture.input_files[0]
            source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            turns = [{}, {"observed": checks.observe_run(fixture, project, run_dir)}, {}, {}]
            turns.append({"observed": checks.observe_run(fixture, project, run_dir),
                          "workspace_state": state_for(project)})
            results = self.statuses(fixture, project, turns)
            self.assertEqual(results["camps_saved"]["status"], "fail")
            self.assertIn("no project layer is loaded", results["camps_saved"]["detail"])
            self.assertEqual(results["camps_final"]["status"], "fail")
            self.assertIn(f"({demarcation[0]:g}, {demarcation[1]:g}) is 'não informado', expected 'demarcação'",
                          results["camps_final"]["detail"])
            self.assertEqual(results["camps_sources"]["status"], "fail")
            self.assertEqual(results["camps_merge"]["status"], "fail")

    def test_a_project_layer_that_did_not_reload_its_file_is_reported(self):
        with self.scenario("camps_merge") as (fixture, project, run_dir):
            path = fixture.input_files[0].parent / fixture.derived_file
            write_points(path, fixture.expected_derived)
            layer = load(project, path)
            write_points(path, fixture.expected_final)
            turns = [{}, {}, {}, {"observed": checks.observe_run(fixture, project, run_dir),
                                  "workspace_state": state_for(project)}]
            final = self.statuses(fixture, project, turns)["camps_final"]
            self.assertEqual(layer.featureCount(), len(fixture.expected_derived), "the layer still serves old features")
            self.assertEqual(final["status"], "fail")
            self.assertIn(f"shows {len(fixture.expected_derived)} features while its file holds "
                          f"{len(fixture.expected_final)}", final["detail"])

    def test_layer_keep_passes_when_the_file_survives_the_removal(self):
        for variant in ("baseline", "heldout"):
            with self.scenario("layer_keep", variant) as (fixture, project, run_dir):
                path = fixture.input_files[0].parent / fixture.derived_file
                self.assertEqual(len(fixture.expected_derived), 2)
                write_points(path, fixture.expected_derived)
                layer = load(project, path)
                turns = [{"observed": checks.observe_run(fixture, project, run_dir)}]
                removed_id = layer.id()
                project.removeMapLayer(removed_id)
                turns.append({"observed": checks.observe_run(fixture, project, run_dir)})
                turns.append({"observed": checks.observe_run(fixture, project, run_dir),
                              "workspace_state": state_for(project)})
                results = self.statuses(fixture, project, turns)
                self.assertEqual({name: check["status"] for name, check in results.items()}, {
                    "kept_saved": "pass", "kept_file": "pass", "kept_unloaded": "pass",
                    "workspace_state": "pass", "layer_keep": "pass"}, results)

    def test_layer_keep_fails_when_the_removal_deletes_the_file(self):
        with self.scenario("layer_keep") as (fixture, project, run_dir):
            path = fixture.input_files[0].parent / fixture.derived_file
            write_points(path, fixture.expected_derived)
            layer = load(project, path)
            turns = [{"observed": checks.observe_run(fixture, project, run_dir)}]
            ghost = f"- {layer.name()} (id={layer.id()}, type=vector) features=2 crs=EPSG:4326"
            project.removeMapLayer(layer.id())
            path.unlink()
            turns.append({"observed": checks.observe_run(fixture, project, run_dir)})
            turns.append({"observed": checks.observe_run(fixture, project, run_dir),
                          "workspace_state": state_for(project, ghost)})
            results = self.statuses(fixture, project, turns)
            self.assertEqual(results["kept_saved"]["status"], "pass")
            self.assertEqual(results["kept_file"]["status"], "fail")
            self.assertIn("was deleted after its layer was removed", results["kept_file"]["detail"])
            self.assertEqual(results["workspace_state"]["status"], "fail")
            self.assertIn("is no longer in the project", results["workspace_state"]["detail"])
            self.assertEqual(results["layer_keep"]["status"], "fail")

    def test_layer_keep_fails_when_the_layer_stays_or_nothing_was_created(self):
        with self.scenario("layer_keep") as (fixture, project, run_dir):
            path = fixture.input_files[0].parent / fixture.derived_file
            write_points(path, fixture.expected_derived)
            load(project, path)
            observed = checks.observe_run(fixture, project, run_dir)
            turns = [{"observed": observed}, {"observed": observed},
                     {"observed": observed, "workspace_state": state_for(project)}]
            results = self.statuses(fixture, project, turns)
            self.assertEqual(results["kept_unloaded"]["status"], "fail")
            self.assertIn("is still in the project", results["kept_unloaded"]["detail"])
            empty = [{"observed": {}}] * 3
            results = self.statuses(fixture, project, empty)
            self.assertTrue(all(check["status"] == "fail" for check in results.values()), results)

    def test_workspace_state_flags_a_stale_feature_count(self):
        with self.scenario("layer_keep") as (fixture, project, run_dir):
            layer = next(iter(project.mapLayers().values()))
            stale = state_for(project).replace(f"id={layer.id()}, type=vector) features={layer.featureCount()}",
                                               f"id={layer.id()}, type=vector) features={layer.featureCount() + 1}")
            self.assertNotEqual(stale, state_for(project))
            turn = {"workspace_state": stale}
            result = checks._workspace_state_check(turn, project)
            self.assertEqual(result["status"], "fail")
            self.assertIn(f"{layer.name()} is listed with {layer.featureCount() + 1} features", result["detail"])
            self.assertEqual(checks._workspace_state_check({}, project)["status"], "fail")

    def test_runner_records_file_layers_and_state_after_each_turn(self):
        class Backend:
            def __init__(self, config, toolkit, executor):
                pass

            def send(self, message, history, emit, should_stop):
                emit(import_module(f"{PACKAGE}.backends.base").AgentEvent(
                    import_module(f"{PACKAGE}.backends.base").EventType.TEXT, {"text": "pronto"}))
                return history + [message]

        with tempfile.TemporaryDirectory() as directory:
            for case_id, variant in (("camps_merge", "heldout"), ("layer_keep", "baseline")):
                trace = run_case(case_id, Path(directory) / case_id, "offline", "fake", variant=variant,
                                 backend_factory=Backend)
                self.assertEqual(len(trace["turns"]), 4 if case_id == "camps_merge" else 3)
                for turn in trace["turns"]:
                    self.assertIn("observed", turn)
                    self.assertIn("### Layers", turn["workspace_state"])
                self.assertIn(case_id, [check["id"] for check in trace["checks"]])
                self.assertIn("workspace_state", [check["id"] for check in trace["checks"]])
            trace = run_case("load", Path(directory) / "load", "offline", "fake", backend_factory=Backend)
            self.assertNotIn("observed", trace["turns"][0])


if __name__ == "__main__":
    unittest.main()
