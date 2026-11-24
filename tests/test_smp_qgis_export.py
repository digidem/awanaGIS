"""Real headless QGIS SMP export tests, benchmarks, cancellation, and external validation."""

from importlib import import_module
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

smp_tools = import_module(f"{ROOT.name}.integrations.smp.tools")
smp_exporter = import_module(f"{ROOT.name}.integrations.smp.exporter")
smp_estimator = import_module(f"{ROOT.name}.integrations.smp.estimator")
AwanaPlugin = import_module(f"{ROOT.name}.plugin").AwanaGisPlugin


def setUpModule():
    global app
    app = QgsApplication.instance() or QgsApplication([], False)


def _wait_for_job(job_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = smp_tools.smp_export_status(job_id)
        if st.get("state") in ("completed", "failed", "cancelled"):
            return st
        app.processEvents()
        time.sleep(0.02)
    raise TimeoutError(f"SMP export job {job_id} did not finish within {timeout}s")


class SmpQgisExportTests(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.project.setTitle("AwanaGIS Field Map")
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))

        # 1. Styled polygon layer (SIRGAS 2000)
        self.poly_layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4674&field=name:string(40)", "territory_poly", "memory"
        )
        f_poly = QgsFeature()
        f_poly.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((-60.15 -3.15, -59.95 -3.15, -59.95 -2.95, -60.15 -2.95, -60.15 -3.15))"
            )
        )
        f_poly.setAttributes(["Terra Indigena Teste"])
        self.poly_layer.dataProvider().addFeatures([f_poly])
        self.poly_layer.updateExtents()
        fill = QgsFillSymbol.createSimple({"color": "180,225,180,180", "outline_color": "34,120,34", "outline_width": "0.6"})
        self.poly_layer.setRenderer(QgsSingleSymbolRenderer(fill))

        # 2. Styled river line layer with labels
        self.line_layer = QgsVectorLayer(
            "LineString?crs=EPSG:4674&field=name:string(40)", "rivers", "memory"
        )
        f_line = QgsFeature()
        f_line.setGeometry(
            QgsGeometry.fromWkt("LINESTRING(-60.14 -3.10, -60.05 -3.05, -59.96 -2.98)")
        )
        f_line.setAttributes(["Rio Verde"])
        self.line_layer.dataProvider().addFeatures([f_line])
        self.line_layer.updateExtents()
        line_sym = QgsLineSymbol.createSimple({"color": "20,100,220", "width": "1.2"})
        self.line_layer.setRenderer(QgsSingleSymbolRenderer(line_sym))
        pal = QgsPalLayerSettings()
        pal.fieldName = "name"
        pal.enabled = True
        self.line_layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        self.line_layer.setLabelsEnabled(True)

        # 3. Styled point layer with labels
        self.pt_layer = QgsVectorLayer(
            "Point?crs=EPSG:4674&field=name:string(40)", "monitoring_sites", "memory"
        )
        f_pt = QgsFeature()
        f_pt.setGeometry(QgsGeometry.fromWkt("POINT(-60.05 -3.05)"))
        f_pt.setAttributes(["Base 01"])
        self.pt_layer.dataProvider().addFeatures([f_pt])
        self.pt_layer.updateExtents()
        pt_sym = QgsMarkerSymbol.createSimple({"color": "220,40,40", "size": "3.5"})
        self.pt_layer.setRenderer(QgsSingleSymbolRenderer(pt_sym))
        pt_pal = QgsPalLayerSettings()
        pt_pal.fieldName = "name"
        pt_pal.enabled = True
        self.pt_layer.setLabeling(QgsVectorLayerSimpleLabeling(pt_pal))
        self.pt_layer.setLabelsEnabled(True)

        # 4. Blocked sensitive layer (must remain excluded from actual rendered tiles)
        self.secret_layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4674&field=name:string(40)", "isolated_zone", "memory"
        )
        self.secret_layer.setCustomProperty("awanagis/sensitivity", "isolated_peoples")
        f_sec = QgsFeature()
        f_sec.setGeometry(
            QgsGeometry.fromWkt("POLYGON((-60.06 -3.06, -60.04 -3.06, -60.04 -3.04, -60.06 -3.04, -60.06 -3.06))")
        )
        f_sec.setAttributes(["Secret"])
        self.secret_layer.dataProvider().addFeatures([f_sec])
        self.secret_layer.updateExtents()
        sec_fill = QgsFillSymbol.createSimple({"color": "255,0,255,255"})
        self.secret_layer.setRenderer(QgsSingleSymbolRenderer(sec_fill))

        self.project.addMapLayers([self.poly_layer, self.line_layer, self.pt_layer, self.secret_layer])
        self.tmp = tempfile.mkdtemp(prefix="test_smp_export_")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def tearDown(self):
        smp_exporter.get_export_manager().cleanup_all()
        self.project.removeAllMapLayers()

    def _run_and_validate(self, out_name, **estimate_kwargs):
        est = smp_tools.smp_estimate(output_dir=self.tmp, **estimate_kwargs)
        self.assertTrue(est["ok"], est)
        out_path = os.path.join(self.tmp, out_name)
        started = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=out_path,
            approved=True,
            approval_callback=lambda _s: True,
        )
        self.assertTrue(started["ok"], started)
        st = _wait_for_job(started["job_id"])
        self.assertEqual(st["state"], "completed", st)
        self.assertTrue(os.path.isfile(out_path))
        self.assertTrue(os.path.isfile(out_path + ".manifest.json"))

        # Check manifest does not include blocked_sensitive layer
        manifest = json.loads(Path(out_path + ".manifest.json").read_text(encoding="utf-8"))
        layer_ids = {l["id"] for l in manifest["approved_layers"]}
        self.assertNotIn(self.secret_layer.id(), layer_ids)
        self.assertIn(self.poly_layer.id(), layer_ids)

        # Full validation (including external styled-map-package Reader if available)
        val = smp_tools.smp_validate_file(out_path, run_external=True)
        self.assertTrue(val["valid"], val)
        self.assertEqual(val["tile_count"], est["tile_counts"]["total"])
        return est, st, val, out_path

    def test_three_real_smp_exports_and_external_validation(self):
        local_bounds = [-60.08, -3.08, -60.02, -3.02]
        region_bounds = [-60.15, -3.15, -59.95, -2.95]

        # 1. Tiny Local-only
        est1, st1, val1, p1 = self._run_and_validate(
            "local_only.smp",
            local_bounds=local_bounds,
            local_min_zoom=10,
            local_max_zoom=11,
            tile_format="PNG",
            sample=True,
            sample_size=4,
        )
        self.assertIn("mbtiles-source", val1["sources"])

        # Verify blocked_sensitive magenta pixels (255,0,255) were NOT rendered into tiles!
        from PIL import Image
        import io
        with zipfile.ZipFile(p1, "r") as zf:
            tile_names = [n for n in zf.namelist() if n.endswith(".png")]
            self.assertTrue(tile_names)
            for tn in tile_names:
                with Image.open(io.BytesIO(zf.read(tn))) as im:
                    rgba = im.convert("RGBA")
                    colors = rgba.getcolors(maxcolors=100000) or []
                    self.assertFalse(
                        any(rgb[:3] == (255, 0, 255) and rgb[3] > 0 for _cnt, rgb in colors),
                        f"Blocked sensitive layer leaked into rendered tile {tn}",
                    )

        # 2. Region + Local
        est2, st2, val2, _p2 = self._run_and_validate(
            "region_local.smp",
            local_bounds=local_bounds,
            local_min_zoom=10,
            local_max_zoom=11,
            include_region=True,
            region_bounds=region_bounds,
            region_min_zoom=7,
            region_max_zoom=8,
            tile_format="JPG",
            quality=80,
            sample=True,
            sample_size=6,
        )
        self.assertEqual(set(val2["sources"].keys()), {"region-detail", "local-detail"})

        # 3. World + Region + Local
        est3, st3, val3, _p3 = self._run_and_validate(
            "world_region_local.smp",
            local_bounds=local_bounds,
            local_min_zoom=10,
            local_max_zoom=11,
            include_world=True,
            world_max_zoom=1,
            include_region=True,
            region_bounds=region_bounds,
            region_min_zoom=7,
            region_max_zoom=8,
            tile_format="PNG",
            sample=True,
            sample_size=8,
        )
        self.assertEqual(
            set(val3["sources"].keys()),
            {"world-overview", "region-detail", "local-detail"},
        )

    def test_mid_export_cancellation_leaves_no_corrupt_final_file(self):
        # Moderate tile count so cancellation triggers cleanly mid-flight
        est = smp_tools.smp_estimate(
            local_bounds=[-60.15, -3.15, -59.95, -2.95],
            local_min_zoom=10,
            local_max_zoom=13,
            tile_format="PNG",
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(est["ok"])
        self.assertGreater(est["tile_counts"]["total"], 20)

        out_path = os.path.join(self.tmp, "cancelled.smp")
        started = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=out_path,
            approved=True,
            approval_callback=lambda _s: True,
        )
        self.assertTrue(started["ok"])
        time.sleep(0.05)
        cancel_res = smp_tools.smp_cancel_export(started["job_id"])
        self.assertTrue(cancel_res["ok"])
        self.assertTrue(cancel_res["cancelled"])

        st = _wait_for_job(started["job_id"])
        self.assertEqual(st["state"], "cancelled")
        self.assertFalse(os.path.exists(out_path))
        leftover_tmps = [f for f in os.listdir(self.tmp) if ".smp.tmp" in f]
        self.assertEqual(leftover_tmps, [])

    def test_isolated_snapshot_preserves_unsaved_edits_when_live_project_mutates(self):
        self.poly_layer.startEditing()
        extra = QgsFeature(self.poly_layer.fields())
        extra.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((-60.08 -3.08, -60.02 -3.08, -60.02 -3.02, -60.08 -3.02, -60.08 -3.08))"
            )
        )
        extra.setAttributes(["Unsaved Feature"])
        self.poly_layer.addFeature(extra)

        est = smp_tools.smp_estimate(
            local_bounds=[-60.08, -3.08, -60.02, -3.02],
            local_min_zoom=10,
            local_max_zoom=11,
            tile_format="PNG",
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(est["ok"], est)
        out_path = os.path.join(self.tmp, "isolated_snap.smp")

        orig_init = smp_exporter.SMPGenerator.__init__
        observed_projects = []

        def _spy_init(gen_self, feedback=None, project=None):
            observed_projects.append(project)
            return orig_init(gen_self, feedback=feedback, project=project)

        with patch.object(smp_exporter.SMPGenerator, "__init__", _spy_init):
            started = smp_tools.smp_start_export(
                plan_id=est["plan_id"],
                output_path=out_path,
                approved=True,
                approval_callback=lambda _s: True,
            )
            self.assertTrue(started["ok"], started)
            # Mutate the live project layer immediately while worker renders snapshot
            self.poly_layer.rollBack()
            st = _wait_for_job(started["job_id"])

        self.assertEqual(st["state"], "completed", st)
        self.assertTrue(os.path.isfile(out_path))
        self.assertTrue(observed_projects)
        self.assertIsNotNone(observed_projects[0])
        self.assertIsNot(observed_projects[0], self.project)

    def test_render_layer_errors_fail_export_cleanly(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.08, -3.08, -60.02, -3.02],
            local_min_zoom=10,
            local_max_zoom=10,
            tile_format="PNG",
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(est["ok"])
        out_path = os.path.join(self.tmp, "render_err.smp")
        fake_err = Mock(layerID=self.poly_layer.id(), message="Simulated provider render error")
        with patch(
            "qgis.core.QgsMapRendererCustomPainterJob.errors",
            return_value=[fake_err],
        ):
            started = smp_tools.smp_start_export(
                plan_id=est["plan_id"],
                output_path=out_path,
                approved=True,
                approval_callback=lambda _s: True,
            )
            self.assertTrue(started["ok"], started)
            st = _wait_for_job(started["job_id"])

        self.assertEqual(st["state"], "failed", st)
        self.assertIn("Simulated provider render error", st["error"])
        self.assertFalse(os.path.exists(out_path))
        self.assertFalse(os.path.exists(out_path + ".manifest.json"))

    def test_cancel_during_validation_prevents_publish(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.08, -3.08, -60.02, -3.02],
            local_min_zoom=10,
            local_max_zoom=10,
            tile_format="PNG",
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(est["ok"])
        out_path = os.path.join(self.tmp, "cancel_val.smp")
        orig_validate = smp_exporter.validate_file
        started_holder = {}

        def _cancelling_validate(path, run_external=False):
            res = orig_validate(path, run_external=run_external)
            smp_tools.smp_cancel_export(started_holder["job_id"])
            return res

        with patch.object(smp_exporter, "validate_file", side_effect=_cancelling_validate):
            started = smp_tools.smp_start_export(
                plan_id=est["plan_id"],
                output_path=out_path,
                approved=True,
                approval_callback=lambda _s: True,
            )
            started_holder["job_id"] = started["job_id"]
            self.assertTrue(started["ok"], started)
            st = _wait_for_job(started["job_id"])

        self.assertEqual(st["state"], "cancelled", st)
        self.assertFalse(os.path.exists(out_path))
        self.assertFalse(os.path.exists(out_path + ".manifest.json"))

    def test_plugin_unload_cleans_up_exports(self):
        iface = Mock()
        plugin = AwanaPlugin(iface)
        with patch.object(smp_exporter.get_export_manager(), "cleanup_all") as mock_clean:
            plugin.unload()
            mock_clean.assert_called_once()

    def test_sample_fixture_validates(self):
        fixture = ROOT / "tests" / "fixtures" / "smp" / "sample_local_only.smp"
        if not fixture.exists():
            self.skipTest("Sample fixture not yet generated")
        val = smp_tools.smp_validate_file(str(fixture), run_external=True)
        self.assertTrue(val["valid"], val)
        self.assertLess(fixture.stat().st_size, 50 * 1024)


if __name__ == "__main__":
    unittest.main()
