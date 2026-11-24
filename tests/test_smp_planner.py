"""Tests for SMP region planning, CRS handling, tile math, and calibration."""

from importlib import import_module
from pathlib import Path
import sys
import unittest

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

smp_tools = import_module(f"{ROOT.name}.integrations.smp.tools")
smp_planner = import_module(f"{ROOT.name}.integrations.smp.planner")
smp_estimator = import_module(f"{ROOT.name}.integrations.smp.estimator")
SMPGenerator = import_module(f"{ROOT.name}.integrations.smp.vendor.comapeo_smp_generator").SMPGenerator


def setUpModule():
    global app
    app = QgsApplication.instance() or QgsApplication([], False)


class SmpPlannerTests(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))

        self.layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4674&field=name:string(40)", "territory", "memory"
        )
        pr = self.layer.dataProvider()
        # ~0.12 deg box in Amazon
        poly1 = QgsFeature()
        poly1.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((-60.12 -3.12, -60.00 -3.12, -60.00 -3.00, -60.12 -3.00, -60.12 -3.12))"
            )
        )
        poly1.setAttributes(["TI Sample"])

        poly2 = QgsFeature()
        poly2.setGeometry(
            QgsGeometry.fromWkt(
                "POLYGON((-60.08 -3.08, -60.04 -3.08, -60.04 -3.04, -60.08 -3.04, -60.08 -3.08))"
            )
        )
        poly2.setAttributes(["Focus Zone"])
        pr.addFeatures([poly1, poly2])
        self.layer.updateExtents()
        self.project.addMapLayer(self.layer)

    def tearDown(self):
        self.project.removeAllMapLayers()
        smp_estimator.get_plan_registry().clear()

    def test_exact_xyz_tile_math_matches_generator(self):
        bounds = [-60.12, -3.12, -60.00, -3.00]
        region_bounds = [-60.20, -3.20, -59.90, -2.90]
        res = smp_tools.smp_estimate(
            local_bounds=bounds,
            local_min_zoom=10,
            local_max_zoom=12,
            include_world=True,
            world_max_zoom=2,
            include_region=True,
            region_bounds=region_bounds,
            region_min_zoom=6,
            region_max_zoom=8,
            sample=False,
        )
        self.assertTrue(res["ok"], res)

        gen = SMPGenerator()
        local_rect = smp_planner.wgs84_bounds_to_project_rect(bounds, self.project)
        region_rect = smp_planner.wgs84_bounds_to_project_rect(region_bounds, self.project)
        expected = gen._build_export_plan(
            local_rect,
            10,
            12,
            include_world_base_zooms=True,
            world_max_zoom=2,
            include_region=True,
            region_extent=region_rect,
            region_min_zoom=6,
            region_max_zoom=8,
        )
        self.assertEqual(res["tile_counts"]["total"], expected["total_tiles"])
        self.assertEqual(res["tile_counts"]["world"], expected["sources"][0]["total_tiles"])
        self.assertEqual(res["tile_counts"]["region"], expected["sources"][1]["total_tiles"])
        self.assertEqual(res["tile_counts"]["local"], expected["sources"][2]["total_tiles"])
        self.assertEqual(res["tile_counts"]["world"], 1 + 4 + 16)

    def test_uncalibrated_vs_sampled_estimation(self):
        bounds = [-60.10, -3.10, -60.02, -3.02]
        rough = smp_tools.smp_estimate(
            local_bounds=bounds,
            local_min_zoom=10,
            local_max_zoom=11,
            tile_format="PNG",
            sample=False,
        )
        self.assertTrue(rough["ok"])
        self.assertEqual(rough["calibration"], "uncalibrated_rough")
        self.assertEqual(rough["estimated_archive_bytes"]["calibration"], "uncalibrated_rough")
        self.assertIsNone(rough["estimated_runtime_seconds"]["likely"])
        self.assertEqual(rough["estimated_runtime_seconds"]["calibration"], "unknown")
        self.assertIsNone(rough["sample_stats"])

        sampled = smp_tools.smp_estimate(
            local_bounds=bounds,
            local_min_zoom=10,
            local_max_zoom=13,
            tile_format="PNG",
            sample=True,
            sample_size=6,
        )
        self.assertTrue(sampled["ok"], sampled)
        self.assertEqual(sampled["calibration"], "sampled")
        self.assertEqual(sampled["estimated_archive_bytes"]["calibration"], "sampled")
        self.assertGreater(sampled["estimated_archive_bytes"]["low"], 0)
        self.assertLessEqual(
            sampled["estimated_archive_bytes"]["low"],
            sampled["estimated_archive_bytes"]["likely"],
        )
        self.assertLessEqual(
            sampled["estimated_archive_bytes"]["likely"],
            sampled["estimated_archive_bytes"]["high"],
        )
        self.assertGreater(sampled["estimated_runtime_seconds"]["likely"], 0)
        self.assertEqual(sampled["sample_stats"]["count"], 6)

        # When total_tiles < sample_size, sample count caps cleanly at total_tiles
        tiny_sampled = smp_tools.smp_estimate(
            local_bounds=bounds,
            local_min_zoom=10,
            local_max_zoom=11,
            tile_format="PNG",
            sample=True,
            sample_size=6,
        )
        self.assertTrue(tiny_sampled["ok"], tiny_sampled)
        self.assertEqual(tiny_sampled["sample_stats"]["count"], tiny_sampled["tile_counts"]["total"])

    def test_suggest_regions_selection_and_budget(self):
        # Select only the smaller inner polygon
        feats = [f for f in self.layer.getFeatures() if f["name"] == "Focus Zone"]
        self.layer.selectByIds([feats[0].id()])

        res = smp_tools.smp_suggest_regions(
            area_reference={"type": "layer", "layer_id": self.layer.id()},
            local_reference={"type": "selection", "layer_id": self.layer.id()},
            constraints={"target_size_mb": 5.0, "preferred_format": "JPG"},
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(res["candidates"]), 3)
        names = [c["name"] for c in res["candidates"]]
        self.assertEqual(names, ["Compact", "Balanced", "Detailed"])

        for cand in res["candidates"]:
            self.assertFalse(cand["include_world"])
            self.assertTrue(cand["include_region"])
            reg_b = cand["coverage"]["region"]["bounds_wgs84"]
            loc_b = cand["coverage"]["local"]["bounds_wgs84"]
            self.assertTrue(SMPGenerator._extent_contains_bounds(reg_b, loc_b))
            self.assertEqual(cand["provisional_estimate"]["calibration"], "uncalibrated_rough")
            self.assertIn("bounds_3857", cand["coverage"]["local"])

    def test_latitude_clamping_polar_and_antimeridian_rejection(self):
        # Partial >85.05112878° latitude -> clamped with warning
        warn_res = smp_tools.smp_estimate(
            local_bounds=[-10.0, 80.0, 10.0, 88.0],
            local_min_zoom=2,
            local_max_zoom=3,
            sample=False,
        )
        self.assertTrue(warn_res["ok"], warn_res)
        self.assertEqual(warn_res["effective_config"]["local_bounds_wgs84"][3], 85.0511)
        self.assertTrue(any("85.0511" in w for w in warn_res["warnings"]))

        # Pure polar -> rejected
        polar = smp_tools.smp_estimate(
            local_bounds=[-10.0, 86.0, 10.0, 89.0],
            local_min_zoom=2,
            local_max_zoom=3,
        )
        self.assertFalse(polar["ok"])
        self.assertEqual(polar["error_code"], "polar_extent_unsupported")

        # Antimeridian crossing -> rejected with guidance
        anti = smp_tools.smp_estimate(
            local_bounds=[175.0, -10.0, -175.0, 10.0],
            local_min_zoom=2,
            local_max_zoom=3,
        )
        self.assertFalse(anti["ok"])
        self.assertEqual(anti["error_code"], "antimeridian_crossing")
        self.assertIn("hemisphere", anti["error"].lower())

    def test_invalid_zoom_ordering_and_containment_rejected(self):
        # World max >= Region min
        z_err = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=8,
            local_max_zoom=10,
            include_world=True,
            world_max_zoom=4,
            include_region=True,
            region_bounds=[-60.2, -3.2, -59.9, -2.9],
            region_min_zoom=4,
            region_max_zoom=6,
        )
        self.assertFalse(z_err["ok"])

        # Region does not contain Local
        cont_err = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=8,
            local_max_zoom=10,
            include_region=True,
            region_bounds=[-60.05, -3.05, -60.01, -3.01],
            region_min_zoom=5,
            region_max_zoom=7,
        )
        self.assertFalse(cont_err["ok"])
        self.assertEqual(cont_err["error_code"], "region_containment")

    def test_utm_project_crs_and_br_resolved_area_fallback(self):
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:31983"))
        res = smp_tools.smp_suggest_regions(
            area_reference={"type": "br_resolved_area", "name": "TI Test"},
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "gisbr_unavailable")

        ok_res = smp_tools.smp_suggest_regions(
            area_reference={
                "type": "br_resolved_area",
                "name": "TI Test",
                "bounds": [-60.15, -3.15, -59.95, -2.95],
            },
        )
        self.assertTrue(ok_res["ok"], ok_res)
        self.assertTrue(
            ok_res["candidates"][0]["coverage"]["local"]["provenance"].startswith("br_resolved_area:")
        )


if __name__ == "__main__":
    unittest.main()
