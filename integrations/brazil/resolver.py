"""Geographic area resolver for Brazilian administrative units, QGIS layers, and Indigenous territories.

Uses GISBR's bundled IBGE regional/metropolitan CSVs (all ~5,570 municipalities)
for offline code validation and multi-UF name disambiguation, optional live IBGE
API enrichment when reachable, QGIS project layer inspection, and a curated
FUNAI TI index for ``indigenous_territory`` resolution.
"""

import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .vendor.gisbr.core.constants import UF_ABBREV_TO_CODE, UF_CODE_TO_ABBREV

_DATA_DIR = Path(__file__).resolve().parent / "data"
_GISBR_DATA_DIR = Path(__file__).resolve().parent / "vendor" / "gisbr" / "core" / "data"

_VALID_AREA_TYPES = {
    "municipality",
    "state",
    "metropolitan_region",
    "microregion",
    "mesoregion",
    "macroregion",
    "project_layer",
    "indigenous_territory",
}

_UF_NAMES = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo",
    "SE": "Sergipe",
    "TO": "Tocantins",
}

_MUNI_ROWS: Optional[List[Dict[str, str]]] = None
_MUNI_BY_CODE: Optional[Dict[str, Dict[str, str]]] = None
_RM_BY_ID: Optional[Dict[str, Dict[str, Any]]] = None
_TI_INDEX: Optional[List[Dict[str, Any]]] = None


def _fold(text: Any) -> str:
    raw = str(text or "").lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip()


def _load_divisao_regional() -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, str]]]:
    global _MUNI_ROWS, _MUNI_BY_CODE
    if _MUNI_ROWS is not None and _MUNI_BY_CODE is not None:
        return _MUNI_ROWS, _MUNI_BY_CODE

    rows: List[Dict[str, str]] = []
    by_code: Dict[str, Dict[str, str]] = {}
    csv_path = _GISBR_DATA_DIR / "divisao_regional.csv"
    with csv_path.open("r", encoding="utf-8") as fh:
        lines = (line for line in fh if not line.startswith("#") and line.strip())
        reader = csv.DictReader(lines, delimiter=";")
        for row in reader:
            code = str(row.get("code_muni") or "").strip()
            if not code:
                continue
            rows.append(row)
            by_code[code] = row

    _MUNI_ROWS = rows
    _MUNI_BY_CODE = by_code
    return rows, by_code


def _load_regioes_metropolitanas() -> Dict[str, Dict[str, Any]]:
    global _RM_BY_ID
    if _RM_BY_ID is not None:
        return _RM_BY_ID
    rms: Dict[str, Dict[str, Any]] = {}
    csv_path = _GISBR_DATA_DIR / "regioes_metropolitanas.csv"
    with csv_path.open("r", encoding="utf-8") as fh:
        lines = (line for line in fh if not line.startswith("#") and line.strip())
        reader = csv.DictReader(lines, delimiter=";")
        for row in reader:
            rm_id = str(row.get("id_rm") or "").strip()
            if not rm_id:
                continue
            entry = rms.setdefault(
                rm_id,
                {
                    "id": rm_id,
                    "name": str(row.get("nome_rm") or "").strip(),
                    "ufs": set(),
                    "codes": [],
                    "nomes": [],
                },
            )
            entry["ufs"].add(str(row.get("sigla_uf") or "").strip().upper())
            entry["codes"].append(str(row.get("code_muni") or "").strip())
            entry["nomes"].append(str(row.get("nome_muni") or "").strip())
    for entry in rms.values():
        entry["ufs"] = sorted(entry["ufs"])
    _RM_BY_ID = rms
    return rms


def _load_ti_index() -> List[Dict[str, Any]]:
    global _TI_INDEX
    if _TI_INDEX is not None:
        return _TI_INDEX
    idx_path = _DATA_DIR / "indigenous_territories_index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    _TI_INDEX = list(data.get("territories") or [])
    return _TI_INDEX


def _geometry_fingerprint(wkt: str) -> str:
    return hashlib.sha256(wkt.encode("utf-8")).hexdigest()[:16]


