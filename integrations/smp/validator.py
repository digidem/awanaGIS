"""Pure-Python + optional external SMP archive structural and image validator."""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import zipfile

from PIL import Image

_TILE_PATH_RE = re.compile(r"^s/(\d+)/(\d+)/(\d+)/(\d+)\.(png|jpg|jpeg|webp)$")
_SMP_TILE_TEMPLATE_RE = re.compile(r"^smp://maps\.v1/(s/\d+)/\{z\}/\{x\}/\{y\}\.(png|jpg|jpeg|webp)$")


def _find_external_http_urls(obj, path: str = "style") -> list[str]:
    """Recursively find disallowed http(s) resource URLs in style definitions."""
    hits = []
    if isinstance(obj, str):
        if obj.strip().lower().startswith(("http://", "https://")):
            hits.append(f"{path}={obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(_find_external_http_urls(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(_find_external_http_urls(item, f"{path}[{idx}]"))
    return hits
_MAX_PIL_IMAGE_SAMPLES = 50
MAX_ARCHIVE_ENTRIES = 300_000
MAX_VERSION_ENTRY_BYTES = 64
MAX_STYLE_JSON_BYTES = 16 * 1024 * 1024
MAX_TILE_ENTRY_BYTES = 16 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_TESTZIP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_COVERAGE_SET_TILES = 250_000


def _deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 1 << zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def _expected_tile_range(bounds, zoom):
    west, south, east, north = (float(v) for v in bounds)
    north = min(85.0511, max(-85.0511, north))
    south = min(85.0511, max(-85.0511, south))
    n = 1 << zoom
    min_x, min_y = _deg2num(north, west, zoom)
    max_x, max_y = _deg2num(south, east, zoom)
    min_x = max(0, min(n - 1, min_x))
    max_x = max(0, min(n - 1, max_x))
    min_y = max(0, min(n - 1, min_y))
    max_y = max(0, min(n - 1, max_y))
    return min_x, max_x, min_y, max_y


def _is_unsafe_archive_path(name):
    if not name or "\x00" in name:
        return True
    if name.startswith(("/", "\\")):
        return True
    if len(name) >= 2 and name[1] == ":":
        return True
    parts = name.replace("\\", "/").split("/")
    return any(p in ("..", "") for p in parts[:-1]) or (parts[-1] == "..")


def _find_smp_binary():
    which_smp = shutil.which("smp")
    if which_smp:
        return which_smp
    bun_smp = "/home/luandro/.bun/bin/smp"
    if os.path.isfile(bun_smp) and os.access(bun_smp, os.X_OK):
        return bun_smp
    return None


def _run_external_smp_checks(abs_path):
    """Run independent SMP CLI / styled-map-package Reader checks when installed."""
    smp_bin = _find_smp_binary()
    if not smp_bin:
        return {
            "cli_available": False,
            "cli_validate_supported": False,
            "cli_validate_passed": None,
            "reader_check_available": False,
            "reader_check_passed": None,
            "note": "No 'smp' binary found on PATH or /home/luandro/.bun/bin/smp.",
        }

    result = {
        "cli_available": True,
        "cli_path": smp_bin,
        "cli_validate_supported": False,
        "cli_validate_passed": None,
        "cli_output": None,
        "reader_check_available": False,
        "reader_check_passed": None,
        "reader_output": None,
    }

    try:
        help_proc = subprocess.run(
            [smp_bin, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        help_text = (help_proc.stdout or "") + "\n" + (help_proc.stderr or "")
    except Exception as exc:
        result["cli_output"] = f"Failed to probe smp --help: {exc}"
        return result

    if re.search(r"^\s*validate\b", help_text, re.MULTILINE):
        result["cli_validate_supported"] = True
        try:
            val_proc = subprocess.run(
                [smp_bin, "validate", abs_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            result["cli_validate_passed"] = val_proc.returncode == 0
            result["cli_output"] = (val_proc.stdout or val_proc.stderr or "").strip()
        except Exception as exc:
            result["cli_validate_passed"] = False
            result["cli_output"] = f"smp validate error: {exc}"
    else:
        result["cli_output"] = "Installed smp CLI does not expose a 'validate' subcommand."

    # Also test styled-map-package/reader via Node if installed alongside smp_bin
    node_bin = shutil.which("node")
    real_smp = os.path.realpath(smp_bin)
    pkg_dir = os.path.dirname(os.path.dirname(real_smp))
    reader_entry = os.path.join(pkg_dir, "dist", "reader.js")
    if node_bin and os.path.isfile(reader_entry):
        result["reader_check_available"] = True
        script = (
            "import { pathToFileURL } from 'node:url';"
            "import { buffer } from 'node:stream/consumers';"
            "const { Reader } = await import(pathToFileURL(process.env.SMP_READER_PATH).href);"
            "const r = new Reader(process.env.SMP_FILE_PATH);"
            "try {"
            "  await r.opened();"
            "  const style = await r.getStyle();"
            "  let tileCheck = null;"
            "  if (process.env.SMP_SAMPLE_TILE) {"
            "    const res = await r.getResource(process.env.SMP_SAMPLE_TILE);"
            "    const buf = await buffer(res.stream);"
            "    tileCheck = { contentType: res.contentType, contentLength: res.contentLength, bytesRead: buf.length };"
            "  }"
            "  console.log(JSON.stringify({ ok: true, sources: Object.keys(style.sources || {}), tileCheck }));"
            "} finally { await r.close(); }"
        )
        env = dict(os.environ)
        env["SMP_READER_PATH"] = reader_entry
        env["SMP_FILE_PATH"] = abs_path
        # Find a sample tile path using zipfile cheaply
        try:
            with zipfile.ZipFile(abs_path, "r") as zf:
                sample_tile = next((n for n in zf.namelist() if _TILE_PATH_RE.match(n)), "")
        except Exception:
            sample_tile = ""
        env["SMP_SAMPLE_TILE"] = sample_tile
        try:
            node_proc = subprocess.run(
                [node_bin, "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                check=False,
            )
            if node_proc.returncode == 0:
                result["reader_check_passed"] = True
                result["reader_output"] = node_proc.stdout.strip()
            else:
                result["reader_check_passed"] = False
                result["reader_output"] = (node_proc.stderr or node_proc.stdout or "").strip()
        except Exception as exc:
            result["reader_check_passed"] = False
            result["reader_output"] = f"Reader check error: {exc}"

    return result


def validate_file(file_path, run_external=True):
    """Validate an `.smp` archive structurally, visually (PIL), and via external tooling."""
    if not file_path or not isinstance(file_path, str):
        return {"ok": False, "valid": False, "issues": ["file_path is required."]}

    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        return {
            "ok": True,
            "valid": False,
            "file_path": abs_path,
            "issues": [f"File does not exist: {abs_path}"],
        }

    issues = []
    archive_size = os.path.getsize(abs_path)
    if archive_size == 0:
        return {
            "ok": True,
            "valid": False,
            "file_path": abs_path,
            "archive_size_bytes": 0,
            "issues": ["SMP archive is 0 bytes."],
        }

    tile_entries = []
    sources_summary = {}
    zoom_ranges = {}
    pil_checked = 0

    try:
        with zipfile.ZipFile(abs_path, "r") as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                issues.append(
                    f"Archive entry count ({len(infos):,}) exceeds maximum allowed ({MAX_ARCHIVE_ENTRIES:,})."
                )
                return {
                    "ok": True,
                    "valid": False,
                    "file_path": abs_path,
                    "archive_size_bytes": archive_size,
                    "tile_count": 0,
                    "pil_tiles_verified": 0,
                    "sources": {},
                    "zoom_ranges": {},
                    "issues": issues,
                    "consumer_test_status": {"cli_available": False, "reader_check_available": False},
                }

            total_uncompressed = 0
            info_by_name = {}
            names = []
            for info in infos:
                name = info.filename
                names.append(name)
                if info.file_size < 0:
                    issues.append(f"Invalid negative uncompressed size on entry: {name!r}")
                total_uncompressed += max(0, int(info.file_size))
                info_by_name[name] = info

            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                issues.append(
                    f"Total uncompressed archive size ({total_uncompressed:,} B) exceeds safety limit "
                    f"({MAX_TOTAL_UNCOMPRESSED_BYTES:,} B)."
                )
                return {
                    "ok": True,
                    "valid": False,
                    "file_path": abs_path,
                    "archive_size_bytes": archive_size,
                    "tile_count": 0,
                    "pil_tiles_verified": 0,
                    "sources": {},
                    "zoom_ranges": {},
                    "issues": issues,
                    "consumer_test_status": {"cli_available": False, "reader_check_available": False},
                }

            if len(names) != len(set(names)):
                issues.append("Archive contains duplicate entry names.")

            for name in names:
                if _is_unsafe_archive_path(name):
                    issues.append(f"Unsafe ZIP entry path rejected: {name!r}")
                if os.path.basename(name) == "_cache_meta.json":
                    issues.append(f"Internal cache metadata leaked into archive: {name!r}")

            if "VERSION" not in info_by_name:
                issues.append("Missing required 'VERSION' entry.")
            elif info_by_name["VERSION"].file_size > MAX_VERSION_ENTRY_BYTES:
                issues.append(
                    f"'VERSION' entry uncompressed size ({info_by_name['VERSION'].file_size} B) exceeds {MAX_VERSION_ENTRY_BYTES} B."
                )
            else:
                ver_text = zf.read("VERSION").decode("utf-8", errors="replace").strip()
                if ver_text != "1.0":
                    issues.append(f"Unexpected VERSION '{ver_text}' (expected '1.0').")

            if "style.json" not in info_by_name:
                issues.append("Missing required 'style.json' entry.")
                style = None
            elif info_by_name["style.json"].file_size > MAX_STYLE_JSON_BYTES:
                issues.append(
                    f"'style.json' uncompressed size ({info_by_name['style.json'].file_size:,} B) exceeds {MAX_STYLE_JSON_BYTES:,} B."
                )
                style = None
            else:
                try:
                    style = json.loads(zf.read("style.json").decode("utf-8"))
                except Exception as exc:
                    issues.append(f"Invalid style.json JSON: {exc}")
                    style = None

            for info in infos:
                if info.filename not in ("VERSION", "style.json") and info.file_size > MAX_TILE_ENTRY_BYTES:
                    issues.append(
                        f"Entry '{info.filename}' uncompressed size ({info.file_size:,} B) exceeds {MAX_TILE_ENTRY_BYTES:,} B."
                    )

            if not issues and total_uncompressed <= MAX_TESTZIP_UNCOMPRESSED_BYTES:
                bad_member = zf.testzip()
                if bad_member is not None:
                    issues.append(f"ZIP CRC/integrity failure on entry: {bad_member}")

            if isinstance(style, dict):
                if style.get("version") != 8:
                    issues.append(f"style.json version must be 8, got {style.get('version')!r}.")

                for ext_field in ("glyphs", "sprite", "sources", "layers"):
                    if ext_field in style:
                        for hit in _find_external_http_urls(style[ext_field], f"style.{ext_field}"):
                            issues.append(f"External URL disallowed in {hit}")

                metadata = style.get("metadata")
                if not isinstance(metadata, dict):
                    issues.append("style.json missing metadata object.")
                    source_folders = {}
                else:
                    bounds = metadata.get("smp:bounds")
                    if (
                        not isinstance(bounds, list)
                        or len(bounds) != 4
                        or not all(isinstance(v, (int, float)) for v in bounds)
                    ):
                        issues.append("style.json metadata['smp:bounds'] must be a 4-number list.")
                    source_folders = metadata.get("smp:sourceFolders")
                    if not isinstance(source_folders, dict) or not source_folders:
                        issues.append("style.json metadata['smp:sourceFolders'] is missing or empty.")
                        source_folders = {}

                sources = style.get("sources")
                if not isinstance(sources, dict) or not sources:
                    issues.append("style.json missing non-empty 'sources' object.")
                else:
                    expected_folders = {}
                    for sid, src in sources.items():
                        if not isinstance(src, dict):
                            issues.append(f"Source '{sid}' is not a dict.")
                            continue
                        if src.get("type") != "raster":
                            issues.append(f"Source '{sid}' type must be 'raster', got {src.get('type')!r}.")
                        if src.get("tileSize") != 256:
                            issues.append(f"Source '{sid}' tileSize must be 256, got {src.get('tileSize')!r}.")
                        if src.get("scheme") != "xyz":
                            issues.append(f"Source '{sid}' scheme must be 'xyz', got {src.get('scheme')!r}.")
                        sbounds = src.get("bounds")
                        if (
                            not isinstance(sbounds, list)
                            or len(sbounds) != 4
                            or sbounds[0] >= sbounds[2]
                            or sbounds[1] >= sbounds[3]
                        ):
                            issues.append(f"Source '{sid}' has invalid bounds: {sbounds!r}")
                        zmin = src.get("minzoom")
                        zmax = src.get("maxzoom")
                        if not isinstance(zmin, int) or not isinstance(zmax, int) or zmin > zmax:
                            issues.append(f"Source '{sid}' has invalid minzoom/maxzoom: {zmin}..{zmax}")
                        else:
                            zoom_ranges[sid] = [zmin, zmax]

                        folder = source_folders.get(sid)
                        if not folder:
                            issues.append(f"Source '{sid}' missing from metadata['smp:sourceFolders'].")
                        else:
                            expected_folders[folder] = (sid, src)

                        decl_fmt = str(src.get("format") or "").lower()
                        tpl_exts = set()
                        tiles_urls = src.get("tiles")
                        if not isinstance(tiles_urls, list) or not tiles_urls:
                            issues.append(f"Source '{sid}' missing 'tiles' URL template.")
                        else:
                            for turl in tiles_urls:
                                if not isinstance(turl, str):
                                    issues.append(f"Source '{sid}' tile URL must be a string: {turl!r}")
                                    continue
                                m_tpl = _SMP_TILE_TEMPLATE_RE.match(turl)
                                if not m_tpl:
                                    issues.append(
                                        f"Source '{sid}' tile URL must match 'smp://maps.v1/<folder>/{{z}}/{{x}}/{{y}}.<ext>': {turl!r}"
                                    )
                                    continue
                                tpl_folder, tpl_ext = m_tpl.groups()
                                tpl_exts.add(tpl_ext)
                                if folder and tpl_folder != folder:
                                    issues.append(
                                        f"Source '{sid}' tile URL folder '{tpl_folder}' does not match smp:sourceFolders '{folder}'."
                                    )
                                if decl_fmt and tpl_ext != decl_fmt:
                                    issues.append(
                                        f"Source '{sid}' tile URL extension '.{tpl_ext}' mismatches declared format {decl_fmt!r}."
                                    )
                        if len(tpl_exts) > 1:
                            issues.append(f"Source '{sid}' defines inconsistent tile extensions: {sorted(tpl_exts)}")
                        sources_summary[sid] = {
                            "folder": folder,
                            "minzoom": zmin,
                            "maxzoom": zmax,
                            "format": src.get("format"),
                            "template_exts": sorted(tpl_exts),
                            "bounds": sbounds,
                            "tile_count": 0,
                        }

                    # Compute expected coverage per source and scan tile entries
                    expected_ranges_by_sid = {}
                    expected_total_by_sid = {}
                    seen_coords_by_sid = {}
                    observed_zoom_counts_by_sid = {}
                    for sid, src in sources.items():
                        sbounds = src.get("bounds")
                        zmin = src.get("minzoom")
                        zmax = src.get("maxzoom")
                        if (
                            isinstance(sbounds, list)
                            and len(sbounds) == 4
                            and all(isinstance(v, (int, float)) for v in sbounds)
                            and sbounds[0] < sbounds[2]
                            and sbounds[1] < sbounds[3]
                            and isinstance(zmin, int)
                            and isinstance(zmax, int)
                            and 0 <= zmin <= zmax <= 24
                        ):
                            z_ranges = {}
                            exp_tot = 0
                            for z in range(zmin, zmax + 1):
                                rng = _expected_tile_range(sbounds, z)
                                z_ranges[z] = rng
                                exp_tot += (rng[1] - rng[0] + 1) * (rng[3] - rng[2] + 1)
                            expected_ranges_by_sid[sid] = z_ranges
                            expected_total_by_sid[sid] = exp_tot
                            seen_coords_by_sid[sid] = set() if exp_tot <= MAX_COVERAGE_SET_TILES else None
                            observed_zoom_counts_by_sid[sid] = {}

                    for name in names:
                        if name in ("VERSION", "style.json"):
                            continue
                        m = _TILE_PATH_RE.match(name)
                        if not m:
                            issues.append(f"Unexpected non-tile archive entry: {name!r}")
                            continue
                        s_idx, z_str, x_str, y_str, ext = m.groups()
                        folder = f"s/{s_idx}"
                        z_int = int(z_str)
                        x_int = int(x_str)
                        y_int = int(y_str)
                        if folder not in expected_folders:
                            issues.append(f"Tile '{name}' references undeclared source folder '{folder}'.")
                            continue
                        sid, src = expected_folders[folder]
                        zmin = src.get("minzoom")
                        zmax = src.get("maxzoom")
                        if isinstance(zmin, int) and isinstance(zmax, int) and not (zmin <= z_int <= zmax):
                            issues.append(
                                f"Tile '{name}' zoom {z_int} outside declared range {zmin}..{zmax} for '{sid}'."
                            )
                        else:
                            n_axis = 1 << z_int if 0 <= z_int <= 24 else 0
                            if n_axis == 0 or not (0 <= x_int < n_axis and 0 <= y_int < n_axis):
                                issues.append(
                                    f"Tile '{name}' coordinates ({z_int}/{x_int}/{y_int}) out of XYZ bounds."
                                )
                            elif sid in expected_ranges_by_sid and z_int in expected_ranges_by_sid[sid]:
                                r_min_x, r_max_x, r_min_y, r_max_y = expected_ranges_by_sid[sid][z_int]
                                if not (r_min_x <= x_int <= r_max_x and r_min_y <= y_int <= r_max_y):
                                    issues.append(
                                        f"Tile '{name}' ({z_int}/{x_int}/{y_int}) outside declared bounds range "
                                        f"[{r_min_x}..{r_max_x}, {r_min_y}..{r_max_y}] for '{sid}'."
                                    )
                                else:
                                    obs_z = observed_zoom_counts_by_sid[sid]
                                    obs_z[z_int] = obs_z.get(z_int, 0) + 1
                                    seen_set = seen_coords_by_sid.get(sid)
                                    if seen_set is not None:
                                        seen_set.add((z_int, x_int, y_int))
                        decl_fmt = str(src.get("format") or "").lower()
                        tpl_exts = set(sources_summary[sid].get("template_exts") or [])
                        if tpl_exts and ext not in tpl_exts:
                            issues.append(
                                f"Tile '{name}' extension .{ext} does not match tiles URL template extension {sorted(tpl_exts)}."
                            )
                        elif decl_fmt and ext != decl_fmt and not (decl_fmt == "jpg" and ext == "jpeg"):
                            issues.append(
                                f"Tile '{name}' extension .{ext} mismatches source format {decl_fmt!r}."
                            )
                        tile_entries.append(name)
                        sources_summary[sid]["tile_count"] += 1

                    # Check missing tiles against declared coverage
                    for sid, z_ranges in expected_ranges_by_sid.items():
                        seen_set = seen_coords_by_sid.get(sid)
                        folder = sources_summary[sid]["folder"]
                        decl_ext = str(sources_summary[sid].get("format") or "png").lower()
                        if seen_set is not None:
                            missing = []
                            missing_count = 0
                            for z, (r_min_x, r_max_x, r_min_y, r_max_y) in z_ranges.items():
                                for gx in range(r_min_x, r_max_x + 1):
                                    for gy in range(r_min_y, r_max_y + 1):
                                        if (z, gx, gy) not in seen_set:
                                            missing_count += 1
                                            if len(missing) < 5:
                                                missing.append(f"{folder}/{z}/{gx}/{gy}.{decl_ext}")
                            if missing_count > 0:
                                issues.append(
                                    f"Source '{sid}' is missing {missing_count} tile(s) from declared coverage "
                                    f"(e.g. {', '.join(missing)})."
                                )
                        else:
                            obs_z = observed_zoom_counts_by_sid.get(sid, {})
                            for z, (r_min_x, r_max_x, r_min_y, r_max_y) in z_ranges.items():
                                exp_z_count = (r_max_x - r_min_x + 1) * (r_max_y - r_min_y + 1)
                                got_z_count = obs_z.get(z, 0)
                                if got_z_count < exp_z_count:
                                    issues.append(
                                        f"Source '{sid}' zoom {z} has {got_z_count}/{exp_z_count} tiles "
                                        f"(missing {exp_z_count - got_z_count})."
                                    )

                if not tile_entries:
                    issues.append("Archive contains zero raster tile files.")
                else:
                    for sid, info in sources_summary.items():
                        if info["tile_count"] == 0:
                            issues.append(f"Declared source '{sid}' has 0 tiles in archive.")

                # Verify PIL image readability on a bounded stratified subset
                if tile_entries:
                    step = max(1, len(tile_entries) // _MAX_PIL_IMAGE_SAMPLES)
                    sampled_tiles = tile_entries[::step][:_MAX_PIL_IMAGE_SAMPLES]
                    for tname in sampled_tiles:
                        tinfo = info_by_name.get(tname)
                        if tinfo is not None and tinfo.file_size > MAX_TILE_ENTRY_BYTES:
                            continue
                        try:
                            raw = zf.read(tname)
                            with Image.open(io.BytesIO(raw)) as im:
                                im.verify()
                            with Image.open(io.BytesIO(raw)) as im2:
                                im2.load()
                                if im2.size != (256, 256):
                                    issues.append(
                                        f"Tile '{tname}' dimensions {im2.size} != (256, 256)."
                                    )
                            pil_checked += 1
                        except Exception as exc:
                            issues.append(f"Corrupt or unreadable tile image '{tname}': {exc}")

    except zipfile.BadZipFile as exc:
        issues.append(f"Invalid ZIP archive: {exc}")
    except OSError as exc:
        issues.append(f"Failed to read archive: {exc}")

    external_status = None
    if run_external and not issues:
        external_status = _run_external_smp_checks(abs_path)
        if external_status.get("cli_validate_supported") and external_status.get("cli_validate_passed") is False:
            issues.append(f"External 'smp validate' failed: {external_status.get('cli_output')}")
        if external_status.get("reader_check_available") and external_status.get("reader_check_passed") is False:
            issues.append(
                f"External 'styled-map-package/reader' check failed: {external_status.get('reader_output')}"
            )

    return {
        "ok": True,
        "valid": len(issues) == 0,
        "file_path": abs_path,
        "archive_size_bytes": archive_size,
        "tile_count": len(tile_entries),
        "pil_tiles_verified": pil_checked,
        "sources": sources_summary,
        "zoom_ranges": zoom_ranges,
        "issues": issues,
        "consumer_test_status": external_status or {
            "cli_available": False,
            "reader_check_available": False,
        },
    }
