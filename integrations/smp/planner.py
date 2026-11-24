"""Region & zoom recommendation planner for CoMapeo SMP exports."""

from __future__ import annotations

import math

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
)

from .inspector import transform_rect_to_wgs84
from .policy import classify_layer_policy, visible_layers_in_render_order
from .vendor.comapeo_smp_generator import SMPGenerator, SourceConfigError

MAX_MERCATOR_LAT = 85.05112878
CLAMPED_MERCATOR_LAT = 85.0511
EQUATORIAL_M_PER_PX_Z0 = 156543.03392804097
DEFAULT_WORLD_MAX_ZOOM = 3
DEFAULT_TARGET_SIZE_MB = 500.0


def ground_resolution_m_per_px(zoom, center_lat_deg=0.0):
    """Return approximate Web Mercator ground resolution (meters/pixel) at ``zoom``."""
    cos_lat = max(0.05, abs(math.cos(math.radians(center_lat_deg))))
    return (EQUATORIAL_M_PER_PX_Z0 * cos_lat) / (2 ** zoom)


def _buffer_bounds_wgs84(bounds, buffer_km):
    """Expand a WGS84 [west, south, east, north] box by ``buffer_km``."""
    west, south, east, north = bounds
    if not buffer_km or buffer_km <= 0:
        return [west, south, east, north]
    center_lat = (south + north) / 2.0
    d_lat = buffer_km / 111.32
    cos_lat = max(0.05, math.cos(math.radians(center_lat)))
    d_lon = buffer_km / (111.32 * cos_lat)
    return [
        max(-180.0, west - d_lon),
        max(-CLAMPED_MERCATOR_LAT, south - d_lat),
        min(180.0, east + d_lon),
        min(CLAMPED_MERCATOR_LAT, north + d_lat),
    ]


def validate_and_normalize_wgs84_bounds(bounds, warnings=None, label="extent"):
    """Validate WGS84 [west, south, east, north], rejecting antimeridian/polar bounds.

    Clamps latitudes outside +/-85.05112878 with an explicit warning when part of
    the extent lies inside Web Mercator range.
    """
    if isinstance(bounds, dict):
        if all(k in bounds for k in ("west", "south", "east", "north")):
            bounds = [bounds["west"], bounds["south"], bounds["east"], bounds["north"]]
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError(f"Invalid {label}: expected 4 numbers [west, south, east, north].")
    try:
        west, south, east, north = (float(v) for v in bounds)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: coordinates must be numeric.") from exc

    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError(f"Invalid {label}: coordinates must be finite.")

    # Antimeridian check
    if west > east or west < -180.0 or east > 180.0:
        raise ValueError(
            f"Antimeridian crossing detected in {label} (west={west:.4f}, east={east:.4f}). "
            "CoMapeo SMP plans cannot span the 180° antimeridian in one rectangular box; "
            "split the export into separate Western and Eastern hemisphere SMP packages."
        )

    if south > north:
        raise ValueError(f"Invalid {label}: south ({south}) must not exceed north ({north}).")

    if south >= MAX_MERCATOR_LAT or north <= -MAX_MERCATOR_LAT:
        raise ValueError(
            f"Polar {label} (south={south:.4f}, north={north:.4f}) lies completely outside "
            f"Web Mercator limits (±{MAX_MERCATOR_LAT}°)."
        )

    if south < -MAX_MERCATOR_LAT or north > MAX_MERCATOR_LAT:
        orig_south, orig_north = south, north
        south = max(-CLAMPED_MERCATOR_LAT, south)
        north = min(CLAMPED_MERCATOR_LAT, north)
        if warnings is not None:
            warnings.append(
                f"{label.capitalize()} latitudes ({orig_south:.4f}..{orig_north:.4f}) exceed "
                f"Web Mercator limits (±{MAX_MERCATOR_LAT}°) and were clamped to "
                f"({south:.4f}..{north:.4f})."
            )

    return [west, south, east, north]


