"""Transcript geometry: the Qt layout alone sizes every row of the chat.

Synthetic content only; nothing here reads a saved session.
"""

import base64
from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QSettings, QTranslator
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QLabel, QPushButton, QWIDGETSIZE_MAX, QWidget
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
pkg = ROOT.name
config_mod = import_module(f"{pkg}.config")
SessionStore = import_module(f"{pkg}.core.session_store").SessionStore
QgisToolkit = import_module(f"{pkg}.core.toolkit").QgisToolkit
AgentEvent = import_module(f"{pkg}.backends.base").AgentEvent
EventType = import_module(f"{pkg}.backends.base").EventType
atb_mod = import_module(f"{pkg}.gui.agent_turn_bubble")
mb_mod = import_module(f"{pkg}.gui.message_bubble")
StatsWidget = import_module(f"{pkg}.gui.stats_widget").StatsWidget
GifWidget = import_module(f"{pkg}.gui.gif_widget").GifWidget
theme = import_module(f"{pkg}.gui.theme")
AgentTurnBubble = atb_mod.AgentTurnBubble
ToolCallRow = atb_mod.ToolCallRow
MessageBubble = mb_mod.MessageBubble
MessageContainer = mb_mod.MessageContainer

# The caption contract.
CAPTION_MARGIN = 8         # between the caption and each side of its host
CAPTION_FIT_STEPS = 32     # the caption fit is bounded
CAPTION_MIN_LIMIT = 24     # below this the caption is hidden rather than squeezed

PARA = ("Paragraph %d: the quick brown fox jumps over the lazy dog and keeps running across the map canvas, "
        "which forces a wrap or two at every width.")
TABLE = ("Result:\n\n| name | count | note |\n|---|---|---|---|\n| a | 1 | x |\n| b | 2 | y |\n| c | 3 | z |\n\n"
         + "\n\n".join(PARA % i for i in range(1, 6)))
LONGWORD = "Longest unbroken token: " + "w" * 260 + "\n\n" + PARA % 9
MIXED_CAPTION = ("\u0627 j.A \u0627\u0627 \u0627\u0645 \u202c \u0644.f.\u0627\u0627\U0001f469WA "
                 "\u0645\u0645\U0001f469\u0644 jvvW")
LONG_TOOL = "mcp__awanagis__list_every_layer_with_its_full_symbology_and_metadata_for_the_whole_project"
GIF_BYTES = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")  # a valid 1x1 GIF


class LongTranslations(QTranslator):
    """Interface strings as long as a sentence, where the code normally has a word."""
    LONG = "Übersetzte sehr lange Überschrift " * 12

    def translate(self, context, source, disambiguation=None, n=-1):
        if source in ("Input", "Output", "INPUT", "OUTPUT", "Copy"):
            return self.LONG
        return None


def settle(ms=500):
    QTest.qWait(ms)


def rows(dock):
    lay = dock.transcript_layout
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]


def row_required(row):
    """Height the row's own layout needs at its actual width.

    A leaf label row reports its style-sheet padding inside sizeHint().
    """
    if row.hasHeightForWidth():
        return row.heightForWidth(row.width())
    return max(row.sizeHint().height(), row.minimumSizeHint().height())


