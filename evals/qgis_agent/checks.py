"""Deterministic graders for QGIS project state and exported artifacts."""

import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlparse
import zipfile
import hashlib

from .cases import CASES
from .trace import artifacts_under


def _result(case_id, status, detail):
    return {"id": case_id, "status": status, "detail": detail}


def _trace_text(trace):
    chunks = []

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("reply", "assistant_reply") and isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, (dict, list, tuple)):
                    walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            chunks.append(value)

    if isinstance(trace, dict):
        walk(trace.get("turns", []))
        walk(trace.get("assistant_replies", []))
    return "\n".join(chunks)


def _questions(trace):
    questions = []
    if not isinstance(trace, dict):
        return questions
    raw = trace.get("questions", [])
    if isinstance(raw, list):
        questions.extend(item for item in raw if isinstance(item, str))
    for turn in trace.get("turns", []):
        if isinstance(turn, dict):
            values = turn.get("questions", [])
            if isinstance(values, str):
                questions.append(values)
            elif isinstance(values, list):
                questions.extend(item for item in values if isinstance(item, str))
    return questions


def _layers(project):
    if project is None:
        return {}
    try:
        return {layer.name(): layer for layer in project.mapLayers().values()}
    except (AttributeError, RuntimeError):
        return {}


def _source_path(layer):
    try:
        source = layer.source()
    except (AttributeError, RuntimeError):
        return ""
    if source.startswith("file://"):
        source = unquote(urlparse(source).path)
    source = source.split("?", 1)[0].split("|", 1)[0]
    return Path(source)


def _matches_fixture(layer, fixture, filename):
    source_path = _source_path(layer)
    if source_path.name.casefold() != filename.casefold() or not source_path.is_file():
        return False
    expected_digest = dict(getattr(fixture, "source_hashes", ())).get(filename)
    return not expected_digest or hashlib.sha256(source_path.read_bytes()).hexdigest() == expected_digest


def _events(trace):
    events = trace.get("events", []) if isinstance(trace, dict) else []
    found = []

    def collect(node):
        if isinstance(node, dict):
            if "event" in node or "tool" in node or "name" in node:
                found.append(node)
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(events)
    collect(trace.get("turns", []) if isinstance(trace, dict) else [])
    return found


def _artifacts(fixture):
    output_dir = Path(fixture.output_dir)
    return [output_dir / path for path in artifacts_under(output_dir)]


def _premature_smp_export(trace):
    first_turn = next(iter(trace.get("turns", [])), {})
    return any(name.lower().endswith(".smp") for name in first_turn.get("artifacts", [])) or any(
        event["data"].get("smp_export") is True for event in first_turn.get("events", [])
    )


def _tile_xy(lon, lat, zoom):
    lat = max(-85.05112878, min(85.05112878, lat))
    count = 1 << zoom
    x = min(count - 1, max(0, int((lon + 180.0) / 360.0 * count)))
    rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * count)
    return x, min(count - 1, max(0, y))


def _coverage_tiles_present(names, slot, source):
    """Check that all tiles intersecting source bounds exist at each zoom."""
    bounds = source.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        return False
    west, south, east, north = map(float, bounds)
    minzoom, maxzoom = int(source["minzoom"]), int(source["maxzoom"])
    members = set(names)
    ext = str(source.get("format", "png")).lower()
    for zoom in range(minzoom, maxzoom + 1):
        x0, y1 = _tile_xy(west, south, zoom)
        x1, y0 = _tile_xy(east, north, zoom)
        count = 1 << zoom
        x_ranges = (range(x0, x1 + 1),) if x0 <= x1 else (range(x0, count), range(0, x1 + 1))
        for x_range in x_ranges:
            for x in x_range:
                for y in range(min(y0, y1), max(y0, y1) + 1):
                    if f"s/{slot}/{zoom}/{x}/{y}.{ext}" not in members:
                        return False
    return True


def _bounds_match(actual, expected, tolerance=0.0002):
    return (
        isinstance(actual, list)
        and len(actual) == 4
        and len(expected) == 4
        and all(abs(float(left) - float(right)) <= tolerance for left, right in zip(actual, expected))
    )


def _tile_zooms(names, slot):
    return {
        int(match.group(1))
        for name in names
        if (match := re.fullmatch(rf"s/{slot}/(\d+)/\d+/\d+\.(?:png|jpg|webp)", name))
    }


def _layer_features_by_key(layer, key="codigo"):
    fields = {field.name() for field in layer.fields()}
    if key not in fields:
        return None
    return list(layer.getFeatures())


def _marker_shape(layer):
    try:
        symbol = layer.renderer().symbol()
        marker = symbol.symbolLayer(0)
        return str(marker.properties().get("name", "unknown")).casefold()
    except (AttributeError, RuntimeError, TypeError):
        return "unknown"


def _source_files_unchanged(fixture):
    for filename, digest in getattr(fixture, "source_hashes", ()):
        source = next((path for path in fixture.input_files if path.name == filename), None)
        if not source or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            return False, filename
    return True, ""


def _feature_signature(feature):
    point = feature.geometry().asPoint()
    return (
        str(feature["codigo"]),
        str(feature["nome"]),
        str(feature["escola"]),
        float(point.x()),
        float(point.y()),
    )


