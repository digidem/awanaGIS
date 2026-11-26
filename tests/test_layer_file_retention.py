"""Removing an analysis layer must not delete a file the user keeps."""

from importlib import import_module
import json
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
Config = import_module(f"{ROOT.name}.config").Config
toolkit_module = import_module(f"{ROOT.name}.core.toolkit")
QgisToolkit = toolkit_module.QgisToolkit

GEOJSON = {
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "properties": {"nome": "sintético"},
                  "geometry": {"type": "Point", "coordinates": [-60.5, -2.5]}}],
}


class LayerFileRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def setUp(self):
        # Both folders are created before the temporary folder is replaced.
        self.kept = TemporaryDirectory()
        self.addCleanup(self.kept.cleanup)
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        patcher = patch.object(toolkit_module.tempfile, "gettempdir", return_value=self.scratch.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Config()
        self.config._s = QSettings(str(Path(temp.name) / "state.ini"), QSettings.Format.IniFormat)
        self.project = QgsProject.instance()
        self.project.clear()
        self.addCleanup(self.project.clear)
        self.toolkit = QgisToolkit(iface=None, config=self.config)

    def write(self, folder, name):
        path = Path(folder) / name
        path.write_text(json.dumps(GEOJSON), encoding="utf-8")
        return path

    def test_a_kept_file_survives_remove_layer_and_a_new_session(self):
        first = self.write(self.kept.name, "acampamentos.geojson")
        second = self.write(self.kept.name, "outra_camada.geojson")
        added = self.toolkit.add_layer(uri=str(first), is_analysis=True)
        self.assertTrue(added["ok"], added)
        self.toolkit.add_layer(uri=str(second), is_analysis=True)

        removed = self.toolkit.remove_layer(layer_id=added["layer_id"])

        self.assertTrue(removed["ok"], removed)
        self.assertTrue(first.is_file(), "the file the user asked to keep was deleted with its layer")
        self.toolkit.reset_agent_state()
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file(), "a new chat session deleted a kept file")
        self.assertEqual(self.toolkit._temp_layer_files, {})

    def test_a_temporary_file_is_still_deleted_with_its_layer(self):
        scratch = self.write(self.scratch.name, "awanagis_result.geojson")
        added = self.toolkit.add_layer(uri=str(scratch), is_analysis=True)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])

        self.assertFalse(scratch.exists())

    def test_a_link_outside_the_temporary_folder_is_not_deleted(self):
        target = self.write(self.scratch.name, "awanagis_target.geojson")
        link = Path(self.kept.name) / "atalho.geojson"
        link.symlink_to(target)
        added = self.toolkit.add_layer(uri=str(link), is_analysis=True)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])

        self.assertTrue(link.is_symlink(), "the user's link was deleted")
        self.assertTrue(target.is_file())

    def test_an_analysis_layer_marked_in_a_saved_project_keeps_its_file(self):
        kept = self.write(self.kept.name, "acampamentos.geojson")
        layer = QgsVectorLayer(str(kept), "acampamentos", "ogr")
        layer.setCustomProperty("awanagis/analysis", True)
        self.project.addMapLayer(layer)

        self.assertTrue(self.toolkit.remove_layer(layer_id=layer.id())["ok"])

        self.assertTrue(kept.is_file(), "the marker stored in the project made the plugin delete a kept file")


if __name__ == "__main__":
    unittest.main()
