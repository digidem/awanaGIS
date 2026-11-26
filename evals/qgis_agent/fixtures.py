"""Create small, synthetic QGIS projects for repeatable agent evaluations."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .cases import CASES


@dataclass(frozen=True)
class Fixture:
    case_id: str
    project_path: Path
    turns: tuple[str, ...]
    output_dir: Path
    territory_names: tuple[str, ...]
    layer_names: tuple[str, ...]
    raster_path: Path
    region_extent: tuple[float, float, float, float]
    territory_bounds: tuple[float, float, float, float]
    village_join_values: tuple[tuple[str, int], ...]
    villages_path: Path
    input_files: tuple[Path, ...]
    source_hashes: tuple[tuple[str, str], ...]
    project_crs: str
    expected_view_bounds: tuple[float, float, float, float]
    initial_view_bounds: tuple[float, float, float, float]
    expected_visible_layer_ids: tuple[str, ...]
    expected_selected_codes: tuple[str, ...]
    expected_category_values: tuple[str, ...]
    expected_unique_codes: tuple[str, ...]
    expected_village_names: tuple[str, ...]
    expected_village_records: tuple[tuple[str, str, str, float, float], ...]
    preselected_codes: tuple[str, ...]
    pdf_requires_local_basemap: bool
    # The derived file a session case asks the agent to keep on disk, and
    # what it must hold once created and after the user's later instructions:
    # (x, y, type) for every point, sorted.
    derived_file: str = ""
    expected_derived: tuple[tuple[float, float, str], ...] = ()
    expected_final: tuple[tuple[float, float, str], ...] = ()
    area_names: tuple[str, ...] = ()


def _feature_collection(features):
    return {"type": "FeatureCollection", "features": features}


def _write_geojson(path: Path, geometry_name: str, features):
    path.write_text(
        json.dumps(_feature_collection(features), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _inside(bounds, x, y):
    xmin, ymin, xmax, ymax = bounds
    return xmin <= x <= xmax and ymin <= y <= ymax


def _camps_plan(variant):
    """Three synthetic layers for the camps case, and the rules the user gives.

    Records are (first attribute, notes, x, y). Every camp lies clearly
    inside or outside the named areas; the second area's name extends the
    first, so an agent that matches names loosely also removes its camps.
    """
    if variant == "heldout":
        return {
            "layer_names": ("Registros de campo (teste)", "Observações (teste)", "Áreas (teste)"),
            "areas": (
                ("TI Uraricoera", (-60.74, -2.74, -60.50, -2.54)),
                ("TI Uraricoera Sul", (-60.46, -2.42, -60.26, -2.22)),
            ),
            "field_records": (
                ("acampamento", "Acampamento da trilha", -60.72, -2.68),
                ("acampamento", "Primeira noite", -60.56, -2.33),
                ("maloca", "Maloca antiga", -60.64, -2.58),
                ("acampamento", "Acampamento do lago", -60.47, -2.47),
                ("cachoeira", "Cachoeira pequena", -60.77, -2.39),
            ),
            "observation_records": (
                ("Acampamento de vigilância", "Ronda", -60.68, -2.66),
                ("Acampamento", "Vigilante da estrada", -60.62, -2.60),
                ("Acampamento", "Acampamento 07", -60.48, -2.61),
                ("Acampamento", "Acampamento 02", -60.42, -2.34),
                ("Pesca", "Lugar de pesca", -60.79, -2.49),
                ("Acampamento", "Sem informação", -60.57, -2.27),
            ),
            "is_vigilance": lambda category, notes: "vigil" in f"{category} {notes}".casefold(),
            "relabelled": "observations",
            "file": "base_campo.geojson",
        }
    return {
        "layer_names": ("Pontos de campo", "Observações", "Áreas"),
        "areas": (
            ("TI Rio Claro", (-60.72, -2.72, -60.52, -2.56)),
            ("TI Rio Claro Norte", (-60.44, -2.40, -60.28, -2.24)),
        ),
        "field_records": (
            ("acampamento", "Acampamento da picada", -60.70, -2.70),
            ("acampamento", "Base da equipe", -60.55, -2.35),
            ("roça", "Roça nova", -60.62, -2.60),
            ("acampamento", "Acampamento do igarapé", -60.47, -2.46),
            ("cachoeira", "Cachoeira grande", -60.75, -2.40),
            ("acampamento", "Segunda noite", -60.32, -2.30),
        ),
        "observation_records": (
            ("Acampamento de vigilância", "Ronda do limite", -60.66, -2.66),
            ("Pesca", "Pesca do dia", -60.78, -2.50),
            ("Acampamento", "Acampamento 03", -60.50, -2.62),
            ("Acampamento de vigilância", "Vigilante na boca", -60.40, -2.32),
            ("Acampamento", "Sem nota", -60.58, -2.28),
            ("Caça", "Caça", -60.36, -2.52),
        ),
        "is_vigilance": lambda category, notes: "vigil" in category.casefold(),
        "relabelled": "field",
        "file": "acampamentos.geojson",
    }


def _camps_expectations(plan, shift):
    """What the derived file must hold after the merge and after the later instructions."""
    target = tuple(value + shift for value in plan["areas"][0][1])
    decoy = tuple(value + shift for value in plan["areas"][1][1])

    def place(record):
        return record[2] + shift, record[3] + shift

    field_camps = [record for record in plan["field_records"] if record[0] == "acampamento"]
    observation_camps = [record for record in plan["observation_records"] if "acampamento" in record[0].casefold()]
    if not (any(_inside(target, *place(record)) for record in field_camps + observation_camps)
            and any(_inside(decoy, *place(record)) for record in field_camps + observation_camps)):
        raise RuntimeError("Camps fixture must place camps inside the named area and inside the similar one")

    derived = []
    final = []
    for source, camps in (("field", field_camps), ("observations", observation_camps)):
        for record in camps:
            x, y = place(record)
            vigilance = source == "observations" and plan["is_vigilance"](record[0], record[1])
            derived.append((x, y, "vigilância" if vigilance else "não informado"))
            if _inside(target, x, y):
                continue
            if source == plan["relabelled"]:
                final.append((x, y, "demarcação"))
            else:
                final.append((x, y, "vigilância" if vigilance else "não informado"))
    return tuple(sorted(derived)), tuple(sorted(final))


def _build_camps_fixture(root: Path, variant: str) -> Fixture:
    """Build the camps case: two point layers of mixed records and a layer of named areas."""
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsProject,
        QgsReferencedRectangle,
        QgsRectangle,
        QgsVectorLayer,
    )

    plan = _camps_plan(variant)
    shift = 0.04 if variant == "heldout" else 0.0
    input_dir = root / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir = root / "outputs"
    output_dir.mkdir(exist_ok=True)

    def point_files(records, first, path):
        _write_geojson(path, "Point", [
            {"type": "Feature",
             "properties": {first: record[0], "notas": record[1]},
             "geometry": {"type": "Point", "coordinates": [record[2] + shift, record[3] + shift]}}
            for record in records
        ])

    pontos_path = input_dir / "pontos_campo.geojson"
    point_files(plan["field_records"], "tipo", pontos_path)
    observacoes_path = input_dir / "observacoes.geojson"
    point_files(plan["observation_records"], "categoria", observacoes_path)
    areas_path = input_dir / "areas.geojson"
    areas = []
    for name, bounds in plan["areas"]:
        xmin, ymin, xmax, ymax = (value + shift for value in bounds)
        areas.append((name, (xmin, ymin, xmax, ymax)))
    _write_geojson(areas_path, "Polygon", [
        {"type": "Feature",
         "properties": {"nome": name},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]]}}
        for name, (xmin, ymin, xmax, ymax) in areas
    ])
    paths = (pontos_path, observacoes_path, areas_path)

    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    layers = []
    for path, name in zip(paths, plan["layer_names"]):
        layer = QgsVectorLayer(str(path), name, "ogr")
        if not layer.isValid():
            raise RuntimeError(f"Could not load synthetic fixture layer {name}: {path}")
        project.addMapLayer(layer)
        layers.append(layer)
    union = QgsRectangle(layers[0].extent())
    for layer in layers[1:]:
        union.combineExtentWith(layer.extent())
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(union, project.crs()))
    project_path = root / "fixture.qgz"
    if not project.write(str(project_path)):
        raise RuntimeError(f"Could not write fixture project: {project_path}")
    derived, final = _camps_expectations(plan, shift)
    case = CASES["camps_merge"]
    return Fixture(
        case_id="camps_merge",
        project_path=project_path,
        turns=case.heldout_turns if variant == "heldout" else case.turns,
        output_dir=output_dir,
        territory_names=tuple(name for name, _ in areas),
        layer_names=plan["layer_names"],
        raster_path=root / "unused.tif",
        region_extent=(0.0, 0.0, 0.0, 0.0),
        territory_bounds=areas[0][1],
        village_join_values=(),
        villages_path=pontos_path,
        input_files=paths,
        source_hashes=tuple(
            (path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths
        ),
        project_crs="EPSG:4326",
        expected_view_bounds=(union.xMinimum(), union.yMinimum(), union.xMaximum(), union.yMaximum()),
        initial_view_bounds=(union.xMinimum(), union.yMinimum(), union.xMaximum(), union.yMaximum()),
        expected_visible_layer_ids=(),
        expected_selected_codes=(),
        expected_category_values=(),
        expected_unique_codes=(),
        expected_village_names=(),
        expected_village_records=(),
        preselected_codes=(),
        pdf_requires_local_basemap=False,
        derived_file=plan["file"],
        expected_derived=derived,
        expected_final=final,
        area_names=tuple(name for name, _ in areas),
    )


def _create_raster(path: Path):
    from osgeo import gdal, osr
    import numpy

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(path), 32, 32, 3, gdal.GDT_Byte)
    dataset.SetGeoTransform((-61.0, 0.04, 0.0, -2.0, 0.0, -0.06))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(4326)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    # A deterministic, locally generated green/blue raster; no network access.
    for index, color in enumerate((68, 126, 84), start=1):
        band = dataset.GetRasterBand(index)
        values = numpy.full((32, 32), color, dtype=numpy.uint8)
        values[8:24, 8:24] = min(color + 35, 255)
        band.WriteArray(values)
    dataset.FlushCache()
    dataset = None


def build_fixture(case_id: str, run_dir: Path, variant: str = "baseline") -> Fixture:
    """Build a clean synthetic project and return paths/prompts for one case.

    Requires QGIS's Python runtime. ``variant='heldout'`` shifts the geometry and
    changes labels while retaining the same expected behavior.
    """
    if case_id not in CASES:
        raise ValueError(f"Unknown evaluation case: {case_id}")
    if variant not in ("baseline", "heldout"):
        raise ValueError(f"Unknown fixture variant: {variant}")

    root = Path(run_dir)
    if case_id == "camps_merge":
        return _build_camps_fixture(root, variant)

    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsMarkerSymbol,
        QgsProject,
        QgsRasterLayer,
        QgsReferencedRectangle,
        QgsSingleSymbolRenderer,
        QgsVectorLayer,
    )

    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    input_dir = root / "inputs"
    input_dir.mkdir(exist_ok=True)
    output_dir = root / "outputs"
    output_dir.mkdir(exist_ok=True)
    shift = 0.04 if variant == "heldout" else 0.0
    suffix = " (teste)" if variant == "heldout" else ""
    codes = ("B11", "B12", "B13") if variant == "heldout" else ("A1", "A2", "A3")
    population_values = (180, 65) if variant == "heldout" else (120, 95)

    villages_path = input_dir / "aldeias.geojson"
    village_features = [
        {
            "type": "Feature",
            "properties": {"nome": f"Aldeia Arumã{suffix}", "escola": "sim", "codigo": codes[0]},
            "geometry": {"type": "Point", "coordinates": [-60.60 + shift, -2.45]},
        },
        {
            "type": "Feature",
            "properties": {"nome": f"Aldeia Muruci{suffix}", "escola": "não", "codigo": codes[1]},
            "geometry": {"type": "Point", "coordinates": [-60.50 + shift, -2.50]},
        },
        {
            "type": "Feature",
            "properties": {"nome": f"Aldeia Samaúma{suffix}", "escola": "sim", "codigo": codes[2]},
            "geometry": {"type": "Point", "coordinates": [-60.40 + shift, -2.55]},
        },
    ]
    if case_id == "dedup":
        village_features.append(dict(village_features[0]))
    _write_geojson(
        villages_path,
        "Point",
        village_features,
    )
    territories_path = input_dir / "territorios.geojson"
    territories = [
        ("Território Rio Claro", [-60.85 + shift, -2.85, -60.20 + shift, -2.15]),
    ]
    if case_id == "smp_ambiguous":
        territories.append(("Território Igarapé", [-60.12, -2.82, -59.48, -2.22]))
    features = []
    for name, (xmin, ymin, xmax, ymax) in territories:
        features.append({
            "type": "Feature",
            "properties": {"nome": name, "codigo": name[-2:]},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]]],
            },
        })
    _write_geojson(territories_path, "Polygon", features)
    table_path = input_dir / "dados_aldeias.csv"
    pop_a, pop_c = population_values
    table_path.write_text(
        "codigo,populacao,fonte\n"
        f"{codes[0]},{pop_a},levantamento sintetico\n"
        f"{codes[2]},{pop_c},levantamento sintetico\n",
        encoding="utf-8",
    )
    source_hashes = tuple(
        (path.name, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (villages_path, territories_path, table_path)
    )
    raster_path = input_dir / "fundo_sintetico.tif"
    _create_raster(raster_path)

    project_crs = "EPSG:3857" if case_id == "crs_view" else "EPSG:4326"
    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem(project_crs))
    raster = QgsRasterLayer(str(raster_path), "Fundo sintético", "gdal")
    if not raster.isValid():
        raise RuntimeError("Could not load local synthetic raster basemap")
    if case_id not in ("load",):
        project.addMapLayer(raster)
    layers = []
    for path, name in (
        (villages_path, f"Aldeias duplicadas{suffix}" if case_id == "dedup" else f"Aldeias{suffix}"),
        (territories_path, "Territórios"),
        (table_path, "Dados das aldeias"),
    ):
        provider = "ogr"
        if path.suffix == ".csv":
            uri = str(path)
            provider = "ogr"
        else:
            uri = str(path)
            provider = "ogr"
        layer = QgsVectorLayer(uri, name, provider)
        if not layer.isValid():
            raise RuntimeError(f"Could not load synthetic fixture layer {name}: {uri}")
        if case_id not in ("load", "workflow"):
            project.addMapLayer(layer)
        layers.append(layer)
    if case_id not in ("load", "workflow"):
        layers[0].setRenderer(
            QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"name": "square", "color": "180,45,45,255"}))
        )
        territory_transform = QgsCoordinateTransform(layers[1].crs(), project.crs(), project)
        view_extent = territory_transform.transformBoundingBox(layers[1].extent())
        if case_id == "crs_view":
            start_transform = QgsCoordinateTransform(layers[0].crs(), project.crs(), project)
            initial_extent = start_transform.transformBoundingBox(layers[0].extent())
        else:
            initial_extent = view_extent
        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(initial_extent, project.crs()))
    elif case_id == "workflow":
        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(raster.extent(), raster.crs()))
    if case_id == "selection":
        selected_ids = [
            feature.id()
            for feature in layers[0].getFeatures()
            if str(feature["codigo"]) in (codes[0], codes[2])
        ]
        layers[0].selectByIds(selected_ids)
    if case_id == "crs_view":
        # Extent is in the project's projected CRS while source geometries stay in WGS84.
        view_bounds = (
            view_extent.xMinimum(), view_extent.yMinimum(), view_extent.xMaximum(), view_extent.yMaximum()
        )
    else:
        view_bounds = tuple(territories[0][1])
    initial_bounds = (
        initial_extent.xMinimum(), initial_extent.yMinimum(), initial_extent.xMaximum(), initial_extent.yMaximum()
    ) if case_id not in ("load", "workflow") else tuple(territories[0][1])
    project_path = root / "fixture.qgz"
    if not project.write(str(project_path)):
        raise RuntimeError(f"Could not write fixture project: {project_path}")

    return Fixture(
        case_id=case_id,
        project_path=project_path,
        turns=(CASES[case_id].heldout_turns if variant == "heldout" and CASES[case_id].heldout_turns
               else CASES[case_id].turns),
        output_dir=output_dir,
        territory_names=tuple(name for name, _ in territories),
        layer_names=tuple(layer.name() for layer in layers) + (raster.name(),),
        raster_path=raster_path,
        region_extent=(-60.62 + shift, -2.57, -60.37 + shift, -2.40),
        territory_bounds=tuple(territories[0][1]),
        village_join_values=((codes[0], pop_a), (codes[2], pop_c)),
        villages_path=villages_path,
        input_files=(villages_path, territories_path, table_path),
        source_hashes=source_hashes,
        project_crs=project_crs,
        expected_view_bounds=view_bounds,
        initial_view_bounds=initial_bounds,
        expected_visible_layer_ids=tuple(layer.id() for layer in layers if layer.isSpatial()) + (
            (raster.id(),) if case_id not in ("load",) else ()
        ),
        expected_selected_codes=(codes[0], codes[2]),
        expected_category_values=("sim", "não"),
        expected_unique_codes=codes,
        expected_village_names=tuple(feature["properties"]["nome"] for feature in village_features[:3]),
        expected_village_records=tuple(
            (
                feature["properties"]["codigo"],
                feature["properties"]["nome"],
                feature["properties"]["escola"],
                feature["geometry"]["coordinates"][0],
                feature["geometry"]["coordinates"][1],
            )
            for feature in village_features[:3]
        ),
        preselected_codes=(codes[0], codes[2]) if case_id == "selection" else (),
        pdf_requires_local_basemap=case_id == "pdf_basemap",
        derived_file="aldeias_com_escola.geojson" if case_id == "layer_keep" else "",
        expected_derived=tuple(sorted(
            (feature["geometry"]["coordinates"][0], feature["geometry"]["coordinates"][1], "")
            for feature in village_features[:3] if feature["properties"]["escola"] == "sim"
        )) if case_id == "layer_keep" else (),
    )