def wgs84_bounds_to_3857(bounds_wgs84, project=None):
    """Transform [west, south, east, north] EPSG:4326 to EPSG:3857 bounds."""
    project = project or QgsProject.instance()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    mercator = QgsCoordinateReferenceSystem("EPSG:3857")
    rect = QgsRectangle(
        bounds_wgs84[0],
        max(-CLAMPED_MERCATOR_LAT, bounds_wgs84[1]),
        bounds_wgs84[2],
        min(CLAMPED_MERCATOR_LAT, bounds_wgs84[3]),
    )
    transform = QgsCoordinateTransform(wgs84, mercator, project)
    if not transform.isValid():
        raise ValueError("Unable to construct EPSG:4326 -> EPSG:3857 coordinate transform.")
    mrect = transform.transformBoundingBox(rect)
    return [
        float(mrect.xMinimum()),
        float(mrect.yMinimum()),
        float(mrect.xMaximum()),
        float(mrect.yMaximum()),
    ]


def wgs84_bounds_to_project_rect(bounds_wgs84, project=None):
    """Transform WGS84 [w, s, e, n] into a ``QgsRectangle`` in ``project.crs()``."""
    project = project or QgsProject.instance()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    rect = QgsRectangle(*bounds_wgs84)
    project_crs = project.crs()
    if project_crs is None or not project_crs.isValid() or project_crs.authid() == "EPSG:4326":
        return rect
    transform = QgsCoordinateTransform(wgs84, project_crs, project)
    if not transform.isValid():
        raise ValueError(
            f"Cannot transform WGS84 bounds to project CRS '{project_crs.authid()}'."
        )
    return transform.transformBoundingBox(rect)


