"""Onboarding: Tinfoil provider, model rules, configured check and setup page."""

from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtTest import QTest
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
pkg = ROOT.name
config_mod = import_module(f"{pkg}.config")
providers = import_module(f"{pkg}.backends.providers")
openai_http = import_module(f"{pkg}.backends.openai_http")
onboarding = import_module(f"{pkg}.core.onboarding")
SessionStore = import_module(f"{pkg}.core.session_store").SessionStore
QgisToolkit = import_module(f"{pkg}.core.toolkit").QgisToolkit


class FakeConfig:
    def __init__(self, **values):
        self.values = dict(config_mod.DEFAULTS)
        self.values.update(values)

    def get(self, name, default=None):
        return self.values.get(name, default)

    def set(self, name, value):
        self.values[name] = value


class ProviderTests(unittest.TestCase):
    def test_tinfoil_is_first_builtin(self):
        first = providers.BUILT_INS[0]
        self.assertEqual(first["id"], "tinfoil")
        self.assertEqual(first["label"], "Tinfoil (private inference)")
        self.assertEqual(first["base_url"], "https://inference.tinfoil.sh/v1")
        self.assertEqual(first["format"], "openai")
        self.assertEqual(first["default_model"], "deepseek-v4-1-flash")
        self.assertEqual(first["key_env"], "TINFOIL_API_KEY")
        self.assertIs(providers.get_provider("tinfoil"), first)
        self.assertIsNotNone(providers.get_provider("openai"))
        self.assertIsNotNone(providers.get_provider("anthropic"))

    def test_defaults_use_tinfoil(self):
        self.assertEqual(config_mod.DEFAULTS["provider"], "tinfoil")
        self.assertEqual(config_mod.DEFAULTS["model"], "deepseek-v4-1-flash")

    def test_saved_settings_survive_new_defaults(self):
        with TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "s.ini"), QSettings.Format.IniFormat)
            settings.setValue("AwanaGIS/provider", "anthropic")
            settings.setValue("AwanaGIS/model", "claude-opus-4-8")
            cfg = config_mod.Config()
            cfg._s = settings
            self.assertEqual(cfg.get("provider"), "anthropic")
            self.assertEqual(cfg.get("model"), "claude-opus-4-8")
            settings.remove("AwanaGIS/provider")
            self.assertEqual(cfg.get("provider"), "tinfoil")


class PickDefaultModelTests(unittest.TestCase):
    def test_keeps_current_when_listed(self):
        self.assertEqual(providers.pick_default_model("tinfoil", ["a", "deepseek-v4-1-flash"], "a"), "a")

    def test_tinfoil_prefers_default(self):
        self.assertEqual(providers.pick_default_model("tinfoil", ["a", "deepseek-v4-1-flash"], "gone"), "deepseek-v4-1-flash")

    def test_tinfoil_falls_back_to_first(self):
        self.assertEqual(providers.pick_default_model("tinfoil", ["b", "a"], ""), "b")

    def test_other_provider_default_then_first(self):
        self.assertEqual(providers.pick_default_model("openai", ["x", "gpt-4.1"], "claude"), "gpt-4.1")
        self.assertEqual(providers.pick_default_model("openai", ["x", "y"], "claude"), "x")

    def test_empty_list_returns_current_or_default(self):
        self.assertEqual(providers.pick_default_model("openai", [], "mine"), "mine")
        self.assertEqual(providers.pick_default_model("openai", [], ""), "gpt-4.1")


class FetchModelsProbeTests(unittest.TestCase):
    URL = "https://inference.tinfoil.sh/v1"

    @staticmethod
    def _resp(body):
        import io

        class R(io.BytesIO):
            pass

        return R(body)

    def _run(self, provider_id, post_result):
        import json as _json
        import urllib.error

        requests = []

        def fake_urlopen(request, **kwargs):
            requests.append(request)
            if request.get_method() == "GET":
                return self._resp(_json.dumps({"data": [{"id": "deepseek-v4-1-flash", "endpoints": ["/v1/chat/completions"]}]}).encode())
            if post_result == 200:
                return self._resp(b"{}")
            raise urllib.error.HTTPError(
                request.full_url, post_result, "x", {},
                self._resp(_json.dumps({"error": {"message": "Incorrect API key provided.", "code": "invalid_api_key"}}).encode()),
            )

        with patch.object(openai_http, "_safe_urlopen", fake_urlopen):
            result = providers.fetch_models("openai", self.URL, "tk_bogus", provider_id)
        return result, requests

    def test_tinfoil_bad_key_fails(self):
        result, requests = self._run("tinfoil", 401)
        self.assertEqual(result, ([], "Incorrect API key provided."))
        post = requests[-1]
        self.assertEqual(post.get_method(), "POST")
        self.assertEqual(post.full_url, self.URL + "/chat/completions")
        self.assertIn(b'"max_tokens": 1', post.data)
        self.assertIn(b"deepseek-v4-1-flash", post.data)

    def test_tinfoil_good_key_returns_models(self):
        result, requests = self._run("tinfoil", 200)
        self.assertEqual(result, (["deepseek-v4-1-flash"], None))
        self.assertEqual(len(requests), 2)

    def test_other_provider_has_no_probe(self):
        result, requests = self._run("openai", 401)
        self.assertEqual(result, (["deepseek-v4-1-flash"], None))
        self.assertEqual([r.get_method() for r in requests], ["GET"])

    def test_custom_none_has_no_probe(self):
        _result, requests = self._run(None, 401)
        self.assertEqual(len(requests), 1)


