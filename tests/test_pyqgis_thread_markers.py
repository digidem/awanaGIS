"""Which ``run_pyqgis`` code must stay on the QGIS main thread."""

from importlib import import_module
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
tools = import_module(f"{ROOT.name}.core.tools")


class PyqgisThreadMarkerTests(unittest.TestCase):
    def test_code_that_walks_the_project_layers_stays_on_the_main_thread(self):
        for code in (
            "for layer in QgsProject.instance().mapLayers().values():\n    print(layer.name())",
            "names = [layer.name() for layer in QgsProject.instance().mapLayersByName('Aldeias')]",
            "project.addMapLayer(layer)",
            "layer = QgsProject.instance().mapLayer(layer_id)",
        ):
            with self.subTest(code=code.splitlines()[0][:60]):
                self.assertFalse(tools._should_auto_background_pyqgis(code))

    def test_code_without_project_access_still_runs_in_the_background(self):
        for code in ("values = sorted(set(range(10)))\nresult = sum(values)",
                     "import math\nresult = math.hypot(3, 4)"):
            with self.subTest(code=code.splitlines()[-1]):
                self.assertTrue(tools._should_auto_background_pyqgis(code))


if __name__ == "__main__":
    unittest.main()