def _resolve_reference_bounds(ref, iface, project, warnings, label):
    """Resolve an area_reference or local_reference dict into (wgs84_bounds, provenance)."""
    if not isinstance(ref, dict):
        raise ValueError(f"Invalid {label}: expected a dict.")

    ref_type = str(ref.get("type") or "").strip().lower()
    if ref_type == "bounds":
        raw_bounds = ref.get("bounds")
        if not isinstance(raw_bounds, (list, tuple)) or len(raw_bounds) != 4:
            raise ValueError(f"{label} with type='bounds' requires 'bounds': [west, south, east, north].")
        crs_auth = ref.get("crs") or "EPSG:4326"
        if crs_auth.upper() != "EPSG:4326":
            src_crs = QgsCoordinateReferenceSystem(crs_auth)
            if not src_crs.isValid():
                raise ValueError(f"Invalid CRS '{crs_auth}' in {label}.")
            src_rect = QgsRectangle(*(float(v) for v in raw_bounds))
            wgs_rect = transform_rect_to_wgs84(src_rect, src_crs, project)
            if wgs_rect is None or wgs_rect.isEmpty():
                raise ValueError(f"Failed to transform {label} bounds from {crs_auth} to EPSG:4326.")
            raw_bounds = [
                wgs_rect.xMinimum(),
                wgs_rect.yMinimum(),
                wgs_rect.xMaximum(),
                wgs_rect.yMaximum(),
            ]
        return validate_and_normalize_wgs84_bounds(raw_bounds, warnings, label=label), f"explicit_bounds:{crs_auth}"

    if ref_type == "br_resolved_area":
        if ref.get("bounds") is not None:
            raw = validate_and_normalize_wgs84_bounds(ref["bounds"], warnings, label=label)
            name = ref.get("name") or ref.get("id") or "resolved_area"
            return raw, f"br_resolved_area:{name}"
        raise RuntimeError(
            "GISBR br_resolve_area integration is not available or no bounds were supplied; "
            "provide explicit WGS84 bounds or select a loaded QGIS layer/canvas."
        )

    if ref_type == "selection":
        target_id = ref.get("layer_id") or ref.get("id")
        layers = (
            [project.mapLayer(target_id)]
            if target_id
            else list(project.mapLayers().values())
        )
        union_rect = None
        count = 0
        for layer in layers:
            if layer is None or not callable(getattr(layer, "selectedFeatureCount", None)):
                continue
            if classify_layer_policy(layer) == "blocked_sensitive":
                if target_id:
                    raise PermissionError(
                        f"Layer '{layer.name()}' is marked blocked_sensitive and cannot be used to derive export bounds."
                    )
                continue
            sc = int(layer.selectedFeatureCount())
            if sc <= 0:
                continue
            count += sc
            sbbox = layer.boundingBoxOfSelected()
            wgs = transform_rect_to_wgs84(sbbox, layer.crs(), project)
            if wgs is not None and not wgs.isEmpty():
                if union_rect is None:
                    union_rect = QgsRectangle(wgs)
                else:
                    union_rect.combineExtentWith(wgs)
            elif wgs is not None and sbbox.width() == 0 and sbbox.height() == 0:
                # Point selection with 0-width bbox
                pt_rect = QgsRectangle(wgs.xMinimum(), wgs.yMinimum(), wgs.xMaximum(), wgs.yMaximum())
                if union_rect is None:
                    union_rect = pt_rect
                else:
                    union_rect.combineExtentWith(pt_rect)
        if union_rect is None or count == 0:
            raise ValueError(f"No selected features found for {label}.")
        raw = [union_rect.xMinimum(), union_rect.yMinimum(), union_rect.xMaximum(), union_rect.yMaximum()]
        return validate_and_normalize_wgs84_bounds(raw, warnings, label=label), f"selection:{count}_features"

    if ref_type == "layer":
        target_id = ref.get("layer_id") or ref.get("id")
        layer = project.mapLayer(target_id) if target_id else None
        if layer is None and ref.get("name"):
            matches = project.mapLayersByName(ref["name"])
            layer = matches[0] if matches else None
        if layer is None:
            raise ValueError(f"Layer not found for {label}: {target_id or ref.get('name')}")
        if classify_layer_policy(layer) == "blocked_sensitive":
            raise PermissionError(
                f"Layer '{layer.name()}' is marked blocked_sensitive and cannot be used to derive export bounds."
            )
        wgs = transform_rect_to_wgs84(layer.extent(), layer.crs() or project.crs(), project)
        if wgs is None:
            raise ValueError(f"Unable to compute WGS84 extent for layer '{layer.name()}'.")
        raw = [wgs.xMinimum(), wgs.yMinimum(), wgs.xMaximum(), wgs.yMaximum()]
        return validate_and_normalize_wgs84_bounds(raw, warnings, label=label), f"layer:{layer.name()}"

    if ref_type == "canvas":
        if iface is not None and callable(getattr(iface, "mapCanvas", None)):
            canvas = iface.mapCanvas()
            if canvas is not None:
                cext = canvas.extent()
                if cext is not None and not cext.isEmpty():
                    wgs = transform_rect_to_wgs84(cext, project.crs(), project)
                    if wgs is not None and not wgs.isEmpty():
                        raw = [wgs.xMinimum(), wgs.yMinimum(), wgs.xMaximum(), wgs.yMaximum()]
                        return validate_and_normalize_wgs84_bounds(raw, warnings, label=label), "canvas"
        raise ValueError(f"Map canvas extent is unavailable for {label} (headless or empty canvas).")

    raise ValueError(
        f"Unsupported reference type '{ref_type}' in {label}. "
        "Use 'canvas', 'layer', 'selection', 'bounds', or 'br_resolved_area'."
    )