def geometry_report(dock):
    """Measure one transcript state.

    Every counter should be 0, except ``stat_short``, the one named exception.
    ``notes`` names each violation with its numbers.
    """
    tw = dock.transcript_widget
    ws = rows(dock)
    report = {"not_contained": 0, "clipped": 0, "stat_short": 0, "slack": 0, "notes": []}
    notes = report["notes"]

    def outside(widget, parent):
        report["not_contained"] += 1
        notes.append("%s %dx%d at x=%d outside %s %dx%d" % (
            type(widget).__name__, widget.width(), widget.height(), widget.x(),
            type(parent).__name__, parent.width(), parent.height()))

    def clipped(widget, need, parent):
        report["clipped"] += 1
        notes.append("%s %dx%d needs height %d in %s %dx%d" % (
            type(widget).__name__, widget.width(), widget.height(), need,
            type(parent).__name__, parent.width(), parent.height()))

    bounds = tw.rect()
    for w in ws:
        if not bounds.contains(w.geometry()):
            outside(w, tw)                    # the row itself must stay inside the transcript
        if isinstance(w, QLabel) and w.wordWrap() and w.isVisible() and w.height() < w.heightForWidth(w.width()):
            clipped(w, w.heightForWidth(w.width()), tw)    # a wrapped row root gets the same check
        for c in w.findChildren(QWidget):
            if c.isWindow() or not c.isVisible():
                continue
            p = c.parentWidget()
            if p is not None and not p.rect().contains(c.geometry()):
                outside(c, p)
            if isinstance(c, QLabel) and c.wordWrap():
                need = c.heightForWidth(c.width())
                if need >= 0 and c.height() < need:
                    short = need - c.height()
                    if isinstance(p.parentWidget(), StatsWidget) and short <= 4:
                        report["stat_short"] += 1    # named exception: stat leaves may be up to 4 px short
                    else:
                        clipped(c, need, p)
        excess = w.height() - row_required(w)
        if excess > 1:
            report["slack"] = max(report["slack"], excess)
            notes.append("%s %dx%d is taller than its required %d" % (
                type(w).__name__, w.width(), w.height(), row_required(w)))
    for t in tw.findChildren(AgentTurnBubble):
        if not t.isVisible():
            continue
        area = t._tools_area
        need = area.heightForWidth(area.width()) if area.hasHeightForWidth() else area.sizeHint().height()
        if area.isVisible() and area.height() < need:
            clipped(area, need, t)           # the tool list
        frame = t._answer
        need = frame.heightForWidth(frame.width()) if frame.hasHeightForWidth() else frame.minimumSizeHint().height()
        if frame.isVisible() and frame.height() < need:
            clipped(frame, need, t)          # the answer frame
        if t.height() < t.minimumSizeHint().height():
            clipped(t, t.minimumSizeHint().height(), t.parentWidget())
    vs = dock.scroll.verticalScrollBar()
    last = ws[-1].geometry() if ws else None
    gap = ((tw.height() - dock.transcript_layout.contentsMargins().bottom())
           - (last.y() + last.height())) if last is not None else 0   # QRect.bottom() is inclusive
    if tw.minimumSizeHint().width() > tw.width():
        notes.append("transcript minimum width %d is wider than its width %d" % (
            tw.minimumSizeHint().width(), tw.width()))
        report["not_contained"] += 1   # the scroll area would size the transcript at the wider minimum width
    report.update({
        "rows": len(ws),
        "range": vs.maximum(),
        "blank": gap,
        "tw_w": tw.width(),
        "tw_h": tw.height(),
        "max_row_w": max((w.geometry().width() for w in ws), default=0),
    })
    return report


def caption_faults(dock):
    """Caption contract violations, over every GIF that carries captions.

    One rendered line, inside its host, at least 8 px from each side, and the original caption as
    tooltip exactly when what is shown differs from it. A missing caption is a violation.
    """
    faults, seen = [], 0
    for gif in dock.transcript_widget.findChildren(GifWidget):
        if not gif._frame_labels:
            continue                              # this GIF carries no captions by design
        seen += 1
        host, overlay = gif._animation_label, gif._label_overlay
        if host is None or overlay is None:
            faults.append("the caption label is missing")
            continue
        if host.width() - 2 * CAPTION_MARGIN < CAPTION_MIN_LIMIT:
            if overlay.isVisible():
                faults.append("a host %d px wide shows a caption" % host.width())
            continue
        if not overlay.isVisible():
            faults.append("a host %d px wide shows no caption" % host.width())
            continue
        original = gif._caption_text
        if overlay.height() > overlay.fontMetrics().height() + 8:
            faults.append("caption on a host %d px wide renders more than one line" % host.width())
        if not host.rect().contains(overlay.geometry()):
            faults.append("caption on a host %d px wide leaves its host" % host.width())
        if overlay.x() < CAPTION_MARGIN or overlay.geometry().right() > host.width() - CAPTION_MARGIN - 1:
            faults.append("caption on a host %d px wide is closer than %d px to a side" % (
                host.width(), CAPTION_MARGIN))
        shortened = overlay.text() != " ".join(original.split()) or overlay.maximumWidth() < QWIDGETSIZE_MAX
        if (overlay.toolTip() == original) != shortened:
            faults.append("caption on a host %d px wide has its tooltip out of step with its text" % host.width())
    if not seen:
        faults.append("no GIF with captions was found")
    return faults


