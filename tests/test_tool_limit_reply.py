"""A turn that ends at the tool limit still tells the user what happened."""

from importlib import import_module
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
PACKAGE = ROOT.name
base = import_module(f"{PACKAGE}.backends.base")
openai_backend = import_module(f"{PACKAGE}.backends.openai_backend")
api_backend = import_module(f"{PACKAGE}.backends.api_backend")
openai_http = import_module(f"{PACKAGE}.backends.openai_http")
anthropic_http = import_module(f"{PACKAGE}.backends.anthropic_http")
MainThreadExecutor = import_module(f"{PACKAGE}.core.executor").MainThreadExecutor
AgentEvent, EventType = base.AgentEvent, base.EventType
CLOSING = "Salvei o arquivo. Falta remover a camada antiga do projeto."
PARTIAL = "Salvei a primeira parte"


def config(**values):
    settings = {"provider": "custom", "custom_api_key": "offline-test-key", "model": "offline-model",
                "max_iterations": 2}
    settings.update(values)
    return SimpleNamespace(get=lambda name, default=None: settings.get(name, default))


class FakeClient:
    """Requests tool calls while tools are offered, and answers once they are not."""

    def __init__(self, anthropic=False, fail_closing=False, partial=False):
        self.anthropic = anthropic
        self.fail_closing = fail_closing
        self.partial = partial
        self.calls = []

    def stream_message(self, model, max_tokens, system, tools, messages, on_text, should_stop, **kwargs):
        self.calls.append({"tools": tools, "messages": [dict(message) for message in messages]})
        if tools:
            call = {"type": "tool_use", "id": f"call-{len(self.calls)}", "name": "list_layers", "input": {}}
            return [call], ("tool_use" if self.anthropic else "tool_calls")
        if self.fail_closing:
            if self.partial:
                on_text(PARTIAL)
            raise OSError("offline")
        on_text(CLOSING)
        return [{"type": "text", "text": CLOSING}], ("end_turn" if self.anthropic else "stop")


class ToolLimitReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsApplication
        from qgis.PyQt.QtCore import QCoreApplication
        cls.process_events = QCoreApplication.processEvents
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def run_turn(self, backend_type, fake, **settings):
        """Run one turn as the chat does: the backend on its own thread."""
        toolkit = SimpleNamespace(list_layers=lambda **_: {"ok": True, "layers": []},
                                  agent_state_summary=lambda: "## Workspace State\n### Layers: none loaded")
        backend = backend_type(config(**settings), toolkit, MainThreadExecutor())
        backend._client = lambda: fake
        events, outcome, done = [], {}, threading.Event()

        def worker():
            try:
                outcome["history"] = backend.send("Onde está a camada nova?", [], events.append, lambda: False)
            except BaseException as exc:  # noqa: BLE001 - reported through the assertion
                outcome["error"] = exc
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        deadline = time.monotonic() + 30
        while not done.wait(0.01) and time.monotonic() < deadline:
            self.process_events()
        self.assertTrue(done.is_set(), "the turn did not end")
        self.assertNotIn("error", outcome, outcome.get("error"))
        return outcome["history"], events

    def text_after_last_tool(self, events):
        last_tool = max(index for index, event in enumerate(events) if event.type == EventType.TOOL_RESULT)
        return "".join(event.data.get("text", "") for event in events[last_tool + 1:] if event.type == EventType.TEXT)

    def text_events_after_last_tool(self, events):
        last_tool = max(index for index, event in enumerate(events) if event.type == EventType.TOOL_RESULT)
        return [event for event in events[last_tool + 1:] if event.type == EventType.TEXT]

    def test_openai_backend_replies_when_the_tool_limit_ends_the_turn(self):
        fake = FakeClient()

        history, events = self.run_turn(openai_backend.OpenAIBackend, fake, custom_format="openai")

        self.assertEqual(len([call for call in fake.calls if call["tools"]]), 2, "one request per allowed step")
        self.assertIsNone(fake.calls[-1]["tools"], "the closing request offers no tools")
        self.assertEqual(self.text_after_last_tool(events), CLOSING)
        self.assertEqual(history[-1], {"role": "assistant", "content": CLOSING})
        self.assertEqual(events[-1].type, EventType.DONE)

    def test_anthropic_backend_replies_when_the_tool_limit_ends_the_turn(self):
        fake = FakeClient(anthropic=True)

        history, events = self.run_turn(api_backend.ApiBackend, fake, custom_format="anthropic")

        closing = fake.calls[-1]
        self.assertIsNone(closing["tools"])
        last = closing["messages"][-1]
        self.assertEqual(last["role"], "user", "the request joins the message that carries the tool results")
        self.assertEqual([block["text"] for block in last["content"] if block.get("type") == "text"
                          and not block["text"].startswith("[Current QGIS")],
                         [base.TOOL_LIMIT_PROMPT])
        self.assertEqual(self.text_after_last_tool(events), CLOSING)
        self.assertEqual(history[-1]["content"], CLOSING)
        self.assertEqual(events[-1].type, EventType.DONE)

    def test_the_limit_notice_is_shown_when_the_closing_request_fails(self):
        for backend_type, wire in ((openai_backend.OpenAIBackend, "openai"), (api_backend.ApiBackend, "anthropic")):
            with self.subTest(wire=wire):
                fake = FakeClient(anthropic=wire == "anthropic", fail_closing=True)

                history, events = self.run_turn(backend_type, fake, custom_format=wire)

                shown = self.text_events_after_last_tool(events)
                self.assertEqual(len(shown), 1, "the user sees one line instead of silence")
                self.assertIsInstance(shown[0].data["text"], base.BackendFeedback, "the notice stays translatable")
                notice = str(shown[0].data["text"])
                self.assertTrue(notice.strip())
                self.assertEqual(history[-1], {"role": "assistant", "content": notice})
                self.assertEqual(events[-1].type, EventType.DONE)

    def test_text_that_arrived_before_the_closing_request_failed_is_kept(self):
        for backend_type, wire in ((openai_backend.OpenAIBackend, "openai"), (api_backend.ApiBackend, "anthropic")):
            with self.subTest(wire=wire):
                fake = FakeClient(anthropic=wire == "anthropic", fail_closing=True, partial=True)

                history, events = self.run_turn(backend_type, fake, custom_format=wire)

                self.assertEqual(self.text_after_last_tool(events), PARTIAL)
                self.assertEqual(history[-1], {"role": "assistant", "content": PARTIAL})

    def test_openai_requests_without_tools_carry_no_tool_fields(self):
        client = openai_http.OpenAIHttpClient(api_key="offline-test-key", base_url="https://example.invalid/v1")
        sent = []

        def capture(data, headers, timeout, on_connecting=None):
            sent.append(json.loads(data))
            raise RuntimeError("offline")

        tool = {"type": "function", "function": {"name": "list_layers", "parameters": {"type": "object"}}}
        with patch.object(client, "_open_stream", side_effect=capture):
            for tools in (None, [tool]):
                with self.assertRaises(RuntimeError):
                    client.stream_message(model="m", max_tokens=16, system="s", tools=tools,
                                          messages=[{"role": "user", "content": "oi"}],
                                          on_text=lambda _text: None, should_stop=lambda: False)

        self.assertNotIn("tools", sent[0])
        self.assertNotIn("tool_choice", sent[0])
        self.assertEqual(sent[1]["tools"], [tool])
        self.assertEqual(sent[1]["tool_choice"], "auto")

    def test_anthropic_requests_without_tools_carry_no_tool_fields(self):
        client = anthropic_http.AnthropicHttpClient(
            api_key="offline-test-key", base_url="https://example.invalid/v1")
        sent = []

        class Connection:
            def request(self, method, path, body, headers):
                sent.append(json.loads(body))

            def getresponse(self):
                # A permanent status ends the request without a retry.
                return SimpleNamespace(status=400, read=lambda size: b"offline")

        with patch.object(client, "_ensure_conn", return_value=(Connection(), True)):
            for tools in (None, [{"name": "list_layers", "description": "d", "input_schema": {}}]):
                with self.assertRaises(anthropic_http.AnthropicHttpError):
                    client.stream_message(model="m", max_tokens=16, system="s", tools=tools,
                                          messages=[{"role": "user", "content": "oi"}],
                                          on_text=lambda _text: None, should_stop=lambda: False)

        self.assertNotIn("tools", sent[0])
        self.assertEqual(len(sent[1]["tools"]), 1)


if __name__ == "__main__":
    unittest.main()
