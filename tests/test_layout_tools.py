"""Offline checks for the print layout tools: no model, no network, no display."""

from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtGui import QColor, QImage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
Config = import_module(f"{ROOT.name}.config").Config
QgisToolkit = import_module(f"{ROOT.name}.core.toolkit").QgisToolkit

MARKER = QColor(255, 0, 0)
FILL = QColor(0, 0, 255)
VIEW = QgsRectangle(-61.0, -3.0, -59.0, -1.0)
EVERYTHING = ["map", "title", "legend", "scale bar", "north arrow"]


class Iface:
    """The canvas calls the layout tools make."""

    def __init__(self, project):
        self.canvas = QgsMapCanvas()
        self.canvas.resize(1024, 768)
        self.canvas.setDestinationCrs(project.crs())
        QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), self.canvas).setCanvasLayers()
        self.canvas.setExtent(VIEW)

    def mapCanvas(self):
        return self.canvas

    def activeLayer(self):
        return self.canvas.layers()[0] if self.canvas.layers() else None


def symbol_layer(geometry, name, symbol):
    layer = QgsVectorLayer(f"{geometry}?crs=EPSG:4326&field=nome:string(50)", name, "memory")
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    return layer


def page_items(layout, kind):
    return [item for item in layout.items() if isinstance(item, kind)]


class LayoutToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from qgis.core import QgsApplication

        cls.app = QgsApplication.instance() or QgsApplication([], True)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        settings = QSettings(str(self.temp / "layout.ini"), QSettings.Format.IniFormat)
        self.config = Config()
        self.config._s = settings
        self.project = QgsProject.instance()
        self.project.clear()
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        # Added bottom first, so the villages draw above the territory.
        self.territory = symbol_layer("Polygon", "Territórios", QgsFillSymbol.createSimple({"color": FILL.name()}))
        territory = QgsFeature(self.territory.fields())
        territory.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(-60.8, -2.8), QgsPointXY(-60.2, -2.8),
            QgsPointXY(-60.2, -2.2), QgsPointXY(-60.8, -2.2), QgsPointXY(-60.8, -2.8),
        ]]))
        self.territory.dataProvider().addFeature(territory)
        self.villages = symbol_layer("Point", "Aldeias", QgsMarkerSymbol.createSimple(
            {"color": MARKER.name(), "size": "6"}))
        for x, y in ((-60.6, -2.6), (-60.4, -2.4)):
            village = QgsFeature(self.villages.fields())
            village.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            self.villages.dataProvider().addFeature(village)
        for layer in (self.territory, self.villages):
            self.assertTrue(layer.isValid(), layer.name())
            self.assertTrue(self.project.addMapLayer(layer))
        self.toolkit = QgisToolkit(iface=Iface(self.project), config=self.config)

    def test_layout_gets_a_map_with_the_visible_layers_and_the_canvas_view(self):
        result = self.toolkit.create_layout("Mapa", page_size="A4", orientation="landscape")
        self.assertTrue(result["ok"], result)
        layout = self.project.layoutManager().layoutByName("Mapa")
        maps = page_items(layout, QgsLayoutItemMap)
        self.assertEqual(len(maps), 1, "the exported page has a map")
        visible = self.toolkit.iface.mapCanvas().layers()
        self.assertEqual([layer.id() for layer in maps[0].layersToRender()], [layer.id() for layer in visible])
        shown = maps[0].extent()
        self.assertTrue(shown.contains(VIEW), shown.toString())
        self.assertEqual(maps[0].crs().authid(), "EPSG:4326")
        self.assertEqual(result["items"], EVERYTHING)
        self.assertEqual(result["layers"], [layer.name() for layer in visible])
        self.assertEqual(result["crs"], "EPSG:4326")

    def test_page_has_a_title_a_legend_a_scale_bar_and_a_north_arrow(self):
        self.toolkit.create_layout("Mapa da reunião", orientation="landscape")
        layout = self.project.layoutManager().layoutByName("Mapa da reunião")
        labels = page_items(layout, QgsLayoutItemLabel)
        self.assertEqual([label.text() for label in labels], ["Mapa da reunião"])
        self.assertGreaterEqual(labels[0].rect().height(), 10.0, "the title has room for its text")
        legends = page_items(layout, QgsLayoutItemLegend)
        self.assertEqual(len(legends), 1)
        names = [node.layer().name() for node in legends[0].model().rootGroup().findLayers()
                 if node.layer() is not None]
        self.assertEqual(sorted(names), ["Aldeias", "Territórios"])
        bars = page_items(layout, QgsLayoutItemScaleBar)
        self.assertEqual(len(bars), 1)
        self.assertIsNotNone(bars[0].linkedMap(), "the scale bar follows the map")
        self.assertEqual(len(page_items(layout, QgsLayoutItemPicture)), 1)
        page = layout.pageCollection().page(0).pageSize()
        items = labels + legends + bars + page_items(layout, QgsLayoutItemMap)
        for item in items:
            kind = type(item).__name__
            self.assertLess(item.pos().x() + item.rect().width(), page.width(), kind)
            self.assertLess(item.pos().y() + item.rect().height(), page.height(), kind)
        map_item = page_items(layout, QgsLayoutItemMap)[0]
        self.assertLess(map_item.pos().y() + map_item.rect().height(), legends[0].pos().y(),
                        "the legend stays below the map")
        self.assertLessEqual(labels[0].pos().y() + labels[0].rect().height(), map_item.pos().y(),
                             "the title stays above the map")

    def test_exported_page_shows_the_map_content(self):
        self.assertTrue(self.toolkit.create_layout("Mapa", orientation="portrait")["ok"])
        outputs = self.temp / "outputs"
        outputs.mkdir()
        result = self.toolkit.export_layout("Mapa", str(outputs / "mapa.pdf"))
        self.assertTrue(result["ok"], result)
        self.assertEqual((outputs / "mapa.pdf").read_bytes()[:5], b"%PDF-")
        result = self.toolkit.export_layout("Mapa", str(outputs / "mapa.png"), format="png")
        self.assertTrue(result["ok"], result)
        image = QImage(str(outputs / "mapa.png"))
        self.assertFalse(image.isNull())
        small = image.scaledToWidth(300)
        reds = blues = title_ink = 0
        for y in range(small.height()):
            for x in range(small.width()):
                color = QColor(small.pixel(x, y))
                reds += color.red() > 200 and color.green() < 80 and color.blue() < 80
                blues += color.blue() > 200 and color.red() < 80 and color.green() < 80
                # The top 20 mm of an A4 portrait page hold the title.
                title_ink += y < 20 * small.width() / 210 and color.lightness() < 96
        self.assertGreater(reds, 0, "the red villages are on the page")
        self.assertGreater(blues, 40, "the blue territory is on the page")
        self.assertGreater(title_ink, 5, "the title is printed")

    def test_requested_layers_and_the_project_view_without_a_canvas(self):
        result = self.toolkit.create_layout("Só aldeias", layers=["Aldeias"], orientation="landscape")
        self.assertTrue(result["ok"], result)
        layout = self.project.layoutManager().layoutByName("Só aldeias")
        self.assertEqual([layer.name() for layer in page_items(layout, QgsLayoutItemMap)[0].layersToRender()],
                         ["Aldeias"])
        legend = page_items(layout, QgsLayoutItemLegend)[0]
        self.assertEqual([node.layer().name() for node in legend.model().rootGroup().findLayers()],
                         ["Aldeias"], "the legend lists what the map shows")

        self.project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(VIEW, self.project.crs()))
        result = QgisToolkit(iface=None, config=self.config).create_layout("Sem tela")
        self.assertTrue(result["ok"], result)
        layout = self.project.layoutManager().layoutByName("Sem tela")
        maps = page_items(layout, QgsLayoutItemMap)
        self.assertTrue(maps[0].extent().contains(VIEW), maps[0].extent().toString())
        self.assertEqual(result["items"], EVERYTHING)

    def test_without_a_canvas_or_a_saved_view_the_project_crs_and_layer_extents_are_used(self):
        self.project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle())
        projected = QgsVectorLayer("Point?crs=EPSG:3857", "Longe", "memory")
        far = QgsFeature(projected.fields())
        far.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-6720000.0, -290000.0)))
        projected.dataProvider().addFeature(far)
        self.assertTrue(self.project.addMapLayer(projected))
        result = QgisToolkit(iface=None, config=self.config).create_layout("Sem vista salva")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["crs"], "EPSG:4326", "an unsaved view falls back to the project CRS")
        extent = QgsRectangle(*result["extent"])
        self.assertTrue(extent.contains(QgsPointXY(-60.4, -2.4)), extent.toString())
        self.assertLess(extent.width(), 5.0, "layer extents are reprojected before they are combined")
        self.assertLess(extent.height(), 5.0, extent.toString())

    def test_hidden_layers_are_not_printed_behind_an_empty_layer_list(self):
        for node in self.project.layerTreeRoot().findLayers():
            node.setItemVisibilityChecked(False)
        QgsLayerTreeMapCanvasBridge(self.project.layerTreeRoot(), self.toolkit.iface.mapCanvas()).setCanvasLayers()
        self.assertEqual(self.toolkit.iface.mapCanvas().layers(), [])
        result = self.toolkit.create_layout("Tudo oculto")
        self.assertFalse(result["ok"])
        self.assertIn("No visible layers", result["error"])
        self.assertEqual(len(self.project.layoutManager().layouts()), 0)

    def test_a_legend_too_tall_for_the_page_is_left_out_and_said_so(self):
        from unittest.mock import patch

        with patch.object(QgisToolkit, "_layout_legend", return_value=(object(), 300.0)):
            result = self.toolkit.create_layout("Legenda imensa")
        self.assertTrue(result["ok"], result)
        self.assertNotIn("legend", result["items"])
        self.assertTrue(any("legend" in note for note in result["notes"]), result["notes"])
        layout = self.project.layoutManager().layoutByName("Legenda imensa")
        self.assertEqual(page_items(layout, QgsLayoutItemLegend), [])

    def test_tables_are_project_data_and_stay_out_of_the_legend(self):
        table = QgsVectorLayer("None?field=codigo:string(10)", "Dados", "memory")
        self.assertTrue(table.isValid())
        self.assertTrue(self.project.addMapLayer(table))
        result = self.toolkit.create_layout("Com tabela")
        self.assertTrue(result["ok"], result)
        layout = self.project.layoutManager().layoutByName("Com tabela")
        legend = page_items(layout, QgsLayoutItemLegend)[0]
        names = sorted(node.layer().name() for node in legend.model().rootGroup().findLayers()
                       if node.layer() is not None)
        self.assertEqual(names, ["Aldeias", "Territórios"])
        self.assertNotIn(table.id(), [layer.id() for layer in page_items(layout, QgsLayoutItemMap)[0].layers()])

    def test_a_repeated_name_is_refused_and_leaves_one_layout(self):
        self.assertTrue(self.toolkit.create_layout("Mapa")["ok"])
        second = self.toolkit.create_layout("Mapa")
        self.assertFalse(second["ok"])
        self.assertIn("already exists", second["error"])
        self.assertEqual(len(self.project.layoutManager().layouts()), 1)


if __name__ == "__main__":
    unittest.main()