def _maybe_live_ibge_lookup(ibge_code: str, *, allow_network: bool = False) -> Optional[Dict[str, Any]]:
    """Optional read-only IBGE API enrichment when offline lookup lacks a record."""
    if not allow_network:
        return None
    if not re.fullmatch(r"\d{7}", ibge_code):
        return None
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios/{ibge_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AwanaGIS-Resolver/0.1"})
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 - fixed https IBGE URL
            obj = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
        if isinstance(obj, dict) and obj.get("id"):
            uf_sigla = (
                obj.get("microrregiao", {})
                .get("mesorregiao", {})
                .get("UF", {})
                .get("sigla")
            )
            return {
                "code_muni": str(obj["id"]),
                "nome_muni": str(obj.get("nome") or ""),
                "sigla_uf": str(uf_sigla or "").upper(),
            }
    except Exception:
        return None
    return None


def _resolve_municipality(
    *,
    name: Optional[str] = None,
    uf: Optional[str] = None,
    ibge_code: Optional[str] = None,
    allow_live_lookup: bool = False,
) -> Dict[str, Any]:
    rows, by_code = _load_divisao_regional()
    uf_norm = str(uf or "").strip().upper() or None

    if ibge_code is not None:
        code_str = str(ibge_code).strip()
        if not re.fullmatch(r"\d{7}", code_str):
            return {
                "ok": False,
                "status": "invalid_ibge_code",
                "error": f"Invalid IBGE municipality code '{code_str}': must be exactly 7 digits.",
                "candidates": [],
            }
        row = by_code.get(code_str)
        if row is None and allow_live_lookup:
            row = _maybe_live_ibge_lookup(code_str, allow_network=True)
        if row is None:
            return {
                "ok": False,
                "status": "invalid_ibge_code",
                "error": f"Unknown 7-digit IBGE municipality code '{code_str}'.",
                "candidates": [],
            }
        if uf_norm and row["sigla_uf"].upper() != uf_norm:
            return {
                "ok": False,
                "status": "uf_mismatch",
                "error": (
                    f"IBGE code '{code_str}' belongs to {row['nome_muni']} ({row['sigla_uf']}), "
                    f"not UF '{uf_norm}'."
                ),
                "candidates": [_muni_candidate(row)],
            }
        cand = _muni_candidate(row)
        return {
            "ok": True,
            "status": "resolved",
            "area": cand,
            "candidates": [cand],
        }

    if not name or not str(name).strip():
        return {
            "ok": False,
            "status": "missing_input",
            "error": "Provide ibge_code or municipality name.",
            "candidates": [],
        }

    folded_target = _fold(name)
    exact: List[Dict[str, str]] = []
    prefix: List[Dict[str, str]] = []
    contains: List[Dict[str, str]] = []
    for row in rows:
        if uf_norm and row["sigla_uf"].upper() != uf_norm:
            continue
        rn = _fold(row["nome_muni"])
        if rn == folded_target:
            exact.append(row)
        elif rn.startswith(folded_target):
            prefix.append(row)
        elif folded_target in rn:
            contains.append(row)

    matches = exact or prefix or contains
    if not matches:
        return {
            "ok": False,
            "status": "not_found",
            "error": f"No municipality matched '{name}'" + (f" in UF {uf_norm}." if uf_norm else "."),
            "candidates": [],
        }

    candidates = [_muni_candidate(r) for r in matches[:25]]
    if len(candidates) == 1:
        return {
            "ok": True,
            "status": "resolved",
            "area": candidates[0],
            "candidates": candidates,
        }

    return {
        "ok": True,
        "status": "ambiguous",
        "needs_disambiguation": True,
        "area": None,
        "candidates": candidates,
        "message": (
            f"Multiple municipalities matched '{name}' ({len(matches)} matches). "
            "Specify uf or ibge_code to disambiguate."
        ),
    }


def _muni_candidate(row: Dict[str, str]) -> Dict[str, Any]:
    code = row["code_muni"]
    uf = row["sigla_uf"].upper()
    return {
        "type": "municipality",
        "id": code,
        "ibge_code": code,
        "name": row["nome_muni"],
        "display_name": f"{row['nome_muni']} ({uf})",
        "uf": uf,
        "ufs": [uf],
        "codes": [code],
        "nomes": [row["nome_muni"]],
        "recorte_type": "municipio",
        "crs": "EPSG:4674",
        "source": "IBGE divisao_regional (offline authoritative lookup)",
    }


def _resolve_state(*, name: Optional[str] = None, uf: Optional[str] = None, ibge_code: Optional[str] = None) -> Dict[str, Any]:
    rows, _ = _load_divisao_regional()
    target_uf = None
    if uf:
        u = str(uf).strip().upper()
        if u in UF_ABBREV_TO_CODE:
            target_uf = u
    elif ibge_code:
        try:
            target_uf = UF_CODE_TO_ABBREV.get(int(str(ibge_code).strip()[:2]))
        except ValueError:
            target_uf = None
    elif name:
        fn = _fold(name)
        for sigla, full_name in _UF_NAMES.items():
            if fn == _fold(sigla) or fn == _fold(full_name):
                target_uf = sigla
                break

    if not target_uf:
        return {
            "ok": False,
            "status": "not_found",
            "error": "Could not resolve Brazilian state (UF). Provide a valid 2-letter UF sigla, state name, or 2-digit UF code.",
            "candidates": [],
        }

    codes = [r["code_muni"] for r in rows if r["sigla_uf"].upper() == target_uf]
    nomes = [r["nome_muni"] for r in rows if r["sigla_uf"].upper() == target_uf]
    uf_code = str(UF_ABBREV_TO_CODE[target_uf])
    area = {
        "type": "state",
        "id": target_uf,
        "uf_code": uf_code,
        "name": _UF_NAMES[target_uf],
        "display_name": f"{_UF_NAMES[target_uf]} ({target_uf})",
        "uf": target_uf,
        "ufs": [target_uf],
        "codes": codes,
        "nomes": nomes,
        "recorte_type": "uf",
        "crs": "EPSG:4674",
        "source": "IBGE divisao_regional",
    }
    return {"ok": True, "status": "resolved", "area": area, "candidates": [area]}


def _resolve_regional(
    area_type: str,
    *,
    name: Optional[str] = None,
    uf: Optional[str] = None,
    ibge_code: Optional[str] = None,
) -> Dict[str, Any]:
    uf_norm = str(uf or "").strip().upper() or None
    if area_type == "metropolitan_region":
        rms = _load_regioes_metropolitanas()
        matches = []
        for rm in rms.values():
            if uf_norm and uf_norm not in rm["ufs"]:
                continue
            if ibge_code and rm["id"] == str(ibge_code).strip():
                matches = [rm]
                break
            if name and _fold(name) in _fold(rm["name"]):
                matches.append(rm)
            elif not name and not ibge_code and uf_norm:
                matches.append(rm)
        if not matches:
            return {"ok": False, "status": "not_found", "error": "No matching metropolitan region found.", "candidates": []}
        cands = [
            {
                "type": "metropolitan_region",
                "id": m["id"],
                "name": m["name"],
                "display_name": f"{m['name']} ({'/'.join(m['ufs'])})",
                "ufs": m["ufs"],
                "codes": m["codes"],
                "nomes": m["nomes"],
                "recorte_type": "rm",
                "crs": "EPSG:4674",
                "source": "IBGE regioes_metropolitanas",
            }
            for m in matches[:25]
        ]
        if len(cands) == 1:
            return {"ok": True, "status": "resolved", "area": cands[0], "candidates": cands}
        return {"ok": True, "status": "ambiguous", "needs_disambiguation": True, "area": None, "candidates": cands}

    col_map = {
        "microregion": ("id_micro", "nome_micro", "micro"),
        "mesoregion": ("id_meso", "nome_meso", "meso"),
        "macroregion": ("id_regiao", "nome_regiao", "macro"),
    }
    id_col, name_col, rec_type = col_map[area_type]
    rows, _ = _load_divisao_regional()
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        gid = str(row.get(id_col) or "").strip()
        gname = str(row.get(name_col) or "").strip()
        row_uf = str(row.get("sigla_uf") or "").strip().upper()
        if not gid or not gname:
            continue
        if uf_norm and row_uf != uf_norm and area_type != "macroregion":
            continue
        entry = grouped.setdefault(
            gid,
            {"id": gid, "name": gname, "ufs": set(), "codes": [], "nomes": []},
        )
        entry["ufs"].add(row_uf)
        entry["codes"].append(row["code_muni"])
        entry["nomes"].append(row["nome_muni"])

    matches = []
    for entry in grouped.values():
        if ibge_code and entry["id"] == str(ibge_code).strip():
            matches = [entry]
            break
        if name and _fold(name) in _fold(entry["name"]):
            matches.append(entry)
        elif not name and not ibge_code and uf_norm and uf_norm in entry["ufs"]:
            matches.append(entry)

    if not matches:
        return {"ok": False, "status": "not_found", "error": f"No {area_type} matched.", "candidates": []}

    cands = [
        {
            "type": area_type,
            "id": m["id"],
            "name": m["name"],
            "ufs": sorted(m["ufs"]),
            "codes": m["codes"],
            "nomes": m["nomes"],
            "recorte_type": rec_type,
            "crs": "EPSG:4674",
            "source": "IBGE divisao_regional",
        }
        for m in matches[:25]
    ]
    if len(cands) == 1:
        return {"ok": True, "status": "resolved", "area": cands[0], "candidates": cands}
    return {"ok": True, "status": "ambiguous", "needs_disambiguation": True, "area": None, "candidates": cands}


def _resolve_project_layer(
    *,
    layer_id: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsGeometry,
        QgsProject,
        QgsVectorLayer,
        QgsWkbTypes,
    )

    project = QgsProject.instance()
    target_layer = None
    if layer_id:
        target_layer = project.mapLayer(str(layer_id))
    elif name:
        matches = project.mapLayersByName(str(name))
        if len(matches) > 1:
            return {
                "ok": True,
                "status": "ambiguous",
                "needs_disambiguation": True,
                "area": None,
                "candidates": [{"layer_id": l.id(), "name": l.name()} for l in matches],
            }
        if matches:
            target_layer = matches[0]

    if target_layer is None:
        return {
            "ok": False,
            "status": "not_found",
            "error": "Project layer not found. Provide a valid layer_id or exact layer name.",
            "candidates": [],
        }

    if not isinstance(target_layer, QgsVectorLayer) or not target_layer.isValid():
        return {
            "ok": False,
            "status": "unsupported",
            "error": "Selected layer must be a valid vector polygon layer.",
            "candidates": [],
        }

    if target_layer.geometryType() != QgsWkbTypes.GeometryType.PolygonGeometry:
        return {
            "ok": False,
            "status": "unsupported",
            "error": (
                f"Project layer '{target_layer.name()}' is not a polygon layer; "
                "exact polygon clip requires polygon geometry (extent bbox alone is not accepted)."
            ),
            "candidates": [],
        }

    if not target_layer.crs().isValid():
        return {
            "ok": False,
            "status": "invalid_crs",
            "error": f"Project layer '{target_layer.name()}' does not have a valid CRS.",
            "candidates": [],
        }

    geoms = []
    for feat in target_layer.getFeatures():
        g = feat.geometry()
        if g is not None and not g.isEmpty() and g.isGeosValid():
            geoms.append(QgsGeometry(g))

    if not geoms:
        return {
            "ok": False,
            "status": "invalid_geometry",
            "error": f"Project layer '{target_layer.name()}' has no valid non-empty polygon geometries.",
            "candidates": [],
        }

    union_geom = QgsGeometry.unaryUnion(geoms)
    if union_geom is None or union_geom.isEmpty():
        return {
            "ok": False,
            "status": "invalid_geometry",
            "error": "Failed to combine valid polygon mask from project layer.",
            "candidates": [],
        }

    target_crs = QgsCoordinateReferenceSystem("EPSG:4674")
    if target_layer.crs() != target_crs:
        xform = QgsCoordinateTransform(target_layer.crs(), target_crs, project)
        union_geom.transform(xform)

    rect = union_geom.boundingBox()
    wkt = union_geom.asWkt(6)
    area = {
        "type": "project_layer",
        "id": target_layer.id(),
        "layer_id": target_layer.id(),
        "name": target_layer.name(),
        "display_name": target_layer.name(),
        "ufs": [],
        "codes": [],
        "crs": "EPSG:4674",
        "native_crs": target_layer.crs().authid(),
        "bbox": [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()],
        "geometry_wkt": wkt,
        "geometry_fingerprint": _geometry_fingerprint(wkt),
        "clip_geometry_available": True,
        "recorte_type": "polygon_mask",
        "source": f"QGIS project layer ({target_layer.id()})",
    }
    return {"ok": True, "status": "resolved", "area": area, "candidates": [area]}


def _search_loaded_ti_layer(
    *,
    territory_id: Optional[str] = None,
    name: Optional[str] = None,
    uf: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Inspect existing QGIS project layers for a loaded FUNAI/geobr TI polygon."""
    try:
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsCoordinateTransform,
            QgsGeometry,
            QgsProject,
            QgsVectorLayer,
            QgsWkbTypes,
        )
    except Exception:
        return None

    project = QgsProject.instance()
    folded_name = _fold(name or "")
    uf_norm = str(uf or "").strip().upper() or None

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            continue
        if layer.geometryType() != QgsWkbTypes.GeometryType.PolygonGeometry:
            continue
        field_names = {f.name().lower(): f.name() for f in layer.fields()}
        code_field = next((field_names[k] for k in ("terrai_cod", "code_terrai", "terrai_codigo") if k in field_names), None)
        name_field = next((field_names[k] for k in ("terrai_nom", "name_indigenous_land", "nome_ti") if k in field_names), None)
        uf_field = next((field_names[k] for k in ("uf_sigla", "abbrev_state", "uf") if k in field_names), None)
        stage_field = next((field_names[k] for k in ("fase_ti", "situacao_juridica", "fase") if k in field_names), None)
        if not (code_field or name_field):
            continue

        matched_geoms = []
        matched_attrs: Dict[str, Any] = {}
        for feat in layer.getFeatures():
            f_code = str(feat[code_field]).strip() if code_field and feat[code_field] is not None else ""
            f_name = str(feat[name_field]).strip() if name_field and feat[name_field] is not None else ""
            f_uf = str(feat[uf_field]).strip().upper() if uf_field and feat[uf_field] is not None else ""
            if territory_id and f_code != str(territory_id).strip():
                continue
            if not territory_id and folded_name and folded_name != _fold(f_name) and folded_name not in _fold(f_name):
                continue
            if uf_norm and f_uf and uf_norm not in f_uf:
                continue
            g = feat.geometry()
            if g is not None and not g.isEmpty():
                matched_geoms.append(QgsGeometry(g))
                matched_attrs = {
                    "terrai_cod": f_code or territory_id,
                    "name": f_name or name,
                    "uf": f_uf,
                    "legal_stage": str(feat[stage_field]) if stage_field and feat[stage_field] is not None else "unknown",
                    "layer_id": layer.id(),
                    "provenance_source": str(layer.customProperty("fonte") or layer.name()),
                }
        if matched_geoms:
            union_geom = QgsGeometry.unaryUnion(matched_geoms)
            target_crs = QgsCoordinateReferenceSystem("EPSG:4674")
            if layer.crs().isValid() and layer.crs() != target_crs:
                xform = QgsCoordinateTransform(layer.crs(), target_crs, project)
                union_geom.transform(xform)
            rect = union_geom.boundingBox()
            wkt = union_geom.asWkt(6)
            matched_attrs["bbox"] = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
            matched_attrs["geometry_wkt"] = wkt
            matched_attrs["geometry_fingerprint"] = _geometry_fingerprint(wkt)
            return matched_attrs
    return None


def _resolve_indigenous_territory(
    *,
    name: Optional[str] = None,
    uf: Optional[str] = None,
    territory_id: Optional[str] = None,
    source_id: Optional[str] = None,
    layer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve an Indigenous Territory (TI) by FUNAI ``terrai_cod`` or disambiguated name.

    Explicitly separates FUNAI TI legal demarcation polygons from SESAI/FUNAI DSEI
    operational health jurisdiction areas.
    """
    if source_id == "funai_dsei_areas":
        return {
            "ok": False,
            "status": "concept_mismatch",
            "error": (
                "funai_dsei_areas represents SESAI/FUNAI DSEI operational health-service "
                "jurisdiction districts, NOT Indigenous Territory (TI) demarcation boundaries. "
                "Use funai_ti_boundaries or geobr_terras_indigenas to resolve TI boundaries."
            ),
            "candidates": [],
        }

    # Check if caller explicitly supplied a project layer holding the TI polygon
    if layer_id:
        layer_res = _resolve_project_layer(layer_id=layer_id)
        if not layer_res.get("ok"):
            return layer_res
        area = dict(layer_res["area"])
        area["type"] = "indigenous_territory"
        area["territory_id"] = str(territory_id or area["id"])
        area["concept_note"] = "TI demarcation boundary (NOT DSEI operational health district)."
        return {"ok": True, "status": "resolved", "area": area, "candidates": [area]}

    # Check if an already-loaded QGIS TI layer contains the requested TI polygon
    loaded_match = _search_loaded_ti_layer(territory_id=territory_id, name=name, uf=uf)
    if loaded_match is not None:
        ufs = [u.strip() for u in (loaded_match.get("uf") or "").split(",") if u.strip()]
        area = {
            "type": "indigenous_territory",
            "id": loaded_match["terrai_cod"],
            "territory_id": loaded_match["terrai_cod"],
            "terrai_cod": loaded_match["terrai_cod"],
            "name": loaded_match["name"],
            "display_name": f"TI {loaded_match['name']} ({'/'.join(ufs) or 'BR'})",
            "ufs": ufs,
            "legal_stage": loaded_match["legal_stage"],
            "cross_uf": len(ufs) > 1,
            "crs": "EPSG:4674",
            "bbox": loaded_match["bbox"],
            "geometry_wkt": loaded_match["geometry_wkt"],
            "geometry_fingerprint": loaded_match["geometry_fingerprint"],
            "clip_geometry_available": True,
            "recorte_type": "polygon_mask",
            "source_id": source_id or loaded_match["provenance_source"],
            "concept_note": "FUNAI/geobr TI boundary polygon (distinct from SESAI/FUNAI DSEI operational health areas).",
        }
        return {"ok": True, "status": "resolved", "area": area, "candidates": [area]}

    # Offline curated FUNAI TI index lookup
    ti_index = _load_ti_index()
    uf_norm = str(uf or "").strip().upper() or None
    tid_norm = str(territory_id or "").strip() or None
    folded_q = _fold(name or "")

    matches: List[Dict[str, Any]] = []
    if tid_norm:
        for item in ti_index:
            if item["terrai_cod"] == tid_norm:
                matches.append(item)
    elif folded_q:
        exact = []
        partial = []
        for item in ti_index:
            if uf_norm and uf_norm not in item["ufs"]:
                continue
            fn = _fold(item["name"])
            if fn == folded_q:
                exact.append(item)
            elif folded_q in fn:
                partial.append(item)
        matches = exact or partial
    else:
        return {
            "ok": False,
            "status": "missing_input",
            "error": "Provide territory_id (FUNAI terrai_cod) or territory name for indigenous_territory resolution.",
            "candidates": [],
        }

    if not matches:
        return {
            "ok": False,
            "status": "needs_reference_data",
            "error": (
                f"TI '{territory_id or name}' was not found in the local reference index or loaded project layers. "
                "Load 'funai_ti_boundaries' (or 'geobr_terras_indigenas' if FUNAI is unreachable) and pass its layer_id, "
                "or verify the FUNAI terrai_cod."
            ),
            "reference_source_options": ["funai_ti_boundaries", "geobr_terras_indigenas"],
            "candidates": [],
        }

    candidates = []
    for item in matches:
        ufs = list(item["ufs"])
        munis = list(item.get("municipalities") or [])
        candidates.append(
            {
                "type": "indigenous_territory",
                "id": item["terrai_cod"],
                "territory_id": item["terrai_cod"],
                "terrai_cod": item["terrai_cod"],
                "name": item["name"],
                "display_name": f"TI {item['name']} ({'/'.join(ufs)}) — {item['legal_stage']}",
                "ufs": ufs,
                "codes": munis,
                "cross_municipal": len(munis) > 1,
                "cross_uf": len(ufs) > 1,
                "legal_stage": item["legal_stage"],
                "modality": item.get("modality"),
                "etnia": item.get("etnia"),
                "crs": "EPSG:4674",
                "clip_geometry_available": False,
                "recorte_type": "polygon_mask",
                "source_id": source_id or "funai_ti_boundaries",
                "concept_note": "FUNAI TI boundary metadata (distinct from DSEI operational health district polygons).",
            }
        )

    if len(candidates) > 1:
        return {
            "ok": True,
            "status": "ambiguous",
            "needs_disambiguation": True,
            "area": None,
            "candidates": candidates,
            "message": f"Multiple Indigenous Territories matched '{name}'. Specify territory_id (terrai_cod) or uf.",
        }

    chosen = candidates[0]
    return {
        "ok": True,
        "status": "needs_reference_data",
        "area": chosen,
        "candidates": [chosen],
        "reference_source_options": ["funai_ti_boundaries", "geobr_terras_indigenas"],
        "message": (
            f"Resolved TI identity '{chosen['name']}' (terrai_cod={chosen['terrai_cod']}, "
            f"UFs={','.join(chosen['ufs'])}, stage={chosen['legal_stage']}), "
            "which spans multiple municipalities/UFs and cannot be approximated by a single-municipality Recorte. "
            "No polygon geometry is currently loaded in QGIS; plan/approve a bounded load of "
            "'funai_ti_boundaries' (or 'geobr_terras_indigenas' if FUNAI is unreachable) to obtain the exact polygon mask."
        ),
    }


def resolve_area(
    type: str,  # noqa: A002
    *,
    name: Optional[str] = None,
    uf: Optional[str] = None,
    ibge_code: Optional[str] = None,
    layer_id: Optional[str] = None,
    territory_id: Optional[str] = None,
    source_id: Optional[str] = None,
    allow_live_lookup: bool = False,
) -> Dict[str, Any]:
    """Resolve a Brazilian area of interest (municipality, region, project layer, or TI)."""
    area_type = str(type or "").strip().lower()
    if area_type not in _VALID_AREA_TYPES:
        return {
            "ok": False,
            "status": "unsupported_area_type",
            "error": f"Unsupported area type '{type}'. Supported: {sorted(_VALID_AREA_TYPES)}",
            "candidates": [],
        }

    if area_type == "municipality":
        return _resolve_municipality(
            name=name,
            uf=uf,
            ibge_code=ibge_code,
            allow_live_lookup=allow_live_lookup,
        )
    if area_type == "state":
        return _resolve_state(name=name, uf=uf, ibge_code=ibge_code)
    if area_type in ("metropolitan_region", "microregion", "mesoregion", "macroregion"):
        return _resolve_regional(area_type, name=name, uf=uf, ibge_code=ibge_code)
    if area_type == "project_layer":
        return _resolve_project_layer(layer_id=layer_id, name=name)
    if area_type == "indigenous_territory":
        return _resolve_indigenous_territory(
            name=name,
            uf=uf,
            territory_id=territory_id,
            source_id=source_id,
            layer_id=layer_id,
        )
    return {"ok": False, "status": "unsupported_area_type", "error": f"Unhandled area type: {area_type}"}
