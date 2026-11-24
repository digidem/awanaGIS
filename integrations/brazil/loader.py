"""Cancellable, atomic, worker-safe source loader and QGIS layer registration."""

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

from .catalog import get_allowed_hosts, get_source
from .manifest import CATALOG_VERSION
from .planner import get_frozen_plan
from .policy import (
    check_source_loadable,
    redact_sensitive_text,
    sanitize_cql_literal,
    tag_layer_provenance,
    validate_allowlisted_url,
    validate_cql_identifier,
)
from .vendor.gisbr.core import capabilities, diagnostico as gisbr_diag
from .vendor.gisbr.core.connectors import (
    arcgis_rest,
    cog_raster,
    ibge_agregados,
    wfs,
    zip_remoto,
)
from .vendor.gisbr.core.recorte import Recorte


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fold(text: Any) -> str:
    raw = str(text or "").lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


def _is_cancelled(should_stop: Optional[Callable[[], bool]]) -> bool:
    try:
        return bool(should_stop and should_stop())
    except Exception:
        return False


def _make_feedback(should_stop: Optional[Callable[[], bool]] = None):
    from qgis.core import QgsProcessingFeedback

    class _CancelFeedback(QgsProcessingFeedback):
        def __init__(self):
            super().__init__()
            self.warnings: List[str] = []

        def isCanceled(self):
            if _is_cancelled(should_stop):
                return True
            return super().isCanceled()

        def pushWarning(self, warning):
            self.warnings.append(str(warning))
            super().pushWarning(warning)

    return _CancelFeedback()


def _build_processing_context(transform_context=None):
    from qgis.core import QgsCoordinateTransformContext, QgsProcessingContext

    ctx = QgsProcessingContext()
    if transform_context is not None:
        ctx.setTransformContext(transform_context)
    else:
        ctx.setTransformContext(QgsCoordinateTransformContext())
    return ctx


def _build_recorte(area: Dict[str, Any]) -> Optional[Recorte]:
    atype = str(area.get("type") or "").lower()
    codes = [str(c) for c in (area.get("codes") or [])]
    nomes = [str(n) for n in (area.get("nomes") or [])]
    aid = str(area.get("id") or area.get("ibge_code") or "area")
    name = str(area.get("name") or aid)
    if atype == "municipality" and codes:
        return Recorte.de_municipio(codes[0], nomes[0] if nomes else name, bbox=area.get("bbox"))
    if atype == "metropolitan_region" and codes:
        return Recorte.de_rm(aid, name, codes, nomes)
    if atype in ("microregion", "mesoregion", "state", "macroregion") and codes:
        rec_type = area.get("recorte_type") or {
            "microregion": "micro",
            "mesoregion": "meso",
            "state": "uf",
            "macroregion": "macro",
        }[atype]
        return Recorte.de_agregado(rec_type, aid, name, codes, nomes)
    return None


def _mask_layer_from_area(area: Dict[str, Any], feedback=None):
    """Build or fetch a valid EPSG:4674 polygon mask ``QgsVectorLayer`` off the main thread."""
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    wkt = area.get("geometry_wkt")
    if wkt:
        geom = QgsGeometry.fromWkt(wkt)
        if geom is not None and not geom.isEmpty():
            vl = QgsVectorLayer("MultiPolygon?crs=EPSG:4674", "area_mask", "memory")
            prov = vl.dataProvider()
            feat = QgsFeature()
            feat.setGeometry(geom)
            prov.addFeatures([feat])
            vl.updateExtents()
            if vl.isValid() and vl.featureCount() > 0:
                return vl

    recorte = _build_recorte(area)
    if recorte is not None:
        if recorte.tipo == "municipio":
            layer = gisbr_diag._municipio_poligono(recorte.codes[0])
            if layer is not None and layer.isValid():
                return layer
        from .vendor.gisbr.core.recorte import camada_do_recorte

        layer = camada_do_recorte(recorte, feedback=feedback)
        if layer is not None and layer.isValid():
            return layer
    return None


def _bbox_for_area(area: Dict[str, Any], mask_layer) -> Optional[Tuple[float, float, float, float]]:
    bbox = area.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if mask_layer is not None and mask_layer.isValid():
        ext = mask_layer.extent()
        if not ext.isNull():
            return (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum())
    return None