def _projected_extent(fixture):
    try:
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle

        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        destination_crs = QgsCoordinateReferenceSystem(fixture.project_crs)
        transform = QgsCoordinateTransform(source_crs, destination_crs, QgsProject.instance())
        rect = transform.transformBoundingBox(QgsRectangle(*fixture.territory_bounds))
        return (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
    except (AttributeError, RuntimeError, ValueError):
        return tuple(fixture.territory_bounds)


def _case_status(case_id, fixture, project, trace):
    layers = _layers(project)
    text = _trace_text(trace)
    lower_text = text.casefold()
    events = _events(trace)

    if case_id == "basemap":
        selected = []
        for layer in layers.values():
            try:
                source = layer.source().casefold()
            except (AttributeError, RuntimeError):
                source = ""
            google_host = "google" in source and ("http" in source or "url=" in source)
            satellite = "satellite" in source or "lyrs=s" in source or "lyrs%3Ds" in source
            if google_host and satellite:
                selected.append(source)
        if selected:
            return "pass", "Google Satellite XYZ source is configured in the live project layer state."
        policy_denial = any(
            any(word in str(event).casefold() for word in ("blocked", "denied", "approval required", "not authorized"))
            for event in events
        )
        if policy_denial:
            return "blocked", "Basemap selection was gated by the active external-access permission policy."
        return "fail", "No concrete Google Satellite raster URL is present in the live project layer state."

    if case_id in ("load", "workflow"):
        fixture_files = {path.name.casefold() for path in getattr(fixture, "input_files", ())}
        aldeias_layers = [
            layer for layer in layers.values()
            if _matches_fixture(layer, fixture, "aldeias.geojson")
        ]
        territory_layers = [
            layer for layer in layers.values()
            if _matches_fixture(layer, fixture, "territorios.geojson")
        ]
        missing = []
        if "aldeias.geojson" in fixture_files and not aldeias_layers:
            missing.append("aldeias.geojson")
        if "territorios.geojson" in fixture_files and not territory_layers:
            missing.append("territorios.geojson")
        if "dados_aldeias.csv" in fixture_files and not any(
            _matches_fixture(layer, fixture, "dados_aldeias.csv") for layer in layers.values()
        ):
            missing.append("dados_aldeias.csv")
        if missing:
            return "fail", f"Missing supplied fixture layers in QGIS project: {', '.join(missing)}."
        aldeias = aldeias_layers[0]
        territory = territory_layers[0]
        try:
            counts_ok = (
                aldeias.featureCount() == 3
                and territory.featureCount() == len(getattr(fixture, "territory_names", ()))
            )
        except (AttributeError, RuntimeError):
            counts_ok = False
        names_present = any(name in text for name in ("Arumã", "Muruci", "Samaúma"))
        expected_territories = len(getattr(fixture, "territory_names", ()))
        count_terms = {
            1: (r"1|um|uma", r"território|territorio|área|area"),
            2: (r"2|dois|duas", r"territórios|territorios|áreas|areas"),
        }
        village_count = re.search(
            r"(?:\b3\b|\btrês\b)\s+(?:aldeias|comunidades|pontos)\b",
            text,
            re.IGNORECASE,
        )
        territory_count = False
        if expected_territories in count_terms:
            number, unit = count_terms[expected_territories]
            territory_count = bool(re.search(rf"\b(?:{number})\s+(?:{unit})\b", text, re.IGNORECASE))
        count_text = bool(village_count and territory_count)
        if counts_ok and names_present and count_text:
            detail = (
                f"Loaded layer counts (3 aldeias; {expected_territories} territories) and a feature "
                "example appear in the assistant reply."
            )
            return "pass", detail
        detail = (
            "Layer counts or grounded examples are missing "
            f"(counts_ok={counts_ok}, example={names_present}, counts_in_reply={count_text})."
        )
        return "fail", detail

    if case_id == "style":
        layer = next((layer for name, layer in layers.items() if name.casefold().startswith("aldeias")), None)
        if layer is None:
            return "fail", "Aldeias layer is absent."
        try:
            renderer = layer.renderer()
            symbol = renderer.symbol()
            color = symbol.color().name().lower()
            symbol_layer = symbol.symbolLayer(0)
            symbol_properties = symbol_layer.properties() if symbol_layer else {}
            symbol_name = str(symbol_properties.get("name", "unknown")).casefold()
            label_settings = layer.labeling().settings() if layer.labeling() else None
            label_field = label_settings.fieldName if label_settings else ""
            buffer = label_settings.format().buffer() if label_settings else None
            buffer_enabled = bool(buffer and buffer.enabled())
            buffer_color = buffer.color().name().lower() if buffer_enabled else ""
            blue = color in ("#0000ff", "#007bff", "#0066ff", "#1e90ff", "#0000ee")
            style_ok = (
                blue
                and symbol_name != "square"
                and layer.labelsEnabled()
                and label_field == "nome"
                and buffer_enabled
                and buffer_color == "#ffffff"
            )
            if style_ok:
                return "pass", f"Aldeias uses blue {symbol_name} markers; labels use {label_field} with a white buffer."
            detail = (
                f"Unexpected style state: color={color}, symbol={symbol_name}, "
                f"labels={layer.labelsEnabled()}, field={label_field!r}, "
                f"buffer={buffer_enabled}/{buffer_color}."
            )
            return "fail", detail
        except (AttributeError, RuntimeError) as exc:
            return "fail", f"Could not inspect aldeias renderer and labels: {exc}"

    if case_id == "crs_view":
        state = trace.get("canvas_state_after_turn", {}) if isinstance(trace, dict) else {}
        extent = state.get("extent") if isinstance(state, dict) else None
        layer_ids = set(state.get("layer_ids", [])) if isinstance(state, dict) else set()
        if not isinstance(extent, (list, tuple)) or len(extent) != 4:
            return "fail", "Trace lacks a four-value canvas extent after the CRS/view request."
        if project.crs().authid() != fixture.project_crs:
            return "fail", "The project CRS changed while adjusting the view."
        target = _projected_extent(fixture)
        left, bottom, right, top = map(float, extent)
        xmin, ymin, xmax, ymax = target
        if left > xmin or bottom > ymin or right < xmax or top < ymax:
            return "fail", "Current canvas extent does not contain the full territory after CRS transformation."
        width, height = right - left, top - bottom
        target_width, target_height = xmax - xmin, ymax - ymin
        if width > target_width * 2.5 or height > target_height * 2.5:
            return "fail", "Current canvas is zoomed too far out for the territory and village overview."
        expected_ids = set(getattr(fixture, "expected_visible_layer_ids", ()))
        if not expected_ids.issubset(layer_ids):
            return "fail", "Visible canvas is missing an expected territory, village or local raster layer."
        unchanged, changed_file = _source_files_unchanged(fixture)
        if not unchanged:
            return "fail", f"Source file {changed_file} changed while adjusting the map view."
        return "pass", "The projected canvas contains the full synthetic territory and required visible layers."

    if case_id == "selection":
        target = next(
            (layer for layer in layers.values() if _matches_fixture(layer, fixture, "aldeias.geojson")),
            None,
        )
        if target is None:
            return "fail", "Selection source is not the supplied aldeias GeoJSON."
        expected_codes = set(fixture.expected_selected_codes)
        selected = {
            str(feature["codigo"])
            for feature in target.getFeatures()
            if feature.id() in set(target.selectedFeatureIds())
        }
        if selected != expected_codes:
            return "fail", f"Current selection is {sorted(selected)}; expected exactly {sorted(expected_codes)}."
        if not all(name in text for name in fixture.expected_village_names[::2]):
            return "fail", "The reply does not identify both currently selected aldeias by name."
        expected = {item[0]: item[1:] for item in fixture.expected_village_records}
        actual = {
            _feature_signature(feature)[0]: _feature_signature(feature)[1:]
            for feature in target.getFeatures()
        }
        if actual != expected:
            return "fail", "Feature attributes or geometries changed while reading the selection."
        unchanged, changed_file = _source_files_unchanged(fixture)
        if not unchanged:
            return "fail", f"Source file {changed_file} changed while reading the selection."
        return "pass", (
            "The pre-existing selection contains exactly the school-bearing aldeias, "
            "and the reply names both."
        )

    if case_id == "category_split":
        category_layers = []
        for layer in layers.values():
            try:
                fields = {field.name() for field in layer.fields()}
                if not {"codigo", "escola"}.issubset(fields):
                    continue
                rows = list(layer.getFeatures())
                values = {str(feature["escola"]).casefold() for feature in rows}
                if values in ({"sim"}, {"não"}, {"nao"}):
                    category_layers.append((layer, values, rows))
            except (AttributeError, RuntimeError, TypeError):
                continue
        yes_layer = next((item for item in category_layers if item[1] == {"sim"}), None)
        no_layer = next((item for item in category_layers if item[1] in ({"não"}, {"nao"})), None)
        if not yes_layer or not no_layer:
            return "fail", "The project does not contain separate school=yes and school=no feature layers."
        yes_records = [_feature_signature(feature) for feature in yes_layer[2]]
        no_records = [_feature_signature(feature) for feature in no_layer[2]]
        yes_codes = {record[0] for record in yes_records}
        no_codes = {record[0] for record in no_records}
        expected_yes = set(fixture.expected_selected_codes)
        expected_no = set(fixture.expected_unique_codes) - expected_yes
        if yes_codes != expected_yes or no_codes != expected_no:
            return "fail", (
                f"Category membership differs from fixture (yes={sorted(yes_codes)}, "
                f"no={sorted(no_codes)})."
            )
        expected_records = {record[0]: record[1:] for record in fixture.expected_village_records}
        actual_records = {record[0]: record[1:] for record in yes_records + no_records}
        all_codes = [record[0] for record in yes_records + no_records]
        if len(all_codes) != len(set(all_codes)) or actual_records != expected_records:
            return "fail", "Split categories duplicate or alter source attributes/geometries."
        yes_shape, no_shape = _marker_shape(yes_layer[0]), _marker_shape(no_layer[0])
        if yes_shape == "unknown" or no_shape == "unknown" or yes_shape == no_shape:
            return "fail", "The school categories do not use two distinct point icon shapes."
        unchanged, changed_file = _source_files_unchanged(fixture)
        if not unchanged:
            return "fail", f"Source file {changed_file} changed while splitting categories."
        return "pass", (
            f"Separate school categories preserve expected codes and use distinct "
            f"{yes_shape}/{no_shape} icons."
        )

    if case_id == "dedup":
        candidates = []
        for layer in layers.values():
            try:
                features = _layer_features_by_key(layer)
                if features is not None:
                    candidates.append((layer, features))
            except (AttributeError, RuntimeError):
                continue
        expected = set(fixture.expected_unique_codes)
        matching = None
        expected_records = {
            code: (name, school, x, y)
            for code, name, school, x, y in fixture.expected_village_records
        }
        for layer, features in candidates:
            rows = []
            for feature in features:
                if not feature.hasGeometry() or feature.geometry().isEmpty():
                    rows = []
                    break
                try:
                    point = feature.geometry().asPoint()
                except (TypeError, ValueError):
                    rows = []
                    break
                rows.append((
                    str(feature["codigo"]), str(feature["nome"]), str(feature["escola"]),
                    float(point.x()), float(point.y()),
                ))
            codes = [row[0] for row in rows]
            if len(rows) != len(expected) or set(codes) != expected or len(set(codes)) != len(expected):
                continue
            if all(
                row[1] == expected_records[row[0]][0]
                and row[2] == expected_records[row[0]][1]
                and abs(row[3] - expected_records[row[0]][2]) < 1e-8
                and abs(row[4] - expected_records[row[0]][3]) < 1e-8
                for row in rows
            ):
                matching = layer
                break
        if not matching:
            return "fail", "No output layer has one unchanged feature per expected code with the original geometry."
        for filename, digest in getattr(fixture, "source_hashes", ()):
            source = next((path for path in fixture.input_files if path.name == filename), None)
            if not source or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                return "fail", f"Source file {filename} changed during deduplication."
        return "pass", (
            f"{matching.featureCount()} unique codes remain with original feature data; "
            "source files are unchanged."
        )

    if case_id == "filter_join":
        outputs = []
        for layer in layers.values():
            try:
                fields = {field.name() for field in layer.fields()}
                if "codigo" in fields and fields.intersection({"populacao", "populacao_2"}):
                    records = [
                        (
                            str(feature["codigo"]),
                            int(feature["populacao"] if "populacao" in fields else feature["populacao_2"]),
                        )
                        for feature in layer.getFeatures()
                    ]
                    outputs.append((layer, records))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        expected = dict(getattr(fixture, "village_join_values", (("A1", 120), ("A3", 95))))
        expected_rows = sorted(expected.items())
        match = next(
            (
                (layer, records)
                for layer, records in outputs
                if sorted(records) == expected_rows and len(records) == len(expected)
            ),
            None,
        )
        if match:
            for filename, digest in getattr(fixture, "source_hashes", ()):
                original_path = next((path for path in fixture.input_files if path.name == filename), None)
                if not original_path or hashlib.sha256(original_path.read_bytes()).hexdigest() != digest:
                    return "fail", f"The original source file {filename} changed during filtering/joining."
            return "pass", (
                "The exact school-bearing fixture codes and expected joined population values are present; "
                "source GeoJSON remains unchanged."
            )
        if outputs:
            actual = "; ".join(f"{layer.name()}={records}" for layer, records in outputs)
            return "fail", f"Joined fields exist, but filtered IDs/values do not match {expected}: {actual}."
        return "fail", "No layer contains both a join key and joined population field."
    if case_id in ("pdf", "pdf_basemap"):
        pdfs = [path for path in _artifacts(fixture) if path.suffix.lower() == ".pdf"]
        valid = []
        for path in pdfs:
            try:
                if path.read_bytes()[:5] == b"%PDF-":
                    valid.append(path)
            except OSError:
                continue
        if not valid:
            return "fail", "No exported artifact with a valid PDF header was found."
        if case_id == "pdf_basemap":
            capture = trace.get("first_pdf_export") if isinstance(trace, dict) else None
            if not isinstance(capture, dict):
                if len(valid) > 1:
                    return "blocked", (
                        "Several PDF files exist but the trace does not identify which was exported first; "
                        "first-PDF correctness cannot be determined."
                    )
                return "manual", (
                    f"PDF artifact exists ({valid[0].name}), but the first-export snapshot is unavailable; "
                    "visually inspect this PDF's actual extent, local raster basemap, and thematic layers."
                )
            relative_path = capture.get("output")
            relative_artifacts = artifacts_under(fixture.output_dir)
            if not isinstance(relative_path, str) or relative_path not in relative_artifacts:
                return "fail", "Captured first-PDF path is not an artifact inside the run output directory."
            valid_paths = {
                path.relative_to(Path(fixture.output_dir)).as_posix(): path
                for path in valid
                if path.is_relative_to(Path(fixture.output_dir))
            }
            if relative_path not in valid_paths:
                return "fail", "Captured first-PDF artifact does not have a valid PDF header."
            captured_path = valid_paths[relative_path]
            try:
                if hashlib.sha256(captured_path.read_bytes()).hexdigest() != capture.get("sha256"):
                    return "fail", "Captured first-PDF SHA-256 does not match the artifact bytes."
            except OSError:
                return "fail", "Captured first-PDF artifact is missing or unreadable."
            expected_ids = set(fixture.expected_visible_layer_ids)
            map_layer_ids = capture.get("map_layer_ids", [])
            if not any(expected_ids.issubset(set(layer_ids)) for layer_ids in map_layer_ids):
                return "fail", "No first-PDF map includes the local raster and both thematic layers together."
            if not capture.get("has_scale_bar") or not capture.get("has_legend"):
                return "fail", "The first PDF layout is missing a scale bar or legend."
            return "manual", (
                f"First PDF artifact and SHA-256 are bound to a map containing the local raster and thematic "
                f"layers ({relative_path}); visually inspect actual extent, readability, title, north arrow, "
                "and clipping."
            )
        try:
            from qgis.core import QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemScaleBar

            layouts = project.layoutManager().layouts()
            requested_layout = None
            exports = trace.get("pdf_exports", []) if isinstance(trace, dict) else []
            linked_export = False
            for export in exports:
                output = export.get("output") or export.get("path")
                if output and Path(output).name not in {pdf.name for pdf in valid}:
                    continue
                linked_export = True
                layout_key = export.get("layout_id") or export.get("layout_name")
                requested_layout = next(
                    (
                        layout for layout in layouts
                        if layout.name() == layout_key
                        or (hasattr(layout, "id") and layout.id() == layout_key)
                    ),
                    None,
                )
                if requested_layout:
                    break
            if requested_layout:
                checked_layouts = [requested_layout]
            elif linked_export:
                return "fail", "Trace links the PDF to a layout that is absent from the evaluated QGIS project."
            else:
                detail = (
                    f"PDF header is valid ({valid[0]}), but no trace entry binds this file to a QGIS layout; "
                    "visually inspect the rendered page for its map and required elements."
                )
                return "manual", detail
            items = [item for layout in checked_layouts for item in layout.items()]
            map_items = [item for item in items if isinstance(item, QgsLayoutItemMap)]
            if not map_items:
                return "fail", "PDF exists, but the project has no QgsLayoutItemMap; this is a blank-page export."
            if getattr(fixture, "pdf_requires_local_basemap", False):
                raster_layer = next(
                    (layer for layer in project.mapLayers().values()
                     if _source_path(layer).resolve() == Path(fixture.raster_path).resolve()),
                    None,
                )
                if raster_layer is None:
                    return "fail", "The fixture's local raster basemap is absent from the QGIS project."
                mapped_layers = set()
                for map_item in map_items:
                    try:
                        mapped_layers.update(map_item.layersToRender())
                    except (AttributeError, RuntimeError):
                        if map_item.keepLayerSet():
                            mapped_layers.update(map_item.layers())
                if raster_layer not in mapped_layers:
                    return "fail", "PDF map item does not render the fixture's local raster basemap."
            scale_bars = [item for item in items if isinstance(item, QgsLayoutItemScaleBar)]
            legends = [item for item in items if isinstance(item, QgsLayoutItemLegend)]
            if not scale_bars or not (legends or any("fonte" in str(item).casefold() for item in items)):
                return "fail", "PDF layout lacks a scale bar or a legend/source-credit item."
            detail = (
                "PDF header is valid and the selected project layout contains a map, scale bar and "
                f"legend/credits ({valid[0]}); visually confirm the export also shows the title, extent, "
                "north arrow, and readable unclipped content."
            )
            return "manual", detail
        except (AttributeError, RuntimeError, ImportError) as exc:
            return "fail", f"Could not verify the QGIS print layout structure: {exc}"

    if case_id.startswith("smp_"):
        if case_id == "smp_ambiguous":
            territories = getattr(fixture, "territory_names", ())
            question_text = " ".join(_questions(trace))
            clarification = f"{lower_text}\n{question_text.casefold()}"
            ask = any(mark in clarification for mark in (
                "qual território", "qual é o território", "qual dos territórios",
                "qual desses territórios", "which territory",
            ))
            premature_export = any(path.suffix.lower() == ".smp" for path in _artifacts(fixture))
            if len(territories) < 2:
                return "fail", "Ambiguity fixture must contain at least two territories."
            if not ask:
                return "fail", "Ambiguous territory case did not ask a targeted territory clarification."
            if premature_export:
                return "fail", "An SMP was exported before the user selected one of the ambiguous territories."
            return "pass", "Two territories are available and the agent asked which one to include before exporting."
        smps = [path for path in _artifacts(fixture) if path.suffix.lower() == ".smp"]
        if not smps:
            message = " ".join(str(item) for item in events).casefold()
            if "plugin" in message and ("not installed" in message or "missing" in message):
                return "blocked", "SMP export is blocked because the CoMapeo Map Builder plugin is unavailable."
            return "fail", "No .smp artifact was found in trace artifacts or the run output directory."
        path = smps[0]
        try:
            if case_id == "smp_region" and _premature_smp_export(trace):
                return "fail", "An SMP export was attempted before the user framed and confirmed the specific region."
            with zipfile.ZipFile(path) as archive:
                bad_member = archive.testzip()
                names = set(archive.namelist())
                if bad_member:
                    return "fail", f"SMP ZIP CRC check failed at {bad_member}."
                if "style.json" not in names or "VERSION" not in names:
                    return "fail", "SMP archive lacks style.json or VERSION."
                style = json.loads(archive.read("style.json"))
                sources = style.get("sources", {})
                if not isinstance(sources, dict) or not sources:
                    return "fail", "style.json has no raster sources."
                slots = {}
                for source_id, source in sources.items():
                    match = re.search(r"/s/(\d+)/\{z\}/\{x\}/\{y\}", " ".join(source.get("tiles", [])))
                    if match:
                        slots[source.get("name", source_id)] = (int(match.group(1)), source)
                required_world = next((value for key, value in slots.items() if "world" in key.casefold()), None)
                required_region = next((value for key, value in slots.items() if "region" in key.casefold()), None)
                required_local = next((value for key, value in slots.items() if "local" in key.casefold()), None)
                if required_local is None:
                    return "fail", "No Local source metadata was found in style.json."
                if case_id == "smp_region" and required_region is None:
                    return "fail", "Specific-area export is missing the Region middle-zoom source."
                if case_id != "smp_region" and case_id != "smp_ambiguous" and required_region is not None:
                    return "fail", "Territory-only export unexpectedly has a Region source."
                expected_local_slot = 2
                if required_local[0] != expected_local_slot:
                    return "fail", f"Local source points to s/{required_local[0]}; expected fixed slot s/2."
                local_source = required_local[1]
                if case_id == "smp_region":
                    local_min, local_max = int(local_source.get("minzoom", -1)), int(local_source.get("maxzoom", -1))
                    if local_min != 12 or not 14 <= local_max <= 18:
                        return "fail", (
                            "Specific-area Local source must cover zoom 12 through a recommended "
                            "maximum between 14 and 18."
                        )
                    region_source = required_region[1]
                    region_zooms = (int(region_source.get("minzoom", -1)), int(region_source.get("maxzoom", -1)))
                    if required_region[0] != 1 or region_zooms != (6, 11):
                        return "fail", "Region source must use s/1 for zooms 6–11."
                elif case_id in ("smp_territory", "smp_ambiguous"):
                    if (int(local_source.get("minzoom", -1)), int(local_source.get("maxzoom", -1))) != (6, 11):
                        return "fail", "Territory-only Local source must cover zooms 6–11."
                tile_members = [name for name in names if re.fullmatch(r"s/[0-2]/\d+/\d+/\d+\.(?:png|jpg|webp)", name)]
                if not tile_members:
                    return "fail", "SMP archive has no raster XYZ tile members in s/{slot}/{z}/{x}/{y}.{format} form."
                used_slots = {int(name.split("/")[1]) for name in tile_members}
                if required_local[0] not in used_slots:
                    return "fail", "Local source metadata references a slot with no tile members."
                if required_world is None:
                    return "fail", "World overview source is missing."
                world_source = required_world[1]
                world_zooms = (int(world_source.get("minzoom", -1)), int(world_source.get("maxzoom", -1)))
                if required_world[0] != 0 or world_zooms != (0, 5):
                    return "fail", "World source must use s/0 and cover zooms 0–5."
                if _tile_zooms(names, 0) != set(range(0, 6)):
                    return "fail", "World tile members do not exactly cover zooms 0–5."
                expected_world = [-180.0, -85.0511, 180.0, 85.0511]
                if not _bounds_match(world_source.get("bounds"), expected_world, tolerance=0.001):
                    return "fail", "World source bounds do not cover the expected full Web Mercator world."
                territory_bounds = list(getattr(fixture, "territory_bounds", ()))
                if case_id == "smp_region":
                    actual_canvas = trace.get("canvas_extent_after_pan") if isinstance(trace, dict) else None
                    if not isinstance(actual_canvas, (list, tuple)) or len(actual_canvas) != 4:
                        return "fail", (
                            "The trace lacks canvas_extent_after_pan required to bind Local tiles "
                            "to the user's updated view."
                        )
                    if not _bounds_match(local_source.get("bounds"), list(actual_canvas)):
                        return "fail", "Local source bounds do not match the updated post-pan canvas extent."
                    if not _bounds_match(region_source.get("bounds"), territory_bounds):
                        return "fail", "Region source bounds do not match the fixture territory boundary."
                elif case_id == "smp_territory":
                    if not _bounds_match(local_source.get("bounds"), territory_bounds):
                        return "fail", "Territory Local source bounds do not match the fixture territory boundary."
                if not _coverage_tiles_present(names, required_world[0], world_source):
                    return "fail", "World source is missing tiles across its full bounds and zoom range."
                if not _coverage_tiles_present(names, required_local[0], local_source):
                    return "fail", "Local source is missing tiles across its full bounds and zoom range."
                if required_region and not _coverage_tiles_present(names, required_region[0], required_region[1]):
                    return "fail", "Region source is missing tiles across its full bounds and zoom range."
                for slot, source in ((required_world[0], world_source), (required_local[0], local_source)):
                    if _tile_zooms(names, slot) != set(range(int(source["minzoom"]), int(source["maxzoom"]) + 1)):
                        return "fail", (
                            f"Tiles in source slot s/{slot} fall outside the advertised zoom "
                            "range or leave a zoom gap."
                        )
                region_tiles_valid = (
                    not required_region
                    or _tile_zooms(names, required_region[0])
                    == set(range(int(region_source["minzoom"]), int(region_source["maxzoom"]) + 1))
                )
                if not region_tiles_valid:
                    return "fail", "Region tiles fall outside the advertised zoom range or leave a zoom gap."
                size_bytes = path.stat().st_size
                metrics = trace.get("metrics", {}) if isinstance(trace, dict) else {}
                actual_bytes = metrics.get("smp_bytes") or size_bytes
                elapsed_seconds = metrics.get("export_seconds")
                actual_export = f"Actual package: {actual_bytes} bytes"
                if elapsed_seconds is not None:
                    actual_export += f", export time: {elapsed_seconds} seconds"
                estimate_review = (
                    "Have a reviewer confirm the assistant explained estimated size and preparation time "
                    "with assumptions for extent, zoom range, and available imagery."
                )
                detail = (
                    f"SMP archive structure and zoom bands are valid. {actual_export}. {estimate_review} "
                    "Also inspect tile-edge coverage, rendered styling/labels, and offline viewing in CoMapeo."
                )
                return "manual", detail
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return "fail", f"Could not validate SMP package structure: {exc}"

    return "blocked", f"No deterministic grader is implemented for {case_id}."


OBSERVED_CASES = ("camps_merge", "layer_keep")
_TYPE_ATTRIBUTES = ("tipo", "type")
_ALLOWED_TYPES = ("vigilância", "demarcação", "não informado")
_STATE_LAYER = re.compile(r"^- (?P<name>.+?) \(id=(?P<id>[^,)]+), type=[^)]*\)(?P<rest>.*)$")


def _normalize_type(value):
    return " ".join(str(value or "").casefold().split())


def _point_records(path):
    """(x, y, string attributes) of every point of a GeoJSON file, or None when unreadable."""
    try:
        collection = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    records = []
    for feature in (collection.get("features") or []) if isinstance(collection, dict) else []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        try:
            point = (float(coordinates[0]), float(coordinates[1]))
        except (TypeError, ValueError):
            continue
        properties = feature.get("properties") or {}
        records.append((*point, {key: value for key, value in properties.items() if isinstance(value, str)}))
    return records


def _type_attribute(records):
    """Name of the column whose values are camp types, or None."""
    for key in records[0][2] if records else {}:
        if any(mark in key.casefold() for mark in _TYPE_ATTRIBUTES) and all(
                _normalize_type(properties.get(key)) in _ALLOWED_TYPES for _, _, properties in records):
            return key
    return None


def _point_differences(records, expected, tolerance=1e-6):
    """Why ``records`` does not hold exactly the expected (x, y, type) points; empty when it does."""
    typed = bool(expected and expected[0][2])
    attribute = _type_attribute(records) if typed else None
    problems = [] if not typed or attribute else [
        "no column named like 'tipo' holds only vigilância, demarcação or não informado"
    ]
    remaining = list(records)
    for x, y, kind in expected:
        found = next((record for record in remaining if abs(record[0] - x) <= tolerance
                      and abs(record[1] - y) <= tolerance), None)
        if found is None:
            problems.append(f"no point at ({x:g}, {y:g})")
            continue
        remaining.remove(found)
        if attribute and _normalize_type(found[2].get(attribute)) != _normalize_type(kind):
            problems.append(f"({x:g}, {y:g}) is {found[2].get(attribute)!r}, expected {kind!r}")
    problems.extend(f"unexpected point at ({record[0]:g}, {record[1]:g})" for record in remaining)
    return problems


def observe_run(fixture, project, run_dir):
    """What the derived file of a session case and the project layers backed by it hold now.

    The runner records this after each turn, so a later instruction is graded
    against the state the earlier ones produced, not only against the end of
    the run. Paths are relative to the run directory.
    """
    name = getattr(fixture, "derived_file", "")
    if not name:
        return {}
    root = Path(run_dir).resolve()
    files = {}
    for path in sorted(root.rglob(name)):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        records = _point_records(path)
        if records is not None:
            files[str(path.relative_to(root))] = records
    sources = {path.resolve(): relative for relative, path in ((relative, root / relative) for relative in files)}
    layers = []
    for layer in (project.mapLayers().values() if project is not None else []):
        try:
            layers.append({"name": layer.name(), "file": sources.get(_source_path(layer).resolve()),
                           "features": layer.featureCount()})
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
    return {"files": files, "layers": [layer for layer in layers if layer["file"] is not None]}


def _observed(turn):
    return (turn.get("observed") or {}) if isinstance(turn, dict) else {}


def _derived_file_check(check_id, fixture, observed, expected, require_layer):
    """Grade the derived file of a session case against the points and types it must hold."""
    name = getattr(fixture, "derived_file", "")
    files = {relative: records for relative, records in observed.get("files", {}).items()
             if Path(relative).name == name}
    if not files:
        return _result(check_id, "fail", f"No file named {name} exists under the run directory.")
    problems = [f"{relative}: " + "; ".join(differences)
                for relative, records in sorted(files.items())
                if (differences := _point_differences(records, expected))]
    if require_layer and not any(layer.get("file") in files for layer in observed.get("layers", [])):
        problems.append(f"no project layer is loaded from {name}; the user asked for a layer, not only a file")
    return _result(check_id, "fail" if problems else "pass",
                   "The file holds exactly the expected points and types." if not problems else " ".join(problems))


def _workspace_state_check(turn, project, check_id="workspace_state"):
    """The workspace state sent to the model must list only layers the project still holds."""
    state = turn.get("workspace_state") if isinstance(turn, dict) else None
    if not isinstance(state, str):
        return _result(check_id, "fail", "The runner recorded no workspace state for this turn.")
    problems = []
    for line in state.splitlines():
        match = _STATE_LAYER.match(line.strip())
        if not match:
            continue
        layer_id = match.group("id")
        layer = project.mapLayer(layer_id) if project is not None else None
        if layer is None:
            problems.append(f"{match.group('name')} (id {layer_id[:12]}…) is no longer in the project")
        elif (count := re.search(r"features=(\d+)", match.group("rest"))) and (
                layer.featureCount() != int(count.group(1))):
            problems.append(f"{layer.name()} is listed with {count.group(1)} features and holds {layer.featureCount()}")
    return _result(
        check_id, "fail" if problems else "pass",
        "The workspace state given to the model disagrees with the project: " + "; ".join(problems)
        if problems else
        "The workspace state lists only layers that are in the project, with their current feature counts.")


def _session_results(case_id, fixture, project, trace):
    """Graders for the cases that replay a user's instructions over several turns."""
    turns = trace.get("turns", []) if isinstance(trace, dict) else []
    first, last = (_observed(turns[0]) if turns else {}), (_observed(turns[-1]) if turns else {})
    results = []
    if case_id == "camps_merge":
        results.append(_derived_file_check(
            "camps_saved", fixture, _observed(turns[1]) if len(turns) > 1 else {}, fixture.expected_derived, True))
        final = _derived_file_check("camps_final", fixture, last, fixture.expected_final, False)
        stale = [f"The project layer {layer['name']} shows {layer['features']} features while its file holds "
                 f"{len(last['files'][layer['file']])}."
                 for layer in last.get("layers", []) if layer["features"] != len(last["files"][layer["file"]])]
        if stale:
            final = _result("camps_final", "fail", final["detail"] + " " + " ".join(stale))
        results.append(final)
        unchanged, changed = _source_files_unchanged(fixture)
        results.append(_result("camps_sources", "pass" if unchanged else "fail",
                               "The source files were not modified." if unchanged
                               else f"The source file {changed} was modified."))
        results.append(_workspace_state_check(turns[-1] if turns else {}, project))
        return results
    results.append(_derived_file_check("kept_saved", fixture, first, fixture.expected_derived, True))
    created = sorted(first.get("files", {}))
    if not created:
        results.append(_result("kept_file", "fail", "Nothing to keep: the requested file was not created."))
        results.append(_result("kept_unloaded", "fail", "Nothing to unload: the requested file was not created."))
    else:
        gone = [relative for relative in created if relative not in last.get("files", {})]
        changed = [relative for relative in created if relative not in gone and _point_differences(
            last["files"][relative], [(x, y, "") for x, y, _ in fixture.expected_derived])]
        if gone:
            results.append(_result("kept_file", "fail", (
                f"{', '.join(gone)} was deleted after its layer was removed from the project.")))
        elif changed:
            results.append(_result("kept_file", "fail", (
                f"{', '.join(changed)} no longer holds the points it held when it was created.")))
        else:
            results.append(_result("kept_file", "pass", "The file was kept unchanged after its layer was removed."))
        if len(turns) < 2:
            results.append(_result("kept_unloaded", "fail", "The turn that removes the layer did not run."))
        elif last.get("layers"):
            results.append(_result("kept_unloaded", "fail", (
                f"A layer loaded from {', '.join(layer['name'] for layer in last['layers'])} "
                "is still in the project.")))
        else:
            results.append(_result("kept_unloaded", "pass", "No project layer is loaded from the kept file."))
    results.append(_workspace_state_check(turns[-1] if turns else {}, project))
    return results


def evaluate(fixture, project, trace: dict) -> list[dict]:
    """Evaluate one fixture. Results use pass/fail/manual/blocked statuses."""
    case_id = getattr(fixture, "case_id", None)
    if case_id not in CASES:
        return [_result(str(case_id or "unknown"), "blocked", "Fixture case_id is unknown.")]
    if case_id == "workflow":
        captured = trace.get("workflow_checks", []) if isinstance(trace, dict) else []
        results = [
            {"id": item["id"], "status": item["status"], "detail": item["detail"]}
            for item in captured
            if isinstance(item, dict) and item.get("id") in ("basemap", "load", "style", "filter_join")
        ]
        captured_ids = {item["id"] for item in results}
        for component_id in ("basemap", "load", "style", "filter_join"):
            if component_id not in captured_ids:
                status, detail = _case_status(component_id, fixture, project, trace or {})
                results.append(_result(component_id, status, detail))
        for component_id in ("pdf", "smp_territory"):
            status, detail = _case_status(component_id, fixture, project, trace or {})
            results.append(_result(component_id, status, detail))
        statuses = {result["status"] for result in results}
        if "fail" in statuses:
            aggregate_status = "fail"
        elif "blocked" in statuses:
            aggregate_status = "blocked"
        elif "manual" in statuses:
            aggregate_status = "manual"
        else:
            aggregate_status = "pass"
        results.append(_result(
            "workflow",
            aggregate_status,
            "Aggregate status over basemap, load, style, filter/join, PDF, and territory SMP components.",
        ))
        return results
    if case_id in OBSERVED_CASES:
        results = _session_results(case_id, fixture, project, trace or {})
        statuses = {result["status"] for result in results}
        results.append(_result(
            case_id, next((status for status in ("fail", "blocked", "manual", "pass") if status in statuses), "pass"),
            "Aggregate status over the derived file, its points and types, the project layers and the "
            "workspace state."))
        return results
    status, detail = _case_status(case_id, fixture, project, trace or {})
    return [_result(case_id, status, detail)]


def evaluate_step(case_id: str, fixture, project, trace: dict) -> dict:
    """Evaluate one named stage against the project state at that point in a run."""
    if case_id not in CASES or case_id == "workflow":
        return _result(str(case_id), "blocked", "Unknown or aggregate evaluation stage.")
    status, detail = _case_status(case_id, fixture, project, trace or {})
    return _result(case_id, status, detail)
