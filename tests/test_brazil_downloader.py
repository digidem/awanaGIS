"""Cache staging tests for the vendored gisbr downloader.

Concurrent loads of the same resource must never share a staging file: a
worker that publishes (renames) the shared ``.part`` while another is still
writing would expose incomplete bytes through the cache or fail the second
load.
"""

from importlib import import_module
import itertools
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

PKG = ROOT.name
downloader = import_module(f"{PKG}.integrations.brazil.vendor.gisbr.core.downloader")


class DownloaderStagingTests(unittest.TestCase):
    def test_concurrent_downloads_of_same_resource_stage_separately(self):
        payloads = [b"A" * 4096, b"B" * 8192]
        barrier = threading.Barrier(2, timeout=10)
        counter = itertools.count()
        counter_lock = threading.Lock()
        staged = []
        real_replace = os.replace

        def fake_http(url):
            with counter_lock:
                index = next(counter)
            # Both workers are mid-download at the same time.
            barrier.wait()
            return payloads[index]

        def recording_replace(src, dst):
            staged.append(Path(src))
            return real_replace(src, dst)

        results = []
        errors = []

        def worker():
            try:
                results.append(
                    downloader._fetch_to_cache(
                        "layer.gpkg", ["https://example.invalid/layer.gpkg"]
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Path(tmpdir)
            with patch.object(downloader, "cache_dir", return_value=cache), patch.object(
                downloader, "_http_get", side_effect=fake_http
            ), patch("os.replace", side_effect=recording_replace):
                threads = [threading.Thread(target=worker) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(15)

            self.assertEqual(errors, [])
            dest = cache / "layer.gpkg"
            self.assertEqual(set(results), {dest})
            self.assertIn(dest.read_bytes(), payloads)

            # Each worker staged into its own file inside the cache dir.
            self.assertEqual(len(staged), 2)
            self.assertEqual(len(set(staged)), 2, staged)
            self.assertTrue(all(path.parent == cache for path in staged))

            # Nothing but the published resource is left behind.
            self.assertEqual(sorted(p.name for p in cache.iterdir()), ["layer.gpkg"])

    def test_publish_failure_removes_staging_file(self):
        def failing_replace(src, dst):
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Path(tmpdir)
            with patch.object(downloader, "cache_dir", return_value=cache), patch.object(
                downloader, "_http_get", return_value=b"x" * 32
            ), patch("os.replace", side_effect=failing_replace):
                with self.assertRaises(OSError):
                    downloader._fetch_to_cache(
                        "layer.gpkg", ["https://example.invalid/layer.gpkg"]
                    )

            self.assertFalse((cache / "layer.gpkg").exists())
            self.assertEqual(list(cache.iterdir()), [])

    def test_failed_download_leaves_no_artifacts(self):
        def failing_http(url):
            raise downloader.DownloadError("boom")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Path(tmpdir)
            with patch.object(downloader, "cache_dir", return_value=cache), patch.object(
                downloader, "_http_get", side_effect=failing_http
            ):
                with self.assertRaises(downloader.DownloadError):
                    downloader._fetch_to_cache(
                        "layer.gpkg",
                        [
                            "https://example.invalid/layer.gpkg",
                            "https://mirror.invalid/layer.gpkg",
                        ],
                    )

            self.assertEqual(list(cache.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
