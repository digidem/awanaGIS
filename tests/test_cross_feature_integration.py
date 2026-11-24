"""Cross-feature integration tests for AwanaGIS branding, Brazil/Indigenous data, and SMP export."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer

from awanagis import classFactory
from awanagis.core import tools
from awanagis.core.executor import MainThreadExecutor
from awanagis.core.toolkit import QgisToolkit
from awanagis.integrations.brazil.policy import tag_layer_provenance
from awanagis.integrations.smp import tools as smp_tools
from awanagis.integrations.smp.exporter import ExportManager
from awanagis.server.mcp_server import McpBridgeServer

ROOT = Path(__file__).resolve().parents[1]


class CrossFeatureIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()

    def test_all_new_tools_exposed_identically_across_specs_anthropic_and_mcp(self):
        expected_br = {
            "br_search_sources",
            "br_source_details",
            "br_resolve_area",
            "br_plan_load",
            "br_execute_load",
        }
        expected_smp = {
            "smp_inspect_map",
            "smp_suggest_regions",
            "smp_estimate",
            "smp_start_export",
            "smp_export_status",
            "smp_cancel_export",
            "smp_validate_file",
        }
        expected = expected_br | expected_smp

        spec_names = {s["name"] for s in tools.tool_specs(include_gee=True)}
        anth_names = {s["name"] for s in tools.anthropic_tool_list(include_gee=True)}
        self.assertTrue(expected.issubset(spec_names))
        self.assertEqual(spec_names, anth_names)

        iface = MagicMock()
        iface.mainWindow.return_value = QMainWindow()
        toolkit = QgisToolkit(iface)
        executor = MainThreadExecutor()
        with tempfile.TemporaryDirectory() as tmp:
            disc_file = Path(tmp) / "mcp.json"
            with patch.dict(os.environ, {"AWANAGIS_MCP_DISCOVERY": str(disc_file)}):
                server = McpBridgeServer(
                    toolkit, executor, host="127.0.0.1", port=0,
                    poll_interval=0.05, server_timeout=0.05,
                )
                server.start()
                self.addCleanup(server.stop)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and server._server is None:
                    time.sleep(0.02)
                req = urllib.request.Request(
                    server.base_url,
                    data=json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    mcp_payload = json.loads(resp.read().decode("utf-8"))
        mcp_names = {t["name"] for t in mcp_payload["result"]["tools"]}
        self.assertEqual(spec_names, mcp_names)

    def test_brazil_tagged_sensitive_layer_blocks_smp_sampling_and_export(self):
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "ti_sensitive_test", "memory")
        self.assertTrue(layer.isValid())
        source_meta = {
            "source_id": "funai_indigenous_villages",
            "name": "FUNAI Indigenous Villages",
            "name_pt": "Aldeias Indígenas (FUNAI)",
            "publisher": "FUNAI",
            "distributor": "FUNAI",
            "origin_class": "official_direct",
            "sensitivity": "blocked_sensitive",
            "loader_state": "discovery_only",
            "attribution": "FUNAI",
            "license": "Public",
            "source_year": "2024",
            "srs": "EPSG:4674",
        }
        area_meta = {"type": "state", "id": "PA", "name": "Pará", "ufs": ["PA"]}
        tag_layer_provenance(
            layer,
            source_meta,
            area_meta,
            clip_mode="exact_polygon_clip",
            extracted_at="2026-11-23T00:00:00Z",
            output_path="/tmp/test.gpkg",
        )
        QgsProject.instance().addMapLayer(layer)

        inspected = smp_tools.smp_inspect_map(iface=None)
        self.assertTrue(inspected["ok"])
        self.assertEqual(len(inspected["visible_layers"]), 1)
        self.assertEqual(inspected["visible_layers"][0]["export_policy"], "blocked_sensitive")
        self.assertEqual(inspected["visible_layers"][0]["sensitivity"], "blocked_sensitive")

        # Suggesting a region directly referencing the blocked layer must refuse.
        suggested = smp_tools.smp_suggest_regions(
            iface=None,
            area_reference={"type": "layer", "layer_id": layer.id()},
        )
        self.assertFalse(suggested["ok"])
        self.assertEqual(suggested["error_code"], "blocked_sensitive_layer")

        # Estimating explicitly against the blocked_sensitive layer must refuse immediately.
        est_blocked = smp_tools.smp_estimate(
            local_bounds=[-60.05, -3.05, -60.01, -3.01],
            local_min_zoom=10,
            local_max_zoom=11,
            layer_ids=[layer.id()],
            sample=True,
        )
        self.assertFalse(est_blocked["ok"])
        self.assertEqual(est_blocked["error_code"], "blocked_sensitive_layer")

        # Auto-selecting visible layers with a normal public layer + a blocked layer
        # excludes the blocked_sensitive layer automatically.
        public_layer = QgsVectorLayer("Polygon?crs=EPSG:4326&field=name:string", "public_area", "memory")
        self.assertTrue(public_layer.isValid())
        QgsProject.instance().addMapLayer(public_layer)
        est_auto = smp_tools.smp_estimate(
            local_bounds=[-60.05, -3.05, -60.01, -3.01],
            local_min_zoom=10,
            local_max_zoom=11,
            sample=False,
        )
        self.assertTrue(est_auto["ok"])
        self.assertEqual([e["id"] for e in est_auto["excluded_layers"]], [layer.id()])
        self.assertNotIn(layer.id(), [l["id"] for l in est_auto["effective_layers"]])

        # A Brazil-tagged restricted layer skips unapproved sampling and blocks export
        # unless approved_restricted_layers=True.
        restricted_layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "ti_restricted_test", "memory")
        self.assertTrue(restricted_layer.isValid())
        tag_layer_provenance(
            restricted_layer,
            {**source_meta, "source_id": "funai_ti_studies", "sensitivity": "restricted", "loader_state": "discovery_only"},
            area_meta,
            clip_mode="exact_polygon_clip",
            extracted_at="2026-11-23T00:00:00Z",
            output_path="/tmp/test_restricted.gpkg",
        )
        QgsProject.instance().addMapLayer(restricted_layer)
        est_restricted = smp_tools.smp_estimate(
            local_bounds=[-60.05, -3.05, -60.01, -3.01],
            local_min_zoom=10,
            local_max_zoom=11,
            layer_ids=[restricted_layer.id()],
            sample=True,
        )
        self.assertTrue(est_restricted["ok"])
        self.assertEqual(est_restricted["calibration"], "uncalibrated_rough")
        self.assertEqual(est_restricted["sampling_blocked_reason"], "restricted_sampling_unapproved")

        with tempfile.TemporaryDirectory() as tmp:
            out_smp = str(Path(tmp) / "restricted.smp")
            mgr = ExportManager()
            res = mgr.start_export(
                plan_id=est_restricted["plan_id"],
                output_path=out_smp,
                approved=True,
                approved_restricted_layers=False,
                approval_callback=lambda summary: True,
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error_code"], "restricted_layer_unapproved")
            self.assertFalse(Path(out_smp).exists())

    def test_plugin_lifecycle_registers_and_unloads_brazil_provider_and_i18n(self):
        win = QMainWindow()
        iface = MagicMock()
        iface.mainWindow.return_value = win

        plugin = classFactory(iface)
        plugin.config.set("mcp_enabled", False)
        with patch("awanagis.plugin.resolve_qgis_locale", return_value="pt_BR"), \
             patch("awanagis.core.network_cache.sweep_stale_cache_on_startup"), \
             patch("awanagis.core.network_cache.maybe_enable_default_cache"), \
             patch("awanagis.core.network_cache.clear_cache_on_unload"):
            plugin.initGui()
            reg = QgsApplication.processingRegistry()
            self.assertIsNotNone(reg.providerById("awanagis_brazil"))
            self.assertEqual(plugin._action.text(), "AwanaGIS")
            self.assertEqual(
                QCoreApplication.translate("ToolNames", "Search Brazilian sources"),
                "Buscar fontes brasileiras",
            )
            self.assertEqual(
                QCoreApplication.translate("ToolNames", "Inspect SMP map"),
                "Inspecionar mapa SMP",
            )
            plugin.unload()
            self.assertIsNone(reg.providerById("awanagis_brazil"))
            self.assertIsNone(plugin._translator)


if __name__ == "__main__":
    unittest.main()
