"""Read-only QGIS project and map canvas inspection for CoMapeo SMP exports."""

from __future__ import annotations

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

from .policy import (
    VENDOR_COMMIT,
    classify_layer_policy,
    is_online_layer,
    layer_attribution,
    layer_sensitivity,
    layer_source_uri,
    redact_uri,
    visible_layers_in_render_order,
)
from .vendor.comapeo_smp_generator import SMPGenerator


def _rect_to_list(rect):
    if rect is None or rect.isEmpty():
        return None
    return [
        float(rect.xMinimum()),
        float(rect.yMinimum()),
        float(rect.xMaximum()),
        float(rect.yMaximum()),
    ]


def transform_rect_to_wgs84(rect, source_crs, project):
    """Transform ``QgsRectangle`` from ``source_crs`` to EPSG:4326."""
    if rect is None or rect.isEmpty():
        return None
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if source_crs is None or not source_crs.isValid():
        return None
    if source_crs.authid() == "EPSG:4326":
        return QgsRectangle(rect)
    transform = QgsCoordinateTransform(source_crs, wgs84, project)
    if not transform.isValid():
        return None
    return transform.transformBoundingBox(rect)


def _layer_source_type(layer):
    ltype = getattr(layer, "type", None)
    if callable(ltype):
        val = ltype()
        name = getattr(val, "name", None)
        if name:
            return str(name).lower().replace("layer", "")
        val_str = str(val).lower()
        if "vector" in val_str or val == 0:
            return "vector"
        if "raster" in val_str or val == 1:
            return "raster"
        if "mesh" in val_str or val == 3:
            return "mesh"
        if "pointcloud" in val_str:
            return "pointcloud"
    return "other"


def _layer_entry(layer, visible, project):
    project_crs = project.crs()
    layer_crs = layer.crs() if callable(getattr(layer, "crs", None)) else None
    crs_authid = layer_crs.authid() if layer_crs is not None and layer_crs.isValid() else ""
    extent_rect = layer.extent() if callable(getattr(layer, "extent", None)) else None
    wgs84_rect = transform_rect_to_wgs84(extent_rect, layer_crs or project_crs, project)

    has_scale_vis = False
    min_scale = 0.0
    max_scale = 0.0
    if callable(getattr(layer, "hasScaleBasedVisibility", None)):
        has_scale_vis = bool(layer.hasScaleBasedVisibility())
        if has_scale_vis:
            min_scale = float(layer.minimumScale())
            max_scale = float(layer.maximumScale())

    labels_enabled = False
    if callable(getattr(layer, "labelsEnabled", None)):
        try:
            labels_enabled = bool(layer.labelsEnabled())
        except Exception:
            labels_enabled = False

    selected_count = 0
    if callable(getattr(layer, "selectedFeatureCount", None)):
        try:
            selected_count = int(layer.selectedFeatureCount())
        except Exception:
            selected_count = 0

    is_modified = False
    if callable(getattr(layer, "isModified", None)):
        try:
            is_modified = bool(layer.isModified())
        except Exception:
            is_modified = False

    online = is_online_layer(layer)
    policy = classify_layer_policy(layer)
    sensitivity = layer_sensitivity(layer)

    if policy == "blocked_sensitive":
        extent_payload = {
            "bounds_wgs84": None,
            "bounds_layer_crs": None,
            "redacted": True,
        }
        selected_out = 0
    else:
        extent_payload = {
            "bounds_wgs84": _rect_to_list(wgs84_rect),
            "bounds_layer_crs": _rect_to_list(extent_rect),
        }
        selected_out = selected_count

    return {
        "id": layer.id(),
        "name": layer.name(),
        "visible": bool(visible),
        "source_type": _layer_source_type(layer),
        "provider": str(layer.providerType() or ""),
        "source_uri_redacted": redact_uri(layer_source_uri(layer)),
        "crs": crs_authid,
        "extent": extent_payload,
        "scale_visibility": {
            "enabled": has_scale_vis,
            "min_scale": min_scale,
            "max_scale": max_scale,
        },
        "labels_enabled": labels_enabled,
        "online": online,
        "attribution": layer_attribution(layer),
        "sensitivity": sensitivity,
        "export_policy": policy,
        "selected_count": selected_out,
        "is_modified": is_modified,
    }


def _smp_capabilities():
    supported = []
    for fmt in (
        SMPGenerator.TILE_FORMAT_PNG,
        SMPGenerator.TILE_FORMAT_JPG,
        SMPGenerator.TILE_FORMAT_WEBP,
    ):
        if SMPGenerator.is_tile_format_supported(fmt):
            supported.append(fmt)
    can_render = len(supported) > 0
    reason = None if can_render else "No supported Qt image encoder (PNG/JPG/WEBP) is available."
    return {
        "formats": supported,
        "can_render": can_render,
        "reason": reason,
        "vendor_commit": VENDOR_COMMIT,
    }


