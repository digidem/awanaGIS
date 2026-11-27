"""The workspace state sent to the model must describe the project as it is now."""

from importlib import import_module
from pathlib import Path
import sys
import threading
import time
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, QSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
Config = import_module(f"{ROOT.name}.config").Config
openai_backend = import_module(f"{ROOT.name}.backends.openai_backend")
QgisToolkit = import_module(f"{ROOT.name}.core.toolkit").QgisToolkit
MainThreadExecutor = import_module(f"{ROOT.name}.core.executor").MainThreadExecutor


def point(feature, x, y):
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    return feature


def memory_layer(name, points):
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=nome:string(50)", name, "memory")
    for x, y in points:
        layer.dataProvider().addFeature(point(QgsFeature(layer.fields()), x, y))
    return layer


class AgentStateSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Config()
        self.config._s = QSettings(str(Path(temp.name) / "state.ini"), QSettings.Format.IniFormat)
        self.project = QgsProject.instance()
        self.project.clear()
        self.addCleanup(self.project.clear)
        self.toolkit = QgisToolkit(iface=None, config=self.config)

    def state(self):
        """The registry as a backend thread reads it, without a refresh."""
        return self.toolkit._agent_state.to_system_prompt_section()

    def test_a_removed_layer_leaves_the_state_sent_to_the_model(self):
        layer = memory_layer("Acampamentos", [(-60.5, -2.5)])
        self.project.addMapLayer(layer)
        layer_id = layer.id()
        self.assertIn("Acampamentos", self.toolkit.agent_state_summary())

        result = self.toolkit.remove_layer(layer_id=layer_id)

        self.assertTrue(result["ok"], result)
        self.assertNotIn(layer_id, self.toolkit._agent_state.layers)
        self.assertNotIn("Acampamentos", self.toolkit.agent_state_summary())

    def test_layers_changed_outside_the_tools_update_the_state(self):
        self.project.addMapLayer(memory_layer("Aldeias", [(-60.4, -2.4)]))
        gone = memory_layer("Rios", [(-60.3, -2.3)])
        self.project.addMapLayer(gone)
        QCoreApplication.processEvents()
        self.assertIn("Aldeias", self.state())
        self.assertIn("Rios", self.state())

        self.project.removeMapLayer(gone.id())
        QCoreApplication.processEvents()

        self.assertIn("Aldeias", self.state())
        self.assertNotIn("Rios", self.state())

    def test_an_edited_layer_shows_its_current_count(self):
        layer = memory_layer("Observações", [(-60.2, -2.2)])
        self.project.addMapLayer(layer)
        self.assertIn("features=1", self.toolkit.agent_state_summary())

        layer.dataProvider().addFeature(point(QgsFeature(layer.fields()), -60.1, -2.1))

        self.assertIn("features=2", self.toolkit.agent_state_summary())

    def test_the_state_a_backend_sends_is_read_again_on_the_main_thread(self):
        layer = memory_layer("Aldeias", [(-60.4, -2.4)])
        self.project.addMapLayer(layer)
        # Leave the registry as it was, so only the read before a request can update it.
        self.toolkit._agent_layers_timer.stop()
        layer.dataProvider().addFeature(point(QgsFeature(layer.fields()), -60.3, -2.3))
        backend = openai_backend.OpenAIBackend(SimpleNamespace(get=lambda name, default=None: default),
                                               self.toolkit, MainThreadExecutor(config=self.config))
        sent, done = [], threading.Event()

        def backend_thread():
            sent.append(backend._state_text())
            done.set()

        threading.Thread(target=backend_thread, daemon=True).start()
        deadline = time.monotonic() + 30
        while not done.wait(0.01) and time.monotonic() < deadline:
            QCoreApplication.processEvents()

        self.assertTrue(done.is_set(), "the backend thread could not read the state")
        self.assertIn("Aldeias (id=", sent[0])
        self.assertIn("features=2", sent[0])

        self.project.removeMapLayer(layer.id())
        started = time.monotonic()
        self.assertNotIn("Aldeias (id=", backend._state_text())
        self.assertLess(time.monotonic() - started, 1.0, "a call from the main thread does not wait")

    def test_reading_the_state_does_not_break_while_layers_change(self):
        errors = []

        def reader():
            try:
                for _ in range(300):
                    if "## Workspace State" not in self.toolkit.agent_state_summary():
                        raise AssertionError("incomplete state")
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        worker = threading.Thread(target=reader)
        worker.start()
        try:
            for index in range(300):
                layer = memory_layer(f"Camada {index % 3}", [(-60.0 - index / 1000, -2.0)])
                self.project.addMapLayer(layer)
                self.toolkit.refresh_agent_layers()
                self.project.removeMapLayer(layer.id())
                self.toolkit.refresh_agent_layers()
        finally:
            worker.join(30)
        self.assertEqual(errors, [])
        self.assertFalse(worker.is_alive())

    def test_cleanup_agent_layers_stops_timer_and_disconnects_signals_idempotently(self):
        self.toolkit._agent_layers_timer.start(1000)
        self.assertTrue(self.toolkit._agent_layers_timer.isActive())

        self.toolkit.cleanup_agent_layers()
        self.toolkit.cleanup_agent_layers()

        self.assertFalse(self.toolkit._agent_layers_timer.isActive())
        layer = memory_layer("AfterUnload", [(-60.1, -2.1)])
        self.project.addMapLayer(layer)
        QCoreApplication.processEvents()
        self.assertNotIn(layer.id(), self.toolkit._agent_state.layers)


if __name__ == "__main__":
    unittest.main()