def _auto_detect_region_and_local(iface, project, warnings):
    """Choose sensible default Region and Local bounds from current project state."""
    visible_layers = [
        l for l in visible_layers_in_render_order(project)
        if classify_layer_policy(l) != "blocked_sensitive"
    ]
    if not visible_layers:
        raise ValueError("No exportable visible layers in project to derive region bounds.")

    # Compute visible layers union in WGS84.
    layers_union = None
    for layer in visible_layers:
        wgs = transform_rect_to_wgs84(layer.extent(), layer.crs() or project.crs(), project)
        if wgs is not None:
            if layers_union is None:
                layers_union = QgsRectangle(wgs)
            else:
                layers_union.combineExtentWith(wgs)

    # Check if features are selected -> Local = selection, Region = layers union or canvas
    sel_union = None
    sel_count = 0
    for layer in visible_layers:
        if callable(getattr(layer, "selectedFeatureCount", None)):
            sc = int(layer.selectedFeatureCount())
            if sc > 0:
                sel_count += sc
                wgs = transform_rect_to_wgs84(layer.boundingBoxOfSelected(), layer.crs(), project)
                if wgs is not None:
                    if sel_union is None:
                        sel_union = QgsRectangle(wgs)
                    else:
                        sel_union.combineExtentWith(wgs)

    canvas_wgs = None
    if iface is not None and callable(getattr(iface, "mapCanvas", None)):
        canvas = iface.mapCanvas()
        if canvas is not None and canvas.extent() is not None and not canvas.extent().isEmpty():
            canvas_wgs = transform_rect_to_wgs84(canvas.extent(), project.crs(), project)

    if sel_union is not None and sel_count > 0:
        local_bounds = validate_and_normalize_wgs84_bounds(
            [sel_union.xMinimum(), sel_union.yMinimum(), sel_union.xMaximum(), sel_union.yMaximum()],
            warnings,
            label="local",
        )
        local_prov = f"selection:{sel_count}_features"
        if canvas_wgs is not None and not canvas_wgs.isEmpty():
            region_bounds = validate_and_normalize_wgs84_bounds(
                [canvas_wgs.xMinimum(), canvas_wgs.yMinimum(), canvas_wgs.xMaximum(), canvas_wgs.yMaximum()],
                warnings,
                label="region",
            )
            region_prov = "canvas"
        elif layers_union is not None:
            region_bounds = validate_and_normalize_wgs84_bounds(
                [layers_union.xMinimum(), layers_union.yMinimum(), layers_union.xMaximum(), layers_union.yMaximum()],
                warnings,
                label="region",
            )
            region_prov = "visible_layers_union"
        else:
            region_bounds = None
            region_prov = None
        return local_bounds, local_prov, region_bounds, region_prov

    if canvas_wgs is not None and not canvas_wgs.isEmpty():
        local_bounds = validate_and_normalize_wgs84_bounds(
            [canvas_wgs.xMinimum(), canvas_wgs.yMinimum(), canvas_wgs.xMaximum(), canvas_wgs.yMaximum()],
            warnings,
            label="local",
        )
        local_prov = "canvas"
        region_bounds = None
        region_prov = None
        if layers_union is not None:
            lu = validate_and_normalize_wgs84_bounds(
                [layers_union.xMinimum(), layers_union.yMinimum(), layers_union.xMaximum(), layers_union.yMaximum()],
                warnings,
                label="region",
            )
            # Only offer Region if layers union is noticeably larger than canvas
            if (lu[2] - lu[0]) > (local_bounds[2] - local_bounds[0]) * 1.25 or (lu[3] - lu[1]) > (local_bounds[3] - local_bounds[1]) * 1.25:
                region_bounds = lu
                region_prov = "visible_layers_union"
        return local_bounds, local_prov, region_bounds, region_prov

    if layers_union is not None:
        local_bounds = validate_and_normalize_wgs84_bounds(
            [layers_union.xMinimum(), layers_union.yMinimum(), layers_union.xMaximum(), layers_union.yMaximum()],
            warnings,
            label="local",
        )
        return local_bounds, "visible_layers_union", None, None

    raise ValueError("Unable to derive non-empty bounds from project layers or canvas.")


def _choose_base_zooms(local_bounds, region_bounds, include_world, world_max_zoom):
    """Choose scale-appropriate initial zoom bands from extent spans."""
    lon_span = max(1e-5, local_bounds[2] - local_bounds[0])
    lat_span = max(1e-5, local_bounds[3] - local_bounds[1])
    max_span = max(lon_span, lat_span)

    # Target roughly ~2-6 tiles across at local_min_zoom, up to +4..+6 zooms for detail
    if max_span >= 5.0:
        local_min, local_max = 7, 11
    elif max_span >= 1.0:
        local_min, local_max = 9, 13
    elif max_span >= 0.2:
        local_min, local_max = 11, 15
    else:
        local_min, local_max = 12, 16

    if region_bounds is not None:
        reg_span = max(1e-5, region_bounds[2] - region_bounds[0], region_bounds[3] - region_bounds[1])
        if reg_span >= 5.0:
            reg_min, reg_max = 4, 7
        elif reg_span >= 1.0:
            reg_min, reg_max = 5, 9
        else:
            reg_min, reg_max = 7, 10
        if include_world and reg_min <= world_max_zoom:
            reg_min = world_max_zoom + 1
        reg_max = max(reg_min, min(reg_max, local_min - 1))
        if reg_max >= local_min:
            local_min = reg_max + 1
            local_max = max(local_min, local_max)
    else:
        reg_min, reg_max = None, None
        if include_world and local_min <= world_max_zoom:
            local_min = world_max_zoom + 1
            local_max = max(local_min, local_max)

    return local_min, local_max, reg_min, reg_max


