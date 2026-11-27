"""The floating jump button: visible while the last message is out of view, and it returns there.

Synthetic content only; nothing here reads a saved session.
"""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSettings, QRect, Qt
from qgis.PyQt.QtGui import QWheelEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
pkg = ROOT.name
config_mod = import_module(f"{pkg}.config")
SessionStore = import_module(f"{pkg}.core.session_store").SessionStore
SETTINGS_KEY = import_module(f"{pkg}.core.session_store").SETTINGS_KEY
QgisToolkit = import_module(f"{pkg}.core.toolkit").QgisToolkit
theme = import_module(f"{pkg}.gui.theme")
chat_dock_mod = import_module(f"{pkg}.gui.chat_dock")
MessageContainer = import_module(f"{pkg}.gui.message_bubble").MessageContainer
load_plugin_translator = import_module(f"{pkg}.i18n").load_plugin_translator

ChatDock = chat_dock_mod.ChatDock
JUMP_BUTTON_SIZE = chat_dock_mod.JUMP_BUTTON_SIZE
JUMP_BUTTON_MARGIN = chat_dock_mod.JUMP_BUTTON_MARGIN


def settle(ms=500):
    QTest.qWait(ms)


def wheel(widget, delta):
    """One vertical wheel action of |delta|, delivered straight to the widget."""
    center = QPoint(widget.width() // 2, widget.height() // 2)
    event = QWheelEvent(
        QPointF(center), QPointF(widget.mapToGlobal(center)), QPoint(0, 0), QPoint(0, delta),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def add_rows(dock, n):
    for i in range(n):
        dock._add_widget(MessageContainer("row %d " % i * 30, sender_name="You", is_user=True))


def wait_restored(dock):
    waited = 0
    while dock._restoring_transcript and waited < 25000:
        QTest.qWait(25)
        waited += 25
    settle(800)


class ChatJumpButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)
        # fs() caches whatever scale an earlier test or the user's settings left behind, so pin it.
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

    def _scrolled_up_dock(self):
        """A dock with eight rows whose reader wheeled up, so the button is visible."""
        dock = self.make_dock()
        add_rows(dock, 8)
        settle(600)
        wheel(dock.scroll.viewport(), 240)
        settle(100)
        return dock

    def test_hidden_while_the_last_message_is_in_view(self):
        dock = self.make_dock()
        button = dock._jump_button
        self.assertIsNotNone(button, "the dock builds a jump button")
        parent = button.parentWidget()
        self.assertIs(parent, dock.scroll.viewport(), "the button lies on the viewport")
        self.assertTrue(button.isHidden(), "the button starts hidden")
        add_rows(dock, 8)
        settle(600)
        vs = dock.scroll.verticalScrollBar()
        self.assertEqual(vs.value(), vs.maximum(), "following keeps the view at the bottom")
        self.assertTrue(button.isHidden(), "the button stays hidden while the last message is in view")

    def test_shown_when_the_reader_scrolls_up(self):
        dock = self._scrolled_up_dock()
        self.assertFalse(dock._pinned, "wheeling up unpins the reader")
        self.assertTrue(dock._jump_button.isVisible(),
                        "the button shows once the last message is out of view")

    def test_sits_in_the_bottom_right_corner_on_top_of_the_transcript(self):
        dock = self._scrolled_up_dock()
        button = dock._jump_button
        for width in (380, 300, 520):
            dock.resize(width, 650)
            settle(600)
            viewport = dock.scroll.viewport()
            self.assertEqual(
                button.geometry(),
                QRect(viewport.width() - JUMP_BUTTON_SIZE - JUMP_BUTTON_MARGIN,
                      viewport.height() - JUMP_BUTTON_SIZE - JUMP_BUTTON_MARGIN,
                      JUMP_BUTTON_SIZE, JUMP_BUTTON_SIZE),
                "the button sits in the bottom-right corner at dock width %d" % width)
            self.assertIs(
                QApplication.widgetAt(button.mapToGlobal(QPoint(16, 16))),
                button,
                "the button is on top of the transcript at dock width %d" % width)

    def test_click_returns_to_the_latest_message_and_resumes_following(self):
        dock = self.make_dock()
        add_rows(dock, 24)
        settle(600)
        button = dock._jump_button
        vs = dock.scroll.verticalScrollBar()
        wheel(dock.scroll.viewport(), 1200)
        settle(100)
        self.assertGreater(vs.maximum() - vs.value(), 400, "the reader is far above the last message")
        self.assertTrue(button.isVisible(), "the button shows while the reader is far above")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(16, 16))
        settle(100)
        self.assertEqual(vs.value(), vs.maximum(), "the click returned the view to the latest message")
        self.assertTrue(dock._pinned, "the click resumed following")
        self.assertTrue(button.isHidden(), "the button hides after the click")
        add_rows(dock, 3)
        settle(600)
        self.assertEqual(vs.value(), vs.maximum(), "following continues after the click")
        self.assertTrue(button.isHidden(), "the button stays hidden while following resumes")

    def test_stays_while_content_grows_below(self):
        dock = self._scrolled_up_dock()
        vs = dock.scroll.verticalScrollBar()
        before = vs.value()
        add_rows(dock, 3)
        settle(600)
        self.assertEqual(vs.value(), before, "content that grows below does not move the view")
        self.assertFalse(dock._pinned, "the reader stays unpinned while away from the bottom")
        self.assertTrue(dock._jump_button.isVisible(), "the button stays visible while content grows below")

    def test_hides_when_the_reader_reaches_the_bottom_by_scrolling(self):
        dock = self._scrolled_up_dock()
        button = dock._jump_button
        vs = dock.scroll.verticalScrollBar()
        for _ in range(20):
            if vs.value() >= vs.maximum():
                break
            wheel(dock.scroll.viewport(), -240)
            settle(50)
        settle(100)
        self.assertEqual(vs.value(), vs.maximum(), "wheeling down reached the bottom")
        self.assertTrue(button.isHidden(), "the button hides when the reader reaches the bottom by scrolling")
        self.assertTrue(dock._pinned, "reaching the bottom pins the view again")

        # The same descent with the wheel delivered to the button itself.
        wheel(dock.scroll.viewport(), 240)
        settle(100)
        self.assertTrue(button.isVisible(), "the button shows again after wheeling up")
        for _ in range(20):
            if vs.value() >= vs.maximum():
                break
            wheel(button, -240)
            settle(50)
        settle(100)
        self.assertEqual(vs.value(), vs.maximum(),
                         "wheeling down over the button scrolled the transcript to the bottom")
        self.assertTrue(button.isHidden(),
                        "the button hides when the reader reaches the bottom over the button")
        self.assertTrue(dock._pinned, "reaching the bottom over the button pins the view again")

    def test_wheel_over_the_button_scrolls_and_unpins(self):
        dock = self.make_dock()
        add_rows(dock, 8)
        settle(600)
        button = dock._jump_button
        vs = dock.scroll.verticalScrollBar()
        self.assertEqual(vs.value(), vs.maximum(), "the view starts at the bottom")
        wheel(button, 240)
        settle(100)
        self.assertLess(vs.value(), vs.maximum(), "wheeling up over the button scrolled the transcript")
        self.assertFalse(dock._pinned, "wheeling up over the button unpins the reader")
        self.assertTrue(button.isVisible(), "the button shows after wheeling up over it")

    def test_name_is_translated(self):
        dock = self.make_dock()
        # The CI image may run under another locale, so compare with the catalog in the current one.
        self.assertEqual(dock._jump_button.toolTip(),
                         QCoreApplication.translate("ChatDock", "Jump to latest message"),
                         "the name of the button is the catalogued string in the current locale")
        translator = load_plugin_translator("pt_BR")
        self.assertIsNotNone(translator, "the Brazilian catalog loads")
        self.assertTrue(QCoreApplication.installTranslator(translator), "the catalog installs")
        try:
            dock = self.make_dock()
            self.assertEqual(dock._jump_button.toolTip(), "Ir para a última mensagem",
                             "the name of the button in Brazilian Portuguese")
        finally:
            QCoreApplication.removeTranslator(translator)

    def test_survives_a_session_restore(self):
        events = [{"type": "user", "text": "question %d " % i * 30} for i in range(4)]
        events += [{"type": "agent_turn", "text": "answer %d " % i * 120} for i in range(4)]
        self.settings.setValue(SETTINGS_KEY, json.dumps({
            "schema_version": 1, "active_session_id": "s1",
            "sessions": [
                {"id": "s1", "name": "one", "transcript_events": events},
                {"id": "s2", "name": "two", "transcript_events": events},
            ],
        }))
        dock = self.make_dock()
        wait_restored(dock)
        button = dock._jump_button
        vs = dock.scroll.verticalScrollBar()
        self.assertEqual(vs.value(), vs.maximum(), "the first session is restored at the bottom")
        self.assertTrue(button.isHidden(), "the button is hidden after the restore")
        wheel(dock.scroll.viewport(), 240)
        settle(100)
        self.assertTrue(button.isVisible(), "the button shows after wheeling up")
        dock._switch_to_session("s2", save_current=False)
        wait_restored(dock)
        self.assertEqual(vs.value(), vs.maximum(), "the other session is restored at the bottom")
        self.assertTrue(button.isHidden(), "the button is hidden after the session switch")
        wheel(dock.scroll.viewport(), 240)
        settle(100)
        self.assertTrue(button.isVisible(), "the button shows again after wheeling up")
        self.assertIs(QApplication.widgetAt(button.mapToGlobal(QPoint(16, 16))), button,
                      "the button is still on top of the transcript after the restore")