def _clip_to_mask(layer, mask_layer, target_name: str, feedback=None, transform_context=None):
    """Clip ``layer`` to ``mask_layer`` without touching ``QgsProject.instance()``.

    Returns ``(clipped_layer, "exact_polygon_clip")`` on success,
    ``(layer, "bbox_filter_only")`` only when no mask exists, or
    ``(None, "clip_failed")`` when clipping fails (never returning uncut data as clipped).
    """
    import processing
    from qgis.core import QgsCoordinateReferenceSystem, QgsVectorLayer

    if layer is None or not layer.isValid():
        return None, "invalid_layer"
    if not layer.crs().isValid():
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))

    if mask_layer is None or not mask_layer.isValid():
        return layer, "bbox_filter_only"

    proc_ctx = _build_processing_context(transform_context)

    mask_to_use = mask_layer
    if layer.crs() != mask_layer.crs():
        try:
            reproj = processing.run(
                "native:reprojectlayer",
                {"INPUT": mask_layer, "TARGET_CRS": layer.crs(), "OUTPUT": "memory:"},
                context=proc_ctx,
                feedback=feedback,
            )
            cand = reproj.get("OUTPUT")
            if cand is not None and cand.isValid():
                mask_to_use = cand
        except Exception:
            pass

    def _run_clip(src_layer):
        return processing.run(
            "native:clip",
            {"INPUT": src_layer, "OVERLAY": mask_to_use, "OUTPUT": "memory:"},
            context=proc_ctx,
            feedback=feedback,
        ).get("OUTPUT")

    out = None
    try:
        out = _run_clip(layer)
    except Exception:
        # Real-world government WFS layers (e.g., INPE PRODES) frequently contain
        # minor self-intersections; repair geometries before retrying native:clip.
        try:
            fixed = processing.run(
                "native:fixgeometries",
                {"INPUT": layer, "OUTPUT": "memory:"},
                context=proc_ctx,
                feedback=feedback,
            ).get("OUTPUT")
            if fixed is not None and fixed.isValid():
                out = _run_clip(fixed)
        except Exception:
            out = None

    if isinstance(out, str):
        out = QgsVectorLayer(out, target_name, "ogr")
    if out is None or not out.isValid():
        return None, "clip_failed"
    return out, "exact_polygon_clip"


def _gpkg_has_layer(gpkg_path: Path, layer_name: str) -> bool:
    if not gpkg_path.exists():
        return False
    try:
        from qgis.core import QgsVectorLayer

        vl = QgsVectorLayer(str(gpkg_path), "probe_existing", "ogr")
        if not vl.isValid():
            return False
        for sub in vl.dataProvider().subLayers():
            parts = sub.split("!!::!!")
            if len(parts) > 1 and parts[1] == layer_name:
                return True
    except Exception:
        return False
    return False


@contextmanager
def _exclusive_file_lock(target_path: Path):
    """Advisory exclusive lock on a sibling ``.lock`` file when fcntl is available."""
    if fcntl is None:
        yield
        return
    lock_path = target_path.with_name(f".{target_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _atomic_publish_no_clobber(src: Path, dst: Path, *, replace_existing: bool) -> None:
    """Publish ``src`` to ``dst`` atomically, refusing to overwrite when ``replace_existing=False``."""
    if replace_existing:
        os.replace(str(src), str(dst))
        return
    try:
        os.link(str(src), str(dst))
    except OSError as exc:
        if exc.errno in (errno.EEXIST,):
            raise FileExistsError(dst) from exc
        if exc.errno in (errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP):
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(str(dst), flags, 0o644)
            try:
                with os.fdopen(fd, "wb") as out_f, open(src, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f)
                    out_f.flush()
                    os.fsync(out_f.fileno())
            except Exception:
                try:
                    dst.unlink()
                except OSError:
                    pass
                raise
        else:
            raise
    finally:
        if src.exists():
            try:
                src.unlink()
            except OSError:
                pass


def _write_vector_atomically(
    layer,
    gpkg_path: Path,
    layer_name: str,
    *,
    replace_existing: bool,
    transform_context=None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str, Path]:
    """Write ``layer`` to ``gpkg_path`` safely via staging and strict atomic no-clobber checks."""
    from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter, QgsVectorLayer

    gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    ctx = transform_context if transform_context is not None else QgsCoordinateTransformContext()

    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_awanagis_", suffix=".gpkg", dir=str(gpkg_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        if tmp_path.exists():
            tmp_path.unlink()
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = layer_name
        opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        err, msg = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(tmp_path), ctx, opts)[:2]
        if err != QgsVectorFileWriter.WriterError.NoError:
            return False, f"Failed writing staged GeoPackage: {msg}", gpkg_path

        check = QgsVectorLayer(f"{tmp_path}|layername={layer_name}", layer_name, "ogr")
        if not check.isValid():
            return False, "Staged GeoPackage failed validation.", gpkg_path
        del check

        if _is_cancelled(should_stop):
            return False, "Cancelled before committing GeoPackage.", gpkg_path

        with _exclusive_file_lock(gpkg_path):
            if not gpkg_path.exists():
                try:
                    _atomic_publish_no_clobber(tmp_path, gpkg_path, replace_existing=replace_existing)
                    return True, "", gpkg_path
                except FileExistsError:
                    pass

            if not replace_existing and _gpkg_has_layer(gpkg_path, layer_name):
                return (
                    False,
                    f"Refusing to overwrite existing layer '{layer_name}' in {gpkg_path.name} (replace_existing=false).",
                    gpkg_path,
                )

            opts2 = QgsVectorFileWriter.SaveVectorOptions()
            opts2.driverName = "GPKG"
            opts2.layerName = layer_name
            opts2.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            err2, msg2 = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(gpkg_path), ctx, opts2)[:2]
            if err2 == QgsVectorFileWriter.WriterError.NoError:
                return True, "", gpkg_path

            # Fallback side-by-side file instead of corrupting an open/locked GeoPackage
            sidecar = gpkg_path.with_name(f"{gpkg_path.stem}_{layer_name}.gpkg")
            try:
                _atomic_publish_no_clobber(tmp_path, sidecar, replace_existing=replace_existing)
            except FileExistsError:
                return (
                    False,
                    f"Target GeoPackage busy ({msg2}) and sidecar '{sidecar.name}' already exists (replace_existing=false).",
                    gpkg_path,
                )
            return True, f"Target GeoPackage busy ({msg2}); saved safely to sidecar {sidecar.name}.", sidecar
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _stage_raster_atomically(
    url: str,
    mask_layer,
    tif_path: Path,
    layer_name: str,
    *,
    replace_existing: bool,
    feedback=None,
    should_stop: Optional[Callable[[], bool]] = None,
    fixture_override: Optional[str] = None,
) -> Tuple[Optional[Path], str, List[str]]:
    """Fetch/clip raster to a staging GeoTIFF, validate, check cancel/overwrite, then promote atomically."""
    from qgis.core import QgsRasterLayer

    warnings: List[str] = []
    if tif_path.exists() and not replace_existing:
        return (
            None,
            "failed",
            [f"Refusing to overwrite existing raster '{tif_path.name}' (replace_existing=false)."],
        )

    tif_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_awanagis_", suffix=".tif", dir=str(tif_path.parent))
    os.close(fd)
    tmp_tif = Path(tmp_name)
    try:
        if tmp_tif.exists():
            tmp_tif.unlink()

        if fixture_override:
            shutil.copy2(str(fixture_override), str(tmp_tif))
            fetch_kind = "fixture_raster"
        else:
            rl = cog_raster.fetch_raster(url, mask_layer, str(tmp_tif), layer_name=layer_name, feedback=feedback)
            if rl is None or not rl.isValid():
                err_msg = getattr(rl, "error_msg", "Failed reading COG raster.")
                return None, "failed", [redact_sensitive_text(err_msg)]
            del rl
            fetch_kind = "live_raster"

        if _is_cancelled(should_stop):
            return None, "cancelled", ["Cancelled before committing staged raster."]

        check = QgsRasterLayer(str(tmp_tif), layer_name, "gdal")
        if not check.isValid() or check.width() <= 0 or check.height() <= 0:
            return None, "failed", ["Staged GeoTIFF raster failed validation."]
        del check

        try:
            _atomic_publish_no_clobber(tmp_tif, tif_path, replace_existing=replace_existing)
        except FileExistsError:
            return (
                None,
                "failed",
                [f"Refusing to overwrite existing raster '{tif_path.name}' (replace_existing=false)."],
            )
        return tif_path, fetch_kind, warnings
    finally:
        for candidate in tif_path.parent.glob(f"{tmp_tif.name}*"):
            try:
                candidate.unlink()
            except OSError:
                pass


