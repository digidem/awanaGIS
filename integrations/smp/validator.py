"""Pure-Python + optional external SMP archive structural and image validator."""

import io
import json
import os
import re
import shutil
import subprocess
import zipfile

from PIL import Image

_TILE_PATH_RE = re.compile(r"^s/(\d+)/(\d+)/(\d+)/(\d+)\.(png|jpg|jpeg|webp)$")
_MAX_PIL_IMAGE_SAMPLES = 50


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
            names = zf.namelist()
            if len(names) != len(set(names)):
                issues.append("Archive contains duplicate entry names.")

            for name in names:
                if _is_unsafe_archive_path(name):
                    issues.append(f"Unsafe ZIP entry path rejected: {name!r}")
                if os.path.basename(name) == "_cache_meta.json":
                    issues.append(f"Internal cache metadata leaked into archive: {name!r}")

            if "VERSION" not in names:
                issues.append("Missing required 'VERSION' entry.")
            else:
                ver_text = zf.read("VERSION").decode("utf-8", errors="replace").strip()
                if ver_text != "1.0":
                    issues.append(f"Unexpected VERSION '{ver_text}' (expected '1.0').")

            if "style.json" not in names:
                issues.append("Missing required 'style.json' entry.")
                style = None
            else:
                try:
                    style = json.loads(zf.read("style.json").decode("utf-8"))
                except Exception as exc:
                    issues.append(f"Invalid style.json JSON: {exc}")
                    style = None

            bad_member = zf.testzip()
            if bad_member is not None:
                issues.append(f"ZIP CRC/integrity failure on entry: {bad_member}")

            if isinstance(style, dict):
                if style.get("version") != 8:
                    issues.append(f"style.json version must be 8, got {style.get('version')!r}.")

                for ext_field in ("glyphs", "sprite"):
                    val = style.get(ext_field)
                    if isinstance(val, str) and val.lower().startswith(("http://", "https://")):
                        issues.append(f"External URL disallowed in style.{ext_field}: {val}")

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

                        tiles_urls = src.get("tiles")
                        if not isinstance(tiles_urls, list) or not tiles_urls:
                            issues.append(f"Source '{sid}' missing 'tiles' URL template.")
                        else:
                            for turl in tiles_urls:
                                if not isinstance(turl, str) or not turl.startswith("smp://maps.v1/"):
                                    issues.append(f"Source '{sid}' tile URL must use 'smp://maps.v1/': {turl!r}")
                        folder = source_folders.get(sid)
                        if not folder:
                            issues.append(f"Source '{sid}' missing from metadata['smp:sourceFolders'].")
                        else:
                            expected_folders[folder] = (sid, src)
                        sources_summary[sid] = {
                            "folder": folder,
                            "minzoom": zmin,
                            "maxzoom": zmax,
                            "format": src.get("format"),
                            "bounds": sbounds,
                            "tile_count": 0,
                        }

                    # Scan tile entries
                    for name in names:
                        if name in ("VERSION", "style.json"):
                            continue
                        m = _TILE_PATH_RE.match(name)
                        if not m:
                            issues.append(f"Unexpected non-tile archive entry: {name!r}")
                            continue
                        s_idx, z_str, _x_str, _y_str, ext = m.groups()
                        folder = f"s/{s_idx}"
                        z_int = int(z_str)
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
                        decl_fmt = str(src.get("format") or "").lower()
                        if decl_fmt and ext != decl_fmt and not (decl_fmt == "jpg" and ext == "jpeg"):
                            issues.append(
                                f"Tile '{name}' extension .{ext} mismatches source format {decl_fmt!r}."
                            )
                        tile_entries.append(name)
                        sources_summary[sid]["tile_count"] += 1

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
