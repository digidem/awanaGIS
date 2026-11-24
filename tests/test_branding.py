"""Comprehensive AwanaGIS branding, isolation, migration, icon, MCP, and packaging tests."""

from importlib import import_module
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch
import urllib.request
import zipfile

from PIL import Image
from qgis.PyQt.QtCore import QRectF, QSettings, Qt
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPalette
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication, QMainWindow, QMessageBox
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

brand = import_module(f"{ROOT.name}.gui.brand")
theme = import_module(f"{ROOT.name}.gui.theme")
config_mod = import_module(f"{ROOT.name}.config")
session_store = import_module(f"{ROOT.name}.core.session_store")
migration = import_module(f"{ROOT.name}.core.migration")
discovery = import_module(f"{ROOT.name}.server.discovery")
mcp_server = import_module(f"{ROOT.name}.server.mcp_server")
ChatDock = import_module(f"{ROOT.name}.gui.chat_dock").ChatDock
SettingsDialog = import_module(f"{ROOT.name}.gui.settings_dialog").SettingsDialog
package_plugin = import_module(f"{ROOT.name}.scripts.package_plugin")


class BrandTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def test_tokens_match_official_json_exactly(self):
        tokens_path = ROOT / "docs" / "branding" / "brand-tokens.json"
        data = json.loads(tokens_path.read_text(encoding="utf-8"))
        official = data["official"]

        self.assertEqual(dict(brand.OFFICIAL_PRIMARY), official["primary"])
        self.assertEqual(dict(brand.OFFICIAL_SECONDARY), official["secondary"])
        self.assertEqual(dict(brand.FONT_ROLES), official["font_roles"])
        for key, value in data["awanagis_proposals"]["light"].items():
            self.assertEqual(brand.LIGHT_PROPOSAL[key], value)
        self.assertEqual(brand.WCAG_AA_NORMAL_MIN, data["awanagis_proposals"]["contrast_normal_text_min"])
        self.assertEqual(brand.WCAG_AA_UI_MIN, data["awanagis_proposals"]["contrast_large_text_and_ui_min"])

    def test_wcag_aa_contrast_light_and_dark_palettes(self):
        light_pal = QPalette()
        light_pal.setColor(QPalette.ColorRole.Window, QColor("#FDF7EF"))
        light_pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
        light_pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F5ECE0"))
        light_pal.setColor(QPalette.ColorRole.WindowText, QColor("#1E1E1E"))

        dark_pal = QPalette()
        dark_pal.setColor(QPalette.ColorRole.Window, QColor("#202124"))
        dark_pal.setColor(QPalette.ColorRole.Base, QColor("#28292D"))
        dark_pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#313236"))
        dark_pal.setColor(QPalette.ColorRole.WindowText, QColor("#E8EAED"))

        self.assertFalse(brand.is_dark_palette(light_pal))
        self.assertTrue(brand.is_dark_palette(dark_pal))

        light_tok = brand.resolve_semantic_tokens(light_pal)
        self.assertFalse(light_tok["is_dark"])
        self.assertEqual(light_tok["canvas"], "#FDF7EF")
        self.assertEqual(light_tok["text"], "#6B0030")
        self.assertEqual(light_tok["accent"], "#8D003E")

        dark_tok = brand.resolve_semantic_tokens(dark_pal)
        self.assertTrue(dark_tok["is_dark"])
        self.assertEqual(dark_tok["canvas"], "#202124")

        for tok in (light_tok, dark_tok):
            for fg in ("text", "text_2", "text_3", "text_4", "blue", "warn", "success", "danger"):
                for bg in ("canvas", "surface", "surface_2", "input_bg"):
                    ratio = brand.contrast_ratio(tok[fg], tok[bg])
                    self.assertGreaterEqual(ratio, 4.5, f"{fg} on {bg} contrast {ratio:.2f} < 4.5")
            self.assertGreaterEqual(brand.contrast_ratio(tok["accent_text"], tok["accent"]), 4.5)
            self.assertGreaterEqual(brand.contrast_ratio(tok["danger_text"], tok["danger_bg"]), 4.5)
            self.assertGreaterEqual(brand.contrast_ratio(tok["highlight_fg"], tok["highlight"]), 4.5)
            self.assertGreaterEqual(brand.contrast_ratio(tok["border"], tok["surface_2"]), 3.0)

    def test_font_roles_fallback_and_curved_scrollbars(self):
        installed = {"Tomorrow", "Public Sans", "Space Grotesk"}
        self.assertEqual(brand.resolve_font_family("display", installed), "Tomorrow")
        self.assertEqual(brand.resolve_font_family("body", installed), "Public Sans")
        self.assertEqual(brand.resolve_font_family("caption", installed), "Space Grotesk")

        empty = set()
        for role in ("display", "body", "caption"):
            fallback = brand.resolve_font_family(role, empty)
            self.assertTrue(fallback)
            self.assertNotIn(fallback, ("Tomorrow", "Public Sans", "Space Grotesk"))

        qss = theme.curved_scrollbar_qss(thickness=10, handle_radius=4, include_horizontal=True)
        self.assertIn("border-radius: 4px", qss)
        self.assertIn("QScrollBar::handle:vertical", qss)
        self.assertIn("QScrollBar::handle:horizontal", qss)
        self.assertIn("background: transparent", qss)
        self.assertIn("width: 0px; height: 0px", qss)

    def test_settings_dialog_does_not_mutate_global_qapplication_stylesheet(self):
        app = QApplication.instance()
        before_qss = app.styleSheet()
        with TemporaryDirectory() as tmp:
            ini = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            cfg = config_mod.Config()
            cfg._s = ini
            dlg = SettingsDialog(cfg)
            self.addCleanup(dlg.close)
            self.assertEqual(app.styleSheet(), before_qss)
            self.assertEqual(dlg.windowTitle(), "AwanaGIS — Settings")


class IsolationAndMcpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def test_settings_session_and_discovery_isolation(self):
        self.assertEqual(config_mod._GROUP, "AwanaGIS")
        self.assertEqual(config_mod.DEFAULTS["mcp_port"], 0)
        self.assertEqual(config_mod.DEFAULTS["mcp_host"], "127.0.0.1")
        self.assertEqual(session_store.SETTINGS_KEY, "AwanaGIS/sessions_json")
        self.assertEqual(discovery.ENV_VAR, "AWANAGIS_MCP_DISCOVERY")
        self.assertTrue(discovery.discovery_path().endswith(os.path.join(".awanagis", "mcp.json")))

        with TemporaryDirectory() as tmp:
            ini = QSettings(str(Path(tmp) / "isolated.ini"), QSettings.Format.IniFormat)
            cfg = config_mod.Config()
            cfg._s = ini
            store = session_store.SessionStore(settings=ini)
            dock = ChatDock(
                lambda: None,
                lambda: None,
                lambda: None,
                toolkit=None,
                session_store=store,
                show_startup_picker=False,
            )
            self.addCleanup(dock.close)
            self.assertEqual(dock.windowTitle(), "AwanaGIS")
            self.assertEqual(dock.objectName(), "AwanaGisDock")

    def test_dynamic_mcp_bridge_tools_list_and_call(self):
        with TemporaryDirectory() as tmp:
            disc_file = Path(tmp) / "mcp.json"
            with patch.dict(os.environ, {"AWANAGIS_MCP_DISCOVERY": str(disc_file)}):
                toolkit = Mock()
                executor = Mock()
                server = mcp_server.McpBridgeServer(
                    toolkit, executor, host="127.0.0.1", port=0,
                    poll_interval=0.05, server_timeout=0.05,
                )
                server.start()
                self.addCleanup(server.stop)

                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and (not disc_file.is_file() or server._server is None):
                    time.sleep(0.02)

                self.assertGreater(server.port, 0)
                self.assertTrue(disc_file.is_file())
                entries = discovery.read_servers()
                self.assertTrue(any(e.get("url") == server.base_url for e in entries))

                def rpc(method, params=None, req_id=1):
                    payload = json.dumps({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "method": method,
                        "params": params or {},
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        server.base_url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        return json.loads(resp.read().decode("utf-8"))

                init_res = rpc("initialize", req_id=1)
                self.assertEqual(init_res["result"]["serverInfo"]["name"], "AwanaGIS")

                list_res = rpc("tools/list", req_id=2)
                tool_names = [t["name"] for t in list_res["result"]["tools"]]
                self.assertIn("list_layers", tool_names)
                self.assertIn("run_processing", tool_names)

                with patch.object(mcp_server.tools_mod, "dispatch", return_value={"ok": True, "layers": []}):
                    call_res = rpc("tools/call", {"name": "list_layers", "arguments": {}}, req_id=3)
                self.assertEqual(
                    json.loads(call_res["result"]["content"][0]["text"]),
                    {"ok": True, "layers": []},
                )


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def test_no_auto_migration_and_opt_in_excludes_secrets(self):
        with TemporaryDirectory() as tmp:
            ini_path = Path(tmp) / "coexist.ini"
            settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
            settings.setValue("AgenticGIS/provider", "openai")
            settings.setValue("AgenticGIS/model", "gpt-4o")
            settings.setValue("AgenticGIS/font_scale", 1.25)
            settings.setValue("AgenticGIS/api_key", "sk-secret-legacy")
            settings.setValue("AgenticGIS/custom_api_key", "sk-custom-secret")
            settings.setValue("AgenticGIS/external_access_always_allowed", True)
            settings.setValue("AgenticGIS/gee_always_allowed", True)
            settings.setValue("AgenticGIS/auto_run", False)
            settings.setValue("AgenticGIS/confirm_dangerous_calls", False)
            settings.setValue("AgenticGIS/mcp_enabled", False)
            settings.setValue("AgenticGIS/mcp_port", 7317)
            legacy_sessions = {
                "schema_version": 1,
                "active_session_id": "s1",
                "sessions": [{
                    "id": "s1",
                    "name": "Legacy mapping",
                    "created_at": "2026-10-01T00:00:00Z",
                    "updated_at": "2026-10-02T00:00:00Z",
                    "backend_history": [{"role": "user", "content": "hi"}],
                    "transcript_events": [{"type": "user", "text": "hi"}],
                    "backend_state": {},
                }],
            }
            settings.setValue("AgenticGIS/sessions_json", json.dumps(legacy_sessions))
            settings.sync()

            # Fresh AwanaGIS config/store never reads legacy values automatically.
            cfg = config_mod.Config()
            cfg._s = settings
            self.assertEqual(cfg.get("provider"), "anthropic")
            self.assertEqual(cfg.get("api_key"), "")
            self.assertEqual(cfg.get("mcp_port"), 0)
            self.assertFalse(cfg.get("external_access_always_allowed"))

            preview = migration.inspect_legacy_data(settings)
            self.assertTrue(preview["has_preferences"])
            self.assertTrue(preview["has_sessions"])
            self.assertEqual(preview["session_count"], 1)
            self.assertIn("api_key", preview["excluded_keys"])
            self.assertIn("external_access_always_allowed", preview["excluded_keys"])

            # SettingsDialog shows opt-in migration button only when legacy data exists.
            dlg = SettingsDialog(cfg)
            self.addCleanup(dlg.close)
            self.assertTrue(hasattr(dlg, "_import_legacy_btn"))

            result = migration.import_from_agenticgis(settings)
            self.assertTrue(result["ok"])
            self.assertEqual(cfg.get("provider"), "openai")
            self.assertEqual(cfg.get("model"), "gpt-4o")
            self.assertEqual(cfg.get("font_scale"), 1.25)

            # Secrets and security approvals are NEVER copied.
            self.assertEqual(cfg.get("api_key"), "")
            self.assertEqual(cfg.get("custom_api_key"), "")
            self.assertFalse(cfg.get("external_access_always_allowed"))
            self.assertFalse(cfg.get("gee_always_allowed"))
            self.assertTrue(cfg.get("auto_run"))
            self.assertTrue(cfg.get("confirm_dangerous_calls"))
            self.assertEqual(cfg.get("mcp_port"), 0)

            # Session merged idempotently; legacy data untouched.
            store = session_store.SessionStore(settings=settings)
            self.assertIsNotNone(store.get_session("s1"))
            second = migration.import_from_agenticgis(settings)
            self.assertEqual(second["sessions"]["imported_count"], 0)
            self.assertEqual(second["sessions"]["skipped_count"], 1)
            self.assertEqual(settings.value("AgenticGIS/api_key"), "sk-secret-legacy")

    def test_corrupt_legacy_session_fails_safely(self):
        with TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "bad.ini"), QSettings.Format.IniFormat)
            settings.setValue("AgenticGIS/sessions_json", "{not valid json")
            res = migration.import_sessions_from_agenticgis(settings)
            self.assertFalse(res["ok"])
            self.assertTrue(res["error"])

    def test_corrupt_target_session_fails_safely(self):
        with TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "bad.ini"), QSettings.Format.IniFormat)
            settings.setValue("AgenticGIS/sessions_json", json.dumps({"sessions": [{"id": "s1"}]}))
            for raw in ("{not valid json", json.dumps({"unknown": []})):
                with self.subTest(raw=raw):
                    settings.setValue(session_store.SETTINGS_KEY, raw)
                    res = migration.import_sessions_from_agenticgis(settings)
                    self.assertFalse(res["ok"])
                    self.assertTrue(res["error"])
                    self.assertEqual(settings.value(session_store.SETTINGS_KEY), raw)

    def test_import_sessions_preserves_existing_awanagis_chats_at_capacity(self):
        with TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "cap.ini"), QSettings.Format.IniFormat)
            existing = [
                {
                    "id": f"aw-{i}",
                    "name": f"Awana {i}",
                    "created_at": f"2026-09-{i+1:02d}T00:00:00Z",
                    "updated_at": f"2026-09-{i+1:02d}T00:00:00Z",
                    "backend_history": [],
                    "transcript_events": [],
                    "backend_state": {},
                }
                for i in range(18)
            ]
            settings.setValue(
                session_store.SETTINGS_KEY,
                json.dumps({"schema_version": 1, "active_session_id": "aw-0", "sessions": existing}),
            )
            legacy = [
                {
                    "id": f"leg-{i}",
                    "name": f"Legacy {i}",
                    "created_at": f"2026-11-{i+1:02d}T00:00:00Z",
                    "updated_at": f"2026-11-{i+1:02d}T00:00:00Z",
                    "backend_history": [],
                    "transcript_events": [],
                    "backend_state": {},
                }
                for i in range(5)
            ]
            settings.setValue(
                migration.LEGACY_SESSIONS_KEY,
                json.dumps({"schema_version": 1, "active_session_id": "leg-0", "sessions": legacy}),
            )
            settings.sync()

            res = migration.import_sessions_from_agenticgis(settings, limit=20)
            self.assertTrue(res["ok"])
            self.assertEqual(res["imported_count"], 2)
            self.assertEqual(res["dropped_count"], 3)

            store = session_store.SessionStore(settings=settings, limit=20)
            ids = {item["id"] for item in store.list_sessions()}
            self.assertEqual(len(ids), 20)
            for i in range(18):
                self.assertIn(f"aw-{i}", ids)
            self.assertIn("leg-4", ids)
            self.assertIn("leg-3", ids)

    def test_live_session_store_import_and_font_scale_refresh(self):
        with TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "live.ini"), QSettings.Format.IniFormat)
            settings.setValue("AgenticGIS/font_scale", 1.5)
            settings.setValue("AgenticGIS/provider", "openai")
            settings.setValue("AgenticGIS/model", "gpt-4o-mini")
            settings.setValue(
                migration.LEGACY_SESSIONS_KEY,
                json.dumps({
                    "schema_version": 1,
                    "active_session_id": "leg-live",
                    "sessions": [{
                        "id": "leg-live",
                        "name": "Imported Live Chat",
                        "created_at": "2026-10-10T00:00:00Z",
                        "updated_at": "2026-10-10T00:00:00Z",
                        "backend_history": [{"role": "user", "content": "hello"}],
                        "transcript_events": [{"type": "user", "text": "hello"}],
                        "backend_state": {},
                    }],
                }),
            )
            settings.sync()

            cfg = config_mod.Config()
            cfg._s = settings
            store = session_store.SessionStore(settings=settings)
            dock = ChatDock(
                lambda: None,
                lambda: None,
                lambda: None,
                toolkit=None,
                session_store=store,
                show_startup_picker=False,
            )
            self.addCleanup(dock.close)
            active_id = dock._active_session_id
            # Simulate an un-flushed debounced edit before opening Settings.
            store.schedule_save(
                active_id,
                transcript_events=[{"type": "user", "text": "unsaved edit"}],
            )

            dlg = SettingsDialog(cfg, session_store=store)
            self.addCleanup(dlg.close)
            self.assertEqual(dlg.font_scale_combo.currentData(), 1.0)

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                 patch.object(QMessageBox, "information"):
                dlg._import_from_agenticgis()

            self.assertTrue(dlg.sessions_imported)
            self.assertEqual(dlg.font_scale_combo.currentData(), 1.5)

            # Saving immediately after import must keep imported 1.5 scale, not stale 1.0.
            dlg.api_key_edit.setText("sk-test-only")
            with patch.object(QMessageBox, "warning") as warn_mock:
                dlg._save_and_accept()
            warn_mock.assert_not_called()
            self.assertEqual(cfg.get("font_scale"), 1.5)

            dock.refresh_sessions()
            ids = {s["id"] for s in dock._session_store.list_sessions()}
            self.assertIn("leg-live", ids)
            self.assertIn(active_id, ids)
            self.assertEqual(
                dock._session_store.get_session(active_id)["transcript_events"],
                [{"type": "user", "text": "unsaved edit"}],
            )


class ResidualBrandAndAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def test_residual_agenticgis_references_strictly_classified(self):
        allowed_files = {
            "LICENSE",
            "LICENSES/GPL-2.0.txt",
            "NOTICE",
            "THIRD_PARTY_LICENSES.md",
            "README.md",
            "REBRAND_AUDIT.md",
            "metadata.txt",
            "core/migration.py",
            "core/toolkit.py",
            "backends/adapters.py",
            "gui/formatting.py",
            "gui/settings_dialog.py",
            "i18n/awanagis_pt_BR.ts",
            "resources/ASSET_PROVENANCE.md",
            "integrations/brazil/VENDOR_ATTRIBUTION.md",
            "integrations/smp/policy.py",
        }
        pattern = re.compile(r"agenticgis", re.IGNORECASE)
        unexpected = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel == ".git" or rel.startswith(("docs/", "tests/", "graft/", ".git/", "dist/")):
                continue
            if path.suffix in (".pyc", ".pyo", ".qm", ".png", ".zip"):
                continue
            if rel in allowed_files:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for idx, line in enumerate(text.splitlines(), 1):
                if rel == "ci/qgis_zip_smoke.py" and 'tag in ("AwanaGIS", "AgenticGIS")' in line:
                    continue  # Legacy log tag remains a smoke-test failure.
                if pattern.search(line):
                    unexpected.append(f"{rel}:{idx}: {line.strip()}")
        self.assertEqual(unexpected, [], f"Unexpected AgenticGIS hits: {unexpected}")

    def test_icon_readability_and_provenance(self):
        svg_path = ROOT / "resources" / "icon.svg"
        png_path = ROOT / "resources" / "icon.png"
        prov_path = ROOT / "resources" / "ASSET_PROVENANCE.md"
        self.assertTrue(svg_path.is_file())
        self.assertTrue(png_path.is_file())
        self.assertTrue(prov_path.is_file())

        prov_text = prov_path.read_text(encoding="utf-8").lower()
        self.assertIn("approved", prov_text)
        self.assertIn("awana digital", prov_text)

        self.assertLess(png_path.stat().st_size, 25_000)
        with Image.open(png_path) as pil_img:
            self.assertEqual(pil_img.size, (128, 128))

        base_qimg = QImage(str(png_path))
        self.assertFalse(base_qimg.isNull())
        renderer = QSvgRenderer(str(svg_path))
        self.assertTrue(renderer.isValid())

        for size in (16, 24, 32, 64, 128):
            scaled = base_qimg.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            trans_px = 0
            burg_px = 0
            for y in range(size):
                for x in range(size):
                    c = scaled.pixelColor(x, y)
                    if c.alpha() < 20:
                        trans_px += 1
                    elif c.alpha() >= 180 and c.red() >= 80 and c.green() <= 50:
                        burg_px += 1
            self.assertGreater(trans_px, 0, f"No transparent background pixels in PNG at {size}x{size}")
            self.assertGreater(burg_px, 0, f"No burgundy foreground pixels in PNG at {size}x{size}")

            svg_img = QImage(size, size, QImage.Format.Format_ARGB32)
            svg_img.fill(Qt.GlobalColor.transparent)
            painter = QPainter(svg_img)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            svg_burg = sum(
                1
                for y in range(size)
                for x in range(size)
                if svg_img.pixelColor(x, y).alpha() >= 180
                and svg_img.pixelColor(x, y).red() >= 80
                and svg_img.pixelColor(x, y).green() <= 50
            )
            self.assertGreater(svg_burg, 0, f"No burgundy pixels in SVG at {size}x{size}")


