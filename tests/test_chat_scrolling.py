"""Transcript scrolling and session restore.

The transcript follows the stream only while the reader is at the bottom, and a session restore
cannot be interrupted or damaged. Every session here is synthetic: these tests never read the
saved sessions of the user.

Each scenario records its checks by name and reports every failed one as its own subtest, so a
failure names the behaviour. Input is sent as real Qt events on the offscreen platform.
"""

import re
import sys
import time
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from qgis.PyQt.QtGui import QMouseEvent, QWheelEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QLabel, QStyle, QStyleOptionSlider, QWidget
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
pkg = ROOT.name
config_mod = import_module(f"{pkg}.config")
base_mod = import_module(f"{pkg}.backends.base")
SessionStore = import_module(f"{pkg}.core.session_store").SessionStore
QgisToolkit = import_module(f"{pkg}.core.toolkit").QgisToolkit
theme = import_module(f"{pkg}.gui.theme")
AgentTurnBubble = import_module(f"{pkg}.gui.agent_turn_bubble").AgentTurnBubble
ChatDock = import_module(f"{pkg}.gui.chat_dock").ChatDock
MessageBubble = import_module(f"{pkg}.gui.message_bubble").MessageBubble
MessageContainer = import_module(f"{pkg}.gui.message_bubble").MessageContainer
WrapLabel = import_module(f"{pkg}.gui.wrap_label").WrapLabel
AgentEvent = base_mod.AgentEvent
EventType = base_mod.EventType

PIN_EPS = 2
LEFT = Qt.MouseButton.LeftButton
RIGHT = Qt.MouseButton.RightButton
MARK = re.compile(r"\b([A-H]-[UTA]\d+(?:-\d+)?)\b")
PARA = ("Paragraph %d: the quick brown fox jumps over the lazy dog and keeps running across the map canvas, "
        "which forces a wrap or two at every width.")
TABLE = ("Result:\n\n| name | count | note |\n|---|---|---|\n| a | 1 | x |\n| b | 2 | y |\n| c | 3 | z |\n\n"
         + "\n\n".join(PARA % i for i in range(1, 6)))
LONGWORD = "Longest unbroken token: " + "w" * 260 + "\n\n" + PARA % 9


def record(results, name, ok, **numbers):
    """Store one named check together with the numbers that explain it."""
    results[name] = (bool(ok), "".join(" %s=%r" % item for item in numbers.items()))
    return bool(ok)


def settle(ms):
    QTest.qWait(ms)


def wheel_event(widget, delta_y, delta_x=0):
    """A real QWheelEvent, delivered the way QApplication::notify delivers one (delta > 0 scrolls up)."""
    local = QPoint(widget.width() // 2, widget.height() // 2)
    event = QWheelEvent(QPointF(local), QPointF(widget.mapToGlobal(local)), QPoint(0, 0), QPoint(delta_x, delta_y),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    return event


def wheel(widget, notches=1, delta=120, pause=60):
    """``notches`` wheel events, ``pause`` ms of event loop after each."""
    for _ in range(notches):
        wheel_event(widget, delta)
        if pause:
            settle(pause)
    settle(60)


def mouse(widget, kind, pos, button=LEFT, buttons=None):
    """A real QMouseEvent. QTest.mouseMove only moves the cursor, which the offscreen plugin ignores."""
    if buttons is None:
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    # QPointF: PyQt 6 does not convert a QPoint for these arguments.
    QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)), button, buttons,
                                               Qt.KeyboardModifier.NoModifier))
    settle(100)


def handle_rect(bar):
    """The rect of the scrollbar thumb."""
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    return bar.style().subControlRect(QStyle.ComplexControl.CC_ScrollBar, option,
                                      QStyle.SubControl.SC_ScrollBarSlider, bar)


def handle_center(bar):
    """The centre of the scrollbar thumb."""
    return handle_rect(bar).center()