def _register_project_layer(project, layer, uri_key: str, *, replace_existing: bool):
    """Register ``layer`` in ``project`` on the main thread without leaving duplicates."""
    if replace_existing:
        for existing in list(project.mapLayers().values()):
            try:
                if existing.source() == uri_key or existing.name() == layer.name():
                    project.removeMapLayer(existing.id())
            except Exception:
                pass
    else:
        for existing in project.mapLayers().values():
            try:
                if existing.source() == uri_key:
                    return existing
            except Exception:
                pass
    added = project.addMapLayer(layer)
    return added or layer


def _load_fixture_vector(fixture_path: str, layer_name: str):
    from qgis.core import QgsCoordinateReferenceSystem, QgsVectorLayer

    vl = QgsVectorLayer(str(fixture_path), layer_name, "ogr")
    if vl.isValid() and not vl.crs().isValid():
        vl.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))
    return vl


def _codes_equal(a: Any, b: Any) -> bool:
    sa = str(a if a is not None else "").strip()
    sb = str(b if b is not None else "").strip()
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    try:
        return int(float(sa)) == int(float(sb))
    except (ValueError, TypeError):
        return False


def _filter_ti_layer(layer, area: Dict[str, Any], layer_name: str):
    """Filter a national/multi-TI layer to the specifically requested TI by ID or name."""
    from qgis.core import QgsFeature, QgsVectorLayer, QgsWkbTypes

    target_code = str(area.get("terrai_cod") or area.get("territory_id") or "").strip()
    target_name = _fold(area.get("name") or "")
    target_ufs = {str(u).strip().upper() for u in (area.get("ufs") or []) if str(u).strip()}

    field_names = {f.name().lower(): f.name() for f in layer.fields()}
    code_field = next((field_names[k] for k in ("code_terrai", "terrai_cod", "terrai_codigo") if k in field_names), None)
    name_field = next((field_names[k] for k in ("name_indigenous_land", "terrai_nom", "nome_ti") if k in field_names), None)
    uf_field = next((field_names[k] for k in ("abbrev_state", "uf_sigla", "uf") if k in field_names), None)

    matched_features = []
    for feat in layer.getFeatures():
        matched = False
        if target_code and code_field and _codes_equal(feat[code_field], target_code):
            matched = True
        elif target_name and name_field:
            fn = _fold(feat[name_field])
            if fn == target_name:
                if target_ufs and uf_field:
                    raw_uf = str(feat[uf_field] or "").upper()
                    feat_ufs = {tok.strip() for tok in re.split(r"[,;/\s]+", raw_uf) if tok.strip()}
                    if not feat_ufs or (feat_ufs & target_ufs):
                        matched = True
                else:
                    matched = True
        if matched:
            matched_features.append(feat)

    if not matched_features:
        return None

    geom_str = QgsWkbTypes.displayString(layer.wkbType()) or "MultiPolygon"
    crs_auth = layer.crs().authid() or "EPSG:4674"
    filtered = QgsVectorLayer(f"{geom_str}?crs={crs_auth}", layer_name, "memory")
    prov = filtered.dataProvider()
    prov.addAttributes(list(layer.fields()))
    filtered.updateFields()
    out_feats = []
    for src_f in matched_features:
        nf = QgsFeature(filtered.fields())
        nf.setGeometry(src_f.geometry())
        nf.setAttributes(src_f.attributes())
        out_feats.append(nf)
    prov.addFeatures(out_feats)
    filtered.updateExtents()
    return filtered if filtered.isValid() and filtered.featureCount() > 0 else None