class PackagingAndSmokeTests(unittest.TestCase):
    def test_zip_package_structure_and_headless_qgis_lifecycle(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_zip = tmp_path / "awanagis-0.1.0-test.zip"
            zip_path, sha_path, digest, names = package_plugin.build_plugin_zip(ROOT, out_zip)
            self.assertTrue(zip_path.is_file())
            self.assertTrue(sha_path.is_file())
            self.assertIn(digest, sha_path.read_text(encoding="utf-8"))

            with zipfile.ZipFile(zip_path) as zf:
                entries = zf.namelist()
                self.assertTrue(all(name.startswith("awanagis/") for name in entries))
                for required in (
                    "awanagis/__init__.py",
                    "awanagis/plugin.py",
                    "awanagis/metadata.txt",
                    "awanagis/LICENSE",
                    "awanagis/NOTICE",
                    "awanagis/THIRD_PARTY_LICENSES.md",
                    "awanagis/resources/icon.png",
                    "awanagis/resources/icon.svg",
                    "awanagis/resources/ASSET_PROVENANCE.md",
                    "awanagis/i18n/awanagis_pt_BR.qm",
                    "awanagis/i18n/awanagis_pt_BR.ts",
                    "awanagis/i18n/awanagis.pro",
                ):
                    self.assertIn(required, entries)
                for forbidden_prefix in (
                    "awanagis/.git/",
                    "awanagis/docs/",
                    "awanagis/tests/",
                    "awanagis/scripts/",
                    "awanagis/graft/",
                ):
                    self.assertFalse(any(e.startswith(forbidden_prefix) for e in entries), forbidden_prefix)
                self.assertFalse(any("__pycache__" in e or e.endswith((".pyc", ".db", ".zip", ".env", ".gpkg")) for e in entries))

                qm_bytes = zf.read("awanagis/i18n/awanagis_pt_BR.qm")
                self.assertEqual(qm_bytes[:4], b"\x3c\xb8\x64\x18")

                extract_dir = tmp_path / "plugins"
                zf.extractall(extract_dir)

            script = (
                "import sys; "
                "from unittest.mock import Mock; "
                "from qgis.PyQt.QtWidgets import QMainWindow; "
                "from qgis.core import QgsApplication; "
                f"sys.path.insert(0, {str(extract_dir)!r}); "
                "app = QgsApplication([], False); "
                "import awanagis; "
                "iface = Mock(); "
                "iface.mainWindow.return_value = QMainWindow(); "
                "plugin = awanagis.classFactory(iface); "
                "plugin.config.set('mcp_enabled', False); "
                "plugin.initGui(); "
                "assert plugin._action.text() == 'AwanaGIS'; "
                "plugin.unload(); "
                "print('SMOKE_OK')"
            )
            env = dict(os.environ)
            env["QT_QPA_PLATFORM"] = "offscreen"
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SMOKE_OK", proc.stdout)

    def test_package_excludes_untracked_files_and_symlinks(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "awanagis_repo"
            (repo / "core").mkdir(parents=True)
            (repo / "tests").mkdir()
            (repo / "docs").mkdir()
            (repo / "__init__.py").write_text("def classFactory(i): pass\n", encoding="utf-8")
            (repo / "plugin.py").write_text("", encoding="utf-8")
            (repo / "config.py").write_text("", encoding="utf-8")
            (repo / "metadata.txt").write_text("version=0.1.0\n", encoding="utf-8")
            (repo / "README.md").write_text("# AwanaGIS\n", encoding="utf-8")
            (repo / "LICENSE").write_text("GPL\n", encoding="utf-8")
            (repo / "NOTICE").write_text("Notice\n", encoding="utf-8")
            (repo / "THIRD_PARTY_LICENSES.md").write_text("Licenses\n", encoding="utf-8")
            (repo / "core" / "mod.py").write_text("X = 1\n", encoding="utf-8")
            (repo / "tests" / "test_x.py").write_text("", encoding="utf-8")
            (repo / "docs" / "note.md").write_text("", encoding="utf-8")

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)

            # Create untracked files and symlinks that must NEVER be packaged.
            (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
            (repo / "core" / "untracked_secret.py").write_text("SECRET=1\n", encoding="utf-8")
            (repo / "core" / "symlink.py").symlink_to(repo / "core" / "mod.py")
            # Even a tracked symlink must be rejected.
            (repo / "core" / "tracked_link.py").symlink_to(repo / "core" / "mod.py")
            subprocess.run(["git", "add", "core/tracked_link.py"], cwd=repo, check=True, capture_output=True)

            out_zip = Path(tmp) / "out.zip"
            zip_path, _, _, names = package_plugin.build_plugin_zip(repo, out_zip)
            self.assertIn("awanagis/core/mod.py", names)
            self.assertNotIn("awanagis/.env.local", names)
            self.assertNotIn("awanagis/core/untracked_secret.py", names)
            self.assertNotIn("awanagis/core/symlink.py", names)
            self.assertNotIn("awanagis/core/tracked_link.py", names)
            self.assertNotIn("awanagis/tests/test_x.py", names)
            self.assertNotIn("awanagis/docs/note.md", names)

    def test_package_exported_tree_rejects_dotfiles_and_unapproved_data_extensions(self):
        with TemporaryDirectory() as tmp:
            exported = Path(tmp) / "awanagis_export"
            (exported / "integrations").mkdir(parents=True)
            (exported / "resources").mkdir(parents=True)
            (exported / "i18n").mkdir(parents=True)
            (exported / "__init__.py").write_text("def classFactory(i): pass\n", encoding="utf-8")
            (exported / "plugin.py").write_text("", encoding="utf-8")
            (exported / "config.py").write_text("", encoding="utf-8")
            (exported / "metadata.txt").write_text("version=0.1.0\n", encoding="utf-8")
            (exported / "README.md").write_text("# AwanaGIS\n", encoding="utf-8")
            (exported / "LICENSE").write_text("GPL\n", encoding="utf-8")
            (exported / "NOTICE").write_text("Notice\n", encoding="utf-8")
            (exported / "THIRD_PARTY_LICENSES.md").write_text("Licenses\n", encoding="utf-8")
            (exported / "integrations" / "__init__.py").write_text("", encoding="utf-8")
            (exported / "integrations" / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            (exported / "resources" / "private.gpkg").write_bytes(b"SQLite format 3\x00")
            (exported / "resources" / "server-key.pem").write_text("PRIVATE KEY\n", encoding="utf-8")
            cert_dir = exported / "integrations" / "brazil" / "vendor" / "gisbr" / "core" / "certs"
            cert_dir.mkdir(parents=True)
            (cert_dir / "ca_roots.pem").write_text("CERT\n", encoding="utf-8")
            (exported / "i18n" / "awanagis_pt_BR.ts").write_text("<TS/>", encoding="utf-8")
            (exported / "i18n" / "awanagis.pro").write_text("TRANSLATIONS = awanagis_pt_BR.ts\n", encoding="utf-8")

            out_zip = Path(tmp) / "export_out.zip"
            _, _, _, names = package_plugin.build_plugin_zip(exported, out_zip)
            self.assertIn("awanagis/integrations/__init__.py", names)
            self.assertIn("awanagis/integrations/brazil/vendor/gisbr/core/certs/ca_roots.pem", names)
            self.assertIn("awanagis/i18n/awanagis_pt_BR.ts", names)
            self.assertIn("awanagis/i18n/awanagis.pro", names)
            self.assertNotIn("awanagis/integrations/.env", names)
            self.assertNotIn("awanagis/resources/private.gpkg", names)
            self.assertNotIn("awanagis/resources/server-key.pem", names)



if __name__ == "__main__":
    unittest.main()
