"""Negative security, Indigenous data governance, permission, and redaction tests.

All coordinate fixtures in this module are strictly synthetic non-real coordinates.
"""

from importlib import import_module
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name
catalog = import_module(f"{PKG}.integrations.brazil.catalog")
planner = import_module(f"{PKG}.integrations.brazil.planner")
policy = import_module(f"{PKG}.integrations.brazil.policy")
br_tools = import_module(f"{PKG}.integrations.brazil.tools")
core_tools = import_module(f"{PKG}.core.tools")
Config = import_module(f"{PKG}.config").Config
QgisToolkit = import_module(f"{PKG}.core.toolkit").QgisToolkit
i18n = import_module(f"{PKG}.i18n")

# Strictly synthetic, non-real coordinates for negative security testing
SYNTHETIC_SENSITIVE_LAT = -5.123456
SYNTHETIC_SENSITIVE_LON = -50.654321


class _InlineExecutor:
    def run_sync(self, fn):
        return fn()


class BrazilSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def setUp(self):
        planner.clear_plans()
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = Path(self.temp_dir.name)
        self.area = br_tools.br_resolve_area(type="municipality", ibge_code="1507300")["area"]

    def test_blocked_sensitive_and_discovery_only_across_probe_plan_execute(self):
        restricted_cases = [
            ("mapi_isolated_peoples", "blocked_sensitive"),
            ("mapi_povos_isolados", "blocked_sensitive"),
            ("ibge_indigenous_localities_2022", "discovery_only"),
            ("funai_indigenous_villages", "discovery_only"),
            ("funai_villages", "discovery_only"),
            ("funai_ti_studies", "discovery_only"),
            ("isa_territories", "portal_only"),
            ("raisg_indigenous_territories", "portal_only"),
            ("mapbiomas_alerta", "portal_only"),
        ]

        # 1) Probing must never call network and must return blocked/discovery/portal status
        with patch.object(catalog.urllib.request, "urlopen", side_effect=AssertionError("Probe must not hit network")):
            for sid, expected_status in restricted_cases:
                with self.subTest(stage="probe", sid=sid):
                    det = br_tools.br_source_details([sid], probe=True)
                    self.assertTrue(det["ok"])
                    self.assertEqual(det["sources"][0]["status"], expected_status)
                    self.assertFalse(det["sources"][0]["machine_access_verified"])

        # 2) Planning must produce no executable plan_id even with include_non_government=True
        gpkg = str(self.tmp / "out.gpkg")
        for sid, expected_status in restricted_cases:
            with self.subTest(stage="plan", sid=sid):
                plan = br_tools.br_plan_load(
                    [sid],
                    self.area,
                    output_gpkg=gpkg,
                    include_non_government=True,
                )
                self.assertTrue(plan["ok"])
                self.assertFalse(plan["can_execute"])
                self.assertIsNone(plan["plan_id"])
                self.assertEqual(plan["items"][0]["readiness"], "blocked")
                self.assertEqual(plan["items"][0]["reason_code"], expected_status)
                self.assertFalse(Path(gpkg).exists())

        # 3) Defense-in-depth: even if a forged plan entry exists in _PLAN_STORE, execute_load blocks it
        for sid, expected_status in restricted_cases:
            with self.subTest(stage="execute_forged", sid=sid):
                forged_id = f"forged_{sid}"
                planner._PLAN_STORE[forged_id] = {
                    "plan_id": forged_id,
                    "created_monotonic": 1e18,
                    "executable_ids": [sid],
                    "items": [{"source_id": sid, "readiness": "ready"}],
                    "area": self.area,
                    "output_gpkg": gpkg,
                    "replace_existing": False,
                    "include_non_government": True,
                    "years": {},
                }
                res = br_tools.br_execute_load(forged_id)
                self.assertFalse(res["ok"])
                self.assertEqual(res["results"][0]["status"], expected_status)
                self.assertEqual(res["results"][0]["layer_ids"], [])
                self.assertFalse(Path(gpkg).exists())

    def test_synthetic_coordinates_and_credentials_redacted_in_traces(self):
        fake_trace = (
            f"https://user:supersecret@geoserver.example.org/wfs?token=abc123 "
            f"failed near ({SYNTHETIC_SENSITIVE_LAT}, {SYNTHETIC_SENSITIVE_LON}) password=mysecret"
        )
        redacted = policy.redact_sensitive_text(fake_trace, redact_coordinates=True)
        self.assertNotIn("supersecret", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("mysecret", redacted)
        self.assertNotIn(str(SYNTHETIC_SENSITIVE_LAT), redacted)
        self.assertNotIn(str(SYNTHETIC_SENSITIVE_LON), redacted)
        self.assertIn("[REDACTED]", redacted)
        self.assertIn("[REDACTED_COORDS]", redacted)

        # Tool wrapper redacts coordinates/secrets if internal error occurs
        with patch.object(br_tools, "execute_load", side_effect=RuntimeError(fake_trace)):
            res = br_tools.br_execute_load("brplan_dummy")
            self.assertFalse(res["ok"])
            self.assertNotIn("supersecret", res["error"])
            self.assertNotIn(str(SYNTHETIC_SENSITIVE_LAT), res["error"])
            self.assertNotIn(str(SYNTHETIC_SENSITIVE_LON), res["error"])

    def test_url_allowlist_tls_path_traversal_zip_slip_and_cql(self):
        allowed = catalog.get_allowed_hosts()
        self.assertNotIn("evil.example.com", allowed)
        self.assertNotIn("terrasindigenas.org.br", allowed)
        self.assertNotIn("plataforma.povosisolados.org", allowed)

        bad_urls = [
            "",
            "file:///etc/passwd",
            "ftp://terrabrasilis.dpi.inpe.br/data.zip",
            "javascript:alert(1)",
            "https://evil.example.com/geoserver/ows",
            "https://user:pass@terrabrasilis.dpi.inpe.br/geoserver/ows",
        ]
        for bad in bad_urls:
            ok, _err = policy.validate_allowlisted_url(bad, allowed)
            self.assertFalse(ok, bad)

        ok, _err = policy.validate_allowlisted_url(
            "https://terrabrasilis.dpi.inpe.br/geoserver/ows",
            allowed,
            require_https=True,
        )
        self.assertTrue(ok)

        # Verify no TLS bypass exists anywhere in integrations/brazil (outside comments/docstrings)
        br_dir = ROOT / "integrations" / "brazil"
        for pyfile in br_dir.rglob("*.py"):
            txt = pyfile.read_text(encoding="utf-8")
            self.assertNotIn("verify=False", txt, str(pyfile))
            self.assertNotIn("CERT_NONE", txt, str(pyfile))
            self.assertNotIn("check_hostname = False", txt, str(pyfile))

        # Path traversal & unsafe extensions
        for bad_path in ("../outside.gpkg", "/tmp/a\x00b.gpkg", "/tmp/out.exe", ""):
            ok_p, _err_p, _res = policy.validate_safe_output_path(bad_path)
            self.assertFalse(ok_p, bad_path)

        # Zip-slip member checks
        for bad_member in ("../../etc/passwd", "/etc/shadow", "a\x00b.shp", ""):
            ok_m, _target = policy.validate_archive_member_path(bad_member, self.tmp)
            self.assertFalse(ok_m, bad_member)
        ok_good, target = policy.validate_archive_member_path("layer/data.shp", self.tmp)
        self.assertTrue(ok_good)
        self.assertTrue(str(target).startswith(str(self.tmp.resolve())))

        # CQL escaping & identifier validation
        escaped = policy.sanitize_cql_literal("Xingu'; DROP TABLE t; --\n")
        self.assertNotIn(";", escaped)
        self.assertNotIn("\n", escaped)
        self.assertIn("''", escaped)
        with self.assertRaises(ValueError):
            policy.validate_cql_identifier("bad field; 1=1")
        self.assertEqual(policy.validate_cql_identifier("terrai_cod"), "terrai_cod")

    def test_scope_uf_scale_year_non_gov_and_missing_destination(self):
        # Missing destination without saved project refuses to guess home/cwd
        no_dest = br_tools.br_plan_load(["inpe_prodes"], self.area, project_dir="")
        self.assertFalse(no_dest["ok"])
        self.assertEqual(no_dest["status"], "needs_destination")

        gpkg = str(self.tmp / "scope_check.gpkg")
        # Out-of-scope UF (DF-only schools for PA municipality)
        uf_plan = br_tools.br_plan_load(["df_escolas_publicas"], self.area, output_gpkg=gpkg)
        self.assertFalse(uf_plan["can_execute"])
        self.assertEqual(uf_plan["items"][0]["reason_code"], "out_of_scope_uf")

        # Non-government source blocked by default unless include_non_government=True
        nongov_default = br_tools.br_plan_load(["mapbiomas_cobertura"], self.area, output_gpkg=gpkg)
        self.assertFalse(nongov_default["can_execute"])
        self.assertEqual(nongov_default["items"][0]["reason_code"], "requires_non_government_opt_in")

        nongov_optin = br_tools.br_plan_load(
            ["mapbiomas_cobertura"], self.area, output_gpkg=gpkg, include_non_government=True
        )
        self.assertTrue(nongov_optin["can_execute"])
        self.assertIn("historical land cover", nongov_optin["items"][0]["warnings"][0])

        # Invalid year rejected
        bad_year = br_tools.br_plan_load(
            ["inpe_prodes"], self.area, output_gpkg=gpkg, years={"inpe_prodes": 1900}
        )
        self.assertFalse(bad_year["can_execute"])
        self.assertEqual(bad_year["items"][0]["reason_code"], "invalid_year")

        # Manual SIGEF marked manual
        sigef = br_tools.br_plan_load(["incra_sigef_parcelas"], self.area, output_gpkg=gpkg)
        self.assertFalse(sigef["can_execute"])
        self.assertEqual(sigef["items"][0]["readiness"], "manual")
        self.assertEqual(sigef["items"][0]["reason_code"], "manual_required")

        # Extra kwargs rejected by br_execute_load dispatch
        res_extra = core_tools.dispatch(
            object(),
            _InlineExecutor(),
            "br_execute_load",
            {"plan_id": "brplan_x", "url": "https://evil.example.com"},
        )
        self.assertFalse(res_extra["ok"])
        self.assertEqual(res_extra["status"], "invalid_input")

    def test_permission_gating_and_pre_cancellation(self):
        settings = QSettings(str(self.tmp / "perms.ini"), QSettings.Format.IniFormat)
        cfg = Config()
        cfg._s = settings
        cfg.set("external_access_always_allowed", False)
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=cfg)

        gpkg = str(self.tmp / "perm_test.gpkg")
        plan = br_tools.br_plan_load(["inpe_prodes"], self.area, output_gpkg=gpkg)
        self.assertTrue(plan["can_execute"])
        plan_id = plan["plan_id"]

        # Offline discovery & planning must NOT ask for external access
        ask_calls = []
        toolkit.set_ask_user_emitter(lambda q, opts, aft, req: ask_calls.append(q))
        self.assertIsNone(toolkit.confirm_external_access("br_search_sources", {"query": "PRODES"}))
        self.assertIsNone(toolkit.confirm_external_access("br_source_details", {"source_ids": ["inpe_prodes"], "probe": False}))
        self.assertIsNone(toolkit.confirm_external_access("br_resolve_area", {"type": "municipality", "ibge_code": "1507300"}))
        self.assertIsNone(toolkit.confirm_external_access("br_plan_load", {"source_ids": ["inpe_prodes"], "area": self.area}))
        self.assertEqual(ask_calls, [])

        # Deny blocks br_execute_load before any network/file mutation
        toolkit.set_ask_user_emitter(lambda *_: toolkit._resolve_ask_user({"choice": "Deny"}))
        with patch.object(br_tools, "execute_load", side_effect=AssertionError("Must not execute on Deny")):
            denied = core_tools.dispatch(
                toolkit, _InlineExecutor(), "br_execute_load", {"plan_id": plan_id}
            )
            self.assertFalse(denied["ok"])
            self.assertTrue(denied["cancelled"])
            self.assertIn("Permission denied", denied["error"])
            self.assertFalse(Path(gpkg).exists())
            self.assertFalse(cfg.get("external_access_always_allowed"))

        # Translated display label ("Permitir sempre") is NOT accepted as wire value
        translator = i18n.load_plugin_translator("pt_BR")
        self.assertIsNotNone(translator)
        QCoreApplication.installTranslator(translator)
        self.addCleanup(QCoreApplication.removeTranslator, translator)
        toolkit.set_ask_user_emitter(lambda *_: toolkit._resolve_ask_user({"choice": "Permitir sempre"}))
        denied_pt = core_tools.dispatch(
            toolkit, _InlineExecutor(), "br_execute_load", {"plan_id": plan_id}
        )
        self.assertFalse(denied_pt["ok"])
        self.assertTrue(denied_pt["cancelled"])
        self.assertFalse(cfg.get("external_access_always_allowed"))

        # Pre-cancelled should_stop prevents execution & writes no files
        cancelled = br_tools.br_execute_load(plan_id, should_stop=lambda: True)
        self.assertFalse(cancelled["ok"])
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertFalse(Path(gpkg).exists())

    def test_external_db_signaling_and_partial_offline_resilience(self):
        from unittest.mock import MagicMock
        from qgis.core import QgsProject

        wfs_mod = import_module(f"{PKG}.integrations.brazil.vendor.gisbr.core.connectors.wfs")
        gpkg = str(self.tmp / "resilience.gpkg")
        plan = br_tools.br_plan_load(["funai_ti_boundaries", "icmbio_uc"], self.area, output_gpkg=gpkg)
        self.assertTrue(plan["can_execute"])
        self.assertIn("geoserver.funai.gov.br", plan["external_db_notice"])
        self.assertEqual({d["source_id"] for d in plan["external_databases"]}, {"funai_ti_boundaries", "icmbio_uc"})

        # Permission prompts explicitly name the external DB hosts
        settings = QSettings(str(self.tmp / "perms2.ini"), QSettings.Format.IniFormat)
        cfg = Config()
        cfg._s = settings
        cfg.set("external_access_always_allowed", False)
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            tk = QgisToolkit(iface=None, config=cfg)
        reasons_exec = tk._external_access_reasons("br_execute_load", {"plan_id": plan["plan_id"]})
        self.assertIn("geoserver.funai.gov.br", reasons_exec[0])
        reasons_probe = tk._external_access_reasons(
            "br_source_details", {"source_ids": ["funai_ti_boundaries"], "probe": True}
        )
        self.assertIn("geoserver.funai.gov.br", reasons_probe[0])

        # Multi-source load: FUNAI times out/offline, ICMBio succeeds via local fixture -> partial success + signals
        uc_geojson = self.tmp / "uc_fixture.geojson"
        uc_geojson.write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"nome":"UC Test"},'
            '"geometry":{"type":"Polygon","coordinates":[[[-52.1,-6.7],[-51.9,-6.7],[-51.9,-6.5],[-52.1,-6.5],[-52.1,-6.7]]]}}]}',
            encoding="utf-8",
        )

        class _InvalidWfs:
            def __init__(self, msg):
                self.error_msg = msg
            def isValid(self):
                return False

        msg_bar = MagicMock()
        mock_iface = MagicMock()
        mock_iface.messageBar.return_value = msg_bar
        proj = QgsProject()
        with patch.object(
            wfs_mod,
            "fetch_layer",
            return_value=_InvalidWfs("Falha WFS (Funai:tis_poligonais, host: geoserver.funai.gov.br): Operation timed out"),
        ):
            res = br_tools.br_execute_load(
                plan["plan_id"],
                project=proj,
                local_fixtures={"icmbio_uc": str(uc_geojson)},
                iface=mock_iface,
            )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["offline_sources"], ["funai_ti_boundaries"])
        by_id = {r["source_id"]: r for r in res["results"]}
        self.assertEqual(by_id["funai_ti_boundaries"]["service_status"], "offline_timeout")
        self.assertEqual(by_id["funai_ti_boundaries"]["external_db"]["fallback_source_id"], "geobr_terras_indigenas")
        self.assertEqual(by_id["icmbio_uc"]["status"], "loaded")
        self.assertIn("geoserver.funai.gov.br", res["user_notice"])
        msg_bar.pushMessage.assert_called_once()


if __name__ == "__main__":
    unittest.main()