def drag_bar(bar, target_y):
    """Drag the thumb from wherever it is to ``target_y``."""
    start = handle_center(bar)
    mouse(bar, QEvent.Type.MouseButtonPress, start)
    y = start.y()
    while abs(target_y - y) > 12:
        y += 12 if target_y > y else -12
        mouse(bar, QEvent.Type.MouseMove, QPoint(bar.width() // 2, y))
    mouse(bar, QEvent.Type.MouseButtonRelease, QPoint(bar.width() // 2, target_y))


def to_bottom(dock, limit=600):
    """Wheel down until the bottom edge is in view."""
    vs = dock.scroll.verticalScrollBar()
    notches = 0
    while vs.value() < vs.maximum() - PIN_EPS and notches < limit:
        wheel(dock.scroll.viewport(), 10, delta=-120, pause=5)
        notches += 10
    settle(200)
    return vs.value() >= vs.maximum() - PIN_EPS


def wait_restored(dock, limit=25.0):
    """Let the queued restore batches run, then the layout settle."""
    t0 = time.monotonic()
    while dock._restoring_transcript and time.monotonic() - t0 < limit:
        settle(25)
    settle(600)


def wait_idle(dock, limit=20.0):
    """Wait for the worker thread of a Send, then let the last events land."""
    t0 = time.monotonic()
    while dock._worker is not None and time.monotonic() - t0 < limit:
        settle(15)
    settle(400)


def rows(dock):
    """The row roots of the transcript, in order. The trailing stretch is not a row."""
    layout = dock.transcript_layout
    return [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget() is not None]


def rows_wide(dock):
    """Row roots whose right edge reaches or passes the right edge of the transcript."""
    width = dock.transcript_widget.width()
    return sum(1 for w in rows(dock) if w.geometry().right() >= width)


def caps_follow(dock):
    """True when every row is capped at the transcript's width and has no minimum width of its own."""
    width = dock.transcript_widget.width()
    return all(w.maximumWidth() == width and w.minimumWidth() == 0 for w in rows(dock))


def emit(dock, kind, **data):
    dock._on_event(AgentEvent(kind, data), None)


def added_turn(dock, answer):
    """Append a finished turn without going through send (no re-pin)."""
    dock._add_widget(MessageContainer("Question?", sender_name="You", is_user=True))
    emit(dock, EventType.TEXT, text=answer)
    settle(80)
    emit(dock, EventType.DONE)
    settle(300)


def gone(widgets):
    """True when every widget of the list is deleted or hidden."""
    for widget in widgets:
        try:
            if widget.isVisible():
                return False
        except RuntimeError:
            continue                          # deleted by deleteLater
    return True


def in_layout(layout, widget):
    try:
        return layout.indexOf(widget) >= 0
    except RuntimeError:
        return False                           # deleted


def _dicts(value):
    """The dictionary entries of a stored list; anything else in it is dropped."""
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def session_events(tag, turns):
    """Events whose rows carry the session tag, so row identity and order can be asserted."""
    events = []
    for i in range(turns):
        events.append({"type": "user", "text": "%s-U%d" % (tag, i)})
        turn = {"type": "agent_turn", "thinking": "", "tools": [], "text": ""}
        if i % 3 == 2:
            turn["tools"] = [{"name": "tool_%d" % (j % 3), "input": {"code": "%s-T%d-%d" % (tag, i, j)}, "result": "ok"}
                             for j in range(4 + i % 5)]
        else:
            body = TABLE if i % 2 else LONGWORD if i % 5 == 1 else "\n\n".join(PARA % k for k in range(1, 6))
            turn["text"] = ("%s-A%d\n\n" % (tag, i)) + body
            turn["model"] = "fake"
        events.append(turn)
    return events


def _text_marker(text):
    hit = MARK.search(text)
    return hit.group(1) if hit else "?"


def row_markers(dock):
    """One marker per row: the session tag and index it was built from, '!' for a notice, '?' for a live row."""
    out = []
    for w in rows(dock):
        turn = w.findChild(AgentTurnBubble)
        if turn is None:
            if isinstance(w, QLabel):
                out.append("!")
            else:
                bubble = w.findChild(MessageBubble)
                hit = MARK.search(bubble.text_label.text()) if bubble is not None else None
                out.append(hit.group(1) if hit else "?")
        elif turn._tool_rows and not turn.text_lbl.text():
            out.append(_text_marker(str(turn._tool_rows[0]._input.get("code", ""))))
        else:
            out.append(_text_marker(turn.text_lbl.text()))
    return out


RENDERED = ("user", "agent_turn", "chart", "stats", "gif", "file", "error", "compaction")


def _buildable(event):
    """Whether a stored visual of this turn has a kind the renderer can build."""
    return any(v.get("kind") in ("chart", "stats", "gif") for v in _dicts(event.get("visuals")))


def expected_markers(events):
    """The marker of every row the renderer must produce, in order."""
    out = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in RENDERED or event.get("raises"):
            continue
        kind = event["type"]
        if kind == "compaction":
            out.append("!")
        elif kind in ("user", "agent_turn"):
            text = event.get("text")
            if event.get("inject"):
                continue                      # the test makes this event fail after inserting its row: rolled back
            if isinstance(text, str) and text.strip():
                out.append(_text_marker(text))
            elif kind == "agent_turn" and _dicts(event.get("tools")):
                first = _dicts(event.get("tools"))[0]
                code = str(first.get("input").get("code", "")) if isinstance(first.get("input"), dict) else ""
                out.append(_text_marker(code))
            elif kind == "agent_turn" and (_dicts(event.get("files")) or _buildable(event)):
                out.append("?")
        else:
            out.append(_text_marker(event["text"]) if isinstance(event.get("text"), str) else "?")
    return out


def tool_orders(dock):
    """For every turn that has tools: its answer marker and the ordered (tool name, code) pairs."""
    out = []
    for t in dock.transcript_widget.findChildren(AgentTurnBubble):
        if t._tool_rows:
            hit = MARK.search(t.text_lbl.text())
            pairs = tuple((r.toolTip(), str(r._input.get("code", ""))) for r in t._tool_rows)
            out.append((hit.group(1) if hit else "", pairs))
    return out


def expected_tool_orders(events):
    out = []
    for e in events:
        if not (isinstance(e, dict) and e.get("type") == "agent_turn" and _dicts(e.get("tools"))):
            continue
        text = e.get("text")
        hit = MARK.search(text) if isinstance(text, str) else None
        pairs = tuple((str(t.get("name", "tool")), str(t["input"].get("code", "")))
                      for t in _dicts(e.get("tools")) if isinstance(t.get("input"), dict))
        out.append((hit.group(1) if hit else "", pairs))
    return out


def synthetic_sessions(settings, active="D"):
    """Sessions A, B, C (malformed rows), D (damaged) and E in a store on ``settings``.

    Returns ``{"ids": {tag: id}, "events": {tag: events}}``. Tags in the stored texts let a test
    say which session a row was built from.
    """
    store = SessionStore(settings=settings)
    ids, events = {}, {}

    def save(tag, ev):
        session = store.create_session(tag)
        store.save_session(session["id"], backend_history=[], transcript_events=ev)
        ids[tag], events[tag] = session["id"], ev

    save("B", session_events("B", 3))
    ev_a = session_events("A", 40)
    ev_a.insert(5, {"type": "compaction"})
    save("A", ev_a)
    ev_c = session_events("C", 30)
    # None nested tool: the valid one is kept
    ev_c[11]["tools"] = [None, {"name": "run_pyqgis", "input": {"code": "C-T5-7"}, "result": "ok"}]
    ev_c[21] = {"type": "agent_turn", "tools": "not a list", "text": 5}  # nothing renderable: no row
    ev_c[8]["text"] = None                                               # user row without text: no row
    ev_c.insert(7, {"type": "widget", "data": 1})                        # unknown type: no row
    ev_c.insert(9, None)                                                 # not a dict: no row
    ev_c.insert(13, {"type": "stats", "data": 5, "raises": True})        # the renderer raises: rolled back
    save("C", ev_c)
    ev_d = session_events("D", 8)
    ev_d[5] = {"type": "agent_turn", "thinking": "", "tools": [], "text": "",
               "visuals": [{"kind": "unknown", "data": {}}]}            # only a visual that cannot be built: no row
    ev_d.insert(4, {"type": "stats", "data": 5, "raises": True})        # the renderer raises: rolled back
    ev_d.insert(9, {"type": "user", "text": "X-U9", "inject": "after-insert"})  # fails after inserting a row
    mixed = next(e for e in ev_d if isinstance(e, dict) and "D-A6" in str(e.get("text")))
    # mixed: answer and two tools
    mixed["tools"] = [{"name": "list_layers", "input": {"code": "D-M6-0"}, "result": "ok"},
                      {"name": "run_pyqgis", "input": {"code": "D-M6-1"}, "result": "ok"}]
    save("D", ev_d)
    ev_e = session_events("E", 40)
    ev_e.insert(22, {"type": "user", "text": "X-U22", "inject": "after-insert"})  # fails in the second batch
    save("E", ev_e)
    assert store.set_active_session(ids[active])
    return {"ids": ids, "events": events}


def recording_events(raised, inject=None):
    """A patch of ``ChatDock._restore_event`` that notes in ``raised`` every event whose renderer failed.

    With ``inject`` (a list), an event flagged ``inject: "after-insert"`` first adds a row and then
    fails, so that a row was built when the event fails.
    """
    original = ChatDock._restore_event

    def restore_event(self, event):
        try:
            if inject is not None and isinstance(event, dict) and event.get("inject") == "after-insert":
                label = QLabel("partial row")
                label.setObjectName("injected-partial-row")
                inject.append(label)
                self._add_widget(label)
                raise RuntimeError("injected after insertion")
            return original(self, event)
        except Exception:
            raised.append(event)
            raise

    return patch.object(ChatDock, "_restore_event", restore_event)


class FakeBackend:
    """Streams ``chunks`` text chunks, ``pause`` seconds apart, then DONE."""

    label = "fake"

    def __init__(self, chunks=60, pause=0.02, validate=None):
        self.chunks, self.pause, self._validate = chunks, pause, validate

    def validate(self):
        return self._validate

    def prewarm(self):
        pass

    def send(self, message, history, emit, should_stop):
        for i in range(self.chunks):
            if should_stop():
                break
            emit(AgentEvent(EventType.TEXT, {"text": PARA % i + "\n\n"}))
            time.sleep(self.pause)
        emit(AgentEvent(EventType.DONE, {}))
        return history + [{"role": "user", "content": message}]


class DockCase(unittest.TestCase):
    """A dock on temporary settings, built the way the onboarding tests build one."""

    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        # Row heights scale with the font. Another test module may have changed the plugin's font
        # scale, and nothing set would make it fall back to the user's saved QGIS setting.
        cls.addClassCleanup(setattr, theme, "_user_scale", theme._user_scale)
        theme.set_font_scale(1.0)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.settings = QSettings(str(Path(temp.name) / "s.ini"), QSettings.Format.IniFormat)
        self.config = config_mod.Config()
        self.config._s = self.settings
        self.config.set("api_key", "secret")     # configured, so the chat page is the one on show

    def make_dock(self, backend=lambda: None):
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=self.config)
        dock = ChatDock(
            backend, lambda: None, lambda: None, toolkit,
            session_store=SessionStore(settings=self.settings),
            show_startup_picker=False, config=self.config,
        )
        self.addCleanup(self._dispose, dock)
        dock.resize(380, 650)
        dock.show()
        settle(300)
        return dock

    def _dispose(self, widget):
        settings_dialog = import_module(f"{pkg}.gui.settings_dialog")
        for task in list(settings_dialog._LIVE_TASKS):
            task.wait(5000)
        worker = widget._worker
        if worker is not None:
            widget._stop_active_worker()
            worker.wait(5000)
            self.app.processEvents()            # its queued signals land while the dock still exists
        if widget._restoring_transcript:
            wait_restored(widget)               # a queued batch must not outlive the dock
        shutdown = getattr(getattr(widget, "_onboarding_page", None), "shutdown", None)
        if shutdown:
            shutdown()
        widget.close()
        widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def verify(self, results):
        """Report every failed check under its own name."""
        for name, (ok, detail) in results.items():
            with self.subTest(check=name):
                self.assertTrue(ok, detail)

    def unpinned_at_maximum(self, dock):
        """Leave the view unpinned exactly at the bottom: a notch up, then a range shrink that clamps.

        Answers are hidden one by one until the range has shrunk under the unpinned value.
        """
        vs = dock.scroll.verticalScrollBar()
        wheel(dock.scroll.viewport())
        for turn in reversed(dock.transcript_widget.findChildren(AgentTurnBubble)):
            if vs.value() >= vs.maximum():
                break
            if turn._answer.isVisible():
                turn._answer.setVisible(False)
                turn.updateGeometry()
                settle(250)
        settle(300)
        return dock._pinned is False and vs.value() == vs.maximum()

    def grow(self, dock, tag):
        """Append one short user row to the transcript. Returns how much the scroll range grew.

        A user row has a height of its own in every geometry; a turn with only tool rows may not.
        """
        vs = dock.scroll.verticalScrollBar()
        before = vs.maximum()
        dock._add_widget(MessageContainer("grow %s" % tag, sender_name="You", is_user=True))
        settle(400)
        return vs.maximum() - before


class ScrollInputTests(DockCase):
    """S3: the scroll controller with real input events."""

    def test_input_pins_and_unpins(self):
        dock = self.make_dock()
        vs = bar = dock.scroll.verticalScrollBar()
        vp = dock.scroll.viewport()
        area_reports, bar_reports, focus_calls = [], [], []
        dock.scroll.reader_scrolled.connect(area_reports.append)
        bar.reader_scrolled.connect(bar_reports.append)
        real_focus = dock.scroll.focusNextPrevChild

        def counted_focus(next_):
            focus_calls.append(next_)
            return real_focus(next_)

        for _ in range(6):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))
        results = {}
        try:
            with patch.object(dock.scroll, "focusNextPrevChild", counted_focus):
                record(results, "live_turns_followed_to_bottom", dock._pinned is True and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)

                wheel(vp)
                record(results, "wheel_up_unpins", dock._pinned is False and len(area_reports) == 1,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned, area_reports=len(area_reports))
                v_saved = vs.value()
                added_turn(dock, "\n\n".join(PARA % k for k in range(1, 7)))
                record(results, "growth_keeps_exact_position_when_unpinned",
                       vs.maximum() >= v_saved + 200 and vs.value() == v_saved and dock._pinned is False,
                       value=vs.value(), saved=v_saved, maximum=vs.maximum())

                # A range shrink under the unpinned value: Qt clamps it onto the new maximum. That
                # value change must not read as "at the bottom".
                record(results, "clamp_setup_unpinned_at_maximum", self.unpinned_at_maximum(dock))
                record(results, "clamp_keeps_unpinned", dock._pinned is False and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
                QTest.keyClick(vp, Qt.Key.Key_Shift)
                settle(150)
                record(results, "unrelated_key_does_not_pin", dock._pinned is False, pinned=dock._pinned)
                v_clamped = vs.value()
                grew = self.grow(dock, "grow0")
                record(results, "no_growth_followed_after_clamp",
                       grew > 0 and vs.value() == v_clamped and dock._pinned is False,
                       grew=grew, value=vs.value(), maximum=vs.maximum())

                QTest.keyClick(vp, Qt.Key.Key_PageDown)
                settle(200)
                record(results, "PageDown_pins", dock._pinned is True and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum())
                QTest.keyClick(vp, Qt.Key.Key_Home)     # the viewport rejects Home: no scroll input was handled
                settle(150)
                record(results, "Home_on_viewport_changes_nothing",
                       dock._pinned is True and vs.value() == vs.maximum(), value=vs.value(), maximum=vs.maximum())
                QTest.keyClick(vp, Qt.Key.Key_PageUp)
                settle(200)
                record(results, "PageUp_unpins", dock._pinned is False, value=vs.value(), maximum=vs.maximum())

                reports = len(bar_reports)
                drag_bar(bar, bar.height() - 3)
                settle(250)
                record(results, "drag_to_bottom_pins",
                       dock._pinned is True and vs.value() == vs.maximum() and len(bar_reports) - reports >= 3,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned, reports=len(bar_reports) - reports)
                drag_bar(bar, bar.height() // 3)
                settle(250)
                record(results, "drag_up_unpins", dock._pinned is False, value=vs.value(), maximum=vs.maximum())
                record(results, "wheel_to_bottom_pins", to_bottom(dock) and dock._pinned is True,
                       value=vs.value(), maximum=vs.maximum())

                dock.resize(300, 650)
                settle(1500)
                record(results, "resize_keeps_bottom", dock._pinned is True and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum())
                record(results, "row_caps_follow_narrow_viewport", caps_follow(dock),
                       caps=[(w.minimumWidth(), w.maximumWidth()) for w in rows(dock)],
                       transcript=dock.transcript_widget.width())
                # Far enough above the bottom that the wider dock, where the text needs fewer lines,
                # cannot clamp the value.
                notches = 0
                while vs.value() > vs.maximum() * 0.4 and notches < 2000:
                    wheel(vp, 10, pause=0)
                    notches += 10
                v_saved = vs.value()
                dock.resize(520, 650)
                settle(1500)
                record(results, "resize_keeps_unpinned_value",
                       vs.maximum() >= v_saved + 1 and vs.value() == v_saved and dock._pinned is False,
                       value=vs.value(), saved=v_saved, maximum=vs.maximum(), pinned=dock._pinned)
                record(results, "row_caps_follow_wide_viewport", caps_follow(dock),
                       caps=[(w.minimumWidth(), w.maximumWidth()) for w in rows(dock)],
                       transcript=dock.transcript_widget.width())
                for _ in range(3):
                    added_turn(dock, "\n\n".join(PARA % k for k in range(1, 9)))
                record(results, "wheel_to_bottom_pins_2", to_bottom(dock) and dock._pinned is True,
                       value=vs.value(), maximum=vs.maximum())
                dock.resize(300, 650)
                settle(1500)
                record(results, "pinned_after_narrow", dock._pinned is True and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum())

                wheel(vp)
                record(results, "one_notch_up_unpins", dock._pinned is False and vs.maximum() - vs.value() < 120,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
                dock.resize(520, 650)
                settle(1500)
                record(results, "resize_clamp_keeps_unpinned", dock._pinned is False and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum())

                # Focus navigation: Tab moves the focus and may scroll. It must never pin.
                wheel(vp)
                tabs = 0
                while tabs < 200 and vs.value() < vs.maximum() - PIN_EPS:
                    QTest.keyClick(vp, Qt.Key.Key_Tab)
                    tabs += 1
                    settle(80)
                record(results, "Tab_arrival_stays_unpinned",
                       tabs > 0 and vs.value() >= vs.maximum() - PIN_EPS and dock._pinned is False
                       and len(focus_calls) == tabs,
                       tabs=tabs, focus_calls=len(focus_calls), value=vs.value(), maximum=vs.maximum(),
                       pinned=dock._pinned)
                QTest.keyClick(vp, Qt.Key.Key_PageDown)
                settle(150)
                record(results, "keyboard_recovery_after_Tab", dock._pinned is True and vs.value() == vs.maximum(),
                       value=vs.value(), maximum=vs.maximum())

                # Backward focus navigation also scrolls without passing an input handler: only the
                # value rule can unpin the view then.
                back = 0
                while back < tabs and vs.value() >= vs.maximum() - PIN_EPS:
                    QTest.keyClick(vp, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
                    back += 1
                    settle(30)
                record(results, "backward_Tab_scrolling_unpins",
                       0 < back <= tabs and vs.value() < vs.maximum() - PIN_EPS and dock._pinned is False,
                       back=back, tabs=tabs, value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
        finally:
            self.verify(results)

    def test_wheel_over_the_scrollbar_counts_as_input(self):
        """A wheel event that lands on the scrollbar itself is reader input too."""
        dock = self.make_dock()
        vs = bar = dock.scroll.verticalScrollBar()
        for _ in range(6):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))
        wheel_event(bar, 120)
        settle(150)
        self.assertFalse(dock._pinned)
        self.assertLess(vs.value(), vs.maximum())
        notches = 0
        while vs.value() < vs.maximum() - PIN_EPS and notches < 600:
            wheel_event(bar, -120)
            notches += 1
        settle(200)
        self.assertLess(notches, 600)
        self.assertTrue(dock._pinned)
        self.assertEqual(vs.value(), vs.maximum())

    def test_input_that_cannot_move_still_unpins(self):
        """On a transcript that fits the viewport a wheel up moves nothing, yet the reader asked to
        leave the bottom: the next content must not be followed."""
        dock = self.make_dock()
        vs = dock.scroll.verticalScrollBar()
        added_turn(dock, PARA % 1)
        self.assertEqual(vs.maximum(), 0)
        self.assertTrue(dock._pinned)
        wheel_event(dock.scroll.viewport(), 0)                 # no vertical delta: not scroll input
        wheel_event(dock.scroll.viewport(), 0, delta_x=120)    # horizontal only: not scroll input
        settle(150)
        self.assertTrue(dock._pinned)
        wheel(dock.scroll.viewport())
        self.assertFalse(dock._pinned)
        added_turn(dock, "\n\n".join(PARA % k for k in range(1, 7)))
        self.assertGreater(vs.maximum(), 200)
        self.assertEqual(vs.value(), 0)
        self.assertFalse(dock._pinned)

    def test_unrelated_input_never_pins(self):
        """At an unpinned maximum only input the reader meant as "down" re-pins the view."""
        dock = self.make_dock()
        vs = bar = dock.scroll.verticalScrollBar()
        vp = dock.scroll.viewport()
        for _ in range(10):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 3)))
        results = {}
        try:
            def at_maximum(group):
                """The setup for one group of checks: unpinned exactly at the bottom."""
                record(results, "setup_unpinned_at_maximum_" + group, self.unpinned_at_maximum(dock),
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)

            at_maximum("right_click")
            v0 = vs.value()
            mouse(bar, QEvent.Type.MouseButtonPress, handle_center(bar), button=RIGHT)
            mouse(bar, QEvent.Type.MouseButtonRelease, handle_center(bar), button=RIGHT)
            record(results, "right_click_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g1")
            record(results, "no_growth_followed_after_right_click",
                   grew > 0 and vs.value() == v0 and dock._pinned is False, grew=grew, value=vs.value(), was=v0)

            wheel_event(vp, 0)
            settle(150)
            record(results, "zero_delta_wheel_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g2")
            record(results, "no_growth_followed_after_zero_delta",
                   grew > 0 and vs.value() == v0 and dock._pinned is False, grew=grew, value=vs.value(), was=v0)

            wheel_event(vp, 0, delta_x=120)
            settle(150)
            record(results, "horizontal_wheel_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g3")
            record(results, "no_growth_followed_after_horizontal_wheel",
                   grew > 0 and vs.value() == v0 and dock._pinned is False, grew=grew, value=vs.value(), was=v0)

            # A deliberate downward command that reaches the edge resumes following.
            at_maximum("downward_notch")
            v2 = vs.value()
            record(results, "clamp_keeps_unpinned_again", dock._pinned is False and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())
            QTest.keyClick(vp, Qt.Key.Key_Up)
            settle(150)
            record(results, "Up_unpins_and_moves", dock._pinned is False and vs.value() < v2, value=vs.value(), was=v2)
            wheel_event(vp, -120)
            settle(150)
            record(results, "downward_notch_reaches_bottom_pins", dock._pinned is True and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())
            grew = self.grow(dock, "g5")
            record(results, "growth_followed_after_downward_notch",
                   grew > 0 and dock._pinned is True and vs.value() == vs.maximum(),
                   grew=grew, value=vs.value(), maximum=vs.maximum())

            # A left click on the thumb without moving is deliberate scrollbar input: the position decides.
            at_maximum("thumb_click")
            record(results, "clamp_keeps_unpinned_2", dock._pinned is False and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())
            QTest.keyClick(vp, Qt.Key.Key_End)      # the viewport rejects End: it cannot re-pin
            settle(150)
            record(results, "End_on_viewport_does_not_pin", dock._pinned is False and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
            p = handle_center(bar)
            mouse(bar, QEvent.Type.MouseButtonPress, p)
            mouse(bar, QEvent.Type.MouseButtonRelease, p)
            record(results, "left_click_on_thumb_pins_at_edge", dock._pinned is True and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())
            grew = self.grow(dock, "g4")
            record(results, "growth_followed_after_left_click", grew > 0 and vs.value() == vs.maximum(),
                   grew=grew, value=vs.value(), maximum=vs.maximum())

            # A release with no matching press changes nothing.
            at_maximum("unmatched_release")
            v3 = vs.value()
            mouse(bar, QEvent.Type.MouseButtonRelease, handle_center(bar))
            record(results, "unmatched_release_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g6")
            record(results, "no_growth_followed_after_unmatched_release",
                   grew > 0 and vs.value() == v3 and dock._pinned is False, grew=grew, value=vs.value(), was=v3)

            # Home and End are accepted by the scrollbar that has the focus, not by the viewport.
            bar.setFocus(Qt.FocusReason.OtherFocusReason)
            QTest.keyClick(bar, Qt.Key.Key_End)
            settle(200)
            record(results, "End_on_scrollbar_pins", dock._pinned is True and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())
            QTest.keyClick(bar, Qt.Key.Key_Home)
            settle(200)
            record(results, "Home_on_scrollbar_unpins", dock._pinned is False and vs.value() == 0,
                   value=vs.value(), maximum=vs.maximum())
            # Toward the bottom is not enough: the bottom must be in view afterwards.
            wheel_event(vp, -120)
            settle(150)
            v_partial = vs.value()
            record(results, "downward_notch_below_the_bottom_stays_unpinned",
                   dock._pinned is False and 0 < v_partial < vs.maximum(), value=v_partial, maximum=vs.maximum())
            QTest.keyClick(vp, Qt.Key.Key_PageDown)
            settle(200)
            v_partial = vs.value()
            record(results, "PageDown_below_the_bottom_stays_unpinned",
                   dock._pinned is False and v_partial < vs.maximum(), value=v_partial, maximum=vs.maximum())
            grew = self.grow(dock, "g10")
            record(results, "no_growth_followed_after_partial_descent",
                   grew > 0 and vs.value() == v_partial and dock._pinned is False,
                   grew=grew, value=vs.value(), was=v_partial)

            # What a left press landed on decides what its release means. With the dock's style sheet
            # the style reports no control for points outside the thumb, so a click there neither
            # scrolls nor changes the pin state.
            record(results, "to_bottom_before_trough", to_bottom(dock))
            wheel(vp)
            v4, p4 = vs.value(), dock._pinned
            off_thumb = QPoint(bar.width() // 2, 3)
            mouse(bar, QEvent.Type.MouseButtonPress, off_thumb)
            record(results, "press_off_thumb_is_no_interaction", bar._pin_control is None, control=bar._pin_control)
            mouse(bar, QEvent.Type.MouseButtonRelease, off_thumb)
            record(results, "click_off_thumb_changes_nothing", vs.value() == v4 and dock._pinned == p4,
                   value=vs.value(), was=v4, pinned=dock._pinned)
            thumb = handle_center(bar)
            mouse(bar, QEvent.Type.MouseButtonPress, thumb)
            record(results, "press_on_thumb_is_a_thumb_interaction", bar._pin_control == "thumb",
                   control=bar._pin_control)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb)
            record(results, "release_clears_the_interaction", bar._pin_control is None, control=bar._pin_control)

            # Other buttons never touch a left interaction in progress.
            at_maximum("chord")
            mouse(bar, QEvent.Type.MouseButtonPress, thumb)
            mouse(bar, QEvent.Type.MouseButtonPress, thumb, button=RIGHT, buttons=LEFT | RIGHT)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb, button=RIGHT, buttons=LEFT)
            record(results, "other_button_keeps_the_interaction", bar._pin_control == "thumb", control=bar._pin_control)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb)
            record(results, "left_release_after_chord_pins_at_edge",
                   dock._pinned is True and vs.value() == vs.maximum(), value=vs.value(), maximum=vs.maximum())
            grew = self.grow(dock, "g7")
            record(results, "growth_followed_after_chord",
                   grew > 0 and dock._pinned is True and vs.value() == vs.maximum(),
                   grew=grew, value=vs.value(), maximum=vs.maximum())

            # The reverse chord: Qt starts no drag while another button is held, so nothing is recorded.
            at_maximum("reverse_chord")
            mouse(bar, QEvent.Type.MouseButtonPress, thumb, button=RIGHT, buttons=RIGHT)
            mouse(bar, QEvent.Type.MouseButtonPress, thumb, button=LEFT, buttons=LEFT | RIGHT)
            record(results, "reverse_chord_records_nothing", bar._pin_control is None and not bar.isSliderDown(),
                   control=bar._pin_control, slider_down=bar.isSliderDown())
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb, button=LEFT, buttons=RIGHT)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb, button=RIGHT, buttons=Qt.MouseButton.NoButton)
            record(results, "reverse_chord_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g8")
            record(results, "growth_keeps_position_after_reverse_chord",
                   grew > 0 and vs.value() < vs.maximum() and dock._pinned is False,
                   grew=grew, value=vs.value(), maximum=vs.maximum())

            # A lost mouse grab ends a thumb interaction.
            at_maximum("ungrab")
            mouse(bar, QEvent.Type.MouseButtonPress, thumb)
            record(results, "thumb_press_is_recorded", bar._pin_control == "thumb" and bar.isSliderDown(),
                   control=bar._pin_control, slider_down=bar.isSliderDown())
            QApplication.sendEvent(bar, QEvent(QEvent.Type.UngrabMouse))
            record(results, "ungrab_ends_the_interaction", bar._pin_control is None, control=bar._pin_control)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb)
            record(results, "release_after_ungrab_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "g9")
            record(results, "growth_keeps_position_after_ungrab",
                   grew > 0 and vs.value() < vs.maximum() and dock._pinned is False,
                   grew=grew, value=vs.value(), maximum=vs.maximum())
            record(results, "to_bottom_after_ungrab", to_bottom(dock))

            # A hidden scrollbar ends a thumb interaction.
            at_maximum("hidden_bar")
            mouse(bar, QEvent.Type.MouseButtonPress, thumb)
            bar.hide()
            bar.show()
            settle(100)
            record(results, "hidden_scrollbar_ends_the_interaction", bar._pin_control is None, control=bar._pin_control)
            mouse(bar, QEvent.Type.MouseButtonRelease, thumb)
            record(results, "release_after_hidden_scrollbar_does_not_pin", dock._pinned is False, pinned=dock._pinned)

            # A move or a release counts only for a press that landed on the thumb.
            at_maximum("move_off_thumb")
            bottom = QPoint(bar.width() // 2, bar.height() - 3)
            mouse(bar, QEvent.Type.MouseButtonPress, off_thumb)
            mouse(bar, QEvent.Type.MouseMove, bottom)
            record(results, "move_after_a_press_off_the_thumb_is_no_input",
                   bar._pin_control is None and dock._pinned is False and vs.value() == vs.maximum(),
                   control=bar._pin_control, value=vs.value(), maximum=vs.maximum())
            mouse(bar, QEvent.Type.MouseButtonRelease, bottom)
            record(results, "release_after_a_press_off_the_thumb_does_not_pin", dock._pinned is False,
                   pinned=dock._pinned)

            # On a plain scrollbar Qt pages at once on a trough press, which moves the thumb under
            # the cursor: the control has to be recorded before Qt handles the press. With the thumb
            # at the top, one page moves it by its own length, onto a point just below it.
            record(results, "to_bottom_before_plain_trough", to_bottom(dock))
            sheet = dock.scroll.styleSheet()
            dock.scroll.setStyleSheet("")
            try:
                settle(600)
                vs.setValue(0)
                settle(200)
                handle = handle_rect(bar)
                below = QPoint(bar.width() // 2, handle.bottom() + 1 + min(20, handle.height() // 2))
                v_before = vs.value()
                mouse(bar, QEvent.Type.MouseButtonPress, below)
                record(results, "plain_trough_press_recorded_as_toward",
                       bar._pin_control == "toward" and vs.value() > v_before,
                       control=bar._pin_control, value=vs.value(), was=v_before)
                settle(900)                    # Qt pages on while the press is held
                mouse(bar, QEvent.Type.MouseButtonRelease, below)
                record(results, "plain_trough_release_below_the_bottom_does_not_pin",
                       bar._pin_control is None and dock._pinned is False and vs.value() < vs.maximum(),
                       control=bar._pin_control, value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)

                # Held at the lower edge, Qt steps on until the bottom is in view.
                record(results, "to_bottom_before_plain_edge", to_bottom(dock))
                wheel(vp)
                edge = QPoint(bar.width() // 2, bar.height() - 3)
                mouse(bar, QEvent.Type.MouseButtonPress, edge)
                record(results, "plain_edge_press_recorded_as_toward", bar._pin_control == "toward",
                       control=bar._pin_control)
                t0 = time.monotonic()
                while vs.value() < vs.maximum() - PIN_EPS and time.monotonic() - t0 < 10:
                    settle(100)
                mouse(bar, QEvent.Type.MouseButtonRelease, edge)
                record(results, "plain_trough_release_pins_at_bottom",
                       dock._pinned is True and vs.value() == vs.maximum(), value=vs.value(), maximum=vs.maximum())
            finally:
                dock.scroll.setStyleSheet(sheet)
            settle(600)
        finally:
            self.verify(results)

    def test_range_notifications_write_once_inside(self):
        """While pinned, the controller writes at most once per range notification and never outside one."""
        dock = self.make_dock()
        vs = dock.scroll.verticalScrollBar()
        for _ in range(6):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))
        results = {}
        try:
            record(results, "to_bottom_before_pinned_clamp", to_bottom(dock) and dock._pinned is True)
            notice = {"inside": False, "cur": 0, "log": [], "outside": 0}

            def before(*_):
                notice["inside"] = True
                notice["cur"] = 0

            def after(*_):
                notice["inside"] = False
                notice["log"].append(notice["cur"])

            real_set = vs.setValue

            def counted_set(value):
                if notice["inside"]:
                    notice["cur"] += 1
                else:
                    notice["outside"] += 1
                real_set(value)

            # The controller is bracketed by two observers, so a write is attributed to the
            # notification it happens in, or counted as a write outside every notification.
            vs.rangeChanged.disconnect(dock._on_range_changed)
            vs.rangeChanged.connect(before)
            vs.rangeChanged.connect(dock._on_range_changed)
            vs.rangeChanged.connect(after)
            vs.setValue = counted_set
            try:
                for turn in reversed(dock.transcript_widget.findChildren(AgentTurnBubble)):
                    if turn._answer.isVisible():
                        turn._answer.setVisible(False)
                        turn.updateGeometry()
                        break
                settle(500)
                shrink = list(notice["log"])   # a shrink: Qt notifies before it clamps, the controller clamps
                vs.setRange(1, vs.maximum())   # a minimum-only change: the value is already at the maximum
                settle(200)
                vs.setRange(0, vs.maximum())
                settle(500)
                minimum_only = notice["log"][len(shrink):]
            finally:
                del vs.setValue
                vs.rangeChanged.disconnect(before)
                vs.rangeChanged.disconnect(dock._on_range_changed)
                vs.rangeChanged.disconnect(after)
                vs.rangeChanged.connect(dock._on_range_changed)
            record(results, "shrink_notifications_get_at_most_one_write_inside",
                   len(shrink) >= 1 and max(shrink) <= 1 and dock._pinned is True and vs.value() == vs.maximum(),
                   writes=shrink, value=vs.value(), maximum=vs.maximum())
            record(results, "minimum_only_notifications_write_nothing",
                   len(minimum_only) >= 2 and not any(minimum_only), writes=minimum_only)
            record(results, "no_write_outside_a_notification", notice["outside"] == 0, outside=notice["outside"])

            # A scroll that does not pass through any input handler only ever unpins.
            vs.setValue(vs.maximum() // 2)
            settle(200)
            record(results, "foreign_scroll_unpins", dock._pinned is False,
                   value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
        finally:
            self.verify(results)

    def test_send_reveals_feedback_row(self):
        """Send pins and follows before its validation branches, so the feedback row is in view."""
        dock = self.make_dock()
        vs = dock.scroll.verticalScrollBar()
        vp = dock.scroll.viewport()
        for _ in range(6):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))

        class BadBackend:
            def validate(self):
                return "No API key configured"

        for tag, getter in (("no backend", lambda: None), ("validation error", BadBackend)):
            with self.subTest(branch=tag):
                wheel(dock.scroll.viewport())
                self.assertFalse(dock._pinned)
                dock._get_backend = getter
                n = len(rows(dock))
                dock.input.setPlainText("hello %s" % tag)
                dock._on_send()
                settle(600)
                self.assertEqual(len(rows(dock)), n + 1)
                bubble = rows(dock)[-1].findChild(MessageBubble)
                self.assertIsNotNone(bubble)
                self.assertTrue(bubble.isVisible())
                top = bubble.mapTo(vp, QPoint(0, 0)).y()
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(top + bubble.height(), vp.height())
                self.assertTrue(dock._pinned)
                self.assertEqual(vs.value(), vs.maximum())


class StreamFollowTests(DockCase):
    """S4: the real send path with a fake backend."""

    def test_stream_follows_only_while_pinned(self):
        dock = self.make_dock(backend=lambda: FakeBackend())
        vs = dock.scroll.verticalScrollBar()
        results = {}
        try:
            dock.input.setPlainText("stream please")
            dock._on_send()
            wheeled, v_mid = False, -1
            t0 = time.monotonic()
            while dock._worker is not None and time.monotonic() - t0 < 20:
                settle(10)
                if not wheeled and len(dock._current_text) > 900:
                    wheel(dock.scroll.viewport())
                    v_mid, wheeled = vs.value(), True
            settle(500)
            record(results, "mid_stream_wheel_unpins", wheeled and dock._pinned is False,
                   wheeled=wheeled, pinned=dock._pinned)
            record(results, "DONE_exact_position",
                   wheeled and vs.maximum() >= v_mid + 200 and vs.value() == v_mid,
                   value=vs.value(), v_mid=v_mid, maximum=vs.maximum())
            record(results, "wheel_to_bottom_pins", to_bottom(dock) and dock._pinned is True)

            # The controller is bracketed by two observers, so a write is attributed to the
            # notification it happens in, or counted as a write outside every notification.
            notice = {"inside": False, "cur": 0, "max": 0, "notices": 0, "inside_writes": 0, "outside_writes": 0}

            def notice_before(*_):
                notice["inside"] = True
                notice["cur"] = 0

            def notice_after(*_):
                notice["inside"] = False
                notice["max"] = max(notice["max"], notice["cur"])
                notice["notices"] += 1

            real_set = vs.setValue

            def counted_set(value):
                if notice["inside"]:
                    notice["cur"] += 1
                    notice["inside_writes"] += 1
                else:
                    notice["outside_writes"] += 1
                real_set(value)

            vs.rangeChanged.disconnect(dock._on_range_changed)
            vs.rangeChanged.connect(notice_before)
            vs.rangeChanged.connect(dock._on_range_changed)
            vs.rangeChanged.connect(notice_after)
            vs.setValue = counted_set
            try:
                dock.input.setPlainText("again")
                dock._on_send()
                wait_idle(dock)
            finally:
                del vs.setValue
                vs.rangeChanged.disconnect(notice_before)
                vs.rangeChanged.disconnect(dock._on_range_changed)
                vs.rangeChanged.disconnect(notice_after)
                vs.rangeChanged.connect(dock._on_range_changed)
            record(results, "pinned_follows_to_bottom", vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
            writes = notice["inside_writes"] + notice["outside_writes"]
            record(results, "one_write_inside_each_notification_and_none_outside",
                   notice["notices"] > 0 and notice["max"] <= 1
                   and notice["inside_writes"] == notice["notices"] == writes
                   and notice["outside_writes"] == 0,
                   notices=notice["notices"], most_in_one=notice["max"], inside=notice["inside_writes"],
                   outside=notice["outside_writes"])

            # Stop keeps the bottom when pinned and the exact position when not.
            dock._get_backend = lambda: FakeBackend(chunks=400, pause=0.02)
            dock.input.setPlainText("long one")
            dock._on_send()
            t0 = time.monotonic()
            while dock._worker is not None and len(dock._current_text) < 1500 and time.monotonic() - t0 < 20:
                settle(10)
            dock._on_stop()
            settle(1500)
            record(results, "stop_keeps_bottom_when_pinned", dock._pinned is True and vs.value() == vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())

            dock.input.setPlainText("long two")
            dock._on_send()
            t0 = time.monotonic()
            while dock._worker is not None and len(dock._current_text) < 2500 and time.monotonic() - t0 < 20:
                settle(10)
            wheel(dock.scroll.viewport(), 3)
            v_saved = vs.value()
            t0 = time.monotonic()
            while dock._worker is not None and vs.maximum() < v_saved + 200 and time.monotonic() - t0 < 20:
                settle(10)                      # the stream goes on above the reader
            dock._on_stop()
            settle(1500)
            record(results, "stop_exact_position_when_unpinned",
                   vs.maximum() >= v_saved + 200 and vs.value() == v_saved and dock._pinned is False,
                   value=vs.value(), saved=v_saved, maximum=vs.maximum(), pinned=dock._pinned)
        finally:
            self.verify(results)


class RestoreTests(DockCase):
    """S5: batches, damaged rows, stale callbacks, input during a restore."""

    def test_restore_keeps_a_turn_that_only_thinks(self):
        """A turn stopped while it was thinking is stored with its thinking only; it keeps its row."""
        dock = self.make_dock()
        dock._restore_transcript([
            {"type": "user", "text": "q"},
            {"type": "agent_turn", "thinking": "still thinking", "tools": [], "text": ""},
            {"type": "agent_turn", "thinking": 5, "tools": "not a list", "text": None},
        ])
        wait_restored(dock)
        self.assertEqual(row_markers(dock), ["?", "?"])

    def test_restore_survives_damaged_events(self):
        sessions = synthetic_sessions(self.settings, active="D")
        ev_d, ev_e = sessions["events"]["D"], sessions["events"]["E"]
        injected, raised = [], []
        results = {}
        # The dock is constructed while the damaged session D is active: its damaged rows are in
        # the very first batch.
        with recording_events(raised, inject=injected):
            dock = self.make_dock()
            try:
                exp_d = expected_markers(ev_d)
                wait_restored(dock)
                record(results, "startup_on_damaged_first_batch",
                       not dock._restoring_transcript and dock.transcript_widget.updatesEnabled(),
                       restoring=dock._restoring_transcript, updates=dock.transcript_widget.updatesEnabled())
                record(results, "row_of_failed_event_not_visible", len(injected) == 1 and gone(injected),
                       injected=len(injected))
                markers = row_markers(dock)
                record(results, "damaged_rows_in_order", markers == exp_d and len(raised) == 2,
                       rows=markers, expected=exp_d, rolled_back=len(raised))
                record(results, "damaged_session_recorded_once", len(dock._transcript_events) == len(ev_d),
                       stored=len(dock._transcript_events), events=len(ev_d))
                record(results, "visual_that_cannot_build_leaves_no_row",
                       "D-T2" not in markers and "D-A2" not in markers, rows=markers)
                record(results, "mixed_turn_tool_order_exact", tool_orders(dock) == expected_tool_orders(ev_d),
                       tools=tool_orders(dock), expected=expected_tool_orders(ev_d))
                record(results, "mixed_turn_marker_and_tools_exact",
                       ("D-A6", (("list_layers", "D-M6-0"), ("run_pyqgis", "D-M6-1"))) in tool_orders(dock),
                       tools=tool_orders(dock))
                record(results, "every_row_has_its_marker", "?" not in markers, rows=markers)

                # An exception that escapes a scheduled batch after that batch had begun to publish
                # rows: the generation ends, the rows of the finished events stay, the failed event
                # leaves nothing.
                original_one = ChatDock._restore_one
                calls = {"n": 0}

                def escaping_one(self, event):
                    calls["n"] += 1
                    result = original_one(self, event)
                    if calls["n"] == 24:               # the fourth event of the second batch
                        raise RuntimeError("injected after work began in the second batch")
                    return result

                raised.clear()
                dock._restore_one = MethodType(escaping_one, dock)   # an instance function is not a bound method
                try:
                    dock._switch_to_session(sessions["ids"]["E"], save_current=False)
                    settle(3000)
                finally:
                    del dock._restore_one
                record(results, "failure_in_second_batch_leaves_no_row", len(raised) == 1 and gone(injected),
                       rolled_back=len(raised), injected_visible=not gone(injected))

                # Publication fault: the second row of an event cannot be inserted, and the layout
                # also refuses to hand back the first one.
                created = []

                def two_rows(_event):
                    for _ in range(2):
                        widget = QLabel("synthetic row")
                        created.append(widget)
                        dock._add_widget(widget)

                layout = dock.transcript_layout
                real_insert = layout.insertWidget

                def refuse_second(index, widget):
                    if widget is created[1]:
                        raise RuntimeError("injected: the second insertion fails")
                    real_insert(index, widget)

                count_before = layout.count()
                reported = []
                real_hook = sys.excepthook
                sys.excepthook = lambda *exc: reported.append(exc[0])
                try:
                    with patch.object(dock, "_restore_event", two_rows), \
                            patch.object(layout, "insertWidget", refuse_second), \
                            patch.object(layout, "takeAt", side_effect=RuntimeError):
                        dock._restore_one({"type": "user", "text": "X"})
                finally:
                    sys.excepthook = real_hook
                settle(300)
                record(results, "publication_fault_leaves_no_visible_row", len(created) == 2 and gone(created),
                       created=len(created))
                record(results, "publication_fault_ends_cleanly",
                       dock._restore_staging is None and not dock._restoring_transcript,
                       staging=dock._restore_staging, restoring=dock._restoring_transcript)
                # A batch begins with the sweep; an empty one does nothing else.
                pending, index = dock._pending_restore_events, dock._restore_index
                dock._pending_restore_events, dock._restore_index = [], 0
                dock._restore_batch(schedule=False)
                dock._pending_restore_events, dock._restore_index = pending, index
                settle(300)
                record(results, "detached_row_is_swept_at_the_next_batch",
                       all(not in_layout(layout, widget) for widget in created) and layout.count() == count_before,
                       layout_count=layout.count(), before=count_before,
                       reported_exceptions=[t.__name__ for t in reported])

                record(results, "escaping_batch_ends_generation",
                       not dock._restoring_transcript and dock.transcript_widget.updatesEnabled()
                       and calls["n"] == 24 and dock._restore_index == 24 and len(rows(dock)) == 23
                       and gone(injected),
                       calls=calls["n"], index=dock._restore_index, rows=len(rows(dock)),
                       updates=dock.transcript_widget.updatesEnabled())

                exp_e = expected_markers(ev_e)
                dock._get_backend = lambda: FakeBackend(chunks=5, pause=0.0)
                dock.input.setPlainText("after the failure")
                dock._on_send()
                wait_idle(dock)
                markers = row_markers(dock)
                record(results, "send_works_after_escaping_batch",
                       len(markers) == 25 and markers[:23] == exp_e[:23] and markers[23] == "?"
                       and not dock._restoring_transcript,
                       rows=markers, restoring=dock._restoring_transcript)
            finally:
                self.verify(results)

    def test_restore_switches_input_and_clear(self):
        sessions = synthetic_sessions(self.settings, active="B")
        ids = sessions["ids"]
        ev_a, ev_c = sessions["events"]["A"], sessions["events"]["C"]
        exp_a, exp_c = expected_markers(ev_a), expected_markers(ev_c)
        # at least one callback is pending when each action below runs
        self.assertEqual((len(ev_a), len(exp_a)), (81, 81))
        raised = []
        results = {}
        with recording_events(raised):
            dock = self.make_dock()
            try:
                vs = dock.scroll.verticalScrollBar()

                def pending():
                    return dock._restore_index < len(dock._pending_restore_events) and dock._restoring_transcript

                dock._switch_to_session(ids["A"], save_current=False)
                wait_restored(dock)
                record(results, "a_restore_at_bottom", vs.value() == vs.maximum() and dock._pinned is True,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
                markers = row_markers(dock)
                record(results, "a_restore_rows_exact", markers == exp_a and len(dock._transcript_events) == len(ev_a),
                       rows=markers, stored=len(dock._transcript_events), events=len(ev_a))
                record(results, "a_restore_tool_order_exact", tool_orders(dock) == expected_tool_orders(ev_a),
                       tools=tool_orders(dock), expected=expected_tool_orders(ev_a))
                record(results, "restored_rows_are_capped", caps_follow(dock),
                       caps=sorted({(w.minimumWidth(), w.maximumWidth()) for w in rows(dock)}),
                       transcript=dock.transcript_widget.width())
                notices = [w for w in rows(dock) if isinstance(w, WrapLabel)]
                record(results, "compaction_notice_is_a_wrapping_label",
                       len(notices) == 1 and row_markers(dock).count("!") == 1 and notices[0].wordWrap(),
                       wrap_labels=len(notices), notices=row_markers(dock).count("!"))

                # Switch to B (one batch), then to A.
                dock._switch_to_session(ids["B"], save_current=False)
                settle(800)
                gen_b = dock._restore_generation
                dock._switch_to_session(ids["A"], save_current=False)
                was_pending = pending()
                index, count = dock._restore_index, len(rows(dock))
                dock._resume_restore(gen_b)            # a callback left over from the B restore
                unchanged = (dock._restore_index == index and len(rows(dock)) == count and dock._restoring_transcript)
                record(results, "stale_callback_is_a_noop", was_pending and unchanged,
                       pending=was_pending, index=(index, dock._restore_index), rows=(count, len(rows(dock))))
                wheel(dock.scroll.viewport(), 3)
                wait_restored(dock)
                record(results, "scroll_during_restore_cancels_follow",
                       was_pending and dock._pinned is False and vs.value() < vs.maximum()
                       and row_markers(dock) == exp_a,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned, rows=row_markers(dock))

                # Rapid switches that end on a pending multi-batch restore.
                dock._switch_to_session(ids["B"], save_current=False)
                settle(800)
                dock._switch_to_session(ids["A"], save_current=False)
                dock._switch_to_session(ids["B"], save_current=False)
                dock._switch_to_session(ids["A"], save_current=False)
                was_pending = pending()
                index, count = dock._restore_index, len(rows(dock))
                dock._resume_restore(gen_b)
                unchanged = (dock._restore_index == index and len(rows(dock)) == count)
                wait_restored(dock)
                record(results, "rapid_switch_ends_on_exact_A",
                       was_pending and unchanged and row_markers(dock) == exp_a and not dock._restoring_transcript,
                       pending=was_pending, unchanged=unchanged, rows=row_markers(dock))
                record(results, "rapid_switch_ends_at_bottom", vs.value() == vs.maximum() and dock._pinned is True,
                       value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)

                # Malformed rows: the restore completes, keeps the order, records nothing twice.
                dock._switch_to_session(ids["C"], save_current=False)
                wait_restored(dock)
                markers = row_markers(dock)
                record(results, "malformed_rows_skipped_in_order",
                       not dock._restoring_transcript and markers == exp_c
                       and len(dock._transcript_events) == len(ev_c),
                       restoring=dock._restoring_transcript, rows=markers, stored=len(dock._transcript_events),
                       events=len(ev_c))
                record(results, "malformed_tool_list_keeps_valid_tools",
                       tool_orders(dock) == expected_tool_orders(ev_c),
                       tools=tool_orders(dock), expected=expected_tool_orders(ev_c))
                record(results, "malformed_renderer_error_rolled_back", len(raised) == 1 and markers == exp_c,
                       rolled_back=len(raised))

                # Send between batches: the drain completes, then the live rows follow.
                dock._switch_to_session(ids["A"], save_current=False)
                dock._switch_to_session(ids["C"], save_current=False)
                was_pending = pending()
                dock._get_backend = lambda: FakeBackend(chunks=5, pause=0.0)
                dock.input.setPlainText("live question")
                dock._on_send()
                wait_idle(dock)
                wait_restored(dock)
                markers = row_markers(dock)
                stored = list(dock._transcript_events)
                record(results, "send_between_batches_after_malformed_rows",
                       was_pending and not dock._restoring_transcript
                       and markers[:len(exp_c)] == exp_c and len(markers) == len(exp_c) + 2
                       and len(stored) == len(ev_c) + 2
                       and stored[len(ev_c)] == {"type": "user", "text": "live question"}
                       and stored[-1].get("type") == "agent_turn" and dock.input.toPlainText() == "",
                       pending=was_pending, restoring=dock._restoring_transcript, rows=len(markers),
                       expected=len(exp_c), stored=len(stored), prompt=stored[len(ev_c):len(ev_c) + 1],
                       draft=dock.input.toPlainText())

                # Clear while batches are pending.
                dock._switch_to_session(ids["A"], save_current=False)
                dock._clear_live_ui()
                settle(3000)
                record(results, "clear_stops_pending_batches", len(rows(dock)) == 0 and not dock._restoring_transcript,
                       rows=len(rows(dock)), restoring=dock._restoring_transcript)
            finally:
                self.verify(results)


class CancelledGestureTests(DockCase):
    """S6: cancelled gestures, a failed restore setup, and explicit minimum widths."""

    def test_cancelled_drag_and_failed_restore_setup(self):
        dock = self.make_dock()
        vs = bar = dock.scroll.verticalScrollBar()
        for _ in range(8):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))
        results = {}
        try:
            record(results, "setup_unpinned_at_maximum", self.unpinned_at_maximum(dock))
            pos = handle_center(bar)
            mouse(bar, QEvent.Type.MouseButtonPress, pos)
            record(results, "thumb_press_recorded", bar._pin_control == "thumb" and bar.isSliderDown(),
                   control=bar._pin_control, slider_down=bar.isSliderDown())
            bar.setEnabled(False)
            bar.setEnabled(True)
            settle(200)
            record(results, "disable_cancels_the_gesture", bar._pin_control is None, control=bar._pin_control)
            saved = vs.value()
            mouse(bar, QEvent.Type.MouseButtonRelease, pos)
            record(results, "release_after_cancel_does_not_pin", dock._pinned is False, pinned=dock._pinned)
            grew = self.grow(dock, "c1")
            record(results, "growth_exact_after_cancel",
                   grew > 20 and vs.value() == saved and dock._pinned is False,
                   grew=grew, value=vs.value(), saved=saved, maximum=vs.maximum())

            # A cancelled drag whose release never comes, then a fresh drag that is real.
            record(results, "setup_unpinned_at_maximum_2", self.unpinned_at_maximum(dock))
            mouse(bar, QEvent.Type.MouseButtonPress, pos)
            QApplication.sendEvent(bar, QEvent(QEvent.Type.UngrabMouse))
            mouse(bar, QEvent.Type.MouseButtonRelease, pos)
            saved = vs.value()
            grew = self.grow(dock, "c2")
            record(results, "growth_exact_after_ungrab",
                   grew > 20 and vs.value() == saved and dock._pinned is False,
                   grew=grew, value=vs.value(), saved=saved, maximum=vs.maximum())
            to_bottom(dock)
            drag_bar(bar, bar.height() // 3)
            settle(250)
            record(results, "real_drag_still_unpins", dock._pinned is False and vs.value() < vs.maximum(),
                   value=vs.value(), maximum=vs.maximum())

            # Restore setup failure: the dock must not stay restoring, and a Send must work.
            calls = {"n": 0}

            def failing_prompt(text):
                calls["n"] += 1
                raise RuntimeError("injected into the prompt history")

            raised = False
            with patch.object(dock, "_remember_prompt", failing_prompt):
                try:
                    dock._restore_transcript([{"type": "user", "text": "q"},
                                              {"type": "agent_turn", "text": "a", "tools": []}])
                except Exception:
                    raised = True
            record(results, "setup_failure_does_not_raise", not raised and calls["n"] == 1,
                   raised=raised, prompts_tried=calls["n"])
            record(results, "setup_failure_ends_not_restoring",
                   not dock._restoring_transcript and dock.transcript_widget.updatesEnabled()
                   and dock._restore_staging is None,
                   restoring=dock._restoring_transcript, updates=dock.transcript_widget.updatesEnabled(),
                   staging=dock._restore_staging)
            dock._get_backend = lambda: FakeBackend(chunks=5, pause=0.0)
            n = len(rows(dock))
            dock.input.setPlainText("after the setup failure")
            dock._on_send()
            wait_idle(dock)
            record(results, "send_works_after_setup_failure",
                   len(rows(dock)) == n + 2 and not dock._restoring_transcript,
                   rows=len(rows(dock)), before=n, restoring=dock._restoring_transcript)
        finally:
            self.verify(results)

    def test_row_caps_follow_a_resize_without_scrollbar(self):
        """A dock resize of a transcript that fits the viewport reaches the rows' cap: every row ends
        up capped at the transcript's new width."""
        dock = self.make_dock()
        tw = dock.transcript_widget
        dock._add_widget(MessageContainer("short", sender_name="You", is_user=True))
        settle(200)
        self.assertEqual(dock.scroll.verticalScrollBar().maximum(), 0)
        for width in (520, 300, 380):
            with self.subTest(width=width):
                dock.resize(width, 650)
                settle(800)
                self.assertEqual(dock.scroll.viewport().width(), tw.width())
                self.assertTrue(caps_follow(dock), [(w.minimumWidth(), w.maximumWidth()) for w in rows(dock)])

    def test_explicit_minimum_widths_stay_inside(self):
        """A row, or anything in it, that asks for more width than the dock has cannot widen the transcript."""
        dock = self.make_dock()
        vs = dock.scroll.verticalScrollBar()
        tw = dock.transcript_widget
        for _ in range(6):
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 5)))
        results = {}
        try:
            dock._add_widget(MessageContainer("after", sender_name="You", is_user=True))
            wide_root = QLabel("wide root")
            wide_root.setMinimumWidth(800)
            dock._add_widget(wide_root)
            wide_host = QWidget()
            wide_host.setMinimumWidth(800)
            QLabel("wide child", wide_host)
            dock._add_widget(wide_host)
            inside = QWidget()
            QLabel("wide child", inside).setMinimumWidth(800)
            dock._add_widget(inside)
            settle(800)

            def within_transcript():
                return (wide_root.width() <= tw.width() and wide_host.width() <= tw.width()
                        and inside.width() <= tw.width() and rows_wide(dock) == 0)

            record(results, "viewport_equals_transcript_width", dock.scroll.viewport().width() == tw.width(),
                   viewport=dock.scroll.viewport().width(), transcript=tw.width())
            record(results, "transcript_minimum_within_its_width", tw.minimumSizeHint().width() <= tw.width(),
                   minimum_hint=tw.minimumSizeHint().width(), transcript=tw.width())
            record(results, "row_roots_within_the_transcript", within_transcript(),
                   roots=[(w.width(), w.minimumWidth(), w.maximumWidth()) for w in (wide_root, wide_host, inside)],
                   transcript=tw.width(), rows_wide=rows_wide(dock))

            # The cap follows the viewport, so a later row gets the width the transcript has now.
            for width in (520, 300, 380):
                dock.resize(width, 650)
                settle(1500)
                record(results, "row_caps_follow_viewport_%d" % width,
                       caps_follow(dock) and dock.scroll.viewport().width() == tw.width() and within_transcript(),
                       caps=[(w.minimumWidth(), w.maximumWidth()) for w in (wide_root, wide_host, inside)],
                       viewport=dock.scroll.viewport().width(), transcript=tw.width(), rows_wide=rows_wide(dock))
            dock._add_widget(MessageContainer("later", sender_name="You", is_user=True))
            settle(600)
            record(results, "value_at_bottom_after_all_that", vs.value() == vs.maximum() and dock._pinned is True,
                   value=vs.value(), maximum=vs.maximum(), pinned=dock._pinned)
        finally:
            self.verify(results)


if __name__ == "__main__":
    unittest.main()
