"""Offline checks for custom-endpoint evaluation runs."""
from contextlib import redirect_stderr
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qgis.core import QgsApplication, QgsProject

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
EVAL_MODULE = f"{ROOT.name}.evals.qgis_agent"
BACKENDS = import_module(f"{ROOT.name}.backends.base")
AgentEvent, EventType = BACKENDS.AgentEvent, BACKENDS.EventType
main_module = import_module(f"{EVAL_MODULE}.__main__")
run_case = import_module(f"{EVAL_MODULE}.runner").run_case
trace_module = import_module(f"{EVAL_MODULE}.trace")

KEY_ENV = "EVAL_CUSTOM_ENDPOINT_KEY"
SENTINEL = "custom-endpoint-sentinel-9f4c"
BASE_URL = "https://example.com/v1"


class CustomEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        cls.app.initQgis()

    @staticmethod
    def fixture(case, run_dir, variant):
        project = QgsProject.instance()
        project.clear()
        project_path = run_dir / "project.qgz"
        project.write(str(project_path))
        output = run_dir / "outputs"
        output.mkdir()
        return SimpleNamespace(project_path=project_path, output_dir=output, turns=("um",))

    def parse_args(self, *extra, provider="custom"):
        return main_module.parse_args([
            "--case", "load", "--output", "unused-eval-output",
            "--provider", provider, "--model", "fake", *extra,
        ])

    def assert_argument_error(self, *extra, provider="custom"):
        stderr = StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
            self.parse_args(*extra, provider=provider)
        self.assertEqual(raised.exception.code, 2)
        return stderr.getvalue()

    def run_scripted(self, run_dir, provider="custom", base_url=None, key_env=None, text="Concluído.",
                     model="fake", exception=None):
        captured = []

        class Backend:
            def __init__(self, config, toolkit, executor):
                captured.append(config)

            def send(self, message, history, emit, should_stop):
                if exception is not None:
                    raise exception
                emit(AgentEvent(EventType.TEXT, {"text": text}))
                return history + [message]

        options = {}
        if base_url is not None:
            options.update(base_url=base_url, key_env=key_env)
        with patch(f"{EVAL_MODULE}.fixtures.build_fixture", side_effect=self.fixture), \
                patch(f"{EVAL_MODULE}.checks.evaluate", return_value=[]):
            trace = run_case("load", run_dir, provider, model, backend_factory=Backend, **options)
        return trace, captured

    def test_custom_configuration_reads_the_named_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: SENTINEL}, clear=True):
            trace, captured = self.run_scripted(Path(directory) / "run", base_url=BASE_URL, key_env=KEY_ENV)
        self.assertEqual(len(captured), 1)
        config = captured[0]
        self.assertEqual(config.get("provider"), "custom")
        self.assertEqual(config.get("custom_base_url"), BASE_URL)
        self.assertEqual(config.get("custom_api_key"), SENTINEL)
        self.assertEqual(trace["backend"], {"provider": "custom", "model": "fake", "base_url": BASE_URL})
        self.assertEqual(trace["key_env"], KEY_ENV)

    def test_missing_or_empty_variable_blocks_before_backend_creation(self):
        for value in (None, ""):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                environment = {"EVAL_TEST_UNRELATED_VALUE": SENTINEL}
                if value is not None:
                    environment[KEY_ENV] = value
                run_dir = Path(directory) / "run"
                with patch.dict(os.environ, environment, clear=True):
                    trace, captured = self.run_scripted(run_dir, base_url=BASE_URL, key_env=KEY_ENV)
                self.assertEqual(captured, [])
                self.assertEqual(trace["status"], "blocked")
                self.assertEqual(len(trace["checks"]), 1)
                self.assertEqual(trace["checks"][0]["id"], "runner")
                self.assertEqual(trace["checks"][0]["status"], "blocked")
                self.assertEqual(trace["checks"][0]["detail"],
                                 f"Environment variable {KEY_ENV} is unset or empty")
                for path in run_dir.rglob("*"):
                    if path.is_file():
                        self.assertNotIn(SENTINEL.encode(), path.read_bytes(), str(path))

    def test_base_url_and_key_env_must_be_given_together(self):
        detail = self.assert_argument_error("--base-url", BASE_URL)
        self.assertIn("--base-url", detail)
        self.assertIn("--key-env", detail)
        detail = self.assert_argument_error("--key-env", KEY_ENV)
        self.assertIn("--base-url", detail)
        self.assertIn("--key-env", detail)

    def test_base_url_requires_the_custom_provider(self):
        detail = self.assert_argument_error("--base-url", BASE_URL, "--key-env", KEY_ENV, provider="openai")
        self.assertIn("--provider custom", detail)

    def test_base_url_validation_enforces_every_url_rule(self):
        invalid = (
            ("http://example.com/v1", "https"),
            ("https://user:pass@example.com/v1", "user information"),
            ("https://example.com/v1?key=1", "query"),
            ("https://example.com/v1#x", "fragment"),
            ("https:///v1", "host"),
        )
        for url, rule in invalid:
            with self.subTest(url=url):
                detail = self.assert_argument_error("--base-url", url, "--key-env", KEY_ENV)
                self.assertIn(rule, detail)
        for url in (BASE_URL, "http://127.0.0.1:18765/v1", "http://localhost:18765/v1"):
            with self.subTest(url=url):
                args = self.parse_args("--base-url", url, "--key-env", KEY_ENV)
                self.assertEqual(args.base_url, url)
                self.assertEqual(args.key_env, KEY_ENV)

    def test_report_removes_exactly_one_trailing_slash_from_base_url(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: SENTINEL}, clear=True):
            run_dir = Path(directory) / "run"
            trace, _ = self.run_scripted(run_dir, base_url=BASE_URL + "//", key_env=KEY_ENV)
            report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["backend"]["base_url"], BASE_URL + "/")
        self.assertEqual(report["backend"]["base_url"], BASE_URL + "/")

    def test_report_without_custom_options_keeps_the_original_backend_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            trace, _ = self.run_scripted(Path(directory) / "run", provider="offline")
        self.assertEqual(trace["backend"], {"provider": "offline", "model": "fake"})

    def test_main_rejects_an_existing_output_with_argument_error(self):
        stderr = StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                main_module.main([
                    "--case", "load", "--output", directory,
                    "--provider", "custom", "--model", "fake",
                    "--base-url", "http://127.0.0.1:18765/v1", "--key-env", KEY_ENV,
                ])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("error: --output must not exist", stderr.getvalue())

    def test_supervisor_forwards_custom_options_to_every_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main_module, "supervise", return_value=None) as supervise:
                result = main_module.main([
                    "--case", "load", "--output", str(Path(directory) / "runs"),
                    "--provider", "custom", "--model", "fake", "--base-url", BASE_URL + "/",
                    "--key-env", KEY_ENV, "--repeat", "2",
                ])
        self.assertEqual(result, 0)
        self.assertEqual(supervise.call_count, 2)
        for call in supervise.call_args_list:
            command = call[0][0]
            base_index = command.index("--base-url")
            key_index = command.index("--key-env")
            self.assertEqual(command[base_index + 1], BASE_URL + "/")
            self.assertEqual(command[key_index + 1], KEY_ENV)
            self.assertEqual(call[0][3]["backend"],
                             {"provider": "custom", "model": "fake", "base_url": BASE_URL})
            self.assertEqual(call[0][3]["key_env"], KEY_ENV)

    def test_run_scoped_secret_is_redacted_from_trace_and_report(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: SENTINEL}, clear=True):
            run_dir = Path(directory) / "run"
            trace, _ = self.run_scripted(run_dir, base_url=BASE_URL, key_env=KEY_ENV,
                                         text=f"Chave: {SENTINEL}")
            report_text = (run_dir / "run.json").read_text(encoding="utf-8")
            for path in run_dir.rglob("*"):
                if path.is_file():
                    self.assertNotIn(SENTINEL.encode(), path.read_bytes(), str(path))
        self.assertEqual(trace["turns"][0]["reply"], "Chave: [redacted]")
        self.assertEqual(json.loads(report_text)["key_env"], KEY_ENV)
        self.assertNotIn(SENTINEL, report_text)

    def test_run_case_returns_the_redacted_trace_after_backend_exception(self):
        # _turn records exception types rather than messages, so the type carries the sentinel into the trace.
        exception_type = type(f"BackendError-{SENTINEL}", (Exception,), {})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: SENTINEL}, clear=True):
            run_dir = Path(directory) / "run"
            trace, _ = self.run_scripted(run_dir, base_url=BASE_URL, key_env=KEY_ENV,
                                         exception=exception_type(SENTINEL))
            report_text = (run_dir / "run.json").read_text(encoding="utf-8")
        self.assertEqual(trace["status"], "error")
        self.assertNotIn(SENTINEL, report_text)
        self.assertNotIn(SENTINEL, json.dumps(trace))

    def test_write_trace_redacts_json_special_secret_before_serialization(self):
        secret = 'abc"def\\ghi'
        trace = {"turns": [{"error": ("Backend raised: " + secret,),
                            "detail": f"Backend raised: {secret}"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            trace_module.write_trace(path, trace, (secret,))
            report_text = path.read_text(encoding="utf-8")
            report = json.loads(report_text)
        self.assertNotIn(secret, report["turns"][0]["error"][0])
        self.assertNotIn(secret, report["turns"][0]["detail"])
        self.assertNotIn(r'abc\"def', report_text)

    def test_report_keeps_trusted_base_url_when_secret_occurs_in_it(self):
        base_url = "https://v1.example.com/v1"
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: "v1"}, clear=True):
            run_dir = Path(directory) / "run"
            self.run_scripted(run_dir, base_url=base_url, key_env=KEY_ENV)
            report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["backend"]["base_url"], base_url)

    def test_report_stays_valid_json_when_secret_is_a_quote(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {KEY_ENV: '"'}, clear=True):
            run_dir = Path(directory) / "run"
            self.run_scripted(run_dir, base_url=BASE_URL, key_env=KEY_ENV)
            report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "completed")

    def test_write_trace_walks_values_and_preserves_trusted_metadata(self):
        class SecretValue:
            def __str__(self):
                return "value-v1"

        trace = {
            "backend": {"base_url": "https://v1.example.com/v1"},
            "key_env": "EVAL_v1_KEY",
            "nested": [{"text": "v1", "object": SecretValue(), "count": 7}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            trace_module.write_trace(path, trace, ("v1",))
            report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["backend"], trace["backend"])
        self.assertEqual(report["key_env"], trace["key_env"])
        self.assertEqual(report["nested"], [{"text": "[redacted]", "object": "value-[redacted]", "count": 7}])

    def test_report_without_run_secret_does_not_redact_environment_values(self):
        model = "model-id"
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"UNRELATED_API_TOKEN": model}, clear=True):
            run_dir = Path(directory) / "run"
            self.run_scripted(run_dir, provider="offline", model=model)
            report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(report["backend"], {"provider": "offline", "model": model})


if __name__ == "__main__":
    unittest.main()
