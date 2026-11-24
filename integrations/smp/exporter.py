"""Background SMP export manager with trusted approval, snapshot isolation, staging, and cancel lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Optional
import uuid

from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsTask, QgsVectorLayer

from .estimator import (
    DEFAULT_MAX_EXPORT_TILES,
    DEFAULT_SCRATCH_RESERVE_BYTES,
    get_plan_registry,
)
from .planner import wgs84_bounds_to_project_rect
from .policy import (
    VENDOR_COMMIT,
    classify_layer_policy,
    compute_project_fingerprint,
)
from .validator import validate_file
from .vendor.comapeo_smp_generator import SMPGenerator


def _nearest_existing_dir(path):
    cur = os.path.abspath(path)
    while cur and not os.path.exists(cur):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return cur or tempfile.gettempdir()


def _canonicalize_writable_output_path(raw_path, overwrite=False):
    """Validate output .smp and sidecar manifest paths against traversal/symlinks."""
    if not raw_path or not isinstance(raw_path, str):
        return None, None, "invalid_output_path", "output_path is required."

    stripped = raw_path.strip()
    if not stripped or "\x00" in stripped:
        return None, None, "invalid_output_path", "output_path is empty or contains null bytes."

    raw_p = Path(stripped)
    if ".." in raw_p.parts:
        return None, None, "path_traversal", "output_path must not contain '..' path traversal segments."

    if raw_p.suffix.lower() != ".smp":
        return None, None, "invalid_output_extension", "output_path must end with '.smp'."

    if raw_p.is_symlink():
        return None, None, "symlink_rejected", "output_path must not be a symbolic link."

    parent_raw = raw_p.parent
    if not str(parent_raw) or str(parent_raw) == ".":
        parent_raw = Path.cwd()

    if parent_raw.exists() and not parent_raw.is_dir():
        return None, None, "invalid_output_path", f"Parent path is not a directory: {parent_raw}"

    try:
        os.makedirs(parent_raw, exist_ok=True)
    except OSError as exc:
        return None, None, "unwritable_output_dir", f"Cannot create output directory '{parent_raw}': {exc}"

    real_parent = os.path.realpath(parent_raw)
    if not os.access(real_parent, os.W_OK):
        return None, None, "unwritable_output_dir", f"Output directory is not writable: {real_parent}"

    canonical = os.path.join(real_parent, raw_p.name)
    manifest_path = f"{canonical}.manifest.json"
    if os.path.islink(canonical) or os.path.islink(manifest_path):
        return None, None, "symlink_rejected", "Canonical output or manifest target is a symbolic link."

    if not overwrite and (os.path.exists(canonical) or os.path.exists(manifest_path)):
        existing_target = canonical if os.path.exists(canonical) else manifest_path
        return (
            None,
            None,
            "output_exists",
            f"Output file already exists: {existing_target}. Pass overwrite=True after user confirmation to replace it.",
        )

    return canonical, manifest_path, None, None


def _atomic_publish_file(src_tmp, dst_path, overwrite=False):
    """Atomically publish ``src_tmp`` to ``dst_path``, refusing clobber if ``overwrite=False``."""
    if os.path.islink(dst_path):
        raise PermissionError(f"Refusing to publish to symbolic link target: {dst_path}")

    if overwrite:
        os.replace(src_tmp, dst_path)
        return

    try:
        os.link(src_tmp, dst_path)
        os.unlink(src_tmp)
        return
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EACCES):
            raise

    # Cross-device / no-hardlink fallback using O_CREAT|O_EXCL
    fd = os.open(dst_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as dst_fh, open(src_tmp, "rb") as src_fh:
            shutil.copyfileobj(src_fh, dst_fh, length=1024 * 1024)
            dst_fh.flush()
            os.fsync(dst_fh.fileno())
    except Exception:
        _safe_unlink(dst_path)
        raise
    _safe_unlink(src_tmp)


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_unlink(path):
    if not path:
        return
    try:
        if os.path.exists(path) or os.path.islink(path):
            os.unlink(path)
    except OSError:
        pass


def _clone_layer_for_snapshot(layer):
    """Clone a QGIS layer on the main thread so workers never touch live GUI layers."""
    if isinstance(layer, QgsVectorLayer) and layer.isModified():
        crs_auth = layer.crs().authid() if layer.crs().isValid() else "EPSG:4326"
        geom_wkb = layer.wkbType()
        try:
            from qgis.core import QgsWkbTypes
            geom_name = QgsWkbTypes.displayString(geom_wkb) or "Geometry"
        except Exception:
            geom_name = "Geometry"
        mem = QgsVectorLayer(f"{geom_name}?crs={crs_auth}", layer.name(), "memory")
        mem_pr = mem.dataProvider()
        mem_pr.addAttributes(list(layer.fields()))
        mem.updateFields()
        feats = []
        for feat in layer.getFeatures():
            nf = QgsFeature(mem.fields())
            nf.setGeometry(feat.geometry())
            nf.setAttributes(feat.attributes())
            feats.append(nf)
        if feats:
            mem_pr.addFeatures(feats)
        mem.updateExtents()
        if layer.renderer() is not None:
            mem.setRenderer(layer.renderer().clone())
        if layer.labeling() is not None:
            mem.setLabeling(layer.labeling().clone())
        mem.setLabelsEnabled(bool(layer.labelsEnabled()))
        mem.setOpacity(float(layer.opacity()))
        mem.setBlendMode(layer.blendMode())
        if layer.subsetString():
            mem.setSubsetString(layer.subsetString())
        return mem

    cloned = layer.clone()
    if cloned is None:
        raise RuntimeError(f"Failed to create isolated snapshot clone for layer '{layer.name()}'.")
    return cloned


def _build_isolated_project_snapshot(live_project, render_layers):
    """Create a worker-owned QgsProject + cloned layers on the main thread."""
    snapshot_project = QgsProject()
    if live_project.crs() is not None and live_project.crs().isValid():
        snapshot_project.setCrs(live_project.crs())
    title = (live_project.title() or "").strip() or (live_project.baseName() or "").strip()
    if title:
        snapshot_project.setTitle(title)
    try:
        snapshot_project.setTransformContext(live_project.transformContext())
    except Exception:
        pass

    cloned_layers = []
    for layer in render_layers:
        cloned = _clone_layer_for_snapshot(layer)
        snapshot_project.addMapLayer(cloned, False)
        cloned_layers.append(cloned)
    return snapshot_project, cloned_layers


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
    cache_dir: Optional[str]
    tiles_total: int
    overwrite: bool = False
    state: str = "queued"
    progress_pct: int = 0
    tiles_done: int = 0
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    eta_seconds: Optional[float] = None
    error: Optional[str] = None
    warnings: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    archive_size_bytes: Optional[int] = None
    output_sha256: Optional[str] = None
    validation: Optional[dict] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    task: Optional[object] = None
    layer_ids: tuple = ()
    _signal_conn: Optional[object] = None


class _SmpExportTask(QgsTask):
    """QgsTask running SMPGenerator off the main/GUI thread against an isolated project snapshot."""

    def __init__(
        self,
        job,
        plan,
        local_rect_proj,
        region_rect_proj,
        snapshot_project,
        cloned_layers,
        on_cleanup,
    ):
        super().__init__(f"AwanaGIS CoMapeo SMP Export ({job.job_id})", QgsTask.Flag.CanCancel)
        self._job = job
        self._plan = plan
        self._local_rect_proj = local_rect_proj
        self._region_rect_proj = region_rect_proj
        self._snapshot_project = snapshot_project
        self._cloned_layers = list(cloned_layers)
        self._on_cleanup = on_cleanup
        self._feedback = _JobFeedback(job)

    def cancel(self):
        self._job.cancel_event.set()
        super().cancel()

    def _is_cancelled(self):
        return self._job.cancel_event.is_set() or self.isCanceled()

    def run(self):
        job = self._job
        cfg = self._plan.effective_config
        with job.lock:
            if self._is_cancelled():
                _safe_unlink(job.tmp_output_path)
                job.state = "cancelled"
                job.finished_at = time.monotonic()
                return False
            job.state = "running"
            job.started_at = time.monotonic()

        tmp_manifest = None
        try:
            gen = SMPGenerator(feedback=self._feedback, project=self._snapshot_project)
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
                render_layers=self._cloned_layers,
            )

            if out is None or self._is_cancelled():
                _safe_unlink(job.tmp_output_path)
                with job.lock:
                    job.state = "cancelled"
                    job.finished_at = time.monotonic()
                return False

            with job.lock:
                if self._is_cancelled():
                    _safe_unlink(job.tmp_output_path)
                    job.state = "cancelled"
                    job.finished_at = time.monotonic()
                    return False
                job.state = "validating"
                job.progress_pct = 100
                job.tiles_done = job.tiles_total
                job.eta_seconds = 0.0

            val = validate_file(job.tmp_output_path, run_external=False)
            if not val.get("valid"):
                _safe_unlink(job.tmp_output_path)
                with job.lock:
                    if self._is_cancelled():
                        job.state = "cancelled"
                    else:
                        job.state = "failed"
                        job.error = "Generated SMP failed structural validation: " + "; ".join(val.get("issues", []))
                        job.validation = val
                    job.finished_at = time.monotonic()
                return False

            # Build manifest in an exclusive, unpredictable temp file before publishing
            out_sha = _file_sha256(job.tmp_output_path)
            size_bytes = os.path.getsize(job.tmp_output_path)
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

            manifest_dir = os.path.dirname(job.manifest_path)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=manifest_dir,
                prefix=f".{os.path.basename(job.manifest_path)}.",
                suffix=".tmp",
                delete=False,
            ) as mf:
                tmp_manifest = mf.name
                json.dump(manifest, mf, indent=2, ensure_ascii=False)
                mf.flush()
                os.fsync(mf.fileno())

            # Re-check cancellation under lock immediately prior to final atomic publication
            with job.lock:
                if self._is_cancelled():
                    _safe_unlink(job.tmp_output_path)
                    _safe_unlink(tmp_manifest)
                    job.state = "cancelled"
                    job.finished_at = time.monotonic()
                    return False
                job.state = "publishing"

            # Atomic paired publication: when overwrite=True, back up any existing files
            # inside the try/except rollback block so any failure restores the prior pair
            # and never deletes backups if restoration fails.
            bak_manifest = None
            bak_output = None
            published_manifest_new = False
            publish_ok = False
            try:
                if job.overwrite:
                    if os.path.exists(job.manifest_path):
                        fd_m, cand_m = tempfile.mkstemp(
                            prefix=".bak_", suffix=".manifest.json", dir=manifest_dir
                        )
                        os.close(fd_m)
                        try:
                            os.replace(job.manifest_path, cand_m)
                        except Exception:
                            _safe_unlink(cand_m)
                            raise
                        bak_manifest = cand_m
                    if os.path.exists(job.output_path):
                        fd_o, cand_o = tempfile.mkstemp(
                            prefix=".bak_", suffix=".smp", dir=os.path.dirname(job.output_path)
                        )
                        os.close(fd_o)
                        try:
                            os.replace(job.output_path, cand_o)
                        except Exception:
                            _safe_unlink(cand_o)
                            raise
                        bak_output = cand_o

                _atomic_publish_file(tmp_manifest, job.manifest_path, overwrite=job.overwrite)
                published_manifest_new = True
                _atomic_publish_file(job.tmp_output_path, job.output_path, overwrite=job.overwrite)
                publish_ok = True
            except Exception:
                if bak_manifest and os.path.exists(bak_manifest):
                    try:
                        os.replace(bak_manifest, job.manifest_path)
                        bak_manifest = None
                    except OSError:
                        pass
                elif published_manifest_new:
                    _safe_unlink(job.manifest_path)

                if bak_output and os.path.exists(bak_output):
                    try:
                        os.replace(bak_output, job.output_path)
                        bak_output = None
                    except OSError:
                        pass
                raise
            finally:
                if publish_ok:
                    if bak_manifest:
                        _safe_unlink(bak_manifest)
                    if bak_output:
                        _safe_unlink(bak_output)

            with job.lock:
                job.archive_size_bytes = size_bytes
                job.output_sha256 = out_sha
                job.validation = val
                job.state = "completed"
                job.finished_at = time.monotonic()
            return True

        except FileExistsError as exc:
            _safe_unlink(job.tmp_output_path)
            _safe_unlink(tmp_manifest)
            with job.lock:
                job.state = "failed"
                job.error = f"Refused to overwrite existing destination file: {exc}"
                job.finished_at = time.monotonic()
            return False
        except Exception as exc:
            _safe_unlink(job.tmp_output_path)
            _safe_unlink(tmp_manifest)
            with job.lock:
                if self._is_cancelled():
                    job.state = "cancelled"
                else:
                    job.state = "failed"
                    job.error = str(exc)
                job.finished_at = time.monotonic()
            return False
        finally:
            _safe_unlink(tmp_manifest)
            try:
                self._on_cleanup(job)
            except Exception:
                pass
            job.done_event.set()

    def _release_snapshot(self):
        if self._snapshot_project is not None:
            try:
                self._snapshot_project.removeAllMapLayers()
            except Exception:
                pass
            self._cloned_layers.clear()
            self._snapshot_project = None

    def finished(self, _result):
        # Release worker-owned QgsProject snapshot cleanly on the main thread
        self._release_snapshot()


class ExportManager:
    """Manages SMP export job lifecycle, trusted approval, disk/tile caps, and cleanup."""

    def __init__(self, plan_registry=None, max_export_tiles=DEFAULT_MAX_EXPORT_TILES):
        self._lock = threading.Lock()
        self._jobs = {}
        self._trusted_tokens = {}
        self._plan_registry = plan_registry or get_plan_registry()
        self._max_export_tiles = int(max_export_tiles)

    def _active_job_locked(self):
        for job in self._jobs.values():
            if not job.done_event.is_set() and job.state in ("queued", "running", "validating", "publishing"):
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

    def issue_trusted_approval_token(self, plan_id, canonical_output, overwrite, approved_restricted_layers):
        """Issue an internal one-shot approval token bound to the exact preflight target."""
        token = uuid.uuid4().hex
        with self._lock:
            if len(self._trusted_tokens) > 256:
                self._trusted_tokens.clear()
            self._trusted_tokens[token] = {
                "plan_id": plan_id,
                "output_path": canonical_output,
                "overwrite": bool(overwrite),
                "approved_restricted_layers": bool(approved_restricted_layers),
                "expires_at": time.monotonic() + 600.0,
            }
        return token

    def _consume_trusted_token(self, token, plan_id, canonical_output, overwrite, approved_restricted_layers):
        if not token or not isinstance(token, str):
            return False
        with self._lock:
            rec = self._trusted_tokens.pop(token, None)
        if rec is None or time.monotonic() > rec["expires_at"]:
            return False
        return (
            rec["plan_id"] == plan_id
            and rec["output_path"] == canonical_output
            and rec["overwrite"] == bool(overwrite)
            and (not approved_restricted_layers or rec["approved_restricted_layers"])
        )

    def _check_disk_budgets(self, plan, canonical_output, cache_dir):
        out_dir = _nearest_existing_dir(os.path.dirname(canonical_output))
        scratch_dir = _nearest_existing_dir(cache_dir or tempfile.gettempdir())
        needed_out = max(int(plan.estimated_high_bytes or 0), 1024)
        needed_scratch = max(int(plan.scratch_disk_bytes or 0), needed_out)

        free_out = shutil.disk_usage(out_dir).free
        free_scratch = shutil.disk_usage(scratch_dir).free

        try:
            same_fs = os.stat(out_dir).st_dev == os.stat(scratch_dir).st_dev
        except OSError:
            same_fs = (out_dir == scratch_dir)

        if same_fs:
            required_total = needed_out + needed_scratch + DEFAULT_SCRATCH_RESERVE_BYTES
            if free_out < required_total:
                return (
                    "insufficient_disk_space",
                    f"Insufficient disk space on '{out_dir}': {free_out / (1024 * 1024):.1f} MB free, "
                    f"requires ~{required_total / (1024 * 1024):.1f} MB (archive + scratch + reserve).",
                )
        else:
            req_out = needed_out + DEFAULT_SCRATCH_RESERVE_BYTES
            req_scratch = needed_scratch + DEFAULT_SCRATCH_RESERVE_BYTES
            if free_out < req_out:
                return (
                    "insufficient_disk_space",
                    f"Insufficient destination disk space on '{out_dir}': {free_out / (1024 * 1024):.1f} MB free, "
                    f"requires ~{req_out / (1024 * 1024):.1f} MB.",
                )
            if free_scratch < req_scratch:
                return (
                    "insufficient_disk_space",
                    f"Insufficient scratch/cache disk space on '{scratch_dir}': {free_scratch / (1024 * 1024):.1f} MB free, "
                    f"requires ~{req_scratch / (1024 * 1024):.1f} MB.",
                )
        return None, None

    def preflight_export(
        self,
        plan_id,
        output_path,
        approved=False,
        overwrite=False,
        approved_restricted_layers=False,
        confirm=None,
    ):
        """Validate all gates on the main thread and return ``(error_dict, context_dict)``."""
        effective_approved = bool(approved) if confirm is None else (bool(approved) or bool(confirm))
        if not effective_approved:
            return {
                "ok": False,
                "error_code": "approval_required",
                "error": (
                    "Explicit user approval (approved=True) for the exact plan and output path "
                    "is required before starting an SMP export."
                ),
            }, None

        if not plan_id or not isinstance(plan_id, str):
            return {"ok": False, "error_code": "invalid_plan_id", "error": "plan_id is required."}, None

        plan = self._plan_registry.get(plan_id)
        if plan is None:
            return {
                "ok": False,
                "error_code": "invalid_or_expired_plan",
                "error": f"Export plan '{plan_id}' was not found or has expired. Re-run smp_estimate.",
            }, None

        total_tiles = int(plan.export_plan.get("total_tiles", 0))
        if total_tiles > self._max_export_tiles:
            return {
                "ok": False,
                "error_code": "tile_limit_exceeded",
                "error": (
                    f"Export plan requires {total_tiles:,} tiles, exceeding the maximum allowed "
                    f"({self._max_export_tiles:,}). Shrink the extent or lower zoom levels."
                ),
            }, None

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
                }, None
            pol = classify_layer_policy(layer)
            if pol == "blocked_sensitive":
                return {
                    "ok": False,
                    "error_code": "blocked_sensitive_layer",
                    "error": f"Layer '{layer.name()}' is marked blocked_sensitive and cannot be exported.",
                }, None
            if pol == "restricted" and not approved_restricted_layers:
                return {
                    "ok": False,
                    "error_code": "restricted_layer_unapproved",
                    "error": (
                        f"Layer '{layer.name()}' is marked restricted. Explicit restricted-layer "
                        "authorization is required, or exclude it in smp_estimate."
                    ),
                }, None
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
            }, None

        canonical_output, manifest_path, err_code, err_msg = _canonicalize_writable_output_path(
            output_path, overwrite=bool(overwrite)
        )
        if err_code:
            return {"ok": False, "error_code": err_code, "error": err_msg}, None

        cache_dir = None
        if plan.cache_safe:
            cache_key = hashlib.sha256(
                f"{plan.plan_id}:{plan.project_fingerprint}".encode("utf-8")
            ).hexdigest()[:20]
            cache_dir = os.path.join(tempfile.gettempdir(), "awanagis_smp_cache", cache_key)

        disk_err_code, disk_err_msg = self._check_disk_budgets(plan, canonical_output, cache_dir)
        if disk_err_code:
            return {"ok": False, "error_code": disk_err_code, "error": disk_err_msg}, None

        summary = {
            "plan_id": plan_id,
            "output_path": canonical_output,
            "manifest_path": manifest_path,
            "overwrite": bool(overwrite),
            "tiles_total": total_tiles,
            "estimated_likely_bytes": plan.estimated_likely_bytes,
            "estimated_high_bytes": plan.estimated_high_bytes,
            "has_restricted_layers": plan.has_restricted_layers,
            "restricted_layers": [
                m["name"] for m in plan.effective_layer_meta if m["export_policy"] == "restricted"
            ],
            "remote_layer_warnings": list(plan.remote_layer_warnings),
            "layers": [m["name"] for m in plan.effective_layer_meta],
        }
        return None, {
            "plan": plan,
            "project": project,
            "render_layers": render_layers,
            "canonical_output": canonical_output,
            "manifest_path": manifest_path,
            "cache_dir": cache_dir,
            "summary": summary,
        }

    def start_export(
        self,
        plan_id,
        output_path,
        approved=False,
        overwrite=False,
        approved_restricted_layers=False,
        confirm=None,
        approval_callback=None,
        _trusted_approval_token=None,
    ):
        """Validate gates, verify trusted human approval, snapshot project, and queue QgsTask."""
        err, ctx = self.preflight_export(
            plan_id=plan_id,
            output_path=output_path,
            approved=approved,
            overwrite=overwrite,
            approved_restricted_layers=approved_restricted_layers,
            confirm=confirm,
        )
        if err is not None:
            return err

        plan = ctx["plan"]
        project = ctx["project"]
        render_layers = ctx["render_layers"]
        canonical_output = ctx["canonical_output"]
        manifest_path = ctx["manifest_path"]
        cache_dir = ctx["cache_dir"]
        summary = ctx["summary"]

        # Require a non-caller-forgeable trusted confirmation gate
        token_ok = self._consume_trusted_token(
            _trusted_approval_token,
            plan_id,
            canonical_output,
            overwrite,
            approved_restricted_layers,
        )
        if not token_ok:
            if not callable(approval_callback):
                return {
                    "ok": False,
                    "error_code": "trusted_approval_required",
                    "cancelled": True,
                    "error": (
                        "Trusted human confirmation via the AwanaGIS approval prompt (or an explicit "
                        "approval_callback) is required before starting an SMP export."
                    ),
                }
            if not bool(approval_callback(summary)):
                return {
                    "ok": False,
                    "error_code": "user_approval_denied",
                    "cancelled": True,
                    "error": "SMP export cancelled by user during confirmation.",
                }

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
            with tempfile.NamedTemporaryFile(
                dir=os.path.dirname(canonical_output),
                prefix=f".{os.path.basename(canonical_output)}.{job_id}.",
                suffix=".smp.tmp",
                delete=False,
            ) as tf:
                tmp_output = tf.name

            try:
                snapshot_project, cloned_layers = _build_isolated_project_snapshot(project, render_layers)
                cfg = plan.effective_config
                local_rect_proj = wgs84_bounds_to_project_rect(cfg["local_bounds_wgs84"], snapshot_project)
                region_rect_proj = (
                    wgs84_bounds_to_project_rect(cfg["region_bounds_wgs84"], snapshot_project)
                    if cfg["include_region"] else None
                )
            except Exception:
                _safe_unlink(tmp_output)
                raise

            job = SmpExportJob(
                job_id=job_id,
                plan_id=plan_id,
                output_path=canonical_output,
                tmp_output_path=tmp_output,
                manifest_path=manifest_path,
                cache_dir=cache_dir,
                tiles_total=plan.export_plan["total_tiles"],
                overwrite=bool(overwrite),
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
                snapshot_project,
                cloned_layers,
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
            if not job.done_event.is_set() and job.state in ("queued", "running", "validating", "publishing"):
                state = "cancelling"
            else:
                if job.state == "queued":
                    job.state = "cancelled"
                state = job.state

        return {
            "ok": True,
            "job_id": job.job_id,
            "state": state,
            "cancelled": state != "completed",
        }

    def cleanup_all(self, wait_seconds=5.0):
        """Cancel all active exports, wait for worker exit, and remove staging files."""
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
            if job.task is not None and hasattr(job.task, "_release_snapshot"):
                try:
                    job.task._release_snapshot()
                except Exception:
                    pass
            _safe_unlink(job.tmp_output_path)
        self._plan_registry.clear()
        with self._lock:
            self._trusted_tokens.clear()


_DEFAULT_EXPORT_MANAGER = ExportManager()


def get_export_manager():
    return _DEFAULT_EXPORT_MANAGER
