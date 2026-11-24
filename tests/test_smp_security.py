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
                approval_callback=lambda _s: True,
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
        bridge.toolkit = Mock(iface=None, spec=["iface"])
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

    def test_trusted_human_approval_required_across_dispatch_and_mcp(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
        )
        self.assertTrue(est["ok"])
        out_path = os.path.join(self.tmp, "trusted.smp")

        # 1. Direct Python call with approved=True & confirm=True alone MUST fail closed
        no_cb = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=out_path,
            approved=True,
            confirm=True,
        )
        self.assertFalse(no_cb["ok"])
        self.assertEqual(no_cb["error_code"], "trusted_approval_required")
        self.assertFalse(os.path.exists(out_path))

        # 2. MCP / dispatch call without interactive _ask_user MUST fail closed
        bridge = object.__new__(mcp_server._RpcServer)
        bridge.toolkit = Mock(iface=None, spec=["iface"])
        bridge.executor = None
        mcp_deny = bridge.handle_rpc({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "smp_start_export",
                "arguments": {
                    "plan_id": est["plan_id"],
                    "output_path": out_path,
                    "approved": True,
                    "approval_callback": "forged",
                },
            },
        })
        self.assertTrue(mcp_deny["result"]["isError"])
        deny_payload = json.loads(mcp_deny["result"]["content"][0]["text"])
        self.assertEqual(deny_payload["error_code"], "trusted_approval_required")

        # 3. Toolkit with _ask_user returning cancel/deny refuses export
        tk_deny = Mock(iface=None)
        tk_deny.confirm_external_access.return_value = None
        tk_deny._ask_user.return_value = {"choice": "deny_export", "free_text": None, "cancelled": False}
        res_deny = tools_mod.dispatch(
            tk_deny, None, "smp_start_export",
            {"plan_id": est["plan_id"], "output_path": out_path, "approved": True},
        )
        self.assertFalse(res_deny["ok"])
        self.assertEqual(res_deny["error_code"], "user_approval_denied")
        tk_deny._ask_user.assert_called_once()
        # allow_free_text=False enforced
        self.assertFalse(tk_deny._ask_user.call_args[0][2])
        self.assertIn(est["plan_id"], tk_deny._ask_user.call_args[0][0])

        # 4. Toolkit with _ask_user returning exact approve_export choice succeeds
        tk_ok = Mock(iface=None)
        tk_ok.confirm_external_access.return_value = None
        tk_ok._ask_user.return_value = {"choice": "approve_export", "free_text": None, "cancelled": False}
        res_ok = tools_mod.dispatch(
            tk_ok, None, "smp_start_export",
            {"plan_id": est["plan_id"], "output_path": out_path, "approved": True},
        )
        self.assertTrue(res_ok["ok"], res_ok)
        deadline = __import__("time").monotonic() + 10.0
        while __import__("time").monotonic() < deadline:
            st = smp_tools.smp_export_status(res_ok["job_id"])
            if st["state"] in ("completed", "failed", "cancelled"):
                break
            app.processEvents()
            __import__("time").sleep(0.02)
        self.assertEqual(st["state"], "completed", st)

    def test_no_clobber_race_and_exclusive_manifest_safety(self):
        est = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
        )
        self.assertTrue(est["ok"])
        out_path = os.path.join(self.tmp, "race_target.smp")
        orig_validate = smp_exporter.validate_file

        def _create_target_mid_render(path, run_external=False):
            res = orig_validate(path, run_external=run_external)
            # Simulate a concurrent file appearing at out_path before final commit
            with open(out_path, "wb") as fh:
                fh.write(b"EXISTING_PROTECTED")
            return res

        with patch.object(smp_exporter, "validate_file", side_effect=_create_target_mid_render):
            started = smp_tools.smp_start_export(
                plan_id=est["plan_id"],
                output_path=out_path,
                approved=True,
                overwrite=False,
                approval_callback=lambda _s: True,
            )
            self.assertTrue(started["ok"], started)
            deadline = __import__("time").monotonic() + 10.0
            while __import__("time").monotonic() < deadline:
                st = smp_tools.smp_export_status(started["job_id"])
                if st["state"] in ("completed", "failed", "cancelled"):
                    break
                app.processEvents()
                __import__("time").sleep(0.02)

        self.assertEqual(st["state"], "failed", st)
        self.assertEqual(Path(out_path).read_bytes(), b"EXISTING_PROTECTED")
        self.assertFalse(os.path.exists(out_path + ".manifest.json"))

        # Symlink at sidecar manifest path must be refused
        sym_smp = os.path.join(self.tmp, "sym_man.smp")
        os.symlink(os.path.join(self.tmp, "real_man.json"), sym_smp + ".manifest.json")
        sym_res = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=sym_smp,
            approved=True,
            overwrite=True,
            approval_callback=lambda _s: True,
        )
        self.assertFalse(sym_res["ok"])
        self.assertEqual(sym_res["error_code"], "symlink_rejected")

    def test_tile_limit_and_disk_budget_rejection(self):
        # Plan exceeding tile cap -> rejected before queuing
        huge = smp_tools.smp_estimate(
            local_bounds=[-65.0, -10.0, -55.0, 0.0],
            local_min_zoom=10,
            local_max_zoom=16,
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(huge["ok"])
        self.assertGreater(huge["tile_counts"]["total"], smp_estimator.DEFAULT_MAX_EXPORT_TILES)
        huge_res = smp_tools.smp_start_export(
            plan_id=huge["plan_id"],
            output_path=os.path.join(self.tmp, "huge.smp"),
            approved=True,
            approval_callback=lambda _s: True,
        )
        self.assertFalse(huge_res["ok"])
        self.assertEqual(huge_res["error_code"], "tile_limit_exceeded")

        # Insufficient disk budget -> rejected before queuing
        small = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
            sample=False,
        )
        self.assertTrue(small["ok"])
        FakeUsage = type("FakeUsage", (), {"total": 1000, "used": 999, "free": 1024})
        with patch.object(smp_exporter.shutil, "disk_usage", return_value=FakeUsage()):
            disk_res = smp_tools.smp_start_export(
                plan_id=small["plan_id"],
                output_path=os.path.join(self.tmp, "nodisk.smp"),
                approved=True,
                approval_callback=lambda _s: True,
            )
        self.assertFalse(disk_res["ok"])
        self.assertEqual(disk_res["error_code"], "insufficient_disk_space")

    def test_sampling_refused_for_unapproved_restricted_and_online_layers(self):
        restricted = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string(40)", "restr_sample", "memory")
        restricted.setCustomProperty("awanagis/export_policy", "restricted")
        self.project.addMapLayer(restricted)

        est_r = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            sample=True,
        )
        self.assertTrue(est_r["ok"])
        self.assertEqual(est_r["sampling_blocked_reason"], "restricted_sampling_unapproved")
        self.assertEqual(est_r["calibration"], "uncalibrated_rough")
        self.assertIsNone(est_r["sample_stats"])
        self.project.removeMapLayer(restricted.id())

        xyz_layer = QgsRasterLayer("type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png", "osm_online", "wms")
        self.project.addMapLayer(xyz_layer)
        est_o = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            sample=True,
        )
        self.assertTrue(est_o["ok"])
        self.assertEqual(est_o["sampling_blocked_reason"], "online_sampling_unapproved")
        self.assertEqual(est_o["calibration"], "uncalibrated_rough")
        self.assertIsNone(est_o["sample_stats"])

    def test_validator_catches_missing_tiles_out_of_range_and_oversized_entries(self):
        # Generate a valid 2-tile fixture copy, then remove 1 tile and test
        fixture = ROOT / "tests" / "fixtures" / "smp" / "sample_local_only.smp"
        with zipfile.ZipFile(fixture, "r") as zin:
            entries = {n: zin.read(n) for n in zin.namelist()}
        tile_keys = sorted(k for k in entries if k.startswith("s/"))
        self.assertGreaterEqual(len(tile_keys), 2)

        missing_zip = os.path.join(self.tmp, "missing_tile.smp")
        with zipfile.ZipFile(missing_zip, "w") as zout:
            for k, data in entries.items():
                if k == tile_keys[-1]:
                    continue
                zout.writestr(k, data)
        val_missing = smp_tools.smp_validate_file(missing_zip, run_external=False)
        self.assertFalse(val_missing["valid"])
        self.assertTrue(any("missing" in iss.lower() for iss in val_missing["issues"]), val_missing["issues"])

        # Out-of-range coordinate tile
        oor_zip = os.path.join(self.tmp, "oor_tile.smp")
        with zipfile.ZipFile(oor_zip, "w") as zout:
            for k, data in entries.items():
                zout.writestr(k, data)
            zout.writestr("s/0/10/0/0.png", entries[tile_keys[0]])
        val_oor = smp_tools.smp_validate_file(oor_zip, run_external=False)
        self.assertFalse(val_oor["valid"])
        self.assertTrue(any("outside declared bounds" in iss.lower() for iss in val_oor["issues"]), val_oor["issues"])

        # Oversized style.json detected via ZipInfo.file_size BEFORE zf.read()
        fake_info = Mock(filename="style.json", file_size=50 * 1024 * 1024)
        fake_ver = Mock(filename="VERSION", file_size=3)
        fake_zf = Mock()
        fake_zf.__enter__ = Mock(return_value=fake_zf)
        fake_zf.__exit__ = Mock(return_value=False)
        fake_zf.infolist.return_value = [fake_ver, fake_info]
        fake_zf.read.side_effect = lambda name: b"1.0" if name == "VERSION" else (_ for _ in ()).throw(AssertionError("Should not read oversized style.json!"))
        fake_path = os.path.join(self.tmp, "bomb.smp")
        Path(fake_path).write_bytes(b"PK")
        with patch("zipfile.ZipFile", return_value=fake_zf):
            val_bomb = smp_tools.smp_validate_file(fake_path, run_external=False)
        self.assertFalse(val_bomb["valid"])
        self.assertTrue(any("exceeds" in iss.lower() for iss in val_bomb["issues"]), val_bomb["issues"])
        fake_zf.testzip.assert_not_called()

    def test_online_sampling_requires_trusted_user_approval_and_inspector_redacts_blocked_coords(self):
        # P2 #4: blocked_sensitive layer must never leak extent or selection coordinates in smp_inspect_map
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

        blocked = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "isolated_pt", "memory")
        blocked.setCustomProperty("awanagis/export_policy", "blocked_sensitive")
        feat = QgsFeature(blocked.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-62.1234, -4.5678)))
        feat.setAttributes(["secret_camp"])
        blocked.dataProvider().addFeatures([feat])
        blocked.updateExtents()
        blocked.selectAll()
        self.project.addMapLayer(blocked)

        info = smp_tools.smp_inspect_map(iface=None)
        self.assertTrue(info["ok"])
        vis = next(v for v in info["visible_layers"] if v["id"] == blocked.id())
        self.assertTrue(vis["extent"].get("redacted"))
        self.assertIsNone(vis["extent"]["bounds_wgs84"])
        self.assertIsNone(vis["extent"]["bounds_layer_crs"])
        self.assertEqual(vis["selected_count"], 0)
        if info["selection_extent"] is not None:
            self.assertNotIn(blocked.id(), info["selection_extent"]["layer_ids"])
        self.project.removeMapLayer(blocked.id())

        # P2 #3: caller-supplied allow_online_sampling=True + forged _trusted_sampling_approved
        # cannot trigger online tile rendering without trusted _ask_user confirmation.
        xyz_layer = QgsRasterLayer("type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png", "osm_online", "wms")
        self.project.addMapLayer(xyz_layer)

        tk_no_prompt = Mock(iface=None, spec=["iface"])
        res_no_prompt = smp_tools.dispatch_smp_tool(
            tk_no_prompt,
            None,
            "smp_estimate",
            {
                "local_bounds": [-60.1, -3.1, -60.0, -3.0],
                "local_min_zoom": 10,
                "local_max_zoom": 10,
                "sample": True,
                "allow_online_sampling": True,
                "_trusted_sampling_approved": True,
            },
        )
        self.assertTrue(res_no_prompt["ok"])
        self.assertEqual(res_no_prompt["calibration"], "uncalibrated_rough")
        self.assertEqual(res_no_prompt["sampling_blocked_reason"], "online_sampling_unapproved")

        tk_denied = Mock(iface=None)
        tk_denied._ask_user.return_value = {"choice": "deny_sampling", "cancelled": False}
        res_denied = smp_tools.dispatch_smp_tool(
            tk_denied,
            None,
            "smp_estimate",
            {
                "local_bounds": [-60.1, -3.1, -60.0, -3.0],
                "local_min_zoom": 10,
                "local_max_zoom": 10,
                "sample_mode": "small",
                "allow_online_sampling": True,
            },
        )
        self.assertTrue(res_denied["ok"])
        self.assertEqual(res_denied["sampling_blocked_reason"], "online_sampling_unapproved")
        tk_denied._ask_user.assert_called_once()

    def test_large_memory_layer_geometry_edit_invalidates_plan_and_manifest_rollback(self):
        # P2 #5: editing geometry on >2000-feature memory layer changes project_fingerprint
        from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

        big = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "big_mem", "memory")
        feats = []
        for i in range(2050):
            f = QgsFeature(big.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-60.05 + (i % 50) * 0.001, -3.05 + (i // 50) * 0.001)))
            f.setAttributes([i])
            feats.append(f)
        big.dataProvider().addFeatures(feats)
        big.updateExtents()
        self.project.addMapLayer(big)

        est = smp_tools.smp_estimate(
            local_bounds=[-60.06, -3.06, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
        )
        self.assertTrue(est["ok"])

        # Move one feature without changing feature count
        f0 = next(big.getFeatures())
        big.dataProvider().changeGeometryValues({f0.id(): QgsGeometry.fromPointXY(QgsPointXY(-59.99, -2.99))})
        big.updateExtents()

        out_smp = os.path.join(self.tmp, "stale_big.smp")
        res_stale = smp_tools.smp_start_export(
            plan_id=est["plan_id"],
            output_path=out_smp,
            approved=True,
            approval_callback=lambda _s: True,
        )
        self.assertFalse(res_stale["ok"])
        self.assertEqual(res_stale["error_code"], "stale_plan")
        self.project.removeMapLayer(big.id())

        # P2 #6: if manifest appears mid-render when overwrite=False, .smp archive is NOT published
        small_layer = QgsVectorLayer("Point?crs=EPSG:4326&field=name:string", "small_ok", "memory")
        self.project.addMapLayer(small_layer)
        est2 = smp_tools.smp_estimate(
            local_bounds=[-60.1, -3.1, -60.0, -3.0],
            local_min_zoom=10,
            local_max_zoom=10,
            output_dir=self.tmp,
        )
        out_coll = os.path.join(self.tmp, "manifest_collision.smp")
        orig_validate = smp_exporter.validate_file

        def _create_manifest_mid_render(path, run_external=False):
            res = orig_validate(path, run_external=run_external)
            Path(out_coll + ".manifest.json").write_text('{"existing": true}', encoding="utf-8")
            return res

        with patch.object(smp_exporter, "validate_file", side_effect=_create_manifest_mid_render):
            started = smp_tools.smp_start_export(
                plan_id=est2["plan_id"],
                output_path=out_coll,
                approved=True,
                overwrite=False,
                approval_callback=lambda _s: True,
            )
            self.assertTrue(started["ok"], started)
            deadline = __import__("time").monotonic() + 10.0
            while __import__("time").monotonic() < deadline:
                st = smp_tools.smp_export_status(started["job_id"])
                if st["state"] in ("completed", "failed", "cancelled"):
                    break
                app.processEvents()
                __import__("time").sleep(0.02)
        self.assertEqual(st["state"], "failed", st)
        self.assertFalse(os.path.exists(out_coll), "Archive should not be published when manifest collision fails")

    def test_validator_rejects_external_source_url_and_mismatched_tile_template(self):
        # P2 #7: style.json external source URL and mismatched tile template must fail validation
        fixture = ROOT / "tests" / "fixtures" / "smp" / "sample_local_only.smp"
        with zipfile.ZipFile(fixture, "r") as zin:
            entries = {n: zin.read(n) for n in zin.namelist()}

        style = json.loads(entries["style.json"].decode("utf-8"))
        bad_url_style = json.loads(json.dumps(style))
        first_sid = next(iter(bad_url_style["sources"]))
        bad_url_style["sources"][first_sid]["url"] = "https://example.com/tiles.json"
        bad_url_zip = os.path.join(self.tmp, "bad_src_url.smp")
        with zipfile.ZipFile(bad_url_zip, "w") as zout:
            for k, data in entries.items():
                zout.writestr(k, json.dumps(bad_url_style).encode("utf-8") if k == "style.json" else data)
        v1 = smp_tools.smp_validate_file(bad_url_zip, run_external=False)
        self.assertFalse(v1["valid"])
        self.assertTrue(any("external url" in i.lower() for i in v1["issues"]), v1["issues"])

        bad_tpl_style = json.loads(json.dumps(style))
        bad_tpl_style["sources"][first_sid]["tiles"] = ["smp://maps.v1/s/99/{z}/{x}/{y}.png"]
        bad_tpl_zip = os.path.join(self.tmp, "bad_tpl.smp")
        with zipfile.ZipFile(bad_tpl_zip, "w") as zout:
            for k, data in entries.items():
                zout.writestr(k, json.dumps(bad_tpl_style).encode("utf-8") if k == "style.json" else data)
        v2 = smp_tools.smp_validate_file(bad_tpl_zip, run_external=False)
        self.assertFalse(v2["valid"])
        self.assertTrue(any("does not match smp:sourcefolders" in i.lower() for i in v2["issues"]), v2["issues"])


if __name__ == "__main__":
    unittest.main()
