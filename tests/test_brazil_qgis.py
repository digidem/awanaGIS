"""Headless QGIS integration tests for AwanaGIS Brazil & curated Indigenous data."""

from importlib import import_module
import atexit
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProcessingProvider,
    QgsProject,
    QgsVectorLayer,
)

# Allow headless unittest discovery to import QGIS Processing without full GUI launcher
_QGIS_PLUGINS_DIR = "/usr/share/qgis/python/plugins"
if Path(_QGIS_PLUGINS_DIR).is_dir() and _QGIS_PLUGINS_DIR not in sys.path:
    sys.path.append(_QGIS_PLUGINS_DIR)

from processing.core.Processing import Processing  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name
runtime = import_module(f"{PKG}.integrations.brazil.runtime")
planner = import_module(f"{PKG}.integrations.brazil.planner")
policy = import_module(f"{PKG}.integrations.brazil.policy")
loader = import_module(f"{PKG}.integrations.brazil.loader")
br_tools = import_module(f"{PKG}.integrations.brazil.tools")
wfs_conn = import_module(f"{PKG}.integrations.brazil.vendor.gisbr.core.connectors.wfs")
Config = import_module(f"{PKG}.config").Config
MainThreadExecutor = import_module(f"{PKG}.core.executor").MainThreadExecutor
QgisToolkit = import_module(f"{PKG}.core.toolkit").QgisToolkit
core_tools = import_module(f"{PKG}.core.tools")
catalog = import_module(f"{PKG}.integrations.brazil.catalog")
resolver = import_module(f"{PKG}.integrations.brazil.resolver")
AgenticGisPlugin = import_module(f"{PKG}.plugin").AwanaGisPlugin
mcp_server = import_module(f"{PKG}.server.mcp_server")


class _MockExternalGisbrProvider(QgsProcessingProvider):
    def id(self):
        return "gisbr"

    def name(self):
        return "GISBR Mock"

    def loadAlgorithms(self):
        pass


def _write_geojson(path: Path, features: list, crs_urn: str = "urn:ogc:def:crs:EPSG::4674") -> str:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": crs_urn}},
        "features": features,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _rect_coords(x0: float, y0: float, x1: float, y1: float) -> list:
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]


class BrazilQgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance()
        if cls.app is None:
            cls.app = QgsApplication([], True)
        if not QgsApplication.processingRegistry().providers():
            cls.app.initQgis()
            atexit.register(cls.app.exitQgis)
        if QgsApplication.processingRegistry().providerById("native") is None:
            Processing.initialize()

    def setUp(self):
        QgsProject.instance().clear()
        planner.clear_plans()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = Path(self.temp_dir.name)
        self.addCleanup(QgsProject.instance().clear)
        self.addCleanup(runtime.unregister_brazil_provider)

    def test_vendor_relative_imports_and_provider_coexistence(self):
        # Verify vendored GISBR uses relative imports only (no gisbr.* / gisbr: / sys.path mutation)
        vendor_dir = ROOT / "integrations" / "brazil" / "vendor" / "gisbr"
        for pyfile in vendor_dir.rglob("*.py"):
            txt = pyfile.read_text(encoding="utf-8")
            self.assertNotIn("from gisbr", txt, str(pyfile))
            self.assertNotIn("import gisbr", txt, str(pyfile))
            self.assertNotIn("gisbr:", txt, str(pyfile))
            self.assertNotIn("sys.path", txt, str(pyfile))

        reg = QgsApplication.processingRegistry()
        ext_provider = _MockExternalGisbrProvider()
        self.assertTrue(reg.addProvider(ext_provider))
        self.addCleanup(lambda: reg.providerById("gisbr") and reg.removeProvider(ext_provider))

        prov1 = runtime.register_brazil_provider()
        prov2 = runtime.register_brazil_provider()
        self.assertIsNotNone(prov1)
        self.assertIs(prov1, prov2)
        self.assertEqual(prov1.id(), "awanagis_brazil")
        self.assertEqual(len(prov1.algorithms()), 57)
        self.assertIsNotNone(reg.algorithmById("awanagis_brazil:read_municipality"))
        self.assertIsNotNone(reg.providerById("gisbr"))

        self.assertTrue(runtime.unregister_brazil_provider())
        self.assertIsNone(reg.providerById("awanagis_brazil"))
        # External GISBR provider must remain intact
        self.assertIsNotNone(reg.providerById("gisbr"))

    def test_plugin_lifecycle_registers_and_unregisters_brazil_provider(self):
        iface = Mock()
        iface.mainWindow.return_value = QMainWindow()
        plugin = AgenticGisPlugin(iface)
        reg = QgsApplication.processingRegistry()
        with patch(f"{PKG}.plugin.resolve_qgis_locale", return_value="en"), \
             patch.object(plugin, "_apply_mcp_state"), \
             patch(f"{PKG}.core.network_cache.sweep_stale_cache_on_startup"), \
             patch(f"{PKG}.core.network_cache.maybe_enable_default_cache"), \
             patch(f"{PKG}.core.network_cache.clear_cache_on_unload"):
            try:
                plugin.initGui()
                self.assertIsNotNone(reg.providerById("awanagis_brazil"))
            finally:
                plugin.unload()
            self.assertIsNone(reg.providerById("awanagis_brazil"))

    def test_project_layer_resolution_validation(self):
        # Point layer must be rejected for polygon clipping
        pt_layer = QgsVectorLayer("Point?crs=EPSG:4674", "points_only", "memory")
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromWkt("POINT(-52.0 -5.0)"))
        pt_layer.dataProvider().addFeatures([feat])
        QgsProject.instance().addMapLayer(pt_layer)

        pt_res = br_tools.br_resolve_area(type="project_layer", layer_id=pt_layer.id())
        self.assertFalse(pt_res["ok"])
        self.assertEqual(pt_res["status"], "unsupported")

        # Valid polygon layer resolves with WKT & fingerprint
        poly_layer = QgsVectorLayer("Polygon?crs=EPSG:4674", "study_poly", "memory")
        pfeat = QgsFeature()
        pfeat.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        poly_layer.dataProvider().addFeatures([pfeat])
        poly_layer.updateExtents()
        QgsProject.instance().addMapLayer(poly_layer)

        poly_res = br_tools.br_resolve_area(type="project_layer", layer_id=poly_layer.id())
        self.assertTrue(poly_res["ok"])
        self.assertEqual(poly_res["status"], "resolved")
        self.assertTrue(poly_res["area"]["clip_geometry_available"])
        self.assertTrue(poly_res["area"]["geometry_fingerprint"])

    def test_indigenous_ti_dsei_inpe_fixture_load_clip_provenance_and_chaining(self):
        # Synthetic non-real coordinates for fixture-driven Indigenous workflow
        ti_geojson = _write_geojson(
            self.tmp / "funai_ti.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {
                        "terrai_cod": "99901",
                        "terrai_nom": "Teste Sintético",
                        "uf_sigla": "PA",
                        "fase_ti": "Regularizada",
                    },
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.2, -5.2, -51.8, -4.8)},
                }
            ],
        )
        dsei_geojson = _write_geojson(
            self.tmp / "funai_dsei.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"dsei_cod": "10", "dsei_nome": "DSEI Teste"},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.5, -5.5, -51.5, -4.5)},
                }
            ],
        )
        # One PRODES polygon inside TI (-52.1..-51.9) and one completely outside (-53.5..-53.3)
        prodes_geojson = _write_geojson(
            self.tmp / "inpe_prodes.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2024, "state": "PA", "area_km": 1.25},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.1, -5.1, -51.9, -4.9)},
                },
                {
                    "type": "Feature",
                    "properties": {"year": 2024, "state": "PA", "area_km": 9.99},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-53.5, -5.5, -53.3, -5.3)},
                },
            ],
        )
        deter_geojson = _write_geojson(
            self.tmp / "inpe_deter.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"classname": "DESMATAMENTO_CR", "view_date": "2026-01-15"},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.05, -5.05, -51.95, -4.95)},
                }
            ],
        )

        # 1) Load FUNAI TI polygon first using project polygon / municipality scope
        gpkg_path = str(self.tmp / "indigenous_flow.gpkg")
        sao_felix = br_tools.br_resolve_area(type="municipality", ibge_code="1507300")["area"]
        ti_plan = br_tools.br_plan_load(["funai_ti_boundaries"], sao_felix, output_gpkg=gpkg_path)
        self.assertTrue(ti_plan["can_execute"])
        ti_exec = br_tools.br_execute_load(
            ti_plan["plan_id"],
            local_fixtures={"funai_ti_boundaries": ti_geojson},
        )
        self.assertTrue(ti_exec["ok"])
        self.assertEqual(ti_exec["status"], "loaded")
        ti_layer_id = ti_exec["results"][0]["layer_ids"][0]
        ti_layer = QgsProject.instance().mapLayer(ti_layer_id)
        self.assertIsNotNone(ti_layer)
        self.assertEqual(ti_layer.customProperty(policy.PROP_SENSITIVITY), "territory_boundary")
        self.assertEqual(ti_layer.customProperty(policy.PROP_EXPORT_POLICY), "allow_with_attribution")
        prov_ti = json.loads(ti_layer.customProperty(policy.PROP_PROVENANCE_JSON))
        self.assertEqual(prov_ti["publisher"], "FUNAI / CGGEO")
        self.assertEqual(prov_ti["data_reference_year"], "unknown")
        self.assertTrue(prov_ti["extracted_at"].endswith("Z"))

        # 2) Resolve named TI from the loaded QGIS TI layer
        resolved_ti = br_tools.br_resolve_area(type="indigenous_territory", territory_id="99901")
        self.assertTrue(resolved_ti["ok"])
        self.assertEqual(resolved_ti["status"], "resolved")
        ti_area = resolved_ti["area"]
        self.assertTrue(ti_area["clip_geometry_available"])
        self.assertEqual(ti_area["legal_stage"], "Regularizada")

        # 3) Plan and load DSEI, INPE PRODES, and INPE DETER clipped by the real TI polygon mask
        pressure_plan = br_tools.br_plan_load(
            ["funai_dsei_areas", "inpe_prodes", "inpe_deter"],
            ti_area,
            output_gpkg=gpkg_path,
        )
        self.assertTrue(pressure_plan["can_execute"])
        pressure_exec = br_tools.br_execute_load(
            pressure_plan["plan_id"],
            local_fixtures={
                "funai_dsei_areas": dsei_geojson,
                "inpe_prodes": prodes_geojson,
                "inpe_deter": deter_geojson,
            },
        )
        self.assertTrue(pressure_exec["ok"])
        self.assertEqual(pressure_exec["status"], "loaded")

        by_src = {r["source_id"]: r for r in pressure_exec["results"]}
        # PRODES had 2 features, 1 outside TI -> exact_polygon_clip must leave only 1 feature!
        self.assertEqual(by_src["inpe_prodes"]["feature_count"], 1)
        self.assertEqual(by_src["inpe_prodes"]["clip_mode"], "exact_polygon_clip")
        self.assertEqual(by_src["inpe_deter"]["feature_count"], 1)
        self.assertEqual(by_src["funai_dsei_areas"]["feature_count"], 1)

        prodes_layer_id = by_src["inpe_prodes"]["layer_ids"][0]
        prodes_layer = QgsProject.instance().mapLayer(prodes_layer_id)
        self.assertEqual(prodes_layer.customProperty(policy.PROP_EXPORT_POLICY), "allow_export")
        self.assertTrue(policy.check_layer_export_allowed(prodes_layer)[0])

        # Restricted synthetic tag blocks export check
        prodes_layer_fake_restricted = QgsVectorLayer("Point?crs=EPSG:4674", "restricted", "memory")
        prodes_layer_fake_restricted.setCustomProperty(policy.PROP_SENSITIVITY, "restricted_locality_point")
        self.assertFalse(policy.check_layer_export_allowed(prodes_layer_fake_restricted)[0])

        # 4) Chain loaded layer_ids with existing AwanaGIS toolkit tools (get_layer_fields + run_processing)
        cfg = Config()
        cfg._s = QSettings(str(self.tmp / "toolkit.ini"), QSettings.Format.IniFormat)
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=cfg)

        fields_res = toolkit.get_layer_fields(prodes_layer_id)
        self.assertTrue(fields_res["ok"])
        self.assertIn("year", [f["name"] for f in fields_res["fields"]])

        sel_res = toolkit.select_by_expression(prodes_layer_id, "year = 2024")
        self.assertTrue(sel_res["ok"])
        self.assertEqual(sel_res["selected_count"], 1)

        proc_res = toolkit.run_processing(
            "native:intersection",
            {"INPUT": ti_layer_id, "OVERLAY": prodes_layer_id, "OUTPUT": "TEMPORARY_OUTPUT"},
        )
        self.assertTrue(proc_res["ok"])
        self.assertEqual(proc_res["output"]["OUTPUT_feature_count"], 1)

        # 5) Reuse/skip on repeat plan (replace_existing=False) vs safe replacement (replace_existing=True)
        reuse_plan = br_tools.br_plan_load(["inpe_prodes"], ti_area, output_gpkg=gpkg_path, replace_existing=False)
        self.assertFalse(reuse_plan["can_execute"])
        self.assertEqual(reuse_plan["items"][0]["readiness"], "skipped")

        replace_plan = br_tools.br_plan_load(["inpe_prodes"], ti_area, output_gpkg=gpkg_path, replace_existing=True)
        self.assertTrue(replace_plan["can_execute"])
        before_count = len(QgsProject.instance().mapLayers())
        replace_exec = br_tools.br_execute_load(
            replace_plan["plan_id"],
            local_fixtures={"inpe_prodes": prodes_geojson},
        )
        self.assertTrue(replace_exec["ok"])
        self.assertEqual(len(QgsProject.instance().mapLayers()), before_count)

    def test_partial_failure_wfs_200_error_truncation_and_mcp_parity(self):
        # Partial failure: inpe_prodes loads from fixture while funai_ti_boundaries fails
        prodes_geojson = _write_geojson(
            self.tmp / "prodes_only.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2024},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.1, -5.1, -51.9, -4.9)},
                }
            ],
        )
        poly_layer = QgsVectorLayer("Polygon?crs=EPSG:4674", "mask", "memory")
        pfeat = QgsFeature()
        pfeat.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        poly_layer.dataProvider().addFeatures([pfeat])
        poly_layer.updateExtents()
        QgsProject.instance().addMapLayer(poly_layer)
        area = br_tools.br_resolve_area(type="project_layer", layer_id=poly_layer.id())["area"]

        gpkg_path = str(self.tmp / "partial.gpkg")
        plan = br_tools.br_plan_load(["inpe_prodes", "funai_dsei_areas"], area, output_gpkg=gpkg_path)
        self.assertTrue(plan["can_execute"])
        partial_exec = br_tools.br_execute_load(
            plan["plan_id"],
            local_fixtures={"inpe_prodes": prodes_geojson},
        )
        self.assertTrue(partial_exec["ok"])
        self.assertEqual(partial_exec["status"], "partial")
        by_src = {r["source_id"]: r for r in partial_exec["results"]}
        self.assertEqual(by_src["inpe_prodes"]["status"], "loaded")
        self.assertEqual(by_src["funai_dsei_areas"]["status"], "unavailable")

        # Verify no stale .tmp_awanagis_*.gpkg temp files remain
        self.assertEqual(list(self.tmp.glob(".tmp_awanagis_*.gpkg")), [])

        # WFS HTTP-200 XML Exception & truncation helpers
        err = wfs_conn._detecta_erro_http_200(
            b"<ows:ExceptionReport><ows:Exception><ows:ExceptionText>Layer unknown</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"
        )
        self.assertIn("Layer unknown", err)

        trunc_layer = QgsVectorLayer("Polygon?crs=EPSG:4674", "trunc_test", "memory")
        trunc_bytes = b'{"type":"FeatureCollection","numberMatched":5000,"numberReturned":100,"features":[]}'
        wfs_conn._checa_truncamento(trunc_layer, trunc_bytes, None)
        self.assertEqual(trunc_layer.customProperty("truncado"), "100 de 5000")

        # MCP server parity: tools/list includes all 5 br_* tools and tools/call executes br_search_sources
        bridge = object.__new__(mcp_server._RpcServer)
        bridge.toolkit = Mock()
        bridge.toolkit.confirm_external_access = Mock(return_value=None)
        bridge.toolkit.can_run_background = Mock(return_value=False)
        bridge.executor = type("Exec", (), {"run_sync": staticmethod(lambda fn: fn())})()

        list_resp = bridge.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool_names = {t["name"] for t in list_resp["result"]["tools"]}
        self.assertTrue(
            {"br_search_sources", "br_source_details", "br_resolve_area", "br_plan_load", "br_execute_load"}.issubset(tool_names)
        )

        call_resp = bridge.handle_rpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "br_search_sources", "arguments": {"query": "PRODES", "limit": 5}},
        })
        self.assertFalse(call_resp["result"]["isError"])
        payload = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertIn("inpe_prodes", {s["id"] for s in payload["sources"]})

    def test_no_overwrite_at_write_time_and_no_uncut_persist_on_clip_failure(self):
        # 1) Write-time no-overwrite guard on GeoPackage & sidecar
        layer1 = QgsVectorLayer("Polygon?crs=EPSG:4674", "l1", "memory")
        f1 = QgsFeature()
        f1.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        layer1.dataProvider().addFeatures([f1])

        layer2 = QgsVectorLayer("Polygon?crs=EPSG:4674", "l2", "memory")
        f2 = QgsFeature()
        f2.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.1 -5.1, -51.9 -5.1, -51.9 -4.9, -52.1 -4.9, -52.1 -5.1))"))
        f3 = QgsFeature()
        f3.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.05 -5.05, -51.95 -5.05, -51.95 -4.95, -52.05 -4.95, -52.05 -5.05))"))
        layer2.dataProvider().addFeatures([f2, f3])

        gpkg = self.tmp / "guard.gpkg"
        ok1, _msg1, path1 = loader._write_vector_atomically(
            layer1, gpkg, "shared_table", replace_existing=False
        )
        self.assertTrue(ok1)
        self.assertEqual(path1, gpkg)

        # replace_existing=False MUST refuse to overwrite existing table in gpkg
        ok2, msg2, _path2 = loader._write_vector_atomically(
            layer2, gpkg, "shared_table", replace_existing=False
        )
        self.assertFalse(ok2)
        self.assertIn("Refusing to overwrite", msg2)
        check = QgsVectorLayer(f"{gpkg}|layername=shared_table", "check", "ogr")
        self.assertEqual(check.featureCount(), 1)
        del check

        # Case-variant table name MUST also be refused (SQLite/GPKG names collide case-insensitively)
        ok_cv, msg_cv, _ = loader._write_vector_atomically(
            layer2, gpkg, "SHARED_TABLE", replace_existing=False
        )
        self.assertFalse(ok_cv)
        self.assertIn("Refusing to overwrite", msg_cv)
        check_cv = QgsVectorLayer(f"{gpkg}|layername=shared_table", "check_cv", "ogr")
        self.assertEqual(check_cv.featureCount(), 1)
        del check_cv

        # Uninspectable existing GeoPackage MUST fail closed, not be treated as absent
        broken = self.tmp / "broken_guard.gpkg"
        broken.write_bytes(b"not a sqlite database" * 64)
        ok_bk, msg_bk, _ = loader._write_vector_atomically(
            layer2, broken, "any_table", replace_existing=False
        )
        self.assertFalse(ok_bk)
        self.assertIn("cannot inspect", msg_bk)
        self.assertEqual(broken.read_bytes(), b"not a sqlite database" * 64)

        # Sidecar fallback MUST also refuse overwrite when replace_existing=False
        sidecar = gpkg.with_name(f"{gpkg.stem}_new_table.gpkg")
        sidecar.write_bytes(b"existing-sidecar-sentinel")
        from qgis.core import QgsVectorFileWriter
        real_write = QgsVectorFileWriter.writeAsVectorFormatV3

        def fake_busy_gpkg(lyr, path, ctx, opts):
            if Path(path) == gpkg:
                return (1, "busy")
            return real_write(lyr, path, ctx, opts)

        with patch("qgis.core.QgsVectorFileWriter.writeAsVectorFormatV3", side_effect=fake_busy_gpkg):
            ok_sc, msg_sc, _ = loader._write_vector_atomically(
                layer2, gpkg, "new_table", replace_existing=False
            )
            self.assertFalse(ok_sc)
            self.assertIn("sidecar", msg_sc)
            self.assertEqual(sidecar.read_bytes(), b"existing-sidecar-sentinel")

        # 2) Clip failure must NEVER persist uncut data or add layer to QgsProject
        poly_mask = QgsVectorLayer("Polygon?crs=EPSG:4674", "clip_mask", "memory")
        pm_feat = QgsFeature()
        pm_feat.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        poly_mask.dataProvider().addFeatures([pm_feat])
        poly_mask.updateExtents()
        QgsProject.instance().addMapLayer(poly_mask)
        area = br_tools.br_resolve_area(type="project_layer", layer_id=poly_mask.id())["area"]

        uncut_geojson = _write_geojson(
            self.tmp / "uncut_prodes.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2024},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-53.5, -5.5, -53.3, -5.3)},
                }
            ],
        )
        clip_gpkg = str(self.tmp / "no_uncut.gpkg")
        plan = br_tools.br_plan_load(["inpe_prodes"], area, output_gpkg=clip_gpkg)
        self.assertTrue(plan["can_execute"])
        before_layers = len(QgsProject.instance().mapLayers())
        with patch("processing.run", side_effect=RuntimeError("simulated clip failure")):
            res = br_tools.br_execute_load(
                plan["plan_id"],
                local_fixtures={"inpe_prodes": uncut_geojson},
            )
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["results"][0]["layer_ids"], [])
        self.assertIn("clip failed", res["results"][0]["error"].lower())
        self.assertEqual(len(QgsProject.instance().mapLayers()), before_layers)
        self.assertFalse(Path(clip_gpkg).exists())

    def test_raster_staging_and_actual_loaded_year_in_provenance(self):
        from osgeo import gdal

        # Create a valid 4x4 GeoTIFF fixture in EPSG:4674
        src_tif = self.tmp / "mapbiomas_2010_fixture.tif"
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(str(src_tif), 4, 4, 1, gdal.GDT_Byte)
        ds.SetGeoTransform((-52.2, 0.1, 0.0, -4.8, 0.0, -0.1))
        ds.SetProjection(QgsCoordinateReferenceSystem("EPSG:4674").toWkt())
        ds.GetRasterBand(1).Fill(3)
        ds.FlushCache()
        ds = None

        mask_layer = QgsVectorLayer("Polygon?crs=EPSG:4674", "raster_mask", "memory")
        mf = QgsFeature()
        mf.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        mask_layer.dataProvider().addFeatures([mf])
        mask_layer.updateExtents()
        QgsProject.instance().addMapLayer(mask_layer)
        area = br_tools.br_resolve_area(type="project_layer", layer_id=mask_layer.id())["area"]

        gpkg_path = self.tmp / "raster_flow.gpkg"
        plan = br_tools.br_plan_load(
            ["mapbiomas_cobertura"],
            area,
            output_gpkg=str(gpkg_path),
            years={"mapbiomas_cobertura": 2010},
            include_non_government=True,
        )
        self.assertTrue(plan["can_execute"])
        expected_tif = Path(plan["items"][0]["output_target"])

        # Cancellation after staging must NOT promote raster to final destination
        expected_tif.write_bytes(b"original-protected-raster")
        staged_path, kind, _w = loader._stage_raster_atomically(
            "",
            mask_layer,
            expected_tif,
            "mapbiomas_2010",
            replace_existing=True,
            should_stop=lambda: True,
            fixture_override=str(src_tif),
        )
        self.assertIsNone(staged_path)
        self.assertEqual(kind, "cancelled")
        self.assertEqual(expected_tif.read_bytes(), b"original-protected-raster")
        self.assertEqual(list(self.tmp.glob(".tmp_awanagis_*")), [])

        # replace_existing=False must refuse overwrite
        staged_no_ow, kind_no_ow, _ = loader._stage_raster_atomically(
            "",
            mask_layer,
            expected_tif,
            "mapbiomas_2010",
            replace_existing=False,
            fixture_override=str(src_tif),
        )
        self.assertIsNone(staged_no_ow)
        self.assertEqual(kind_no_ow, "failed")
        self.assertEqual(expected_tif.read_bytes(), b"original-protected-raster")

        # Valid replace_existing=True stages, promotes, and records requested year=2010 (not 2023!)
        plan_ow = br_tools.br_plan_load(
            ["mapbiomas_cobertura"],
            area,
            output_gpkg=str(gpkg_path),
            years={"mapbiomas_cobertura": 2010},
            replace_existing=True,
            include_non_government=True,
        )
        exec_res = br_tools.br_execute_load(
            plan_ow["plan_id"],
            local_fixtures={"mapbiomas_cobertura": str(src_tif)},
        )
        self.assertTrue(exec_res["ok"])
        prov_raster = exec_res["results"][0]["provenance"]
        self.assertEqual(prov_raster["data_reference_year"], 2010)
        self.assertEqual(list(self.tmp.glob(".tmp_awanagis_*")), [])

        # Vector loaded year checks: single year (2021) and multi-year range (2020-2022)
        prodes_2021 = _write_geojson(
            self.tmp / "prodes_2021.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2021},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.1, -5.1, -51.9, -4.9)},
                }
            ],
        )
        prodes_range = _write_geojson(
            self.tmp / "prodes_range.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2020},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.1, -5.1, -52.0, -5.0)},
                },
                {
                    "type": "Feature",
                    "properties": {"year": 2022},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.0, -5.0, -51.9, -4.9)},
                },
            ],
        )
        p21 = br_tools.br_plan_load(["inpe_prodes"], area, output_gpkg=str(gpkg_path))
        r21 = br_tools.br_execute_load(p21["plan_id"], local_fixtures={"inpe_prodes": prodes_2021})
        self.assertEqual(r21["results"][0]["provenance"]["data_reference_year"], 2021)

        prng = br_tools.br_plan_load(["inpe_prodes"], area, output_gpkg=str(gpkg_path), replace_existing=True)
        rrng = br_tools.br_execute_load(prng["plan_id"], local_fixtures={"inpe_prodes": prodes_range})
        self.assertEqual(rrng["results"][0]["provenance"]["data_reference_year"], "2020-2022")

    def test_geobr_ti_fallback_filters_requested_territory_only(self):
        national_ti_geojson = _write_geojson(
            self.tmp / "geobr_all_tis.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"code_terrai": 51901, "name_indigenous_land": "Yanomami", "abbrev_state": "AM,RR"},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-64.0, 1.0, -63.0, 2.0)},
                },
                {
                    "type": "Feature",
                    "properties": {"code_terrai": 21901, "name_indigenous_land": "Kayapó", "abbrev_state": "PA"},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.0, -8.0, -51.0, -7.0)},
                },
                {
                    "type": "Feature",
                    "properties": {"code_terrai": 1901, "name_indigenous_land": "Apyterewa", "abbrev_state": "PA"},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.5, -5.5, -52.0, -5.0)},
                },
            ],
        )

        yan_area = br_tools.br_resolve_area(type="indigenous_territory", name="Yanomami")["area"]
        gpkg = str(self.tmp / "ti_filtered.gpkg")
        plan = br_tools.br_plan_load(["geobr_terras_indigenas"], yan_area, output_gpkg=gpkg)
        self.assertTrue(plan["can_execute"])

        # Mock _carrega_geobr returning the full 3-TI national layer; loader MUST filter to Yanomami only
        national_layer = QgsVectorLayer(national_ti_geojson, "geobr_nat", "ogr")
        with patch.object(loader.gisbr_diag, "_carrega_geobr", return_value=national_layer):
            exec_res = br_tools.br_execute_load(plan["plan_id"])
        self.assertTrue(exec_res["ok"])
        self.assertEqual(exec_res["results"][0]["feature_count"], 1)
        loaded_ti = QgsProject.instance().mapLayer(exec_res["results"][0]["layer_ids"][0])
        names = [f["name_indigenous_land"] for f in loaded_ti.getFeatures()]
        self.assertEqual(names, ["Yanomami"])

        # Unmatched TI in national dataset must fail rather than saving all national TIs
        fake_ti_area = dict(yan_area, terrai_cod="88888", territory_id="88888", name="Nonexistent TI")
        plan_miss = br_tools.br_plan_load(["geobr_terras_indigenas"], fake_ti_area, output_gpkg=gpkg, replace_existing=True)
        national_layer2 = QgsVectorLayer(national_ti_geojson, "geobr_nat2", "ogr")
        with patch.object(loader.gisbr_diag, "_carrega_geobr", return_value=national_layer2):
            miss_res = br_tools.br_execute_load(plan_miss["plan_id"])
        self.assertFalse(miss_res["ok"])
        self.assertEqual(miss_res["results"][0]["status"], "failed")
        self.assertEqual(miss_res["results"][0]["layer_ids"], [])

    def test_off_gui_thread_dispatch_with_main_thread_executor(self):
        main_tid = threading.get_ident()
        cfg = Config()
        cfg._s = QSettings(str(self.tmp / "bg_dispatch.ini"), QSettings.Format.IniFormat)
        cfg.set("external_access_always_allowed", True)
        executor = MainThreadExecutor(config=cfg)
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=cfg)

        observed = {}

        # 1) Probe and IBGE live lookup run OFF GUI thread
        caps_xml = (
            b"<WFS_Capabilities><FeatureTypeList><FeatureType>"
            b"<Name>prodes-legal-amz:yearly_deforestation</Name>"
            b"</FeatureType></FeatureTypeList></WFS_Capabilities>"
        )

        class _Resp:
            status = 200

            def __init__(self, data):
                self._data = data

            def read(self, n=-1):
                return self._data if n < 0 else self._data[:n]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _FakeOpener:
            def __init__(self, opener_open):
                self._open = opener_open

            def open(self, req, timeout=None, **kwargs):
                return self._open(req, timeout=timeout, **kwargs)

        def fake_probe_urlopen(req, timeout=8.0, **_kwargs):
            observed["probe_tid"] = threading.get_ident()
            return _Resp(caps_xml)

        def fake_ibge_urlopen(req, timeout=5.0):
            observed["ibge_tid"] = threading.get_ident()
            return _Resp(b'{"id": 9999998, "nome": "FakeMuni", "microrregiao": {"mesorregiao": {"UF": {"sigla": "PA"}}}}')

        # 2) br_execute_load runs run_load_worker OFF GUI thread and commit_load_results ON GUI thread
        mask = QgsVectorLayer("Polygon?crs=EPSG:4674", "bg_mask", "memory")
        mf = QgsFeature()
        mf.setGeometry(QgsGeometry.fromWkt("POLYGON((-52.2 -5.2, -51.8 -5.2, -51.8 -4.8, -52.2 -4.8, -52.2 -5.2))"))
        mask.dataProvider().addFeatures([mf])
        mask.updateExtents()
        QgsProject.instance().addMapLayer(mask)
        area = br_tools.br_resolve_area(type="project_layer", layer_id=mask.id())["area"]
        gpkg = str(self.tmp / "bg_exec.gpkg")
        plan = br_tools.br_plan_load(["inpe_prodes"], area, output_gpkg=gpkg)
        prodes_geojson = _write_geojson(
            self.tmp / "bg_prodes.geojson",
            [
                {
                    "type": "Feature",
                    "properties": {"year": 2024},
                    "geometry": {"type": "Polygon", "coordinates": _rect_coords(-52.1, -5.1, -51.9, -4.9)},
                }
            ],
        )

        orig_worker = core_tools.run_load_worker
        orig_commit = core_tools.commit_load_results

        def spy_worker(*a, **kw):
            observed["worker_tid"] = threading.get_ident()
            kw["local_fixtures"] = {"inpe_prodes": prodes_geojson}
            return orig_worker(*a, **kw)

        def spy_commit(*a, **kw):
            observed["commit_tid"] = threading.get_ident()
            return orig_commit(*a, **kw)

        results = {}

        def bg_agent_thread():
            catalog._PROBE_CACHE.clear()
            with patch.object(catalog.urllib.request, "build_opener", side_effect=lambda *h, **k: _FakeOpener(fake_probe_urlopen)):
                results["probe"] = core_tools.dispatch(
                    toolkit, executor, "br_source_details", {"source_ids": ["inpe_prodes"], "probe": True}
                )
            with patch.object(resolver.urllib.request, "build_opener", side_effect=lambda *h, **k: _FakeOpener(fake_ibge_urlopen)):
                results["ibge"] = core_tools.dispatch(
                    toolkit, executor, "br_resolve_area", {"type": "municipality", "ibge_code": "9999998", "allow_live_lookup": True}
                )
            with patch.object(core_tools, "run_load_worker", side_effect=spy_worker), \
                 patch.object(core_tools, "commit_load_results", side_effect=spy_commit):
                results["exec"] = core_tools.dispatch(
                    toolkit, executor, "br_execute_load", {"plan_id": plan["plan_id"]}
                )

        t = threading.Thread(target=bg_agent_thread, daemon=True)
        t.start()
        while t.is_alive():
            QCoreApplication.processEvents()
            t.join(0.02)

        self.assertTrue(results["probe"]["ok"])
        self.assertTrue(results["ibge"]["ok"])
        self.assertTrue(results["exec"]["ok"])
        self.assertNotEqual(observed["probe_tid"], main_tid)
        self.assertNotEqual(observed["ibge_tid"], main_tid)
        self.assertNotEqual(observed["worker_tid"], main_tid)
        self.assertEqual(observed["commit_tid"], main_tid)
        executor.deleteLater()
        QCoreApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
