"""Focused regression tests for deterministic QGIS agent evaluation fixtures."""

import importlib
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile

from qgis.core import QgsApplication, QgsProject


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
PACKAGE = ROOT.name
build_fixture = importlib.import_module(f"{PACKAGE}.evals.qgis_agent.fixtures").build_fixture
evaluate = importlib.import_module(f"{PACKAGE}.evals.qgis_agent.checks").evaluate
checks_module = importlib.import_module(f"{PACKAGE}.evals.qgis_agent.checks")


class QgisEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        cls.app.initQgis()

    def fixture(self, case_id):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return build_fixture(case_id, Path(temp.name))

    def read_project(self, fixture):
        project = QgsProject()
        self.assertTrue(project.read(str(fixture.project_path)))
        return project

    def test_load_case_starts_empty_and_exposes_synthetic_attachments(self):
        fixture = self.fixture("load")
        project = self.read_project(fixture)
        self.assertEqual(project.mapLayers(), {})
        self.assertEqual(len(fixture.input_files), 3)
        self.assertTrue(all(path.is_file() for path in fixture.input_files))
        self.assertEqual(fixture.turns, ("Abre esses arquivos e me explica o que tem neles.",))

    def test_workflow_preloads_only_local_raster(self):
        fixture = self.fixture("workflow")
        project = self.read_project(fixture)
        self.assertEqual([layer.name() for layer in project.mapLayers().values()], ["Fundo sintético"])
        self.assertEqual(fixture.turns[-1], "Quero só o território inteiro, sem uma área com mais detalhe.")

    def test_heldout_fixture_changes_names_and_join_keys(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        baseline = build_fixture("dedup", Path(temp.name) / "baseline")
        heldout = build_fixture("dedup", Path(temp.name) / "heldout", "heldout")
        self.assertEqual(baseline.expected_unique_codes, ("A1", "A2", "A3"))
        self.assertEqual(heldout.expected_unique_codes, ("B11", "B12", "B13"))
        self.assertNotEqual(baseline.expected_village_names, heldout.expected_village_names)

    def test_crs_view_requires_projected_extent_and_expected_visible_layers(self):
        fixture = self.fixture("crs_view")
        project = self.read_project(fixture)
        self.assertEqual(project.crs().authid(), "EPSG:3857")
        initial = {
            "canvas_state_after_turn": {
                "extent": list(fixture.initial_view_bounds),
                "layer_ids": list(fixture.expected_visible_layer_ids),
            },
        }
        self.assertEqual(evaluate(fixture, project, initial)[0]["status"], "fail")
        result = evaluate(fixture, project, {
            "canvas_state_after_turn": {
                "extent": list(fixture.expected_view_bounds),
                "layer_ids": list(fixture.expected_visible_layer_ids),
            },
        })[0]
        self.assertEqual(result["status"], "pass")

    def test_selection_case_checks_current_selection_without_changing_it(self):
        fixture = self.fixture("selection")
        project = self.read_project(fixture)
        layer = next(layer for layer in project.mapLayers().values() if layer.name().startswith("Aldeias"))
        selected_ids = [feature.id() for feature in layer.getFeatures() if feature["codigo"] in fixture.preselected_codes]
        layer.selectByIds(selected_ids)
        reply = "As aldeias selecionadas são " + " e ".join(fixture.expected_village_names[::2]) + "."
        result = evaluate(fixture, project, {"turns": [{"reply": reply}]})[0]
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(layer.selectedFeatureIds()), 2)

    def test_category_split_requires_two_correct_iconized_layers(self):
        from qgis.core import QgsFeature, QgsGeometry, QgsMarkerSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

        fixture = self.fixture("category_split")
        project = self.read_project(fixture)
        for name, school, codes, icon in (
            ("Com escola", "sim", fixture.expected_selected_codes, "circle"),
            ("Sem escola", "não", ("A2",), "square"),
        ):
            layer = QgsVectorLayer(
                "Point?crs=EPSG:4326&field=codigo:string&field=nome:string&field=escola:string",
                name,
                "memory",
            )
            features = []
            for code in codes:
                source_feature = next(
                    feature for source in project.mapLayers().values()
                    if source.name().startswith("Aldeias")
                    for feature in source.getFeatures()
                    if feature["codigo"] == code
                )
                feature = QgsFeature(layer.fields())
                feature.setGeometry(QgsGeometry.fromPointXY(source_feature.geometry().asPoint()))
                feature.setAttributes([code, source_feature["nome"], school])
                features.append(feature)
            layer.dataProvider().addFeatures(features)
            layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": icon})))
            project.addMapLayer(layer)
        self.assertEqual(evaluate(fixture, project, {})[0]["status"], "pass")

    def test_dedup_requires_unique_codes_and_unchanged_source(self):
        from qgis.core import QgsFeature, QgsVectorLayer

        fixture = self.fixture("dedup")
        project = self.read_project(fixture)
        output = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=codigo:string&field=nome:string&field=escola:string",
            "Aldeias sem duplicatas",
            "memory",
        )
        original = next(layer for layer in project.mapLayers().values() if layer.name().startswith("Aldeias"))
        features = []
        seen = set()
        for source_feature in original.getFeatures():
            if source_feature["codigo"] in seen:
                continue
            seen.add(source_feature["codigo"])
            feature = QgsFeature(output.fields())
            feature.setGeometry(source_feature.geometry())
            feature.setAttributes([source_feature["codigo"], source_feature["nome"], source_feature["escola"]])
            features.append(feature)
        output.dataProvider().addFeatures(features)
        project.addMapLayer(output)
        self.assertEqual(evaluate(fixture, project, {})[0]["status"], "pass")
        duplicate = QgsFeature(output.fields())
        duplicate.setGeometry(features[0].geometry())
        duplicate.setAttributes(features[0].attributes())
        output.dataProvider().addFeature(duplicate)
        self.assertEqual(evaluate(fixture, project, {})[0]["status"], "fail")

    def test_ambiguous_fixture_has_two_territories_and_requires_clarification(self):
        fixture = self.fixture("smp_ambiguous")
        project = self.read_project(fixture)
        territory = next(layer for layer in project.mapLayers().values() if layer.name() == "Territórios")
        self.assertEqual(territory.featureCount(), 2)
        result = evaluate(fixture, project, {"turns": [{"reply": "Qual território você quer incluir no mapa?"}]})[0]
        self.assertEqual((result["id"], result["status"]), ("smp_ambiguous", "pass"))

    def test_ambiguous_case_does_not_accept_generic_number_as_clarification(self):
        fixture = self.fixture("smp_ambiguous")
        result = evaluate(fixture, self.read_project(fixture), {"turns": [{"reply": "O mapa tem 2 aldeias."}]})[0]
        self.assertEqual(result["status"], "fail")

    def test_load_grader_requires_counts_attached_to_layer_meanings(self):
        fixture = self.fixture("load")
        project = self.read_project(fixture)
        reply = "Arumã tem 3 escolas e o mapa tem 1 cor."
        result = evaluate(fixture, project, {"turns": [{"reply": reply}]})[0]
        self.assertEqual(result["status"], "fail")

    def test_basemap_claim_without_project_layer_is_not_a_pass(self):
        fixture = self.fixture("basemap")
        project = self.read_project(fixture)
        result = evaluate(fixture, project, {"turns": [{"reply": "Google Satellite foi selecionado."}]})[0]
        self.assertEqual(result["status"], "fail")

    def test_pdf_header_without_export_linkage_remains_manual(self):
        fixture = self.fixture("pdf")
        project = self.read_project(fixture)
        pdf = fixture.output_dir / "blank.pdf"
        pdf.write_bytes(b"%PDF-1.7\nblank")
        result = evaluate(fixture, project, {"artifacts": [str(pdf)]})[0]
        self.assertEqual(result["status"], "manual")

    def test_pdf_basemap_without_first_export_snapshot_blocks_if_order_is_ambiguous(self):
        fixture = self.fixture("pdf_basemap")
        project = self.read_project(fixture)
        for name in ("first.pdf", "second.pdf"):
            (fixture.output_dir / name).write_bytes(b"%PDF-1.7\nsynthetic")
        result = evaluate(fixture, project, {})[0]
        self.assertEqual(result["status"], "blocked")

    def test_pdf_outside_symlinked_output_directory_is_not_graded(self):
        fixture = self.fixture("pdf")
        outside = fixture.output_dir.with_name("other")
        outside.mkdir()
        (outside / "mapa.pdf").write_bytes(b"%PDF-1.7\n")
        fixture.output_dir.rmdir()
        fixture.output_dir.symlink_to(outside, target_is_directory=True)
        result, = evaluate(fixture, self.read_project(fixture), {"artifacts": ["mapa.pdf"]})
        self.assertEqual(result["status"], "fail")

    def test_smp_first_turn_artifact_is_premature(self):
        trace = {"turns": [{"artifacts": ["mapa.smp"]}, {"artifacts": []}]}
        self.assertTrue(checks_module._premature_smp_export(trace))

    def test_linked_blank_pdf_without_layout_map_fails(self):
        fixture = self.fixture("pdf")
        project = self.read_project(fixture)
        pdf = fixture.output_dir / "blank.pdf"
        pdf.write_bytes(b"%PDF-1.7\nblank")
        result = evaluate(
            fixture,
            project,
            {"artifacts": [str(pdf)], "pdf_exports": [{"layout_id": "Blank", "output": pdf.name}]},
        )[0]
        self.assertEqual(result["status"], "fail")
        self.assertIn("absent from", result["detail"].casefold())

    def test_first_pdf_must_include_local_raster_layer(self):
        from qgis.core import (
            QgsLayoutItemLegend,
            QgsLayoutItemMap,
            QgsLayoutItemScaleBar,
            QgsPrintLayout,
        )

        fixture = self.fixture("pdf_basemap")
        project = self.read_project(fixture)
        raster = next(layer for layer in project.mapLayers().values() if layer.name() == "Fundo sintético")
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName("Mapa com fundo local")
        map_item = QgsLayoutItemMap(layout)
        layout.addLayoutItem(map_item)
        map_item.setLayers([raster])
        scale_bar = QgsLayoutItemScaleBar(layout)
        scale_bar.setLinkedMap(map_item)
        layout.addLayoutItem(scale_bar)
        layout.addLayoutItem(QgsLayoutItemLegend(layout))
        project.layoutManager().addLayout(layout)
        pdf = fixture.output_dir / "mapa.pdf"
        pdf.write_bytes(b"%PDF-1.7\nsynthetic")
        capture = {
            "output": pdf.name,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "map_layer_ids": [list(fixture.expected_visible_layer_ids)],
            "has_scale_bar": True,
            "has_legend": True,
        }
        result = evaluate(fixture, project, {"artifacts": [str(pdf)], "first_pdf_export": capture})[0]
        self.assertEqual(result["status"], "manual")
        map_item.setLayers([])
        capture["map_layer_ids"] = [[]]
        result = evaluate(fixture, project, {"artifacts": [str(pdf)], "first_pdf_export": capture})[0]
        self.assertEqual(result["status"], "fail")

    def test_smp_wrong_territory_bounds_fail_before_tile_coverage(self):
        fixture = self.fixture("smp_territory")
        project = self.read_project(fixture)
        wrong_bounds = [fixture.territory_bounds[0] + 1, *fixture.territory_bounds[1:]]
        style = {
            "version": 8,
            "sources": {
                "world-overview": {
                    "name": "World Overview", "type": "raster", "format": "png", "minzoom": 0, "maxzoom": 5,
                    "bounds": [-180.0, -85.0511, 180.0, 85.0511],
                    "tiles": ["smp://maps.v1/s/0/{z}/{x}/{y}.png"],
                },
                "local-detail": {
                    "name": "Local Detail", "type": "raster", "format": "png", "minzoom": 6, "maxzoom": 11,
                    "bounds": wrong_bounds,
                    "tiles": ["smp://maps.v1/s/2/{z}/{x}/{y}.png"],
                },
            },
            "layers": [{"id": "background", "type": "background"}],
        }
        package = fixture.output_dir / "wrong-extent.smp"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("style.json", json.dumps(style))
            archive.writestr("VERSION", "1.0")
            for zoom in range(6):
                archive.writestr(f"s/0/{zoom}/0/0.png", b"tile")
            for zoom in range(6, 12):
                archive.writestr(f"s/2/{zoom}/0/0.png", b"tile")
        result = evaluate(fixture, project, {"artifacts": [str(package)]})[0]
        self.assertEqual(result["status"], "fail")
        self.assertIn("bounds", result["detail"].casefold())


if __name__ == "__main__":
    unittest.main()