def _effective_data_reference_year(
    source: Dict[str, Any],
    layer: Any,
    requested_year: Optional[int],
    *,
    is_raster: bool = False,
    loader_year: Any = None,
    year_applied: bool = False,
) -> Any:
    """Determine the honest reference year actually represented by the loaded output."""
    if is_raster:
        return int(loader_year) if loader_year is not None else "unknown"
    if loader_year is not None:
        return loader_year

    # Inspect feature year/ano attribute when available (bounded scan)
    if layer is not None and hasattr(layer, "fields"):
        try:
            field_names = {f.name().lower(): f.name() for f in layer.fields()}
            yfield = next((field_names[k] for k in ("year", "ano", "ano_referencia") if k in field_names), None)
            if yfield:
                years_seen = set()
                for idx, feat in enumerate(layer.getFeatures()):
                    if idx >= 5000:
                        break
                    val = feat[yfield]
                    if val is not None:
                        try:
                            yint = int(str(val).strip()[:4])
                            if 1800 <= yint <= 2100:
                                years_seen.add(yint)
                        except (ValueError, TypeError):
                            pass
                if len(years_seen) == 1:
                    return next(iter(years_seen))
                if len(years_seen) > 1:
                    return f"{min(years_seen)}-{max(years_seen)}"
        except Exception:
            pass

    if year_applied and requested_year is not None:
        return int(requested_year)
    if source.get("source_id") == "inpe_prodes":
        return "unknown"
    src_year = source.get("source_year")
    return src_year if src_year is not None else "unknown"


