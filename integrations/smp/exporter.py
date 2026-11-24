"""Background SMP export manager with approval, policy, staging, and cancel lifecycle."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid

from qgis.core import QgsApplication, QgsProject, QgsTask

from .estimator import get_plan_registry
from .planner import wgs84_bounds_to_project_rect
from .policy import (
    VENDOR_COMMIT,
    classify_layer_policy,
    compute_project_fingerprint,
    layer_attribution,
)
from .validator import validate_file
from .vendor.comapeo_smp_generator import SMPGenerator


def _canonicalize_writable_output_path(raw_path, overwrite=False):
    """Validate output path against traversal/symlink escapes and return canonical path."""
    if not raw_path or not isinstance(raw_path, str):
        return None, "invalid_output_path", "output_path is required."

    stripped = raw_path.strip()
    if not stripped or "\x00" in stripped:
        return None, "invalid_output_path", "output_path is empty or contains null bytes."

    raw_p = Path(stripped)
    if ".." in raw_p.parts:
        return None, "path_traversal", "output_path must not contain '..' path traversal segments."

    if raw_p.suffix.lower() != ".smp":
        return None, "invalid_output_extension", "output_path must end with '.smp'."

    if raw_p.is_symlink():
        return None, "symlink_rejected", "output_path must not be a symbolic link."

    parent_raw = raw_p.parent
    if not str(parent_raw) or str(parent_raw) == ".":
        parent_raw = Path.cwd()

    # Check existing parent or ancestor for symlink safety and writability
    if parent_raw.exists() and not parent_raw.is_dir():
        return None, "invalid_output_path", f"Parent path is not a directory: {parent_raw}"

    try:
        os.makedirs(parent_raw, exist_ok=True)
    except OSError as exc:
        return None, "unwritable_output_dir", f"Cannot create output directory '{parent_raw}': {exc}"

    real_parent = os.path.realpath(parent_raw)
    if not os.access(real_parent, os.W_OK):
        return None, "unwritable_output_dir", f"Output directory is not writable: {real_parent}"

    canonical = os.path.join(real_parent, raw_p.name)
    if os.path.islink(canonical):
        return None, "symlink_rejected", "Canonical output target is a symbolic link."

    if os.path.exists(canonical) and not overwrite:
        return (
            None,
            "output_exists",
            f"Output file already exists: {canonical}. Pass overwrite=True after user confirmation to replace it.",
        )

    return canonical, None, None


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class _JobFeedback:
    """Thread-safe feedback adapter bridging SMPGenerator to SmpExportJob."""

    def __init__(self, job):
        self._job = job

    def isCanceled(self):
        return self._job.cancel_event.is_set()

    def pushInfo(self, msg):
        with self._job.lock:
            if len(self._job.logs) < 200:
                self._job.logs.append(str(msg))

    def pushWarning(self, msg):
        with self._job.lock:
            if len(self._job.warnings) < 100:
                self._job.warnings.append(str(msg))

    def setProgress(self, pct):
        now = time.monotonic()
        with self._job.lock:
            pct_val = max(0, min(100, int(pct)))
            self._job.progress_pct = pct_val
            if self._job.tiles_total > 0:
                self._job.tiles_done = min(
                    self._job.tiles_total,
                    int(round((pct_val / 100.0) * self._job.tiles_total)),
                )
            elapsed = max(0.001, now - self._job.started_at) if self._job.started_at else 0.0
            if pct_val > 0 and elapsed > 0.05:
                est_total = elapsed * (100.0 / pct_val)
                self._job.eta_seconds = round(max(0.0, est_total - elapsed), 1)


@dataclass
class SmpExportJob:
    job_id: str
    plan_id: str
    output_path: str
    tmp_output_path: str
    manifest_path: str
    cache_dir: str | None
    tiles_total: int
    state: str = "queued"
    progress_pct: int = 0
    tiles_done: int = 0
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    eta_seconds: float | None = None
    error: str | None = None
    warnings: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    archive_size_bytes: int | None = None
    output_sha256: str | None = None
    validation: dict | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    task: object | None = None
    layer_ids: tuple = ()
    _signal_conn: object | None = None


class _SmpExportTask(QgsTask):
    """QgsTask running SMPGenerator off the main/GUI thread."""

    def __init__(self, job, plan, local_rect_proj, region_rect_proj, render_layers, on_cleanup):
        super().__init__(f"AwanaGIS CoMapeo SMP Export ({job.job_id})", QgsTask.Flag.CanCancel)
        self._job = job
        self._plan = plan
        self._local_rect_proj = local_rect_proj
        self._region_rect_proj = region_rect_proj
        self._render_layers = list(render_layers)
        self._on_cleanup = on_cleanup
        self._feedback = _JobFeedback(job)

    def cancel(self):
        self._job.cancel_event.set()
        super().cancel()

    def run(self):
        job = self._job
        cfg = self._plan.effective_config
        with job.lock:
            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.finished_at = time.monotonic()
                job.done_event.set()
                return False
            job.state = "running"
            job.started_at = time.monotonic()

        try:
            gen = SMPGenerator(feedback=self._feedback)
            out = gen.generate_smp_from_canvas(
                self._local_rect_proj,
                cfg["local_min_zoom"],
                cfg["local_max_zoom"],
                job.tmp_output_path,
                tile_format=cfg["tile_format"],
                jpeg_quality=cfg["quality"],
                cache_dir=job.cache_dir,
                include_world_base_zooms=cfg["include_world"],
                world_max_zoom=cfg["world_max_zoom"] if cfg["include_world"] else 3,
                include_region=cfg["include_region"],
                region_extent=self._region_rect_proj,
                region_min_zoom=cfg["region_min_zoom"],
                region_max_zoom=cfg["region_max_zoom"],
                export_plan=self._plan.export_plan,
                render_layers=self._render_layers,
            )

            if out is None or job.cancel_event.is_set() or self.isCanceled():
                _safe_unlink(job.tmp_output_path)
                with job.lock:
                    job.state = "cancelled"
                    job.finished_at = time.monotonic()
                return False

            with job.lock:
                job.state = "validating"
                job.progress_pct = 100
                job.tiles_done = job.tiles_total
                job.eta_seconds = 0.0

            val = validate_file(job.tmp_output_path, run_external=False)
            if not val.get("valid"):
                _safe_unlink(job.tmp_output_path)
                with job.lock:
                    job.state = "failed"
                    job.error = "Generated SMP failed structural validation: " + "; ".join(val.get("issues", []))
                    job.validation = val
                    job.finished_at = time.monotonic()
                return False

            # Atomic promote to final destination
            os.replace(job.tmp_output_path, job.output_path)
            size_bytes = os.path.getsize(job.output_path)
            out_sha = _file_sha256(job.output_path)

            manifest = {
                "schema_version": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "job_id": job.job_id,
                "plan_id": job.plan_id,
                "output_path": job.output_path,
                "output_size_bytes": size_bytes,
                "output_sha256": out_sha,
                "renderer_commit": VENDOR_COMMIT,
                "renderer_sha256": self._plan.renderer_sha256,
                "tile_format": cfg["tile_format"],
                "quality": cfg["quality"],
                "zooms": {
                    "world_max_zoom": cfg["world_max_zoom"],
                    "region_min_zoom": cfg["region_min_zoom"],
                    "region_max_zoom": cfg["region_max_zoom"],
                    "local_min_zoom": cfg["local_min_zoom"],
                    "local_max_zoom": cfg["local_max_zoom"],
                },
                "bounds_wgs84": {
                    "world": cfg["world_bounds_wgs84"],
                    "region": cfg["region_bounds_wgs84"],
                    "local": cfg["local_bounds_wgs84"],
                },
                "tile_counts": {
                    "total": job.tiles_total,
                    "sources": [
                        {
                            "source_id": sp.get("source_id"),
                            "role": sp.get("source_role"),
                            "total_tiles": sp.get("total_tiles"),
                            "zooms": sp.get("export_zooms"),
                        }
                        for sp in self._plan.export_plan.get("sources", [])
                    ],
                },
                "approved_layers": [
                    {
                        "id": m["id"],
                        "name": m["name"],
                        "provider": m["provider"],
                        "export_policy": m["export_policy"],
                        "attribution": m["attribution"],
                    }
                    for m in self._plan.effective_layer_meta
                ],
            }
            tmp_manifest = job.manifest_path + ".tmp"
            with open(tmp_manifest, "w", encoding="utf-8") as mf:
                json.dump(manifest, mf, indent=2, ensure_ascii=False)
            os.replace(tmp_manifest, job.manifest_path)

            with job.lock:
                job.archive_size_bytes = size_bytes
                job.output_sha256 = out_sha
                job.validation = val
                job.state = "completed"
                job.finished_at = time.monotonic()
            return True

        except Exception as exc:
            _safe_unlink(job.tmp_output_path)
            with job.lock:
                if job.cancel_event.is_set():
                    job.state = "cancelled"
                else:
                    job.state = "failed"
                    job.error = str(exc)
                job.finished_at = time.monotonic()
            return False
        finally:
            try:
                self._on_cleanup(job)
            except Exception:
                pass
            job.done_event.set()

    def finished(self, _result):
        pass


def _safe_unlink(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


class ExportManager:
    """Manages SMP export job lifecycle, concurrency, cancellation, and cleanup."""

    def __init__(self, plan_registry=None):
        self._lock = threading.Lock()
        self._jobs = {}
        self._plan_registry = plan_registry or get_plan_registry()

    def _active_job_locked(self):
        for job in self._jobs.values():
            if not job.done_event.is_set() and job.state in ("queued", "running", "validating"):
                return job
        return None

    def _disconnect_job_signals(self, job):
        conn = getattr(job, "_signal_conn", None)
        if conn is not None:
            try:
                QgsProject.instance().layersWillBeRemoved.disconnect(conn)
            except Exception:
                pass
            job._signal_conn = None

    def start_export(
        self,
        plan_id,
        output_path,
        approved=False,
        overwrite=False,
        approved_restricted_layers=False,
        confirm=None,
    ):
        """Validate gates and queue a background QgsTask export."""
        effective_approved = bool(approved) if confirm is None else (bool(approved) or bool(confirm))
        if not effective_approved:
            return {
                "ok": False,
                "error_code": "approval_required",
                "error": (
                    "Explicit user approval (approved=True) for the exact plan and output path "
                    "is required before starting an SMP export."
                ),
            }

        if not plan_id or not isinstance(plan_id, str):
            return {"ok": False, "error_code": "invalid_plan_id", "error": "plan_id is required."}

        plan = self._plan_registry.get(plan_id)
        if plan is None:
            return {
                "ok": False,
                "error_code": "invalid_or_expired_plan",
                "error": f"Export plan '{plan_id}' was not found or has expired. Re-run smp_estimate.",
            }

        project = QgsProject.instance()
        all_layers = project.mapLayers()
        render_layers = []
        for lid in plan.effective_layer_ids:
            layer = all_layers.get(lid)
            if layer is None:
                return {
                    "ok": False,
                    "error_code": "stale_plan",
                    "error": f"Approved layer '{lid}' is no longer in the QGIS project. Re-run smp_estimate.",
                }
            pol = classify_layer_policy(layer)
            if pol == "blocked_sensitive":
                return {
                    "ok": False,
                    "error_code": "blocked_sensitive_layer",
                    "error": f"Layer '{layer.name()}' is marked blocked_sensitive and cannot be exported.",
                }
            if pol == "restricted" and not approved_restricted_layers:
                return {
                    "ok": False,
                    "error_code": "restricted_layer_unapproved",
                    "error": (
                        f"Layer '{layer.name()}' is marked restricted. Pass approved_restricted_layers=True "
                        "after explicit user authorization, or exclude it in smp_estimate."
                    ),
                }
            render_layers.append(layer)

        live_fp, _cache_safe = compute_project_fingerprint(project, render_layers)
        if live_fp != plan.project_fingerprint:
            return {
                "ok": False,
                "error_code": "stale_plan",
                "error": (
                    "QGIS project layers, styles, labels, CRS, or feature content changed since "
                    "smp_estimate was run. Re-run smp_estimate before exporting."
                ),
            }

        canonical_output, err_code, err_msg = _canonicalize_writable_output_path(
            output_path, overwrite=bool(overwrite)
        )
        if err_code:
            return {"ok": False, "error_code": err_code, "error": err_msg}

        with self._lock:
            active = self._active_job_locked()
            if active is not None:
                return {
                    "ok": False,
                    "error_code": "export_busy",
                    "active_job_id": active.job_id,
                    "error": f"An SMP export ({active.job_id}) is already running.",
                }

            job_id = f"job_{uuid.uuid4().hex[:16]}"
            tmp_output = f"{canonical_output}.{job_id}.smp.tmp"
            manifest_path = f"{canonical_output}.manifest.json"
            cache_dir = None
            if plan.cache_safe:
                cache_key = hashlib.sha256(
                    f"{plan.plan_id}:{plan.project_fingerprint}".encode("utf-8")
                ).hexdigest()[:20]
                cache_dir = os.path.join(tempfile.gettempdir(), "awanagis_smp_cache", cache_key)

            cfg = plan.effective_config
            local_rect_proj = wgs84_bounds_to_project_rect(cfg["local_bounds_wgs84"], project)
            region_rect_proj = (
                wgs84_bounds_to_project_rect(cfg["region_bounds_wgs84"], project)
                if cfg["include_region"] else None
            )

            job = SmpExportJob(
                job_id=job_id,
                plan_id=plan_id,
                output_path=canonical_output,
                tmp_output_path=tmp_output,
                manifest_path=manifest_path,
                cache_dir=cache_dir,
                tiles_total=plan.export_plan["total_tiles"],
                layer_ids=plan.effective_layer_ids,
            )

            def _on_layers_will_be_removed(removed_ids):
                if any(lid in job.layer_ids for lid in removed_ids):
                    with job.lock:
                        job.error = "Export cancelled because an approved layer was removed from the project."
                    job.cancel_event.set()
                    if job.task is not None:
                        try:
                            job.task.cancel()
                        except Exception:
                            pass

            try:
                job._signal_conn = project.layersWillBeRemoved.connect(_on_layers_will_be_removed)
            except Exception:
                job._signal_conn = None

            task = _SmpExportTask(
                job,
                plan,
                local_rect_proj,
                region_rect_proj,
                render_layers,
                on_cleanup=self._disconnect_job_signals,
            )
            job.task = task
            self._jobs[job_id] = job

        QgsApplication.taskManager().addTask(task)

        return {
            "ok": True,
            "job_id": job_id,
            "status": job.state,
            "output_path_pending": canonical_output,
            "manifest_path_pending": manifest_path,
            "plan_id": plan_id,
            "total_tiles": job.tiles_total,
            "plan_summary": {
                "tile_format": cfg["tile_format"],
                "quality": cfg["quality"],
                "local_zooms": [cfg["local_min_zoom"], cfg["local_max_zoom"]],
                "include_region": cfg["include_region"],
                "include_world": cfg["include_world"],
                "layers": [m["name"] for m in plan.effective_layer_meta],
            },
        }

    def export_status(self, job_id):
        """Return live status/progress for ``job_id``."""
        if not job_id:
            return {"ok": False, "error_code": "invalid_job_id", "error": "job_id is required."}
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "error_code": "job_not_found", "error": f"Unknown job_id: {job_id}"}

        with job.lock:
            now = time.monotonic()
            end_t = job.finished_at if job.finished_at is not None else now
            start_t = job.started_at if job.started_at is not None else job.created_at
            elapsed = round(max(0.0, end_t - start_t), 2)
            payload = {
                "ok": True,
                "job_id": job.job_id,
                "plan_id": job.plan_id,
                "state": job.state,
                "progress_pct": job.progress_pct,
                "tiles_done": job.tiles_done,
                "tiles_total": job.tiles_total,
                "elapsed_seconds": elapsed,
                "eta_seconds": job.eta_seconds,
                "warnings": list(job.warnings),
                "error": job.error,
            }
            if job.state == "completed":
                payload.update({
                    "output_path": job.output_path,
                    "manifest_path": job.manifest_path,
                    "archive_size_bytes": job.archive_size_bytes,
                    "output_sha256": job.output_sha256,
                    "validation": job.validation,
                })
            return payload

    def cancel_export(self, job_id, wait_seconds=0.5):
        """Cooperatively cancel ``job_id`` without leaving corrupt final files."""
        if not job_id:
            return {"ok": False, "error_code": "invalid_job_id", "error": "job_id is required."}
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "error_code": "job_not_found", "error": f"Unknown job_id: {job_id}"}

        job.cancel_event.set()
        if job.task is not None:
            try:
                job.task.cancel()
            except Exception:
                pass

        if wait_seconds and wait_seconds > 0:
            job.done_event.wait(timeout=wait_seconds)

        with job.lock:
            if not job.done_event.is_set() and job.state in ("queued", "running", "validating"):
                state = "cancelling"
            else:
                if job.state == "queued":
                    job.state = "cancelled"
                state = job.state

        return {
            "ok": True,
            "job_id": job.job_id,
            "state": state,
            "cancelled": True,
        }

    def cleanup_all(self, wait_seconds=2.0):
        """Cancel all active exports and remove staging files (called on plugin unload)."""
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
            if job.task is not None:
                try:
                    job.task.cancel()
                except Exception:
                    pass
        for job in jobs:
            if wait_seconds and not job.done_event.is_set():
                job.done_event.wait(timeout=wait_seconds)
            self._disconnect_job_signals(job)
            _safe_unlink(job.tmp_output_path)
        self._plan_registry.clear()


_DEFAULT_EXPORT_MANAGER = ExportManager()


def get_export_manager():
    return _DEFAULT_EXPORT_MANAGER
