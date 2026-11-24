"""Cancellable, atomic source loader and QGIS layer registration for AwanaGIS Brazil."""

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
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
    """Build or fetch a valid EPSG:4674 polygon mask ``QgsVectorLayer`` for clipping."""
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


def _clip_to_mask(layer, mask_layer, target_name: str, feedback=None):
    import processing
    from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer

    if layer is None or not layer.isValid():
        return layer, "invalid_layer"
    if not layer.crs().isValid():
        layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))

    if mask_layer is None or not mask_layer.isValid():
        return layer, "bbox_filter_only"

    # Reproject mask to layer CRS if needed so native:clip stays accurate
    mask_to_use = mask_layer
    if layer.crs() != mask_layer.crs():
        try:
            reproj = processing.run(
                "native:reprojectlayer",
                {"INPUT": mask_layer, "TARGET_CRS": layer.crs(), "OUTPUT": "memory:"},
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
                feedback=feedback,
            ).get("OUTPUT")
            if fixed is not None and fixed.isValid():
                out = _run_clip(fixed)
        except Exception:
            out = None

    if isinstance(out, str):
        out = QgsProject.instance().mapLayer(out) or QgsVectorLayer(out, target_name, "ogr")
    if out is None or not out.isValid():
        return layer, "clip_failed"
    return out, "exact_polygon_clip"


def _write_vector_atomically(layer, gpkg_path: Path, layer_name: str, *, replace_existing: bool) -> Tuple[bool, str, Path]:
    """Write ``layer`` to ``gpkg_path`` safely using a temp staging GeoPackage first.

    If ``gpkg_path`` does not exist yet, writes to a temporary GeoPackage in the
    same directory, validates it, and atomically moves it with ``os.replace``.
    If ``gpkg_path`` already exists, first validates writing to a staging file,
    then writes the layer table into ``gpkg_path`` (falling back to a sidecar
    GeoPackage if ``gpkg_path`` cannot be modified safely).
    """
    from qgis.core import QgsProject, QgsVectorFileWriter, QgsVectorLayer

    gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    ctx = QgsProject.instance().transformContext()

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

        if not gpkg_path.exists():
            os.replace(str(tmp_path), str(gpkg_path))
            return True, "", gpkg_path

        # Existing GeoPackage: add or overwrite this table cleanly
        opts2 = QgsVectorFileWriter.SaveVectorOptions()
        opts2.driverName = "GPKG"
        opts2.layerName = layer_name
        opts2.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        err2, msg2 = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(gpkg_path), ctx, opts2)[:2]
        if err2 == QgsVectorFileWriter.WriterError.NoError:
            return True, "", gpkg_path

        # Fallback side-by-side file instead of corrupting an open/locked GeoPackage
        sidecar = gpkg_path.with_name(f"{gpkg_path.stem}_{layer_name}.gpkg")
        os.replace(str(tmp_path), str(sidecar))
        return True, f"Target GeoPackage busy ({msg2}); saved safely to sidecar {sidecar.name}.", sidecar
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _register_project_layer(project, layer, uri_key: str, *, replace_existing: bool):
    """Register ``layer`` in ``project`` without leaving duplicate layers."""
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
    fixture_override: Optional[str] = None,
):
    """Fetch a raw source layer via GISBR or audited Indigenous/INPE adapters.

    Returns ``(layer_or_none, status_hint, extra_warnings)``.
    """
    from qgis.core import QgsCoordinateReferenceSystem

    sid = source["source_id"]
    proto = source.get("protocol", "")
    srs = source.get("srs", "EPSG:4674")
    warnings: List[str] = []

    if fixture_override:
        vl = _load_fixture_vector(fixture_override, layer_name)
        if not vl.isValid():
            return None, "failed", [f"Fixture failed to load for {sid}."]
        return vl, "fixture", warnings

    allowed_hosts = get_allowed_hosts()
    svc_url = source.get("service_url") or ""
    if svc_url:
        raw_url = svc_url.format(ano=requested_year or source.get("source_year") or 2023) if "{ano}" in svc_url else svc_url
        ok_url, url_err = validate_allowlisted_url(raw_url, allowed_hosts)
        if not ok_url:
            return None, "failed", [url_err]

    # Curated Indigenous / INPE WFS adapters
    if source.get("catalog_origin") == "curated_indigenous":
        if proto != "wfs":
            return None, "failed", [f"Unsupported curated protocol '{proto}' for {sid}."]
        typename = source.get("typename") or ""
        if not typename:
            return None, "unavailable", [
                f"Source '{sid}' has no verified WFS typename yet (service endpoint requires live GetCapabilities)."
            ]
        cql_filter = None
        client_year_filter = None
        if sid == "inpe_prodes" and requested_year is not None:
            if bbox is not None:
                # Keep server-side bbox bound so we never scan the entire Amazon WFS
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
        if layer is not None and layer.isValid() and client_year_filter is not None:
            field_names = {f.name().lower(): f.name() for f in layer.fields()}
            if "year" in field_names:
                yfield = validate_cql_identifier(field_names["year"])
                layer.setSubsetString(f"{yfield} = {client_year_filter}")
        if layer is None or not layer.isValid():
            err_msg = getattr(layer, "error_msg", "WFS endpoint unreachable or returned invalid response")
            if sid in ("funai_ti_boundaries", "funai_dsei_areas"):
                warnings.append(
                    "Official FUNAI GeoServer was unreachable or failed TLS verification; "
                    "for TI boundaries you may explicitly select 'geobr_terras_indigenas' (dated mirror)."
                )
            return None, "unavailable", [redact_sensitive_text(err_msg)] + warnings
        return layer, "live", warnings

    # GISBR-backed sources
    raw = source.get("_raw_gisbr") or {}
    if proto == "raster_cog":
        ano = requested_year or raw.get("ano_default") or source.get("source_year") or 2023
        if mask_layer is None:
            return None, "failed", ["Raster COG clip requires a valid polygon mask."]
        tif_path = gpkg_path.parent / f"{sid}_{ano}_{_area_suffix(area)}.tif"
        url = svc_url.format(ano=ano) if "{ano}" in svc_url else svc_url
        rl = cog_raster.fetch_raster(url, mask_layer, str(tif_path), layer_name=layer_name, feedback=feedback)
        if rl is None or not rl.isValid():
            return None, "failed", [redact_sensitive_text(getattr(rl, "error_msg", "Failed reading COG raster."))]
        return rl, "live_raster", warnings

    if proto == "geobr":
        if source.get("requires_parquet") and capabilities.parquet_backend() is None:
            return None, "failed", ["Requires GDAL Parquet driver or optional pyarrow."]
        code_input = recorte if recorte is not None else "all"
        layer = gisbr_diag._carrega_geobr(raw, code_input, layer_name, ano=requested_year, feedback=feedback)
        if layer is None or not layer.isValid():
            return None, "failed", [redact_sensitive_text(getattr(layer, "error_msg", f"geobr failed for {sid}."))]
        if not layer.crs().isValid():
            layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4674"))
        return layer, "live", warnings

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
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"WFS failed for {sid}."))]
        return layer, "live", warnings

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
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"ArcGIS failed for {sid}."))]
        return layer, "live", warnings

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
            return None, "unavailable", [redact_sensitive_text(getattr(layer, "error_msg", f"zip_remoto failed for {sid}."))]
        return layer, "live", warnings

    if proto == "ibge_tabular":
        if recorte is None:
            return None, "failed", ["IBGE tabular sources require a municipality or regional Recorte."]
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
            return None, "unavailable", [redact_sensitive_text(getattr(tbl, "error_msg", f"IBGE tabular failed for {sid}."))]
        from .vendor.gisbr.core import agro_pipeline
        poly_layer, _rel = agro_pipeline.tabela_para_camada(
            tbl, codes_param, nome_muni=list(recorte.nomes) if recorte.nomes else recorte.rotulo,
            layer_name=layer_name, feedback=feedback,
        )
        if poly_layer is None or not poly_layer.isValid():
            return None, "failed", [f"Failed joining IBGE tabular data to municipality polygons for {sid}."]
        return poly_layer, "live", warnings

    return None, "failed", [f"Protocol '{proto}' is not supported by br_execute_load."]


