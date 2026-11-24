"""Unified tool entrypoints and core/tools.py dispatch bridge for CoMapeo SMP."""

from __future__ import annotations

from qgis.PyQt.QtCore import QCoreApplication

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
    allow_online_sampling=False,
    allow_restricted_sampling=False,
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
        allow_online_sampling=bool(allow_online_sampling),
        allow_restricted_sampling=bool(allow_restricted_sampling),
    )


def smp_start_export(
    plan_id,
    output_path,
    approved=False,
    overwrite=False,
    approved_restricted_layers=False,
    confirm=None,
    approval_callback=None,
):
    return get_export_manager().start_export(
        plan_id=plan_id,
        output_path=output_path,
        approved=approved,
        overwrite=overwrite,
        approved_restricted_layers=approved_restricted_layers,
        confirm=confirm,
        approval_callback=approval_callback,
    )


def smp_export_status(job_id):
    return get_export_manager().export_status(job_id=job_id)


def smp_cancel_export(job_id):
    return get_export_manager().cancel_export(job_id=job_id)


def smp_validate_file(file_path, run_external=True):
    return validate_file(file_path=file_path, run_external=bool(run_external))


def cleanup_all():
    get_export_manager().cleanup_all()


def _format_size_mb(size_bytes):
    if not size_bytes or size_bytes <= 0:
        return "unknown"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _request_trusted_export_approval(toolkit, summary):
    """Prompt the user via ``toolkit._ask_user`` with ``allow_free_text=False``.

    Never relies on caller-supplied booleans alone; fails closed if no trusted
    interactive prompt is available or if the user cancels/denies.
    """
    ask_fn = getattr(toolkit, "_ask_user", None) if toolkit is not None else None
    if not callable(ask_fn):
        return False, {
            "ok": False,
            "error_code": "trusted_approval_required",
            "cancelled": True,
            "error": (
                "Trusted human confirmation is unavailable (no interactive _ask_user prompt); "
                "SMP export refused."
            ),
        }

    overwrite_label = "YES (existing file will be overwritten)" if summary["overwrite"] else "No"
    restricted_note = (
        f"\nRestricted layers: {', '.join(summary['restricted_layers'])}"
        if summary["restricted_layers"] else ""
    )
    remote_note = (
        f"\nOnline/remote warnings: {len(summary['remote_layer_warnings'])}"
        if summary["remote_layer_warnings"] else ""
    )

    question = (
        f"Confirm CoMapeo SMP export?\n"
        f"Plan ID: {summary['plan_id']}\n"
        f"Output path: {summary['output_path']}\n"
        f"Overwrite: {overwrite_label}\n"
        f"Tiles: {summary['tiles_total']:,}\n"
        f"Estimated size: ~{_format_size_mb(summary['estimated_likely_bytes'])} "
        f"(high: {_format_size_mb(summary['estimated_high_bytes'])})"
        f"{restricted_note}{remote_note}"
    )

    if summary["has_restricted_layers"]:
        approve_choice = "approve_export_with_restricted"
        approve_option = {
            "label": approve_choice,
            "display_label": QCoreApplication.translate(
                "SmpExport", "Approve export (including restricted layers)"
            ),
            "description": QCoreApplication.translate(
                "SmpExport", "Export this exact SMP plan, including restricted layers, to the path above."
            ),
        }
    else:
        approve_choice = "approve_export"
        approve_option = {
            "label": approve_choice,
            "display_label": QCoreApplication.translate("SmpExport", "Approve export"),
            "description": QCoreApplication.translate(
                "SmpExport", "Export this exact SMP plan to the destination file above."
            ),
        }

    options = [
        approve_option,
        {
            "label": "deny_export",
            "display_label": QCoreApplication.translate("SmpExport", "Cancel"),
            "description": QCoreApplication.translate(
                "SmpExport", "Do not create or overwrite any SMP file."
            ),
        },
    ]

    answer = ask_fn(question, options, False, display_question=question)
    if not isinstance(answer, dict) or answer.get("cancelled") is True:
        return False, {
            "ok": False,
            "error_code": "user_approval_denied",
            "cancelled": True,
            "error": "SMP export cancelled by user.",
        }

    if answer.get("choice") != approve_choice:
        return False, {
            "ok": False,
            "error_code": "user_approval_denied",
            "cancelled": True,
            "error": "SMP export was not approved by user.",
        }

    return True, None


_MAIN_THREAD_TOOLS = {
    "smp_inspect_map": lambda iface, args: smp_inspect_map(iface=iface, **args),
    "smp_suggest_regions": lambda iface, args: smp_suggest_regions(iface=iface, **args),
    "smp_estimate": lambda _iface, args: smp_estimate(**args),
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
    # Never accept internal trust/callback overrides from serialized tool callers
    clean_args.pop("approval_callback", None)
    clean_args.pop("_trusted_approval_token", None)

    try:
        if name == "smp_start_export":
            mgr = get_export_manager()
            preflight_call = lambda: mgr.preflight_export(**clean_args)
            err, ctx = executor.run_sync(preflight_call) if executor is not None else preflight_call()
            if err is not None:
                return err

            summary = ctx["summary"]
            # Ask the user on the caller/worker thread so GUI _ask_user never deadlocks main thread
            approved_ok, deny_payload = _request_trusted_export_approval(toolkit, summary)
            if not approved_ok:
                return deny_payload

            token = mgr.issue_trusted_approval_token(
                plan_id=summary["plan_id"],
                canonical_output=summary["output_path"],
                overwrite=summary["overwrite"],
                approved_restricted_layers=bool(clean_args.get("approved_restricted_layers")),
            )
            start_call = lambda: mgr.start_export(_trusted_approval_token=token, **clean_args)
            return executor.run_sync(start_call) if executor is not None else start_call()

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
