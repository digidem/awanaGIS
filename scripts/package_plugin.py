#!/usr/bin/env python3
"""Build a clean, deterministic QGIS plugin ZIP archive for AwanaGIS."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import zipfile

PLUGIN_ROOT_NAME = "awanagis"
FIXED_ZIP_TIME = (2026, 11, 23, 0, 0, 0)

APPROVED_ROOT_FILES = frozenset({
    "__init__.py",
    "plugin.py",
    "config.py",
    "metadata.txt",
    "README.md",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_LICENSES.md",
})

APPROVED_RUNTIME_DIRS = frozenset({
    "core",
    "backends",
    "gui",
    "server",
    "resources",
    "i18n",
    "integrations",
})

EXCLUDED_DIR_NAMES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".git",
})

EXCLUDED_FILES = frozenset({
    ".DS_Store",
    "Thumbs.db",
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
    """Return True if *rel_path* is in the approved AwanaGIS runtime manifest."""
    parts = rel_path.parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in APPROVED_ROOT_FILES
    if parts[0] not in APPROVED_RUNTIME_DIRS:
        return False
    if any(part in EXCLUDED_DIR_NAMES or part.endswith(".egg-info") for part in parts[:-1]):
        return False
    name = parts[-1]
    if name in EXCLUDED_FILES or name.endswith(EXCLUDED_SUFFIXES):
        return False
    return True


def _iter_git_tracked_paths(repo_root: Path):
    """Return relative Paths for tracked files in *repo_root* via ``git ls-files``."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout.split(b"\x00")
    return [Path(item.decode("utf-8")) for item in raw if item]


def _iter_manifest_paths(repo_root: Path):
    """Fallback manifest walk when packaging an exported tree without Git metadata."""
    paths = []
    for name in sorted(APPROVED_ROOT_FILES):
        candidate = repo_root / name
        if candidate.exists():
            paths.append(Path(name))
    for dirname in sorted(APPROVED_RUNTIME_DIRS):
        root_dir = repo_root / dirname
        if not root_dir.is_dir() or root_dir.is_symlink():
            continue
        for path in root_dir.rglob("*"):
            paths.append(path.relative_to(repo_root))
    return paths


def iter_package_files(repo_root: Path):
    """Yield sorted ``(abs_path, rel_path)`` pairs from the approved runtime manifest.

    In a Git checkout/worktree, only tracked files (``git ls-files``) are
    considered so untracked local files never enter the ZIP. Symlinks are
    always rejected.
    """
    repo_root = Path(repo_root).resolve()
    is_git_repo = (repo_root / ".git").exists()
    candidates = _iter_git_tracked_paths(repo_root) if is_git_repo else _iter_manifest_paths(repo_root)

    entries = []
    for rel in candidates:
        if not should_include(rel):
            continue
        # Reject symlinks anywhere along the relative path inside the repo.
        cur = repo_root
        has_symlink = False
        for part in rel.parts:
            cur = cur / part
            if cur.is_symlink():
                has_symlink = True
                break
        if has_symlink or not cur.is_file():
            continue
        entries.append((cur, rel))
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
