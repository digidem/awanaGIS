"""Security, permission, policy, credential-redaction, and schema-parity tests for SMP."""

from importlib import import_module
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

smp_tools = import_module(f"{ROOT.name}.integrations.smp.tools")
smp_policy = import_module(f"{ROOT.name}.integrations.smp.policy")
smp_estimator = import_module(f"{ROOT.name}.integrations.smp.estimator")
smp_exporter = import_module(f"{ROOT.name}.integrations.smp.exporter")
tools_mod = import_module(f"{ROOT.name}.core.tools")
formatting = import_module(f"{ROOT.name}.gui.formatting")
mcp_server = import_module(f"{ROOT.name}.server.mcp_server")
mcp_stdio = import_module(f"{ROOT.name}.server.mcp_stdio")
i18n_mod = import_module(f"{ROOT.name}.i18n")

EXPECTED_SMP_TOOLS = {
    "smp_inspect_map",
    "smp_suggest_regions",
    "smp_estimate",
    "smp_start_export",
    "smp_export_status",
    "smp_cancel_export",
    "smp_validate_file",
}


def setUpModule():
    global app
    app = QgsApplication.instance() or QgsApplication([], False)


class SmpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

        self.public_layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=name:string(40)", "rivers", "memory"
        )
        f1 = QgsFeature()
        f1.setGeometry(
            QgsGeometry.fromWkt("POLYGON((-60.1 -3.1, -60.0 -3.1, -60.0 -3.0, -60.1 -3.0, -60.1 -3.1))")
        )
        f1.setAttributes(["Rio Negro"])
        self.public_layer.dataProvider().addFeatures([f1])
        self.public_layer.updateExtents()
        self.project.addMapLayer(self.public_layer)

        self.tmp = tempfile.mkdtemp(prefix="test_smp_sec_")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def tearDown(self):
        smp_exporter.get_export_manager().cleanup_all()
        self.project.removeAllMapLayers()

    def test_credential_redaction_on_uris(self):
        samples = [
            ("https://alice:s3cr3t@tiles.example.org/{z}/{x}/{y}.png?token=abc123&api_key=xyz999",
             ("alice", "s3cr3t", "abc123", "xyz999")),
            ("dbname='gis' host=db.internal user=admin password='my secret pass' table=roads",
             ("my secret pass",)),
            ("type=xyz&url=https://api.mapbox.com/v4/tile/{z}/{x}/{y}.png?access_token=pk.eyJ12345",
             ("pk.eyJ12345",)),
        ]
        for raw, secrets in samples:
            redacted = smp_policy.redact_uri(raw)
            for secret in secrets:
                self.assertNotIn(secret, redacted, f"Secret leaked in {redacted!r}")
            self.assertIn("***", redacted)

        # Verify inspect_map redacts online layer credentials
        xyz_uri = "type=xyz&url=https://user:topsecret@tiles.example.org/{z}/{x}/{y}.png?api_key=MYKEY123"
        xyz_layer = QgsRasterLayer(xyz_uri, "SecretTiles", "wms")
        self.project.addMapLayer(xyz_layer)
        info = smp_tools.smp_inspect_map()
        self.assertTrue(info["ok"])
        found = [l for l in info["visible_layers"] if l["name"] == "SecretTiles"][0]
        self.assertNotIn("topsecret", found["source_uri_redacted"])
        self.assertNotIn("MYKEY123", found["source_uri_redacted"])
        self.assertTrue(found["online"])
        self.assertIn(found["export_policy"], ("warn_online", "warn_license"))

    def test_blocked_sensitive_and_restricted_layer_enforcement(self):
        blocked = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=name:string(40)", "isolated_villages", "memory"
        )
        blocked.setCustomProperty("awanagis/sensitivity", "isolated_peoples")
        fb = QgsFeature()
        fb.setGeometry(QgsGeometry.fromWkt("POINT(-60.05 -3.05)"))
        fb.setAttributes(["Aldeia Secreta"])
        blocked.dataProvider().addFeatures([fb])
        blocked.updateExtents()
        self.project.addMapLayer(blocked)

        restricted = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=name:string(40)", "ti_points", "memory"
        )
        restricted.setCustomProperty("awanagis/export_policy", "restricted")
        fr = QgsFeature()
        fr.setGeometry(QgsGeometry.fromWkt("POINT(-60.06 -3.06)"))
        fr.setAttributes(["Ponto Restrito"])
        restricted.dataProvider().addFeatures([fr])
        restricted.updateExtents()
        self.project.addMapLayer(restricted)

        # Inspect surfaces sensitivity & export_policy custom properties
        info = smp_tools.smp_inspect_map()
        by_id = {l["id"]: l for l in info["visible_layers"]}
        self.assertEqual(by_id[blocked.id()]["sensitivity"], "isolated_peoples")
        self.assertEqual(by_id[blocked.id()]["export_policy"], "blocked_sensitive")
        self.assertEqual(by_id[restricted.id()]["export_policy"], "restricted")

        # Suggest regions must refuse explicit selection/layer on blocked_sensitive layer
        blocked.selectAll()
        refused_sel = smp_tools.smp_suggest_regions(
            local_reference={"type": "selection", "layer_id": blocked.id()},
        )
        self.assertFalse(refused_sel["ok"])
        self.assertEqual(refused_sel["error_code"], "blocked_sensitive_layer")

        # Explicit inclusion of blocked_sensitive must fail
        err = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            layer_ids=[self.public_layer.id(), blocked.id()],
        )
        self.assertFalse(err["ok"])
        self.assertEqual(err["error_code"], "blocked_sensitive_layer")

        # Auto layer selection excludes blocked_sensitive, keeps restricted with warning
        est = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
        )
        self.assertTrue(est["ok"], est)
        eff_ids = {l["id"] for l in est["effective_layers"]}
        self.assertNotIn(blocked.id(), eff_ids)
        self.assertIn(restricted.id(), eff_ids)
        self.assertEqual(len(est["excluded_layers"]), 1)

        # Exporting with restricted layer without approved_restricted_layers=True must fail
        out_path = os.path.join(self.tmp, "restricted.smp")
        deny_res = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=out_path,
            approved=True,
            approved_restricted_layers=False,
        )
        self.assertFalse(deny_res["ok"])
        self.assertEqual(deny_res["error_code"], "restricted_layer_unapproved")
        self.assertFalse(os.path.exists(out_path))

    def test_approval_staleness_path_traversal_and_overwrite_gates(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
        )
        self.assertTrue(est["ok"])
        plan_id = est["plan_id"]
        out_path = os.path.join(self.tmp, "approved.smp")

        # Missing approval -> refused
        no_app = smp_tools.smp_start_export(plan_id=plan_id, output_path=out_path, approved=False)
        self.assertFalse(no_app["ok"])
        self.assertEqual(no_app["error_code"], "approval_required")

        # Forged plan_id -> refused
        forged = smp_tools.smp_start_export(
            plan_id="smp_forged_0000000000000000", output_path=out_path, approved=True
        )
        self.assertFalse(forged["ok"])
        self.assertEqual(forged["error_code"], "invalid_or_expired_plan")

        # Path traversal -> refused
        trav = smp_tools.smp_start_export(
            plan_id=plan_id, output_path=os.path.join(self.tmp, "..", "escape.smp"), approved=True
        )
        self.assertFalse(trav["ok"])
        self.assertEqual(trav["error_code"], "path_traversal")

        # Symlink target -> refused
        link_path = os.path.join(self.tmp, "link.smp")
        real_target = os.path.join(self.tmp, "real.smp")
        os.symlink(real_target, link_path)
        sym = smp_tools.smp_start_export(plan_id=plan_id, output_path=link_path, approved=True)
        self.assertFalse(sym["ok"])
        self.assertEqual(sym["error_code"], "symlink_rejected")

        # Existing output without overwrite=True -> refused
        existing = os.path.join(self.tmp, "exists.smp")
        with open(existing, "wb") as fh:
            fh.write(b"old")
        ow = smp_tools.smp_start_export(
            plan_id=plan_id, output_path=existing, approved=True, overwrite=False
        )
        self.assertFalse(ow["ok"])
        self.assertEqual(ow["error_code"], "output_exists")

        # Mutate memory layer feature -> plan becomes stale!
        self.public_layer.setOpacity(0.5)
        stale = smp_tools.smp_start_export(plan_id=plan_id, output_path=out_path, approved=True)
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["error_code"], "stale_plan")

    def test_remote_render_failure_cleans_partial_output(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
        )
        self.assertTrue(est["ok"])
        out_path = os.path.join(self.tmp, "failed_remote.smp")
        with patch.object(
            smp_exporter.SMPGenerator,
            "generate_smp_from_canvas",
            side_effect=RuntimeError("Remote XYZ provider returned HTTP 503"),
        ):
            started = smp_tools.smp_start_export(
                plan_id=est["plan_id"],
                output_path=out_path,
                approved=True,
            )
            self.assertTrue(started["ok"])
            deadline = __import__("time").monotonic() + 10.0
            st = None
            while __import__("time").monotonic() < deadline:
                st = smp_tools.smp_export_status(started["job_id"])
                if st["state"] in ("completed", "failed", "cancelled"):
                    break
                app.processEvents()
                __import__("time").sleep(0.02)
            self.assertEqual(st["state"], "failed")
            self.assertIn("503", st["error"])
            self.assertFalse(os.path.exists(out_path))
            self.assertEqual([f for f in os.listdir(self.tmp) if ".smp.tmp" in f], [])

    def test_validator_rejects_unsafe_zip_and_cache_leak(self):
        bad_zip = os.path.join(self.tmp, "bad.smp")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("VERSION", "1.0")
            zf.writestr("style.json", json.dumps({"version": 8, "sources": {}, "metadata": {}}))
            zf.writestr("../evil.png", b"notpng")
            zf.writestr("s/0/_cache_meta.json", "{}")
        val = smp_tools.smp_validate_file(bad_zip, run_external=False)
        self.assertFalse(val["valid"])
        joined = "\n".join(val["issues"])
        self.assertIn("Unsafe ZIP entry path", joined)
        self.assertIn("_cache_meta.json", joined)

    def test_api_cli_mcp_schema_parity_and_i18n_tool_names(self):
        api_names = {s["name"] for s in tools_mod.anthropic_tool_list(include_gee=False)}
        all_names = {s["name"] for s in tools_mod.tool_specs()}
        self.assertTrue(EXPECTED_SMP_TOOLS.issubset(api_names))
        self.assertTrue(EXPECTED_SMP_TOOLS.issubset(all_names))

        # MCP tools/list + tools/call parity
        bridge = object.__new__(mcp_server._RpcServer)
        bridge.toolkit = Mock(iface=None)
        bridge.executor = None
        list_resp = bridge.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        mcp_names = {t["name"] for t in list_resp["result"]["tools"]}
        self.assertTrue(EXPECTED_SMP_TOOLS.issubset(mcp_names))

        call_resp = bridge.handle_rpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "smp_inspect_map", "arguments": {}},
        })
        self.assertFalse(call_resp["result"]["isError"])
        payload = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])

        # GUI humanized labels in EN & PT-BR
        self.assertEqual(formatting.humanize_tool_name("smp_inspect_map"), "Inspect SMP map")
        translator = i18n_mod.load_plugin_translator("pt_BR")
        self.assertIsNotNone(translator)
        QCoreApplication.installTranslator(translator)
        self.addCleanup(QCoreApplication.removeTranslator, translator)
        self.assertEqual(formatting.humanize_tool_name("smp_inspect_map"), "Inspecionar mapa SMP")

    def test_no_duplicate_comapeo_smp_provider(self):
        reg = QgsApplication.processingRegistry()
        provider_ids = {p.id() for p in reg.providers()}
        self.assertNotIn("comapeo_smp", provider_ids)


if __name__ == "__main__":
    unittest.main()