def _enforce_zoom_order(
    include_world, world_max_zoom, include_region, region_min_zoom, region_max_zoom, local_min_zoom, local_max_zoom
):
    """Validate strict fixed-slot zoom ordering without silent overlaps."""
    if not (0 <= local_min_zoom <= local_max_zoom <= 24):
        raise ValueError(f"Invalid Local zoom range {local_min_zoom}..{local_max_zoom}.")
    if include_world:
        if not (0 <= world_max_zoom <= 24):
            raise ValueError(f"Invalid World max zoom {world_max_zoom}.")
    if include_region:
        if region_min_zoom is None or region_max_zoom is None:
            raise ValueError("Region min/max zoom required when Region is enabled.")
        if not (0 <= region_min_zoom <= region_max_zoom <= 24):
            raise ValueError(f"Invalid Region zoom range {region_min_zoom}..{region_max_zoom}.")
        if include_world and not (world_max_zoom < region_min_zoom):
            raise ValueError(
                f"World max zoom ({world_max_zoom}) must be < Region min zoom ({region_min_zoom})."
            )
        if not (region_max_zoom < local_min_zoom):
            raise ValueError(
                f"Region max zoom ({region_max_zoom}) must be < Local min zoom ({local_min_zoom})."
            )
    elif include_world and not (world_max_zoom < local_min_zoom):
        raise ValueError(
            f"World max zoom ({world_max_zoom}) must be < Local min zoom ({local_min_zoom})."
        )


def _pick_supported_format(preferred_format):
    supported = [
        fmt for fmt in ("PNG", "JPG", "WEBP")
        if SMPGenerator.is_tile_format_supported(fmt)
    ]
    if not supported:
        return "PNG"
    if preferred_format:
        cand = str(preferred_format).strip().upper()
        if cand in supported:
            return cand
    return "WEBP" if "WEBP" in supported else ("JPG" if "JPG" in supported else supported[0])


