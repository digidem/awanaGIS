#!/usr/bin/env python3
"""Download a GitHub Release asset and verify its published SHA-256 digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def _run_json(command: list[str]) -> dict:
    proc = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object from: {' '.join(command)}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository, owner/name")
    parser.add_argument("--tag", required=True, help="Release tag, for example v1.1.1")
    parser.add_argument("--asset", required=True, help="Exact release asset filename")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    release = _run_json([
        "gh", "release", "view", args.tag,
        "--repo", args.repo,
        "--json", "tagName,isDraft,isPrerelease,url,assets",
    ])
    if release.get("isDraft"):
        raise SystemExit("Refusing a draft GitHub Release asset")
    matches = [asset for asset in release.get("assets", []) if asset.get("name") == args.asset]
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one asset named {args.asset!r}")
    digest = str(matches[0].get("digest", ""))
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise SystemExit("Release asset has no valid sha256 digest")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "gh", "release", "download", args.tag,
        "--repo", args.repo,
        "--pattern", args.asset,
        "--dir", str(args.output_dir),
    ], check=True)
    path = args.output_dir / args.asset
    actual = _sha256(path)
    expected = digest.removeprefix("sha256:")
    if actual != expected:
        raise SystemExit(f"SHA-256 mismatch: expected {expected}, got {actual}")

    print(json.dumps({
        "repo": args.repo,
        "tag": release.get("tagName"),
        "release_url": release.get("url"),
        "asset": args.asset,
        "path": str(path),
        "sha256": actual,
        "verified": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
