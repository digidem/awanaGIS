"""``ask_user`` answers a malformed call with its validation message, not a traceback."""

from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import QSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
Config = import_module(f"{ROOT.name}.config").Config
QgisToolkit = import_module(f"{ROOT.name}.core.toolkit").QgisToolkit


class AskUserArgumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def toolkit(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = Config()
        config._s = QSettings(str(Path(temp.name) / "state.ini"), QSettings.Format.IniFormat)
        project = QgsProject.instance()
        project.clear()
        self.addCleanup(project.clear)
        return QgisToolkit(iface=None, config=config)

    def test_a_missing_question_is_reported_without_raising(self):
        toolkit = self.toolkit()

        for arguments in ({}, {"options": [{"label": "Um", "description": "1"},
                                           {"label": "Dois", "description": "2"}]}):
            with self.subTest(arguments=arguments):
                answer = toolkit.ask_user(**arguments)

                self.assertTrue(str(answer).startswith("ask_user: "), answer)

    def test_options_sent_as_one_json_string_are_accepted(self):
        toolkit = self.toolkit()
        asked = []

        def emitter(question, options, allow_free_text, request):
            asked.append((question, [option["label"] for option in options]))
            toolkit._resolve_ask_user({"choice": "As duas"}, request=request)

        toolkit.set_ask_user_emitter(emitter)
        options = '[{"label": "Só uma", "description": "1"}, {"label": "As duas", "description": "2"}]'

        answer = toolkit.ask_user("Quais áreas?", options)

        self.assertEqual(asked, [("Quais áreas?", ["Só uma", "As duas"])])
        self.assertEqual(answer, {"choice": "As duas", "free_text": None, "cancelled": False})

    def test_an_unreadable_options_string_is_reported_without_raising(self):
        toolkit = self.toolkit()

        for options in ("não é JSON", "[" * 3000 + "]" * 3000):
            with self.subTest(options=options[:12]):
                answer = toolkit.ask_user("Quais áreas?", options)

                self.assertTrue(str(answer).startswith("ask_user: "), answer)


if __name__ == "__main__":
    unittest.main()