def suggest_regions(
    iface=None,
    area_reference=None,
    local_reference=None,
    region_buffer_km=2.0,
    local_buffer_km=0.5,
    include_world=False,
    world_max_zoom=DEFAULT_WORLD_MAX_ZOOM,
    constraints=None,
):
    """Suggest 2-3 practical World/Region/Local SMP candidates from project geometry."""
    constraints = dict(constraints or {})
    project = QgsProject.instance()
    warnings = []

    if project.crs() is None or not project.crs().isValid():
        return {
            "ok": False,
            "error_code": "invalid_project_crs",
            "error": "Active QGIS project has an invalid or unset CRS. Set a valid CRS first.",
        }

    try:
        if area_reference is None and local_reference is None:
            local_bounds, local_prov, region_bounds, region_prov = _auto_detect_region_and_local(
                iface, project, warnings
            )
        elif local_reference is not None and area_reference is not None:
            region_bounds, region_prov = _resolve_reference_bounds(
                area_reference, iface, project, warnings, label="region"
            )
            local_bounds, local_prov = _resolve_reference_bounds(
                local_reference, iface, project, warnings, label="local"
            )
        elif local_reference is not None:
            local_bounds, local_prov = _resolve_reference_bounds(
                local_reference, iface, project, warnings, label="local"
            )
            region_bounds, region_prov = None, None
        else:
            area_bounds, area_prov = _resolve_reference_bounds(
                area_reference, iface, project, warnings, label="area"
            )
            local_bounds, local_prov = area_bounds, area_prov
            region_bounds, region_prov = None, None
    except PermissionError as exc:
        return {"ok": False, "error_code": "blocked_sensitive_layer", "error": str(exc)}
    except RuntimeError as exc:
        return {"ok": False, "error_code": "gisbr_unavailable", "error": str(exc)}
    except ValueError as exc:
        msg = str(exc)
        code = "antimeridian_crossing" if "Antimeridian" in msg else (
            "polar_extent_unsupported" if "Polar" in msg else "invalid_reference"
        )
        return {"ok": False, "error_code": code, "error": msg}

    # Ensure point/line degenerate Local boxes get a small buffer so tiles can be selected.
    if local_bounds[0] == local_bounds[2] or local_bounds[1] == local_bounds[3]:
        buf = max(0.25, float(local_buffer_km or 0.5))
        local_bounds = _buffer_bounds_wgs84(local_bounds, buf)
        warnings.append(f"Point/linear Local extent buffered by {buf} km to form a valid tile box.")
    elif local_buffer_km and local_reference is not None and local_reference.get("type") == "selection":
        local_bounds = _buffer_bounds_wgs84(local_bounds, float(local_buffer_km))

    include_region_pref = constraints.get("include_region")
    if region_bounds is None and include_region_pref is True:
        buf = max(1.0, float(region_buffer_km or 2.0))
        region_bounds = _buffer_bounds_wgs84(local_bounds, buf)
        region_prov = f"local_buffered_{buf}km"
    elif region_bounds is not None and region_buffer_km and area_reference is not None and area_reference.get("type") != "bounds":
        region_bounds = _buffer_bounds_wgs84(region_bounds, float(region_buffer_km))

    if include_region_pref is False:
        region_bounds = None
        region_prov = None

    # Enforce Region containment of Local.
    if region_bounds is not None:
        if not SMPGenerator._extent_contains_bounds(region_bounds, local_bounds):
            if area_reference is not None and area_reference.get("type") == "bounds" and local_reference is not None and local_reference.get("type") == "bounds":
                return {
                    "ok": False,
                    "error_code": "region_containment",
                    "error": (
                        "Region bounds must fully contain Local bounds. Expand Region or shrink Local."
                    ),
                }
            # Expand Region to contain Local when derived from layers/canvas + selection
            region_bounds = [
                min(region_bounds[0], local_bounds[0]),
                min(region_bounds[1], local_bounds[1]),
                max(region_bounds[2], local_bounds[2]),
                max(region_bounds[3], local_bounds[3]),
            ]
            warnings.append("Region extent was expanded to fully contain the Local focus extent.")

    target_size_mb = constraints.get("target_size_mb")
    target_bytes = float(target_size_mb) * 1024 * 1024 if target_size_mb else None
    preferred_format = _pick_supported_format(constraints.get("preferred_format"))
    world_max = int(world_max_zoom if world_max_zoom is not None else DEFAULT_WORLD_MAX_ZOOM)

    gen = SMPGenerator()
    local_rect_proj = wgs84_bounds_to_project_rect(local_bounds, project)
    region_rect_proj = wgs84_bounds_to_project_rect(region_bounds, project) if region_bounds else None
    local_3857 = wgs84_bounds_to_3857(local_bounds, project)
    region_3857 = wgs84_bounds_to_3857(region_bounds, project) if region_bounds else None
    center_lat = (local_bounds[1] + local_bounds[3]) / 2.0

    base_lmin, base_lmax, base_rmin, base_rmax = _choose_base_zooms(
        local_bounds, region_bounds, bool(include_world), world_max
    )

    variants = [
        ("Compact", -2, -1, preferred_format if preferred_format != "PNG" else _pick_supported_format("JPG"), 75,
         "Smallest download/device footprint; lower maximum detail."),
        ("Balanced", 0, 0, preferred_format, 85,
         "Recommended tradeoff between field readability and package size."),
        ("Detailed", 0, 1, "PNG" if SMPGenerator.is_tile_format_supported("PNG") else preferred_format, 90,
         "Sharpest labels/linework and highest zoom detail; larger archive."),
    ]

    candidates = []
    for name, max_delta, reg_delta, fmt, quality, reason in variants:
        l_min = base_lmin
        l_max = max(l_min, min(20, base_lmax + max_delta))
        has_reg = region_bounds is not None
        r_min = base_rmin
        r_max = max(r_min, min(l_min - 1, base_rmax + reg_delta)) if has_reg else None

        # Step down max zooms if target_size_mb is specified and rough estimate exceeds budget
        export_plan = None
        rough_bytes = 0
        while True:
            try:
                _enforce_zoom_order(
                    bool(include_world), world_max, has_reg, r_min, r_max, l_min, l_max
                )
                export_plan = gen._build_export_plan(
                    local_rect_proj,
                    l_min,
                    l_max,
                    include_world_base_zooms=bool(include_world),
                    world_max_zoom=world_max,
                    include_region=has_reg,
                    region_extent=region_rect_proj,
                    region_min_zoom=r_min,
                    region_max_zoom=r_max,
                )
            except (SourceConfigError, ValueError):
                break
            rough_bytes = gen.estimate_tile_storage_bytes(export_plan["total_tiles"], fmt)
            if target_bytes is None or rough_bytes <= target_bytes:
                break
            if l_max > l_min:
                l_max -= 1
            elif has_reg and r_max is not None and r_max > r_min:
                r_max -= 1
            elif l_min > (r_max + 1 if has_reg else (world_max + 1 if include_world else 0)):
                l_min -= 1
                l_max = min(l_max, l_min)
            else:
                break

        if export_plan is None:
            continue

        # Extract exact per-source tile counts from _build_export_plan
        counts = {"world": 0, "region": 0, "local": 0, "total": export_plan["total_tiles"]}
        for sp in export_plan["sources"]:
            role = sp.get("source_role")
            if role in counts:
                counts[role] = sp["total_tiles"]

        effective_local_zooms = export_plan["sources"][-1]["export_zooms"]
        eff_lmin, eff_lmax = effective_local_zooms[0], effective_local_zooms[-1]

        fits_budget = True if target_bytes is None else (rough_bytes <= target_bytes)
        note = "Uncalibrated rough size range (fixed per-tile heuristic). Run smp_estimate with sample=True for calibrated size and duration."
        if not fits_budget:
            note = (
                f"Rough estimate (~{rough_bytes / (1024 * 1024):.1f} MB) exceeds target budget "
                f"({target_size_mb} MB) even at reduced zoom; shrink extent or raise budget."
            )

        candidates.append({
            "name": name,
            "reason": reason,
            "include_world": bool(include_world),
            "include_region": has_reg,
            "coverage": {
                "world": {
                    "bounds_wgs84": [-180.0, -CLAMPED_MERCATOR_LAT, 180.0, CLAMPED_MERCATOR_LAT],
                    "zooms": [0, world_max],
                } if include_world else None,
                "region": {
                    "bounds_wgs84": region_bounds,
                    "bounds_3857": region_3857,
                    "provenance": region_prov,
                    "zooms": [r_min, r_max],
                } if has_reg else None,
                "local": {
                    "bounds_wgs84": local_bounds,
                    "bounds_3857": local_3857,
                    "provenance": local_prov,
                    "zooms": [eff_lmin, eff_lmax],
                    "ground_resolution_m_per_px": {
                        "min_zoom": round(ground_resolution_m_per_px(eff_lmin, center_lat), 2),
                        "max_zoom": round(ground_resolution_m_per_px(eff_lmax, center_lat), 2),
                    },
                },
            },
            "recommended_zooms": {
                "world_max_zoom": world_max if include_world else None,
                "region_min_zoom": r_min if has_reg else None,
                "region_max_zoom": r_max if has_reg else None,
                "local_min_zoom": eff_lmin,
                "local_max_zoom": eff_lmax,
            },
            "format": fmt,
            "quality": quality,
            "exact_tile_counts": counts,
            "provisional_estimate": {
                "calibration": "uncalibrated_rough",
                "estimated_bytes_range": {
                    "low": int(rough_bytes * 0.4),
                    "likely": int(rough_bytes),
                    "high": int(rough_bytes * 2.2),
                },
                "fits_budget": fits_budget,
                "note": note,
            },
        })

    return {
        "ok": True,
        "candidates": candidates,
        "selection_requirements": {
            "rectangular_xyz_note": "SMP uses rectangular EPSG:3857 XYZ bounding boxes per slot (World, Region, Local).",
            "zoom_rule": "world_max < region_min <= region_max < local_min <= local_max",
        },
        "warnings": warnings,
    }
