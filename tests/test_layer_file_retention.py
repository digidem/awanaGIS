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

    def test_an_existing_user_file_inside_temp_is_not_deleted(self):
        user_file = self.write(self.scratch.name, "user_temp_data.geojson")
        added = self.toolkit.add_layer(uri=str(user_file), is_analysis=True)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])
        self.assertTrue(user_file.is_file(), "pre-existing user file inside temp was deleted")

        added2 = self.toolkit.add_layer(uri=str(user_file), is_analysis=True)
        self.assertTrue(added2["ok"], added2)
        self.toolkit.reset_agent_state()
        self.assertTrue(user_file.is_file(), "reset_agent_state deleted pre-existing user file inside temp")

    def test_an_owned_temporary_file_is_deleted_with_its_layer(self):
        scratch = self.write(self.scratch.name, "awanagis_result.geojson")
        self.assertTrue(self.toolkit._register_owned_temp_file(str(scratch)))
        added = self.toolkit.add_layer(uri=str(scratch), is_analysis=True)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])

        self.assertFalse(scratch.exists())

    def test_an_owned_temp_file_replaced_on_disk_is_not_deleted(self):
        scratch = self.write(self.scratch.name, "owned_then_replaced.geojson")
        self.assertTrue(self.toolkit._register_owned_temp_file(str(scratch)))
        added = self.toolkit.add_layer(uri=str(scratch), is_analysis=True)
        self.assertTrue(added["ok"], added)

        replacement = self.write(self.scratch.name, "replacement_inode.geojson")
        replacement.replace(scratch)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])
        self.assertTrue(scratch.is_file(), "replaced file with different inode was deleted")

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

    def test_a_saved_project_analysis_layer_inside_temp_is_not_deleted(self):
        outside = self.write(self.scratch.name, "saved_project_layer.geojson")
        layer = QgsVectorLayer(str(outside), "saved_temp", "ogr")
        layer.setCustomProperty("awanagis/analysis", True)
        self.project.addMapLayer(layer)

        self.assertTrue(self.toolkit.remove_layer(layer_id=layer.id())["ok"])
        self.assertTrue(outside.is_file())

        second = self.write(self.scratch.name, "saved_project_clear.geojson")
        layer2 = QgsVectorLayer(str(second), "saved_clear", "ogr")
        layer2.setCustomProperty("awanagis/analysis", True)
        self.project.addMapLayer(layer2)
        self.assertTrue(self.toolkit.clear_layers(confirm=True)["ok"])
        self.assertTrue(second.is_file())

    def test_a_symlinked_parent_inside_temp_does_not_delete_user_files(self):
        kept_sub = Path(self.kept.name) / "subdir"
        kept_sub.mkdir()
        kept_file = self.write(kept_sub, "user_data.geojson")
        temp_link_dir = Path(self.scratch.name) / "link_dir"
        temp_link_dir.symlink_to(kept_sub, target_is_directory=True)
        via_link = temp_link_dir / "user_data.geojson"

        added = self.toolkit.add_layer(uri=str(via_link), is_analysis=True)
        self.assertTrue(added["ok"], added)
        self.assertEqual(self.toolkit._temp_layer_files, {})

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])
        self.assertTrue(kept_file.is_file(), "symlinked parent inside temp allowed user file deletion")

        added2 = self.toolkit.add_layer(uri=str(via_link), is_analysis=True)
        self.assertTrue(added2["ok"], added2)
        self.toolkit.reset_agent_state()
        self.assertTrue(kept_file.is_file(), "reset_agent_state deleted file via symlinked parent")

    def test_non_analysis_temp_file_is_not_deleted(self):
        temp_file = self.write(self.scratch.name, "non_analysis.geojson")
        added = self.toolkit.add_layer(uri=str(temp_file), is_analysis=False)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.remove_layer(layer_id=added["layer_id"])["ok"])
        self.assertTrue(temp_file.is_file())

    def test_clear_layers_deletes_tracked_temp_file(self):
        scratch = self.write(self.scratch.name, "clear_temp.geojson")
        self.assertTrue(self.toolkit._register_owned_temp_file(str(scratch)))
        added = self.toolkit.add_layer(uri=str(scratch), is_analysis=True)
        self.assertTrue(added["ok"], added)

        self.assertTrue(self.toolkit.clear_layers(confirm=True)["ok"])
        self.assertFalse(scratch.exists())


if __name__ == "__main__":
    unittest.main()
