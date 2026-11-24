"""Deterministic SMP export planner, immutable plan registry, and calibrated estimator."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
import time

from qgis.core import QgsProject

from .planner import (
    CLAMPED_MERCATOR_LAT,
    validate_and_normalize_wgs84_bounds,
    wgs84_bounds_to_3857,
    wgs84_bounds_to_project_rect,
)
from .policy import (
    VENDOR_COMMIT,
    classify_layer_policy,
    compute_project_fingerprint,
    is_online_layer,
    layer_attribution,
    renderer_source_sha256,
    visible_layers_in_render_order,
)
from .vendor.comapeo_smp_generator import SMPGenerator, SourceConfigError

MAX_PLANS = 128
PLAN_TTL_SECONDS = 3600.0
ZIP32_MAX_ENTRIES = 65533
DEFAULT_MAX_EXPORT_TILES = 250_000
DEFAULT_SCRATCH_RESERVE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class ImmutableExportPlan:
    """Immutable normalized SMP export plan stored server-side."""

    plan_id: str
    created_at: float
    project_fingerprint: str
    cache_safe: bool
    renderer_sha256: str
    effective_config: dict
    effective_layer_ids: tuple
    effective_layer_meta: tuple
    export_plan: dict
    remote_layer_warnings: tuple
    privacy_licensing_warnings: tuple
    has_restricted_layers: bool
    estimated_likely_bytes: int = 0
    estimated_high_bytes: int = 0
    scratch_disk_bytes: int = 0


class PlanRegistry:
    """Bounded in-memory registry of immutable export plans."""

    def __init__(self, max_plans=MAX_PLANS, ttl_seconds=PLAN_TTL_SECONDS):
        self._lock = threading.Lock()
        self._plans = OrderedDict()
        self._max_plans = max_plans
        self._ttl_seconds = ttl_seconds
        self._secret_salt = os.urandom(16).hex()

    def make_plan_id(self, canonical_payload):
        raw = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(f"{self._secret_salt}:{raw}".encode("utf-8")).hexdigest()
        return f"smp_{digest[:24]}"

    def store(self, plan):
        with self._lock:
            self._prune_expired_locked()
            self._plans[plan.plan_id] = plan
            self._plans.move_to_end(plan.plan_id)
            while len(self._plans) > self._max_plans:
                self._plans.popitem(last=False)

    def get(self, plan_id):
        with self._lock:
            self._prune_expired_locked()
            return self._plans.get(plan_id)

    def clear(self):
        with self._lock:
            self._plans.clear()

    def _prune_expired_locked(self):
        now = time.monotonic()
        expired = [
            pid for pid, p in self._plans.items()
            if (now - p.created_at) > self._ttl_seconds
        ]
        for pid in expired:
            self._plans.pop(pid, None)


_DEFAULT_PLAN_REGISTRY = PlanRegistry()


def get_plan_registry():
    return _DEFAULT_PLAN_REGISTRY


def _nearest_existing_dir(path):
    cur = os.path.abspath(path)
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return cur or tempfile.gettempdir()


def _resolve_approved_layers(project, requested_layer_ids):
    """Resolve ordered render layers and enforce blocked_sensitive exclusion."""
    visible_ordered = visible_layers_in_render_order(project)
    visible_by_id = {l.id(): l for l in visible_ordered}
    all_by_id = {lid: l for lid, l in project.mapLayers().items() if l is not None}

    excluded = []
    effective = []
    if requested_layer_ids is not None:
        if not isinstance(requested_layer_ids, list) or not requested_layer_ids:
            raise ValueError("layer_ids must be a non-empty list of layer IDs when provided.")
        for lid in requested_layer_ids:
            layer = all_by_id.get(lid)
            if layer is None:
                raise ValueError(f"Requested layer_id not found in project: {lid}")
            pol = classify_layer_policy(layer)
            if pol == "blocked_sensitive":
                raise PermissionError(
                    f"Layer '{layer.name()}' ({lid}) has export_policy='blocked_sensitive' "
                    "and cannot be included in an SMP export."
                )
            effective.append(layer)
    else:
        for layer in visible_ordered:
            pol = classify_layer_policy(layer)
            if pol == "blocked_sensitive":
                excluded.append({
                    "id": layer.id(),
                    "name": layer.name(),
                    "reason": "blocked_sensitive",
                })
                continue
            effective.append(layer)

    if not effective:
        raise ValueError(
            "No exportable layers remain after excluding blocked_sensitive or hidden layers."
        )
    return effective, excluded


def _select_stratified_sample(tiles_by_zoom, max_samples):
    """Pick up to ``max_samples`` stratified tiles across sources, zooms, and positions."""
    if max_samples <= 0 or not tiles_by_zoom:
        return []

    # Enumerate candidate strata: center, corners, edge midpoints, plus grid stride
    candidates_per_band = []
    for zoom, min_x, max_x, min_y, max_y, _, source_index in tiles_by_zoom:
        mid_x = (min_x + max_x) // 2
        mid_y = (min_y + max_y) // 2
        picks = [
            (zoom, mid_x, mid_y, source_index),
            (zoom, min_x, min_y, source_index),
            (zoom, max_x, max_y, source_index),
            (zoom, min_x, max_y, source_index),
            (zoom, max_x, min_y, source_index),
            (zoom, mid_x, min_y, source_index),
            (zoom, mid_x, max_y, source_index),
            (zoom, min_x, mid_y, source_index),
            (zoom, max_x, mid_y, source_index),
        ]
        # Add bounded interior grid points if needed for larger sample budgets
        span_x = max_x - min_x + 1
        span_y = max_y - min_y + 1
        if span_x * span_y > 9:
            step_x = max(1, span_x // 4)
            step_y = max(1, span_y // 4)
            for gx in range(min_x, max_x + 1, step_x):
                for gy in range(min_y, max_y + 1, step_y):
                    picks.append((zoom, gx, gy, source_index))
                    if len(picks) >= max_samples * 2:
                        break
                if len(picks) >= max_samples * 2:
                    break
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for item in picks:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        candidates_per_band.append(deduped)

    # Round-robin across zoom bands so every zoom/source is represented
    selected = []
    selected_set = set()
    idx = 0
    while len(selected) < max_samples:
        progressed = False
        for band in candidates_per_band:
            if idx < len(band):
                item = band[idx]
                if item not in selected_set:
                    selected.append(item)
                    selected_set.add(item)
                    progressed = True
                    if len(selected) >= max_samples:
                        break
        if not progressed:
            break
        idx += 1
    return selected


def _is_tile_blank(tile_path):
    """Return True if a rendered tile image has zero color variance (single solid/transparent color)."""
    try:
        from PIL import Image
        with Image.open(tile_path) as im:
            extrema = im.getextrema()
            if isinstance(extrema[0], tuple):
                return all(lo == hi for lo, hi in extrema)
            return extrema[0] == extrema[1]
    except Exception:
        return False


def _run_tile_sample(gen, render_layers, tiles_by_zoom, tile_format, quality, sample_size):
    """Render a small stratified sample of tiles to calibrate size and render duration."""
    from qgis.PyQt.QtCore import QSize
    from qgis.core import QgsCoordinateTransform, QgsMapSettings

    project = QgsProject.instance()
    web_mercator = gen._web_mercator_crs
    tx = QgsCoordinateTransform(project.crs(), web_mercator, project)
    if not tx.isValid():
        raise ValueError(f"Cannot reproject project CRS '{project.crs().authid()}' to EPSG:3857.")

    ms = QgsMapSettings()
    ms.setDestinationCrs(web_mercator)
    ms.setLayers(render_layers)
    ms.setOutputSize(QSize(256, 256))

    picks = _select_stratified_sample(tiles_by_zoom, sample_size)
    if not picks:
        return None

    sizes = []
    durations_ms = []
    blank_count = 0
    tmp_dir = tempfile.mkdtemp(prefix="awanagis_smp_sample_")
    try:
        t0_all = time.perf_counter()
        for zoom, x, y, source_index in picks:
            t0 = time.perf_counter()
            gen._render_single_tile(
                ms, zoom, x, y, tmp_dir,
                tile_format=tile_format,
                jpeg_quality=quality,
                resume=False,
                source_index=source_index,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            durations_ms.append(dt_ms)
            ext = gen._tile_extension(tile_format)
            tile_path = os.path.join(tmp_dir, str(source_index), str(zoom), str(x), f"{y}.{ext}")
            sizes.append(os.path.getsize(tile_path))
            if _is_tile_blank(tile_path):
                blank_count += 1
        total_sample_ms = (time.perf_counter() - t0_all) * 1000.0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    sizes_sorted = sorted(sizes)
    durs_sorted = sorted(durations_ms)
    n = len(sizes)
    mean_bytes = sum(sizes) / n
    mean_ms = sum(durations_ms) / n
    p10_b = sizes_sorted[max(0, int(0.1 * (n - 1)))]
    p90_b = sizes_sorted[min(n - 1, math.ceil(0.9 * (n - 1)))]
    p10_ms = durs_sorted[max(0, int(0.1 * (n - 1)))]
    p90_ms = durs_sorted[min(n - 1, math.ceil(0.9 * (n - 1)))]

    # Standard error / spread for honest low/likely/high bounds
    low_b = max(64, int(min(p10_b, mean_bytes * 0.7)))
    likely_b = int(mean_bytes)
    high_b = max(likely_b, int(max(p90_b, mean_bytes * 1.35)))

    low_ms = max(0.5, min(p10_ms, mean_ms * 0.75))
    likely_ms = mean_ms
    high_ms = max(likely_ms, max(p90_ms, mean_ms * 1.45))

    return {
        "count": n,
        "min_bytes": sizes_sorted[0],
        "mean_bytes": round(mean_bytes, 1),
        "max_bytes": sizes_sorted[-1],
        "low_bytes_per_tile": low_b,
        "likely_bytes_per_tile": likely_b,
        "high_bytes_per_tile": high_b,
        "mean_ms": round(mean_ms, 2),
        "low_ms_per_tile": round(low_ms, 2),
        "likely_ms_per_tile": round(likely_ms, 2),
        "high_ms_per_tile": round(high_ms, 2),
        "total_sample_ms": round(total_sample_ms, 1),
        "blank_tile_count": blank_count,
    }


def inspect_sampling_layers(layer_ids=None):
    """Return lists of restricted/online layers in the effective sampling set."""
    project = QgsProject.instance()
    try:
        render_layers, _ = _resolve_approved_layers(project, layer_ids)
    except Exception:
        return {"restricted_layers": [], "online_layers": []}
    restricted = []
    online = []
    for layer in render_layers:
        pol = classify_layer_policy(layer)
        if pol == "restricted":
            restricted.append({"id": layer.id(), "name": layer.name()})
        if is_online_layer(layer):
            online.append({"id": layer.id(), "name": layer.name(), "provider": str(layer.providerType() or "")})
    return {"restricted_layers": restricted, "online_layers": online}


def estimate_plan(
    local_bounds,
    local_min_zoom,
    local_max_zoom,
    include_world=False,
    world_max_zoom=3,
    include_region=False,
    region_bounds=None,
    region_min_zoom=None,
    region_max_zoom=None,
    tile_format="PNG",
    quality=85,
    output_dir=None,
    layer_ids=None,
    sample=False,
    sample_mode=None,
    sample_size=12,
    target_size_mb=None,
    allow_online_sampling=False,
    allow_restricted_sampling=False,
    _trusted_sampling_approved=False,
    sampling_approval_callback=None,
    registry=None,
):
    """Build an immutable export plan with exact XYZ tile counts and honest estimates."""
    registry = registry or _DEFAULT_PLAN_REGISTRY
    project = QgsProject.instance()
    warnings = []

    if project.crs() is None or not project.crs().isValid():
        return {
            "ok": False,
            "error_code": "invalid_project_crs",
            "error": "Active QGIS project has an invalid or unset CRS.",
        }

    # Normalize sample flag vs sample_mode
    use_sample = bool(sample)
    if sample_mode is not None:
        sm = str(sample_mode).strip().lower()
        if sm == "small":
            use_sample = True
        elif sm == "none":
            use_sample = False
        else:
            return {
                "ok": False,
                "error_code": "invalid_sample_mode",
                "error": f"Invalid sample_mode '{sample_mode}'. Use 'none' or 'small'.",
            }
    clamped_sample_size = max(1, min(30, int(sample_size or 12)))

    try:
        fmt = SMPGenerator.validate_tile_format(tile_format)
    except ValueError as exc:
        return {"ok": False, "error_code": "unsupported_format", "error": str(exc)}

    quality = max(1, min(100, int(quality if quality is not None else 85)))

    try:
        local_wgs84 = validate_and_normalize_wgs84_bounds(local_bounds, warnings, label="local")
        region_wgs84 = (
            validate_and_normalize_wgs84_bounds(region_bounds, warnings, label="region")
            if include_region else None
        )
    except ValueError as exc:
        msg = str(exc)
        code = "antimeridian_crossing" if "Antimeridian" in msg else (
            "polar_extent_unsupported" if "Polar" in msg else "invalid_bounds"
        )
        return {"ok": False, "error_code": code, "error": msg}

    try:
        render_layers, excluded_layers = _resolve_approved_layers(project, layer_ids)
    except PermissionError as exc:
        return {"ok": False, "error_code": "blocked_sensitive_layer", "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error_code": "invalid_layers", "error": str(exc)}

    gen = SMPGenerator()
    try:
        local_rect_proj = wgs84_bounds_to_project_rect(local_wgs84, project)
        region_rect_proj = wgs84_bounds_to_project_rect(region_wgs84, project) if include_region else None
        export_plan = gen._build_export_plan(
            local_rect_proj,
            int(local_min_zoom),
            int(local_max_zoom),
            include_world_base_zooms=bool(include_world),
            world_max_zoom=int(world_max_zoom if world_max_zoom is not None else 3),
            include_region=bool(include_region),
            region_extent=region_rect_proj,
            region_min_zoom=int(region_min_zoom) if region_min_zoom is not None else None,
            region_max_zoom=int(region_max_zoom) if region_max_zoom is not None else None,
        )
    except SourceConfigError as exc:
        return {"ok": False, "error_code": exc.code, "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "error_code": "invalid_zoom_or_extent", "error": str(exc)}

    # Check if _build_export_plan auto-adjusted local_min_zoom
    effective_local_src = export_plan["sources"][-1]
    eff_lmin = effective_local_src["export_zooms"][0]
    eff_lmax = effective_local_src["export_zooms"][-1]
    auto_adjusted = eff_lmin != int(local_min_zoom)
    for w in export_plan.get("warnings", []) or []:
        warnings.append(w)

    counts = {"world": 0, "region": 0, "local": 0, "total": export_plan["total_tiles"]}
    by_zoom = {}
    for sp in export_plan["sources"]:
        role = sp.get("source_role")
        if role in counts:
            counts[role] = sp["total_tiles"]
    for zoom, _mx, _Mx, _my, _My, ntiles, _si in export_plan["tiles_by_zoom"]:
        by_zoom[str(zoom)] = by_zoom.get(str(zoom), 0) + ntiles
    counts["by_zoom"] = by_zoom

    # Policy & remote layer warnings
    remote_warnings = []
    privacy_warnings = []
    restricted_layers = []
    layer_meta = []
    for layer in render_layers:
        pol = classify_layer_policy(layer)
        attr = layer_attribution(layer)
        online = is_online_layer(layer)
        layer_meta.append({
            "id": layer.id(),
            "name": layer.name(),
            "provider": str(layer.providerType() or ""),
            "export_policy": pol,
            "online": online,
            "attribution": attr,
        })
        if online:
            remote_warnings.append(
                f"Layer '{layer.name()}' ({layer.providerType()}) fetches remote tiles; "
                "export duration and completeness depend on network/provider availability."
            )
        if pol == "warn_license":
            privacy_warnings.append(
                f"Layer '{layer.name()}' may carry third-party tile licensing restrictions"
                + (f" ({attr})" if attr else "") + ". Confirm you hold offline packaging rights."
            )
        elif pol == "restricted":
            restricted_layers.append({"id": layer.id(), "name": layer.name()})
            privacy_warnings.append(
                f"Layer '{layer.name()}' is marked restricted and requires explicit restricted-layer authorization."
            )
    if excluded_layers:
        privacy_warnings.append(
            f"Excluded {len(excluded_layers)} blocked_sensitive layer(s): "
            + ", ".join(e["name"] for e in excluded_layers)
        )

    total_tiles = counts["total"]
    sample_stats = None
    sampling_blocked_reason = None
    if use_sample:
        online_layers = [m for m in layer_meta if m["online"]]
        if restricted_layers:
            trusted_ok = bool(
                allow_restricted_sampling
                and (
                    _trusted_sampling_approved
                    or (
                        callable(sampling_approval_callback)
                        and sampling_approval_callback({
                            "kind": "restricted",
                            "layers": restricted_layers,
                            "sample_size": clamped_sample_size,
                        })
                    )
                )
            )
            if not trusted_ok:
                sampling_blocked_reason = "restricted_sampling_unapproved"
                warnings.append(
                    "Tile sampling skipped because restricted layers require explicit trusted user confirmation. "
                    "Falling back to uncalibrated rough estimation."
                )
        elif online_layers:
            trusted_ok = bool(
                allow_online_sampling
                and (
                    _trusted_sampling_approved
                    or (
                        callable(sampling_approval_callback)
                        and sampling_approval_callback({
                            "kind": "online",
                            "layers": online_layers,
                            "sample_size": clamped_sample_size,
                        })
                    )
                )
            )
            if not trusted_ok:
                sampling_blocked_reason = "online_sampling_unapproved"
                warnings.append(
                    "Tile sampling skipped because online/remote layers require explicit trusted user confirmation. "
                    "Falling back to uncalibrated rough estimation."
                )

        if sampling_blocked_reason is None:
            try:
                sample_stats = _run_tile_sample(
                    gen, render_layers, export_plan["tiles_by_zoom"], fmt, quality, clamped_sample_size
                )
            except Exception as exc:
                warnings.append(f"Tile sampling failed ({exc}); falling back to uncalibrated rough estimate.")
                sample_stats = None

    zip_overhead = 2048 + total_tiles * 96
    if sample_stats is not None:
        calibration = "sampled"
        est_bytes = {
            "low": int(sample_stats["low_bytes_per_tile"] * total_tiles + zip_overhead),
            "likely": int(sample_stats["likely_bytes_per_tile"] * total_tiles + zip_overhead),
            "high": int(sample_stats["high_bytes_per_tile"] * total_tiles + zip_overhead),
            "calibration": "sampled",
            "method": f"stratified_sample_n={sample_stats['count']}",
        }
        est_runtime = {
            "low": round((sample_stats["low_ms_per_tile"] * total_tiles) / 1000.0, 2),
            "likely": round((sample_stats["likely_ms_per_tile"] * total_tiles) / 1000.0, 2),
            "high": round((sample_stats["high_ms_per_tile"] * total_tiles) / 1000.0, 2),
            "calibration": "sampled",
            "method": f"observed_render_ms_n={sample_stats['count']}",
        }
        if sample_stats["blank_tile_count"] >= max(1, sample_stats["count"] // 2):
            warnings.append(
                f"{sample_stats['blank_tile_count']}/{sample_stats['count']} sampled tiles were blank/solid; "
                "verify layer visibility, scale-based visibility, and extent."
            )
    else:
        calibration = "uncalibrated_rough"
        rough_bytes = gen.estimate_tile_storage_bytes(total_tiles, fmt)
        est_bytes = {
            "low": int(rough_bytes * 0.35),
            "likely": int(rough_bytes),
            "high": int(rough_bytes * 2.5),
            "calibration": "uncalibrated_rough",
            "method": "fixed_bytes_per_tile_fallback",
        }
        est_runtime = {
            "low": None,
            "likely": None,
            "high": None,
            "calibration": "unknown",
            "method": "not_sampled",
            "note": "Runtime is unknown without sampling; pass sample=True to calibrate.",
        }

    # Scratch + archive disk check
    scratch_bytes = int(est_bytes["high"] * 1.15)
    target_check_dir = _nearest_existing_dir(output_dir or project.homePath() or tempfile.gettempdir())
    free_disk_bytes = shutil.disk_usage(target_check_dir).free
    disk_sufficient = free_disk_bytes >= (scratch_bytes + est_bytes["high"] + DEFAULT_SCRATCH_RESERVE_BYTES)
    if not disk_sufficient:
        warnings.append(
            f"Low disk space on '{target_check_dir}': {free_disk_bytes / (1024 * 1024):.1f} MB free."
        )

    if total_tiles > DEFAULT_MAX_EXPORT_TILES:
        warnings.append(
            f"Total tiles ({total_tiles:,}) exceed the maximum single-export limit "
            f"({DEFAULT_MAX_EXPORT_TILES:,}); shrink extent or lower zoom levels."
        )
    elif total_tiles > ZIP32_MAX_ENTRIES:
        warnings.append(
            f"Total tiles ({total_tiles:,}) exceed standard ZIP32 entry limit (65,533); "
            "ZIP64 extensions will be required and may not be supported by older mobile importers."
        )

    if target_size_mb is not None:
        cap_bytes = float(target_size_mb) * 1024 * 1024
        if est_bytes["likely"] > cap_bytes:
            warnings.append(
                f"Estimated likely size ({est_bytes['likely'] / (1024 * 1024):.1f} MB) exceeds "
                f"target budget ({target_size_mb} MB)."
            )

    proj_fp, cache_safe = compute_project_fingerprint(project, render_layers)
    renderer_sha = renderer_source_sha256()

    effective_config = {
        "include_world": bool(include_world),
        "world_max_zoom": int(world_max_zoom) if include_world else None,
        "world_bounds_wgs84": [-180.0, -CLAMPED_MERCATOR_LAT, 180.0, CLAMPED_MERCATOR_LAT] if include_world else None,
        "include_region": bool(include_region),
        "region_bounds_wgs84": region_wgs84,
        "region_bounds_3857": wgs84_bounds_to_3857(region_wgs84, project) if include_region else None,
        "region_min_zoom": int(region_min_zoom) if include_region else None,
        "region_max_zoom": int(region_max_zoom) if include_region else None,
        "local_bounds_wgs84": local_wgs84,
        "local_bounds_3857": wgs84_bounds_to_3857(local_wgs84, project),
        "local_min_zoom": eff_lmin,
        "local_max_zoom": eff_lmax,
        "tile_format": fmt,
        "quality": quality,
        "auto_adjusted": auto_adjusted,
    }

    canonical_payload = {
        "effective_config": effective_config,
        "layer_ids": [l.id() for l in render_layers],
        "policies": {m["id"]: m["export_policy"] for m in layer_meta},
        "project_fingerprint": proj_fp,
        "renderer_sha256": renderer_sha,
    }
    plan_id = registry.make_plan_id(canonical_payload)

    plan_obj = ImmutableExportPlan(
        plan_id=plan_id,
        created_at=time.monotonic(),
        project_fingerprint=proj_fp,
        cache_safe=cache_safe,
        renderer_sha256=renderer_sha,
        effective_config=effective_config,
        effective_layer_ids=tuple(l.id() for l in render_layers),
        effective_layer_meta=tuple(layer_meta),
        export_plan=export_plan,
        remote_layer_warnings=tuple(remote_warnings),
        privacy_licensing_warnings=tuple(privacy_warnings),
        has_restricted_layers=bool(restricted_layers),
        estimated_likely_bytes=int(est_bytes["likely"]),
        estimated_high_bytes=int(est_bytes["high"]),
        scratch_disk_bytes=int(scratch_bytes),
    )
    registry.store(plan_obj)

    return {
        "ok": True,
        "plan_id": plan_id,
        "project_fingerprint": proj_fp,
        "cache_safe": cache_safe,
        "calibration": calibration,
        "sampling_blocked_reason": sampling_blocked_reason,
        "sample_stats": sample_stats,
        "effective_config": effective_config,
        "effective_layers": layer_meta,
        "excluded_layers": excluded_layers,
        "restricted_layers": restricted_layers,
        "tile_counts": counts,
        "coverage_gaps": export_plan.get("gap_zooms", []),
        "world_pct": round(export_plan.get("world_pct", 0.0), 4),
        "estimated_archive_bytes": est_bytes,
        "estimated_runtime_seconds": est_runtime,
        "scratch_disk_bytes": scratch_bytes,
        "free_disk_bytes": free_disk_bytes,
        "disk_sufficient": disk_sufficient,
        "remote_layer_warnings": remote_warnings,
        "privacy_licensing_warnings": privacy_warnings,
        "warnings": warnings,
        "vendor_commit": VENDOR_COMMIT,
        "requires_confirmation": True,
    }