def emit(dock, kind, **data):
    dock._on_event(AgentEvent(kind, data), None)


def added_turn(dock, answer):
    """Append a finished turn without going through send."""
    dock._add_widget(MessageContainer("Question?", sender_name="You", is_user=True))
    emit(dock, EventType.TEXT, text=answer)
    settle(80)
    emit(dock, EventType.DONE)
    settle(300)


def cards(dock, turn, long_titles, gif_path="/nonexistent/x.gif"):
    """Add the four card kinds to a turn."""
    dock._add_stats({"layer_name": "Land use " * 8 if long_titles else "Land use", "total_features": 1200,
                     "crs": "EPSG:4326", "geometry_type": 2, "distinct_count": 7, "min": 0.0, "max": 98.5,
                     "mean": 41.25, "stdev": 3.5})
    dock._add_gif({"name": "Land cover change over time " * 4 if long_titles else "Land cover change",
                   "gif_path": gif_path,
                   "frame_labels": ["A long caption for frame zero " * 4,
                                    ("second line of a caption\n" * 30) + "tail"]})
    dock._add_file({"file_path": "/tmp/" + "long_file_name_" * 12 + ".gpkg", "description": "a description " * 40})
    dock._add_chart({"title": "Chart", "chart_type": "bar", "data": [1, 2, 3], "colors": []})


def fit_caption(gif, widths):
    """Fit the caption to each host width in turn; one record per fit."""
    host, overlay = gif._animation_label, gif._label_overlay
    records = []
    for width in widths:
        host.resize(width, 200)
        records.append({
            "width": width,
            "steps": gif._position_label_overlay(),
            "visible": overlay.isVisible(),
            # A clipped fit fixes the label's width, and only for that fit.
            "clipped": overlay.maximumWidth() < QWIDGETSIZE_MAX,
            "tooltip": overlay.toolTip() == gif._caption_text,
            "inside": host.rect().contains(overlay.geometry()),
            "margins": overlay.x() >= CAPTION_MARGIN and overlay.geometry().right() <= width - CAPTION_MARGIN - 1,
            "one_line": overlay.height() <= overlay.fontMetrics().height() + 8,
        })
    return records


def captioned_gifs(dock):
    """The GIFs of a transcript that carry captions."""
    return [g for g in dock.transcript_widget.findChildren(GifWidget) if g._frame_labels]


def caption_font(overlay):
    """The caption font the hostile-input checks use."""
    overlay.setFont(QFont("DejaVu Sans", 14, QFont.Weight.DemiBold))


class ChatScrollingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        # The contract holds for the plugin's default font scale. fs() caches whatever scale an
        # earlier test or the user's own settings left behind, so the scale is pinned here.
        original_scale = theme._user_scale
        cls.addClassCleanup(setattr, theme, "_user_scale", original_scale)
        theme.set_font_scale(1.0)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.settings = QSettings(str(Path(temp.name) / "o.ini"), QSettings.Format.IniFormat)
        self.config = config_mod.Config()
        self.config._s = self.settings
        self.config.set("api_key", "secret")

    def make_dock(self, width=380):
        ChatDock = import_module(f"{pkg}.gui.chat_dock").ChatDock
        with patch.object(QgisToolkit, "_clean_orphan_gee_tiffs"):
            toolkit = QgisToolkit(iface=None, config=self.config)
        dock = ChatDock(
            lambda: None, lambda: None, lambda: None, toolkit,
            session_store=SessionStore(settings=self.settings),
            show_startup_picker=False, config=self.config,
        )
        dock.resize(width, 650)
        dock.show()
        settle(300)
        self.addCleanup(self._dispose, dock)
        return dock

    def _dispose(self, widget):
        settings_dialog = import_module(f"{pkg}.gui.settings_dialog")
        for task in list(settings_dialog._LIVE_TASKS):
            task.wait(5000)
        self.app.processEvents()
        shutdown = getattr(getattr(widget, "_onboarding_page", None), "shutdown", None)
        if shutdown:
            shutdown()
        widget.close()
        widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def assert_clean(self, states, results=None):
        """One assertion over every measured state and every named check."""
        problems = []
        for name, rep in states:
            problems.extend("%s: %s" % (name, note) for note in rep["notes"])
            if rep["range"] > 0 and not 0 <= rep["blank"] <= 1:
                problems.append("%s: %d blank px below the last row of an overflowing transcript" % (
                    name, rep["blank"]))
        problems.extend("%s: %s" % (name, detail) for name, detail in (results or {}).items() if detail)
        self.assertEqual(problems, [])

    def test_rows_get_the_height_of_their_content(self):
        """Every kind of row at four dock widths, and after resizing back and forth."""
        states, results = [], {}

        def measure(name):
            rep = geometry_report(dock)
            states.append((name, rep))
            return rep

        def captions(name):
            faults = caption_faults(dock)
            results["caption contract, " + name] = "; ".join(faults) if faults else None

        with TemporaryDirectory() as tmp:
            gif_path = str(Path(tmp) / "anim.gif")
            Path(gif_path).write_bytes(GIF_BYTES)
            dock = self.make_dock()
            added_turn(dock, PARA % 1)          # a text turn
            added_turn(dock, TABLE)             # a table with trailing text
            added_turn(dock, LONGWORD)          # a 260-character token
            dock._add_widget(MessageContainer("Do the thing", sender_name="You", is_user=True))
            for i in range(12):
                emit(dock, EventType.TOOL_USE, name=LONG_TOOL if i == 0 else "run_pyqgis",
                     input={"code": "x%d = '%s'" % (i, "v" * 40)})
                settle(30)
                emit(dock, EventType.TOOL_RESULT, name="run_pyqgis", result="r" * 30)
                settle(30)
            emit(dock, EventType.DONE)          # 12 tool rows, no answer
            settle(300)
            added_turn(dock, "\n\n".join(PARA % k for k in range(1, 9)))
            turn = dock._get_or_create_agent_turn()
            cards(dock, turn, long_titles=False, gif_path=gif_path)
            turn.finalize()
            dock._add_error_message("Error: " + "something went wrong here " * 12)
            dock._add_widget(MessageContainer("Short", sender_name="You", is_user=True))
            dock._add_widget(MessageContainer("x" * 200, sender_name="You", is_user=True))
            dock._add_widget(MessageContainer(
                "A message of three lines\nthat should wrap inside the pill " + PARA % 3,
                sender_name="You", is_user=True))

            gifs = captioned_gifs(dock)
            for frame in (1, 0):
                # The fixture GIF has one frame: exercise the second caption by hand.
                for gif in gifs:
                    gif._on_frame_changed(frame)
                for w in (380, 300, 520, 760, 300, 520):
                    dock.resize(w, 650)
                    settle(1200)
                    pills = [b for b in dock.transcript_widget.findChildren(MessageBubble) if b.is_user]
                    measure("width %d, caption %d" % (w, frame))
                    captions("width %d, caption %d" % (w, frame))
                    widest = max(b.width() for b in pills)
                    if widest > 440 or any(b.width() > b.parentWidget().width() for b in pills):
                        results["pill within 440 px and its row, width %d" % w] = "widest pill %d px" % widest
                    hug = min(b.width() for b in pills if len(b.text_label.text()) < 40)
                    if not 60 <= hug <= 200:
                        results["short pill hugs its text, width %d" % w] = "%d px" % hug

            tool_rows = dock.transcript_widget.findChildren(ToolCallRow)
            if len(tool_rows) != 12:
                results["tool rows present"] = "%d of 12" % len(tool_rows)
            for row in tool_rows:
                row._toggle_details()
            settle(800)
            collapsed = [row for row in tool_rows if not row._expanded]
            if collapsed:
                results["tool rows expanded"] = "%d of %d rows stayed collapsed" % (len(collapsed), len(tool_rows))
            for w in (300, 380, 760, 300):
                dock.resize(w, 650)
                settle(1500)
                measure("details open, width %d" % w)
            for row in tool_rows:
                row._toggle_details()

            turn = dock._get_or_create_agent_turn()
            turn.stream_reasoning("thinking about the problem " * 12)
            settle(400)
            measure("reasoning ticker live")
            if not turn._ticker.isVisible():
                results["reasoning ticker live"] = "the ticker is not visible"
            turn.finalize()
            settle(300)
            measure("reasoning ticker gone")
            if turn._ticker.isVisible():
                results["reasoning ticker gone"] = "the ticker is still visible"

            added_turn(dock, PARA % 2)
            turn = dock._get_or_create_agent_turn()
            cards(dock, turn, long_titles=True, gif_path=gif_path)
            turn.finalize()
            settle(1200)
            for w in (380, 300, 760):
                dock.resize(w, 650)
                settle(1500)
                measure("cards with long titles, width %d" % w)
                captions("cards with long titles, width %d" % w)

            # Many tools, a table, a chart and a footer in one turn, plus a 90-character tool name.
            dock._add_widget(MessageContainer("Combined?", sender_name="You", is_user=True))
            turn = dock._get_or_create_agent_turn()
            for i in range(18):
                emit(dock, EventType.TOOL_USE, name=LONG_TOOL if i == 0 else "run_pyqgis", input={"code": "c%d" % i})
                settle(20)
                emit(dock, EventType.TOOL_RESULT, name="run_pyqgis", result="ok")
                settle(20)
            emit(dock, EventType.TEXT, text="Intro paragraph.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
                 + "\n\n".join(PARA % k for k in range(1, 8)))
            settle(120)
            dock._add_chart({"title": "Chart", "chart_type": "bar", "data": [1, 2, 3], "colors": []})
            emit(dock, EventType.DONE)
            settle(800)
            if turn._footer is None or not turn._footer.isVisible():
                results["combined turn footer"] = "missing or hidden"
            for w in (380, 300, 760, 300, 520):
                dock.resize(w, 650)
                settle(1500)
                measure("combined turn, width %d" % w)
                captions("combined turn, width %d" % w)

            # Interface strings as long as a sentence: nothing may widen or clip the transcript.
            translator = LongTranslations()
            QCoreApplication.installTranslator(translator)
            self.addCleanup(QCoreApplication.removeTranslator, translator)
            dock._add_widget(MessageContainer("Translated?", sender_name="You", is_user=True))
            turn = dock._get_or_create_agent_turn()
            emit(dock, EventType.TOOL_USE, name="run_pyqgis", input={"code": "tr"})
            settle(30)
            emit(dock, EventType.TOOL_RESULT, name="run_pyqgis", result="ok")
            settle(30)
            emit(dock, EventType.DONE)
            settle(400)
            for row in turn._tool_rows:
                row._toggle_details()
            settle(1000)
            measure("injected translations, details open")
            widest = max(b.width() for b in dock.transcript_widget.findChildren(QPushButton) if b.isVisible())
            if widest > 150:
                results["injected translations: widest visible button"] = "%d px" % widest
            QCoreApplication.removeTranslator(translator)
        self.assert_clean(states, results)

    def test_caption_fit_under_hostile_input(self):
        """Mixed scripts, hard breaks and a very long run, swept one host pixel at a time."""
        problems = []
        with TemporaryDirectory() as tmp:
            gif_path = Path(tmp) / "anim.gif"
            gif_path.write_bytes(GIF_BYTES)
            dock = self.make_dock()
            dock._add_gif({"name": "Sweep", "gif_path": str(gif_path), "frame_labels": ["zero", "one"]})
            settle(600)
            gifs = captioned_gifs(dock)
            if not gifs:
                problems.append("no GIF with captions was found")
            for gif in gifs:
                host, overlay = gif._animation_label, gif._label_overlay
                caption_font(overlay)
                for caption in (MIXED_CAPTION, "line\n" * 60 + "end", "x" * 4000):
                    for width in range(200, 421):
                        host.resize(width, 200)
                        gif._caption_text = caption
                        steps = gif._position_label_overlay()
                        margins = (overlay.x() >= CAPTION_MARGIN
                                   and overlay.geometry().right() <= width - CAPTION_MARGIN - 1)
                        inside = host.rect().contains(overlay.geometry()) and margins
                        one_line = overlay.height() <= overlay.fontMetrics().height() + 8
                        tooltip_ok = (overlay.text() != " ".join(caption.split())) == (overlay.toolTip() == caption)
                        if not (inside and one_line and tooltip_ok) or steps > CAPTION_FIT_STEPS:
                            problems.append("host %d px, caption %r: steps=%d inside=%s one_line=%s tooltip_ok=%s" % (
                                width, caption[:24], steps, inside, one_line, tooltip_ok))
        self.assertEqual(problems[:20], [], "%d violations; the first 20 are listed" % len(problems))

    def test_caption_hides_on_a_narrow_host_and_recovers(self):
        """The clip fallback lasts one fit, and a host too narrow shows no caption."""
        results = {}
        with TemporaryDirectory() as tmp:
            gif_path = Path(tmp) / "a.gif"
            gif_path.write_bytes(GIF_BYTES)
            dock = self.make_dock()
            caption = "a caption that is long enough to need eliding " * 3
            dock._add_gif({"gif_path": str(gif_path), "frame_labels": [caption]})
            settle(600)
            gifs = captioned_gifs(dock)
            if not gifs:
                results["a GIF with captions"] = "none was found"
            for gif in gifs:
                caption_font(gif._label_overlay)
                # The first fit at a width shows the fallback or the hiding; the repeat shows the recovery.
                trace = fit_caption(gif, (27, 16, 40, 60, 400, 27, 400))

                for index in (0, 1, 5):                # 27 px, 16 px, and 27 px again
                    record = trace[index]
                    if record["visible"] or record["steps"]:
                        results["a host %d px wide hides the caption (fit %d)" % (record["width"], index)] = str(record)
                for index in (4, 6):                   # 400 px, also right after a hidden caption
                    record = trace[index]
                    if not (record["visible"] and not record["clipped"] and record["inside"] and record["margins"]):
                        results["a host 400 px wide shows the whole caption (fit %d)" % index] = str(record)
                record = trace[2]                      # 40 px: no room to elide into, so the fit clips
                if not (record["visible"] and record["clipped"] and record["tooltip"] and record["inside"]
                        and record["margins"]):
                    results["a host 40 px wide keeps a clipped caption with its tooltip"] = str(record)
                record = trace[3]                      # 60 px: visible again after the narrow hosts
                if not (record["visible"] and record["inside"] and record["margins"] and record["one_line"]):
                    results["a host 60 px wide shows the caption again"] = str(record)
                slowest = max(entry["steps"] for entry in trace)
                if slowest > CAPTION_FIT_STEPS:
                    results["caption fit is bounded"] = "%d steps" % slowest
        self.assert_clean([], results)

    def test_short_transcript(self):
        """A transcript that fits asserts its row heights; it has no gap below the last row to assert."""
        dock = self.make_dock()
        added_turn(dock, "Short answer.")
        dock._add_widget(MessageContainer("Three short lines\nin a pill\nfor the user",
                                          sender_name="You", is_user=True))
        settle(800)
        self.assert_clean([("short transcript", geometry_report(dock))])