def inspect_map(iface=None, include_hidden=False):
    """Inspect the active QGIS project and map canvas without mutating state."""
    project = QgsProject.instance()
    warnings = []

    title = project.title() if callable(getattr(project, "title", None)) else ""
    base_name = project.baseName() if callable(getattr(project, "baseName", None)) else ""
    project_name = (title or "").strip() or (base_name or "").strip() or "Untitled Project"

    project_crs_obj = project.crs()
    project_crs = project_crs_obj.authid() if project_crs_obj is not None and project_crs_obj.isValid() else ""
    if not project_crs:
        warnings.append("Project CRS is unset or invalid; set a valid CRS before exporting.")

    visible_layers_objs = visible_layers_in_render_order(project)
    visible_ids = {layer.id() for layer in visible_layers_objs}
    visible_layers = [_layer_entry(layer, True, project) for layer in visible_layers_objs]

    hidden_layers = []
    if include_hidden:
        for layer in project.mapLayers().values():
            if layer is not None and layer.id() not in visible_ids:
                hidden_layers.append(_layer_entry(layer, False, project))

    # Canvas extent with graceful headless fallback to union of visible layers.
    canvas_extent_info = {
        "crs": project_crs,
        "bounds_project": None,
        "bounds_wgs84": None,
        "source": "none",
    }
    canvas = None
    if iface is not None and callable(getattr(iface, "mapCanvas", None)):
        try:
            canvas = iface.mapCanvas()
        except Exception:
            canvas = None

    if canvas is not None:
        try:
            cext = canvas.extent()
            if cext is not None and not cext.isEmpty():
                wgs84_cext = transform_rect_to_wgs84(cext, project_crs_obj, project)
                canvas_extent_info = {
                    "crs": project_crs,
                    "bounds_project": _rect_to_list(cext),
                    "bounds_wgs84": _rect_to_list(wgs84_cext),
                    "source": "canvas",
                }
        except Exception:
            pass

    if canvas_extent_info["bounds_wgs84"] is None and visible_layers:
        union_wgs84 = None
        for entry in visible_layers:
            if entry.get("export_policy") == "blocked_sensitive":
                continue
            b = entry["extent"]["bounds_wgs84"]
            if b is not None:
                r = QgsRectangle(*b)
                if union_wgs84 is None:
                    union_wgs84 = QgsRectangle(r)
                else:
                    union_wgs84.combineExtentWith(r)
        if union_wgs84 is not None and not union_wgs84.isEmpty():
            canvas_extent_info = {
                "crs": "EPSG:4326",
                "bounds_project": None,
                "bounds_wgs84": _rect_to_list(union_wgs84),
                "source": "layers_union",
            }
            if canvas is None:
                warnings.append("Map canvas unavailable (headless mode); extent derived from visible layers.")

    # Selected features extent across exportable vector layers (exclude blocked_sensitive).
    selected_layer_ids = []
    selection_union_wgs84 = None
    selected_feature_count = 0
    for layer in project.mapLayers().values():
        if layer is None or not callable(getattr(layer, "selectedFeatureCount", None)):
            continue
        if classify_layer_policy(layer) == "blocked_sensitive":
            continue
        try:
            scount = int(layer.selectedFeatureCount())
        except Exception:
            continue
        if scount <= 0:
            continue
        selected_layer_ids.append(layer.id())
        selected_feature_count += scount
        try:
            sbbox = layer.boundingBoxOfSelected()
            swgs = transform_rect_to_wgs84(sbbox, layer.crs(), project)
            if swgs is not None and not swgs.isEmpty():
                if selection_union_wgs84 is None:
                    selection_union_wgs84 = QgsRectangle(swgs)
                else:
                    selection_union_wgs84.combineExtentWith(swgs)
        except Exception:
            pass

    selection_extent = None
    if selected_layer_ids and selection_union_wgs84 is not None and not selection_union_wgs84.isEmpty():
        selection_extent = {
            "bounds_wgs84": _rect_to_list(selection_union_wgs84),
            "feature_count": selected_feature_count,
            "layer_ids": selected_layer_ids,
        }

    if not visible_layers:
        warnings.append("No visible layers found in the active QGIS project.")

    for entry in visible_layers:
        if entry["export_policy"] == "blocked_sensitive":
            warnings.append(
                f"Layer '{entry['name']}' is marked blocked_sensitive and will be refused from SMP export."
            )
        elif entry["export_policy"] == "restricted":
            warnings.append(
                f"Layer '{entry['name']}' is marked restricted and requires explicit exclusion or authorization."
            )
        elif entry["export_policy"] in ("warn_online", "warn_license"):
            warnings.append(
                f"Layer '{entry['name']}' is an online source ({entry['provider']}); verify offline/licensing terms."
            )

    active_layer_id = None
    if iface is not None and callable(getattr(iface, "activeLayer", None)):
        try:
            al = iface.activeLayer()
            if al is not None:
                active_layer_id = al.id()
        except Exception:
            active_layer_id = None

    result = {
        "ok": True,
        "project_name": project_name,
        "project_crs": project_crs,
        "canvas_extent": canvas_extent_info,
        "visible_layers": visible_layers,
        "selected_layer_ids": selected_layer_ids,
        "active_layer_id": active_layer_id,
        "selection_extent": selection_extent,
        "warnings": warnings,
        "qgis_version": Qgis.QGIS_VERSION,
        "smp_capabilities": _smp_capabilities(),
    }
    if include_hidden:
        result["hidden_layers"] = hidden_layers
    return result