class ModelFilterTests(unittest.TestCase):
    def test_endpoints_filter(self):
        items = [
            {"id": "chat-a", "endpoints": ["/v1/chat/completions", "/v1/responses"]},
            {"id": "nomic-embed-text", "endpoints": ["/v1/embeddings"]},
            {"id": "whisper", "endpoints": ["/v1/audio/transcriptions"]},
            {"id": "no-field"},
            "plain-string",
            {"endpoints": ["/v1/chat/completions"]},
        ]
        self.assertEqual(openai_http.extract_chat_model_ids(items), ["chat-a", "no-field", "plain-string"])

    def test_empty(self):
        self.assertEqual(openai_http.extract_chat_model_ids(None), [])


class ConfiguredTests(unittest.TestCase):
    def check(self, **values):
        return onboarding.is_backend_configured(FakeConfig(**values), environ={})

    def test_default_is_unconfigured(self):
        self.assertFalse(self.check())

    def test_api_key_mode(self):
        self.assertTrue(self.check(api_key="k"))
        self.assertFalse(self.check(api_key="  "))

    def test_env_key_counts(self):
        cfg = FakeConfig()
        self.assertTrue(onboarding.is_backend_configured(cfg, environ={"TINFOIL_API_KEY": "k"}))

    def test_base_url_override(self):
        self.assertTrue(self.check(provider="nope", api_base_url="https://x/v1", api_key="k"))
        self.assertFalse(self.check(provider="nope", api_key="k"))

    def test_ollama_needs_no_key(self):
        self.assertTrue(self.check(provider="ollama"))

    def test_custom_mode(self):
        self.assertFalse(self.check(connection_mode="custom"))
        self.assertTrue(self.check(connection_mode="custom", custom_base_url="http://h/v1"))

    def test_cli_mode_always_configured(self):
        self.assertTrue(self.check(connection_mode="cli_tool"))
        self.assertTrue(self.check(connection_mode="subscription"))


class DockOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.settings = QSettings(str(Path(temp.name) / "o.ini"), QSettings.Format.IniFormat)
        self.config = config_mod.Config()
        self.config._s = self.settings

    def make_dock(self):
        from importlib import import_module as im

        ChatDock = im(f"{pkg}.gui.chat_dock").ChatDock
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=self.config)
        dock = ChatDock(
            lambda: None, lambda: None, lambda: None, toolkit,
            session_store=SessionStore(settings=self.settings),
            show_startup_picker=False, config=self.config,
        )
        dock.resize(380, 650)
        dock.show()
        self.addCleanup(dock.close)
        return dock

    def test_unconfigured_shows_onboarding_then_chat(self):
        dock = self.make_dock()
        self.assertEqual(dock._stack.currentIndex(), 1)
        self.assertFalse(dock.input.isVisible())
        self.assertFalse(dock.scroll.isVisible())
        self.assertTrue(dock._onboarding_page.isVisible())
        self.config.set("api_key", "secret")
        dock.refresh_configuration()
        self.assertEqual(dock._stack.currentIndex(), 0)
        self.assertTrue(dock.input.isVisible())

    def test_configured_shows_chat(self):
        self.config.set("api_key", "secret")
        dock = self.make_dock()
        self.assertEqual(dock._stack.currentIndex(), 0)

    def test_page_autotests_and_starts(self):
        dock = self.make_dock()
        page = dock._onboarding_page
        page._timer.setInterval(10)
        self.assertEqual(page.provider_combo.currentData(), "tinfoil")
        self.assertEqual(page.base_url_edit.text(), "https://inference.tinfoil.sh/v1")
        self.assertFalse(page.start_btn.isEnabled())
        calls = []

        def fake_fetch(fmt, base_url, key, provider_id=None):
            calls.append((fmt, base_url, key))
            return ["other", "deepseek-v4-1-flash"], None

        with patch.object(providers, "fetch_models", fake_fetch):
            page.key_edit.setText("tok")
            for _ in range(100):
                QTest.qWait(20)
                if page.start_btn.isEnabled():
                    break
        self.assertEqual(calls, [("openai", "https://inference.tinfoil.sh/v1", "tok")])
        self.assertEqual(page.model_combo.currentText(), "deepseek-v4-1-flash")
        self.assertTrue(page.start_btn.isEnabled())
        page.start_btn.click()
        self.assertEqual(self.config.get("connection_mode"), "api_key")
        self.assertEqual(self.config.get("provider"), "tinfoil")
        self.assertEqual(self.config.get("api_key"), "tok")
        self.assertEqual(self.config.get("api_base_url"), "")
        self.assertEqual(self.config.get("model"), "deepseek-v4-1-flash")
        self.assertEqual(dock._stack.currentIndex(), 0)

    def test_page_reports_error(self):
        dock = self.make_dock()
        page = dock._onboarding_page
        page._timer.setInterval(10)
        with patch.object(providers, "fetch_models", lambda f, b, k, p=None: ([], "HTTP 401")):
            page.key_edit.setText("bad")
            for _ in range(100):
                QTest.qWait(20)
                if "401" in page.status.text():
                    break
        self.assertIn("401", page.status.text())
        self.assertFalse(page.start_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
