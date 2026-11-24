#!/usr/bin/env python3
"""Build a clean, deterministic QGIS plugin ZIP archive for AwanaGIS."""

import argparse
import hashlib
from pathlib import Path
import zipfile

PLUGIN_ROOT_NAME = "awanagis"
FIXED_ZIP_TIME = (2026, 11, 23, 0, 0, 0)

EXCLUDED_TOP_DIRS = frozenset({
    ".git",
    ".github",
    ".opencode",
    ".claude",
    ".vscode",
    ".idea",
    ".poolside",
    ".pairfob",
    ".pytest_cache",
    "dist",
    "build",
    "dev",
    "docs",
    "graft",
    "htmlcov",
    "scripts",
    "tests",
})

EXCLUDED_DIR_NAMES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".git",
})

EXCLUDED_FILES = frozenset({
    ".DS_Store",
    "Thumbs.db",
    ".coverage",
    ".env",
    ".flake8",
    ".gitattributes",
    ".gitignore",
    "QGIS_COMPATIBILITY_RULES.md",
    "REBRAND_AUDIT.md",
    "setup.cfg",
    "build_release.sh",
})

EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".zip",
    ".db",
    ".log",
    ".qgs~",
    ".qgz~",
    ".ts",
    ".pro",
)


def read_plugin_version(repo_root: Path) -> str:
    """Read ``version=`` from ``metadata.txt``."""
    meta = repo_root / "metadata.txt"
    for line in meta.read_text(encoding="utf-8").splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    return "0.1.0"


def should_include(rel_path: Path) -> bool:
    """Return True if *rel_path* (relative to repo root) belongs in the runtime ZIP."""
    parts = rel_path.parts
    if not parts:
        return False
    if parts[0] in EXCLUDED_TOP_DIRS:
        return False
    if any(part in EXCLUDED_DIR_NAMES or part.endswith(".egg-info") for part in parts[:-1]):
        return False
    name = parts[-1]
    if name in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES):
        return False
    return True


def iter_package_files(repo_root: Path):
    """Yield sorted ``(abs_path, rel_path)`` pairs to pack into the ZIP."""
    entries = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if should_include(rel):
            entries.append((path, rel))
    entries.sort(key=lambda item: item[1].as_posix())
    return entries


def build_plugin_zip(repo_root: Path, output_zip: Path) -> tuple[Path, Path, str, list[str]]:
    """Create the plugin ZIP and matching ``.sha256`` file."""
    repo_root = Path(repo_root).resolve()
    output_zip = Path(output_zip).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    archived_names = []
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for abs_path, rel_path in iter_package_files(repo_root):
            arcname = f"{PLUGIN_ROOT_NAME}/{rel_path.as_posix()}"
            info = zipfile.ZipInfo(arcname, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix
            mode = 0o755 if abs_path.suffix == ".py" and abs_path.stat().st_mode & 0o111 else 0o644
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, abs_path.read_bytes())
            archived_names.append(arcname)

    digest = hashlib.sha256(output_zip.read_bytes()).hexdigest()
    sha_path = Path(f"{output_zip}.sha256")
    sha_path.write_text(f"{digest}  {output_zip.name}\n", encoding="utf-8")
    return output_zip, sha_path, digest, archived_names


def main(argv=None):
    repo_root = Path(__file__).resolve().parents[1]
    version = read_plugin_version(repo_root)
    default_out = repo_root / "dist" / f"{PLUGIN_ROOT_NAME}-{version}.zip"

    parser = argparse.ArgumentParser(description="Package AwanaGIS QGIS plugin ZIP.")
    parser.add_argument("--output", "-o", type=Path, default=default_out, help="Output ZIP file path")
    args = parser.parse_args(argv)

    zip_path, sha_path, digest, names = build_plugin_zip(repo_root, args.output)
    print(f"Built {zip_path} ({len(names)} files)")
    print(f"SHA-256: {digest} -> {sha_path}")


if __name__ == "__main__":
    main()