def _fetch_source_layer(
    source: Dict[str, Any],
    area: Dict[str, Any],
    recorte: Optional[Recorte],
    mask_layer,
    bbox,
    layer_name: str,
    gpkg_path: Path,
    *,
    requested_year: Optional[int],
    replace_existing: bool,
    feedback,
    should_stop: Optional[Callable[[], bool]] = None,
    fixture_override: Optional[str] = None,
):
    """Fetch a raw source layer via GISBR or audited Indigenous/INPE adapters.

    Returns ``(layer_or_path_or_none, status_hint, extra_warnings, raster_year)``.
    """
    from qgis.core import QgsCoordinateReferenceSystem

    sid = source["source_id"]
    proto = source.get("protocol", "")
    srs = source.get("srs", "EPSG:4674")
    warnings: List[str] = []

    if proto == "raster_cog":
        ano = int(requested_year or (source.get("_raw_gisbr") or {}).get("ano_default") or source.get("source_year") or 2023)
        if not fixture_override and mask_layer is None:
            return None, "failed", ["Raster COG clip requires a valid polygon mask."], ano
        allowed_hosts = get_allowed_hosts()
        svc_url = source.get("service_url") or ""
        url = svc_url.format(ano=ano) if "{ano}" in svc_url else svc_url
        if not fixture_override and url:
            ok_url, url_err = validate_allowlisted_url(url, allowed_hosts)
            if not ok_url:
                return None, "failed", [url_err], ano
        tif_path = gpkg_path.parent / f"{sid}_{ano}_{_area_suffix(area)}.tif"
        staged_path, fetch_kind, r_warnings = _stage_raster_atomically(
            url,
            mask_layer,
            tif_path,
            layer_name,
            replace_existing=replace_existing,
            feedback=feedback,
            should_stop=should_stop,
            fixture_override=fixture_override,
        )
        return staged_path, fetch_kind, warnings + r_warnings, ano

    if fixture_override:
        vl = _load_fixture_vector(fixture_override, layer_name)
        if not vl.isValid():
            return None, "failed", [f"Fixture failed to load for {sid}."], None
        if sid in ("geobr_terras_indigenas", "funai_ti_boundaries") and area.get("type") == "indigenous_territory" and not area.get("geometry_wkt"):
            filtered = _filter_ti_layer(vl, area, layer_name)
            if filtered is None:
                return None, "failed", [
                    f"Territory '{area.get('name') or area.get('terrai_cod')}' was not matched in {sid}; refusing to save unrelated national TIs under that territory name."
                ], None
            vl = filtered
        return vl, "fixture", warnings, None

    allowed_hosts = get_allowed_hosts()
    svc_url = source.get("service_url") or ""
    if svc_url:
        raw_url = svc_url.format(ano=requested_year or source.get("source_year") or 2023) if "{ano}" in svc_url else svc_url
        ok_url, url_err = validate_allowlisted_url(raw_url, allowed_hosts)
        if not ok_url:
            return None, "failed", [url_err], None

    # Curated Indigenous / INPE WFS adapters
    if source.get("catalog_origin") == "curated_indigenous":
        if proto != "wfs":
            return None, "failed", [f"Unsupported curated protocol '{proto}' for {sid}."], None
        typename = source.get("typename") or ""
        if not typename:
            return None, "unavailable", [
                f"Source '{sid}' has no verified WFS typename yet (service endpoint requires live GetCapabilities)."
            ], None
        cql_filter = None
        client_year_filter = None
        if sid == "inpe_prodes" and requested_year is not None:
            if bbox is not None:
                client_year_filter = int(requested_year)
            else:
                field = validate_cql_identifier("year")
                cql_filter = f"{field} = {int(requested_year)}"
        elif sid == "funai_ti_boundaries" and area.get("terrai_cod"):
            field = validate_cql_identifier("terrai_cod")
            cql_filter = f"{field} = '{sanitize_cql_literal(area['terrai_cod'])}'"

        layer = wfs.fetch_layer(
            svc_url,
            typename,
            layer_name,
            srs=srs,
            cql_filter=cql_filter,
            bbox=(bbox if not cql_filter else None),
            feedback=feedback,
        )
        if layer is None or not layer.isValid():
            err_msg = getattr(layer, "error_msg", "WFS endpoint unreachable or returned invalid response")
            if sid in ("funai_ti_boundaries", "funai_dsei_areas"):
                warnings.append(
                    "Official FUNAI GeoServer was unreachable or failed TLS verification; "
                    "for TI boundaries you may explicitly select 'geobr_terras_indigenas' (dated mirror)."
                )
            return None, "unavailable", [redact_sensitive_text(err_msg)] + warnings, None
        if client_year_filter is not None:
            field_names = {f.name().lower(): f.name() for f in layer.fields()}
            if "year" in field_names:
                yfield = validate_cql_identifier(field_names["year"])
                layer.setSubsetString(f"{yfield} = {client_year_filter}")
        return layer, "live", warnings, None

    # GISBR-backed sources
    raw = source.get("_raw_gisbr") or {}
    if proto == "geobr":
        if source.get("requires_parquet") and capabilities.parquet_backend() is None:
            return None, "failed", ["Requires GDAL Parquet driver or optional pyarrow."], None
        code_input = recorte if recorte is not None else "all"
        layer = gisbr_diag._carrega_geobr(raw, code_input, layer_name, ano=requested_year, feedback=feedback)
        if layer is None or not layer.isValid():
            return None, "failed", [redact_sensitive_text(getattr(layer, "error_msg", f"geobr failed for {sid}."))], None
        if not layer.crs().isValid():
            layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))
        if sid == "geobr_terras_indigenas" and area.get("type") == "indigenous_territory" and not area.get("geometry_wkt"):
            filtered = _filter_ti_layer(layer, area, layer_name)
            if filtered is None:
                return None, "failed", [
                    f"Territory '{area.get('name') or area.get('terrai_cod')}' was not matched in geobr_terras_indigenas; refusing to save all Brazilian TIs under a single TI name."
                ], None
            layer = filtered
        return layer, "live", warnings, None

    if proto == "wfs":
        ufs = area.get("ufs") or []
        uf_lower = ufs[0].lower() if ufs else ""
        type_name = raw["type_name"].replace("{uf}", uf_lower)
        cql, usa_bbox = gisbr_diag._filtro_para(raw, recorte) if recorte is not None else (None, True)
        layer = wfs.fetch_layer(
            raw["endpoint"],
            type_name,
            layer_name,
            srs=srs,
            cql_filter=cql,
            bbox=(bbox if usa_bbox else None),
            feedback=feedback,
        )
        if layer is None or not layer.isValid():
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"WFS failed for {sid}."))], None
        return layer, "live", warnings, None

    if proto == "arcgis":
        cql, usa_bbox = gisbr_diag._filtro_para(raw, recorte) if recorte is not None else (None, True)
        layer = arcgis_rest.fetch_layer(
            raw["endpoint"],
            raw["layer_id"],
            layer_name,
            srs=srs,
            where=cql,
            bbox=(bbox if usa_bbox else None),
            feedback=feedback,
        )
        if layer is None or not layer.isValid():
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"ArcGIS failed for {sid}."))], None
        return layer, "live", warnings, None

    if proto == "zip_remoto":
        url = raw.get("url") or raw.get("endpoint") or raw.get("origem_url")
        layer = zip_remoto.fetch_layer(
            url,
            layer_name,
            srs=srs,
            subset=raw.get("subset"),
            feedback=feedback,
            cache_id=raw.get("cache_id"),
            refresh=replace_existing,
        )
        if layer is None or not layer.isValid():
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"zip_remoto failed for {sid}."))], None
        return layer, "live", warnings, None

    if proto == "ibge_tabular":
        if recorte is None:
            return None, "failed", ["IBGE tabular sources require a municipality or regional Recorte."], None
        codes_param = list(recorte.codes)
        tbl = ibge_agregados.fetch_layer(
            raw["agregado"],
            codes_param,
            layer_name,
            variaveis=raw.get("variaveis", "all"),
            periodo=raw.get("periodo_default", "-1"),
            classificacao=raw.get("classificacao"),
            feedback=feedback,
        )
        if tbl is None or not tbl.isValid():
            return None, "unavailable", [redact_sensitive_text(getattr(tbl, "error_msg", f"IBGE tabular failed for {sid}."))], None
        from .vendor.gisbr.core import agro_pipeline

        poly_layer, _rel = agro_pipeline.tabela_para_camada(
            tbl,
            codes_param,
            nome_muni=list(recorte.nomes) if recorte.nomes else recorte.rotulo,
            layer_name=layer_name,
            feedback=feedback,
        )
        if poly_layer is None or not poly_layer.isValid():
            return None, "failed", [f"Failed joining IBGE tabular data to municipality polygons for {sid}."], None
        return poly_layer, "live", warnings, None

    return None, "failed", [f"Protocol '{proto}' is not supported by br_execute_load."], None