def _area_suffix(area: Dict[str, Any]) -> str:
    atype = str(area.get("type") or "area").lower()
    aid = str(area.get("id") or area.get("ibge_code") or area.get("territory_id") or "custom")
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in aid.lower())
    return safe if atype in ("municipality", "municipio") else f"{atype}_{safe}"


def execute_load(
    plan_id: str,
    *,
    should_stop: Optional[Callable[[], bool]] = None,
    project=None,
    local_fixtures: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a frozen ``plan_id`` with hard policy checks, cancellation, and atomic output."""
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

    if _is_cancelled(should_stop):
        return {"ok": False, "status": "cancelled", "cancelled": True, "results": [], "error": "Cancelled before execution."}

    plan, plan_err = get_frozen_plan(plan_id)
    if plan is None:
        return {"ok": False, "status": "invalid_plan", "cancelled": False, "results": [], "error": plan_err}

    proj = project or QgsProject.instance()
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

    results: List[Dict[str, Any]] = []
    loaded_count = 0
    reused_count = 0
    failed_count = 0
    empty_count = 0
    cancelled = False

    # Include any non-ready items from the plan honestly in the summary
    planned_by_id = {item["source_id"]: item for item in plan.get("items") or []}

    for sid in plan["executable_ids"]:
        if _is_cancelled(should_stop):
            cancelled = True
            results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled by user."]})
            continue

        source = get_source(sid)
        if source is None:
            failed_count += 1
            results.append({"source_id": sid, "status": "failed", "layer_ids": [], "error": f"Unknown source '{sid}'."})
            continue

        # Re-check policy at execution time (defense in depth)
        allowed, reason_code, reason_msg = check_source_loadable(source, include_non_government=include_non_gov)
        if not allowed:
            failed_count += 1
            results.append({
                "source_id": sid,
                "status": reason_code,
                "layer_ids": [],
                "error": reason_msg,
            })
            continue

        if not mask_attempted:
            mask_attempted = True
            mask_layer = _mask_layer_from_area(area, feedback=feedback)

        bbox = _bbox_for_area(area, mask_layer)
        layer_name = f"{sid}_{suffix}"
        req_year = years_map.get(sid)
        planned_item = planned_by_id.get(sid, {})
        desired_clip = planned_item.get("clip_mode", "exact_polygon_clip")

        raw_layer, fetch_kind, fetch_warnings = _fetch_source_layer(
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
            fixture_override=fixtures.get(sid),
        )

        if _is_cancelled(should_stop):
            cancelled = True
            results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled during fetch."]})
            continue

        if raw_layer is None:
            failed_count += 1
            results.append({
                "source_id": sid,
                "status": fetch_kind if fetch_kind in ("unavailable", "failed") else "failed",
                "layer_ids": [],
                "warnings": fetch_warnings,
                "error": "; ".join(fetch_warnings) or f"Failed loading {sid}.",
            })
            continue

        extracted_at = _utc_now_iso()

        # Raster branch
        if isinstance(raw_layer, QgsRasterLayer):
            reg_layer = _register_project_layer(proj, raw_layer, raw_layer.source(), replace_existing=replace_existing)
            prov = tag_layer_provenance(
                reg_layer,
                source,
                area,
                clip_mode="exact_polygon_clip" if mask_layer is not None else "bbox_filter_only",
                extracted_at=extracted_at,
                output_path=raw_layer.source(),
                feature_count=None,
                truncated=False,
                catalog_version=CATALOG_VERSION,
            )
            loaded_count += 1
            results.append({
                "source_id": sid,
                "status": "loaded",
                "layer_ids": [reg_layer.id()],
                "layer_names": [reg_layer.name()],
                "feature_count": None,
                "output": raw_layer.source(),
                "clip_mode": prov["clip_mode"],
                "truncated": False,
                "provenance": prov,
                "warnings": fetch_warnings,
            })
            continue

        # Vector branch
        if raw_layer.featureCount() == 0:
            empty_count += 1
            results.append({
                "source_id": sid,
                "status": "empty",
                "layer_ids": [],
                "feature_count": 0,
                "warnings": fetch_warnings + ["Service returned 0 features for the requested area."],
            })
            continue

        truncated = bool(raw_layer.customProperty("truncado"))
        trunc_val = raw_layer.customProperty("truncado")
        if truncated:
            fetch_warnings.append(f"Service response truncated ({trunc_val}).")

        working_layer = raw_layer
        actual_clip_mode = desired_clip
        if desired_clip == "exact_polygon_clip":
            working_layer, actual_clip_mode = _clip_to_mask(raw_layer, mask_layer, layer_name, feedback=feedback)
            if working_layer is None or not working_layer.isValid():
                failed_count += 1
                results.append({
                    "source_id": sid,
                    "status": "failed",
                    "layer_ids": [],
                    "warnings": fetch_warnings,
                    "error": f"Polygon clip failed for {sid}.",
                })
                continue
            if working_layer.featureCount() == 0:
                empty_count += 1
                results.append({
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
            results.append({"source_id": sid, "status": "cancelled", "layer_ids": [], "warnings": ["Cancelled before persistence."]})
            continue

        ok_write, write_msg, actual_gpkg = _write_vector_atomically(
            working_layer, gpkg_path, layer_name, replace_existing=replace_existing
        )
        if write_msg:
            fetch_warnings.append(write_msg)
        if not ok_write:
            failed_count += 1
            results.append({
                "source_id": sid,
                "status": "failed",
                "layer_ids": [],
                "warnings": fetch_warnings,
                "error": write_msg,
            })
            continue

        gpkg_uri = f"{actual_gpkg}|layername={layer_name}"
        display_name = f"{source['name_pt']} — {area.get('name') or area.get('id')}"
        persisted = QgsVectorLayer(gpkg_uri, display_name, "ogr")
        if not persisted.isValid():
            failed_count += 1
            results.append({
                "source_id": sid,
                "status": "failed",
                "layer_ids": [],
                "warnings": fetch_warnings,
                "error": f"Persisted GeoPackage layer '{gpkg_uri}' failed to open.",
            })
            continue

        reg_layer = _register_project_layer(proj, persisted, gpkg_uri, replace_existing=replace_existing)
        fcount = reg_layer.featureCount()
        prov = tag_layer_provenance(
            reg_layer,
            source,
            area,
            clip_mode=actual_clip_mode,
            extracted_at=extracted_at,
            output_path=str(actual_gpkg),
            feature_count=fcount,
            truncated=truncated,
            catalog_version=CATALOG_VERSION,
        )
        loaded_count += 1
        results.append({
            "source_id": sid,
            "status": "truncated" if truncated else "loaded",
            "layer_ids": [reg_layer.id()],
            "layer_names": [reg_layer.name()],
            "feature_count": fcount,
            "output": str(actual_gpkg),
            "table_name": layer_name,
            "clip_mode": actual_clip_mode,
            "truncated": truncated,
            "provenance": prov,
            "warnings": fetch_warnings,
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
