"""Unified tool entrypoints and core/tools.py dispatch bridge for CoMapeo SMP."""

from .estimator import estimate_plan
from .exporter import get_export_manager
from .inspector import inspect_map
from .planner import suggest_regions
from .validator import validate_file


def smp_inspect_map(iface=None, include_hidden=False):
    return inspect_map(iface=iface, include_hidden=bool(include_hidden))


def smp_suggest_regions(
    iface=None,
    area_reference=None,
    local_reference=None,
    region_buffer_km=2.0,
    local_buffer_km=0.5,
    include_world=False,
    world_max_zoom=3,
    constraints=None,
):
    return suggest_regions(
        iface=iface,
        area_reference=area_reference,
        local_reference=local_reference,
        region_buffer_km=region_buffer_km,
        local_buffer_km=local_buffer_km,
        include_world=include_world,
        world_max_zoom=world_max_zoom,
        constraints=constraints,
    )


def smp_estimate(
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
):
    return estimate_plan(
        local_bounds=local_bounds,
        local_min_zoom=local_min_zoom,
        local_max_zoom=local_max_zoom,
        include_world=include_world,
        world_max_zoom=world_max_zoom,
        include_region=include_region,
        region_bounds=region_bounds,
        region_min_zoom=region_min_zoom,
        region_max_zoom=region_max_zoom,
        tile_format=tile_format,
        quality=quality,
        output_dir=output_dir,
        layer_ids=layer_ids,
        sample=sample,
        sample_mode=sample_mode,
        sample_size=sample_size,
        target_size_mb=target_size_mb,
    )


def smp_start_export(
    plan_id,
    output_path,
    approved=False,
    overwrite=False,
    approved_restricted_layers=False,
    confirm=None,
):
    return get_export_manager().start_export(
        plan_id=plan_id,
        output_path=output_path,
        approved=approved,
        overwrite=overwrite,
        approved_restricted_layers=approved_restricted_layers,
        confirm=confirm,
    )


def smp_export_status(job_id):
    return get_export_manager().export_status(job_id=job_id)


def smp_cancel_export(job_id):
    return get_export_manager().cancel_export(job_id=job_id)


def smp_validate_file(file_path, run_external=True):
    return validate_file(file_path=file_path, run_external=bool(run_external))


def cleanup_all():
    get_export_manager().cleanup_all()


_MAIN_THREAD_TOOLS = {
    "smp_inspect_map": lambda iface, args: smp_inspect_map(iface=iface, **args),
    "smp_suggest_regions": lambda iface, args: smp_suggest_regions(iface=iface, **args),
    "smp_estimate": lambda _iface, args: smp_estimate(**args),
    "smp_start_export": lambda _iface, args: smp_start_export(**args),
}

_THREADSAFE_TOOLS = {
    "smp_export_status": lambda args: smp_export_status(**args),
    "smp_cancel_export": lambda args: smp_cancel_export(**args),
    "smp_validate_file": lambda args: smp_validate_file(**args),
}


def dispatch_smp_tool(toolkit, executor, name, args):
    """Dispatch an ``smp_*`` tool safely across main thread or background callers."""
    iface = getattr(toolkit, "iface", None)
    clean_args = dict(args or {})

    try:
        if name in _MAIN_THREAD_TOOLS:
            handler = _MAIN_THREAD_TOOLS[name]
            if executor is not None:
                return executor.run_sync(lambda: handler(iface, clean_args))
            return handler(iface, clean_args)

        if name in _THREADSAFE_TOOLS:
            return _THREADSAFE_TOOLS[name](clean_args)

        return {"ok": False, "error": f"Unknown SMP tool: {name}"}
    except TypeError as exc:
        return {"ok": False, "error_code": "invalid_arguments", "error": f"Invalid arguments for {name}: {exc}"}