def _area_suffix(area: Dict[str, Any]) -> str:
    atype = str(area.get("type") or "area").lower()
    aid = str(area.get("id") or area.get("ibge_code") or area.get("territory_id") or "custom")
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in aid.lower())
    return safe if atype in ("municipality", "municipio") else f"{atype}_{safe}"


def prepare_load_context(project=None) -> Dict[str, Any]:
    """Snapshot main-thread QGIS project transformContext prior to worker execution."""
    from qgis.core import QgsCoordinateTransformContext, QgsProject

    proj = project or QgsProject.instance()
    try:
        tctx = proj.transformContext()
    except Exception:
        tctx = QgsCoordinateTransformContext()
    return {"transform_context": tctx}


def run_load_worker(
    plan: Dict[str, Any],
    *,
    transform_context=None,
    should_stop: Optional[Callable[[], bool]] = None,
    local_fixtures: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Perform all network retrieval, clipping, and staged disk writes off the GUI thread."""
    if _is_cancelled(should_stop):
        return {"cancelled": True, "staged": [], "immediate_results": []}

    area = plan["area"]
    gpkg_path = Path(plan["output_gpkg"])
    replace_existing = bool(plan.get("replace_existing", False))
    include_non_gov = bool(plan.get("include_non_government", False))
    years_map = dict(plan.get("years") or {})
    fixtures = dict(local_fixtures or {})
    feedback = _make_feedback(should_stop)

    recorte = _build_recorte(area)
    mask_layer = None
    mask_attempted = False
    suffix = _area_suffix(area)

    planned_by_id = {item["source_id"]: item for item in plan.get("items") or []}
    staged: List[Dict[str, Any]] = []
    immediate_results: List[Dict[str, Any]] = []
    cancelled = False

    for sid in plan["executable_ids"]:
        if _is_cancelled(should_stop):
            cancelled = True
            immediate_results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled by user."]})
            continue

        source = get_source(sid)
        if source is None:
            immediate_results.append({"source_id": sid, "status": "failed", "layer_ids": [], "error": f"Unknown source '{sid}'."})
            continue

        allowed, reason_code, reason_msg = check_source_loadable(source, include_non_government=include_non_gov)
        if not allowed:
            immediate_results.append({"source_id": sid, "status": reason_code, "layer_ids": [], "error": reason_msg})
            continue

        try:
            if not mask_attempted:
                mask_attempted = True
                mask_layer = _mask_layer_from_area(area, feedback=feedback)

            bbox = _bbox_for_area(area, mask_layer)
            layer_name = f"{sid}_{suffix}"
            req_year = years_map.get(sid)
            planned_item = planned_by_id.get(sid, {})
            desired_clip = planned_item.get("clip_mode", "exact_polygon_clip")

            if _is_cancelled(should_stop):
                cancelled = True
                immediate_results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled before fetch."]})
                continue

            raw_res, fetch_kind, fetch_warnings, raster_year = _fetch_source_layer(
                source,
                area,
                recorte,
                mask_layer,
                bbox,
                layer_name,
                gpkg_path,
                requested_year=req_year,
                replace_existing=replace_existing,
                feedback=feedback,
                should_stop=should_stop,
                fixture_override=fixtures.get(sid),
            )

            if fetch_kind == "cancelled" or _is_cancelled(should_stop):
                cancelled = True
                immediate_results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled during fetch."]})
                continue

            if raw_res is None:
                immediate_results.append({
                    "source_id": sid,
                    "status": fetch_kind if fetch_kind in ("unavailable", "failed") else "failed",
                    "layer_ids": [],
                    "warnings": fetch_warnings,
                    "error": "; ".join(fetch_warnings) or f"Failed loading {sid}.",
                })
                continue

            extracted_at = _utc_now_iso()

            # Raster branch (already staged, validated, and promoted to Path)
            if isinstance(raw_res, Path):
                staged.append({
                    "kind": "raster",
                    "source": source,
                    "uri": str(raw_res),
                    "display_name": f"{source['name_pt']} — {area.get('name') or area.get('id')}",
                    "output_path": str(raw_res),
                    "table_name": raw_res.stem,
                    "clip_mode": "exact_polygon_clip" if mask_layer is not None else "bbox_filter_only",
                    "extracted_at": extracted_at,
                    "feature_count": None,
                    "truncated": False,
                    "data_reference_year": _effective_data_reference_year(
                        source, None, req_year, is_raster=True, loader_year=raster_year, year_applied=True
                    ),
                    "warnings": fetch_warnings,
                })
                continue

            # Vector branch
            if raw_res.featureCount() == 0:
                immediate_results.append({
                    "source_id": sid,
                    "status": "empty",
                    "layer_ids": [],
                    "feature_count": 0,
                    "warnings": fetch_warnings + ["Service returned 0 features for the requested area."],
                })
                continue

            truncated = bool(raw_res.customProperty("truncado"))
            trunc_val = raw_res.customProperty("truncado")
            if truncated:
                fetch_warnings.append(f"Service response truncated ({trunc_val}).")

            working_layer = raw_res
            actual_clip_mode = desired_clip
            if desired_clip == "exact_polygon_clip":
                if area.get("geometry_wkt") and (mask_layer is None or not mask_layer.isValid()):
                    immediate_results.append({
                        "source_id": sid,
                        "status": "failed",
                        "layer_ids": [],
                        "warnings": fetch_warnings,
                        "error": f"Polygon mask unavailable for exact clipping of {sid}; refusing to save uncut data.",
                    })
                    continue
                working_layer, actual_clip_mode = _clip_to_mask(
                    raw_res,
                    mask_layer,
                    layer_name,
                    feedback=feedback,
                    transform_context=transform_context,
                )
                if actual_clip_mode == "clip_failed" or working_layer is None or not working_layer.isValid():
                    immediate_results.append({
                        "source_id": sid,
                        "status": "failed",
                        "layer_ids": [],
                        "warnings": fetch_warnings,
                        "error": f"Polygon clip failed for {sid}; uncut data was not saved.",
                    })
                    continue
                if working_layer.featureCount() == 0:
                    immediate_results.append({
                        "source_id": sid,
                        "status": "empty",
                        "layer_ids": [],
                        "feature_count": 0,
                        "clip_mode": actual_clip_mode,
                        "warnings": fetch_warnings + ["0 features remained inside the exact polygon mask after clipping."],
                    })
                    continue

            if _is_cancelled(should_stop):
                cancelled = True
                immediate_results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled before persistence."]})
                continue

            proto_used = str(source.get("protocol") or "")
            if proto_used == "ibge_tabular":
                raw_cfg = source.get("_raw_gisbr") or {}
                period_used = raw_cfg.get("periodo_default")
                effective_year = _effective_data_reference_year(
                    source,
                    working_layer,
                    req_year,
                    loader_year=period_used if period_used not in (None, "", "-1") else "latest_period",
                    year_applied=False,
                )
            else:
                year_was_applied = bool(
                    req_year is not None
                    and (
                        proto_used == "geobr"
                        or (
                            source.get("source_id") == "inpe_prodes"
                            and any(f.name().lower() == "year" for f in working_layer.fields())
                        )
                    )
                )
                effective_year = _effective_data_reference_year(
                    source, working_layer, req_year, year_applied=year_was_applied
                )

            ok_write, write_msg, actual_gpkg = _write_vector_atomically(
                working_layer,
                gpkg_path,
                layer_name,
                replace_existing=replace_existing,
                transform_context=transform_context,
                should_stop=should_stop,
            )
            if write_msg:
                fetch_warnings.append(write_msg)
            if not ok_write:
                is_cancel_err = _is_cancelled(should_stop) or "Cancelled" in write_msg
                if is_cancel_err:
                    cancelled = True
                immediate_results.append({
                    "source_id": sid,
                    "status": "cancelled" if is_cancel_err else "failed",
                    "layer_ids": [],
                    "warnings": fetch_warnings,
                    "error": write_msg,
                })
                continue

            gpkg_uri = f"{actual_gpkg}|layername={layer_name}"
            staged.append({
                "kind": "vector",
                "source": source,
                "uri": gpkg_uri,
                "display_name": f"{source['name_pt']} — {area.get('name') or area.get('id')}",
                "output_path": str(actual_gpkg),
                "table_name": layer_name,
                "clip_mode": actual_clip_mode,
                "extracted_at": extracted_at,
                "feature_count": working_layer.featureCount(),
                "truncated": truncated,
                "data_reference_year": effective_year,
                "warnings": fetch_warnings,
            })
        except Exception as exc:
            immediate_results.append({
                "source_id": sid,
                "status": "failed",
                "layer_ids": [],
                "warnings": [],
                "error": redact_sensitive_text(f"Source load failed ({type(exc).__name__}): {exc}", redact_coordinates=True),
            })

    return {
        "cancelled": cancelled,
        "staged": staged,
        "immediate_results": immediate_results,
    }


def commit_load_results(
    plan_id: str,
    plan: Dict[str, Any],
    worker_output: Dict[str, Any],
    *,
    project=None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Register validated persisted layers in ``QgsProject`` on the main thread."""
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

    proj = project or QgsProject.instance()
    area = plan["area"]
    replace_existing = bool(plan.get("replace_existing", False))

    results: List[Dict[str, Any]] = list(worker_output.get("immediate_results") or [])
    cancelled = bool(worker_output.get("cancelled"))
    loaded_count = 0
    reused_count = 0
    failed_count = sum(1 for r in results if r.get("status") in ("failed", "unavailable"))
    empty_count = sum(1 for r in results if r.get("status") == "empty")

    for item in worker_output.get("staged") or []:
        sid = item["source"]["source_id"]
        if _is_cancelled(should_stop):
            cancelled = True
            results.append({
                "source_id": sid,
                "status": "cancelled",
                "layer_ids": [],
                "warnings": ["Cancelled before project registration; layer not added to project."],
            })
            continue

        if item["kind"] == "raster":
            layer = QgsRasterLayer(item["uri"], item["display_name"], "gdal")
        else:
            layer = QgsVectorLayer(item["uri"], item["display_name"], "ogr")

        if not layer.isValid():
            failed_count += 1
            results.append({
                "source_id": sid,
                "status": "failed",
                "layer_ids": [],
                "warnings": item.get("warnings", []),
                "error": f"Persisted layer '{item['uri']}' failed to open.",
            })
            continue

        reg_layer = _register_project_layer(proj, layer, item["uri"], replace_existing=replace_existing)
        fcount = reg_layer.featureCount() if item["kind"] == "vector" else None
        prov = tag_layer_provenance(
            reg_layer,
            item["source"],
            area,
            clip_mode=item["clip_mode"],
            extracted_at=item["extracted_at"],
            output_path=item["output_path"],
            feature_count=fcount,
            truncated=item["truncated"],
            catalog_version=CATALOG_VERSION,
            data_reference_year=item.get("data_reference_year"),
        )
        loaded_count += 1
        results.append({
            "source_id": sid,
            "status": "truncated" if item["truncated"] else "loaded",
            "layer_ids": [reg_layer.id()],
            "layer_names": [reg_layer.name()],
            "feature_count": fcount,
            "output": item["output_path"],
            "table_name": item["table_name"],
            "clip_mode": item["clip_mode"],
            "truncated": item["truncated"],
            "provenance": prov,
            "warnings": item.get("warnings", []),
        })

    # Include skipped/manual items from plan for complete accounting
    for item in plan.get("items") or []:
        if item.get("readiness") == "skipped":
            reused_count += 1
            results.append({
                "source_id": item["source_id"],
                "status": "reused",
                "layer_ids": [],
                "output": item.get("output_target"),
                "warnings": [item.get("reason", "Already exists; reused.")],
            })
        elif item.get("readiness") == "manual":
            results.append({
                "source_id": item["source_id"],
                "status": "manual_required",
                "layer_ids": [],
                "instructions": item.get("reason"),
                "portal_url": item.get("portal_url", ""),
                "warnings": [],
            })

    if cancelled and loaded_count == 0:
        overall_status = "cancelled"
    elif loaded_count > 0 and (failed_count > 0 or empty_count > 0 or cancelled):
        overall_status = "partial"
    elif loaded_count > 0:
        overall_status = "loaded"
    elif reused_count > 0 and failed_count == 0:
        overall_status = "reused"
    elif empty_count > 0 and failed_count == 0:
        overall_status = "empty"
    else:
        overall_status = "failed"

    return {
        "ok": overall_status in ("loaded", "reused", "partial", "empty"),
        "status": overall_status,
        "plan_id": plan_id,
        "area": {
            "type": area.get("type"),
            "id": area.get("id"),
            "name": area.get("name"),
            "ufs": area.get("ufs"),
        },
        "results": results,
        "cancelled": cancelled,
    }


def execute_load(
    plan_id: str,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
    project=None,
    local_fixtures: Optional[Dict[str, str]] = None,
    executor=None,
) -> Dict[str, Any]:
    """Execute a frozen ``plan_id`` with main-thread project isolation, cancellation, and atomic output."""
    if _is_cancelled(should_stop):
        return {"ok": False, "status": "cancelled", "cancelled": True, "results": [], "error": "Cancelled before execution."}

    plan, plan_err = get_frozen_plan(plan_id)
    if plan is None:
        return {"ok": False, "status": "invalid_plan", "cancelled": False, "results": [], "error": plan_err}

    if executor is not None:
        ctx = executor.run_sync(lambda: prepare_load_context(project))
    else:
        ctx = prepare_load_context(project)

    worker_out = run_load_worker(
        plan,
        transform_context=ctx.get("transform_context"),
        should_stop=should_stop,
        local_fixtures=local_fixtures,
    )

    if executor is not None:
        return executor.run_sync(
            lambda: commit_load_results(plan_id, plan, worker_out, project=project, should_stop=should_stop)
        )
    return commit_load_results(plan_id, plan, worker_out, project=project, should_stop=should_stop)
