# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import tempfile
import threading
import socket
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc import url_video_fetcher


class UrlVideoFetcherTest(unittest.TestCase):
    def test_direct_url_connection_is_pinned_to_the_validated_public_ip(self) -> None:
        connected_addresses = []

        def resolve_public(_host, port, *_args, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def stop_before_tls(address, *_args, **_kwargs):
            connected_addresses.append(address)
            raise OSError("stop before TLS")

        with patch.object(socket, "getaddrinfo", side_effect=resolve_public), patch.object(
            socket, "create_connection", side_effect=stop_before_tls
        ):
            with self.assertRaisesRegex(OSError, "stop before TLS"):
                url_video_fetcher._open_public_direct_url(
                    "https://cdn.example.com/public.mp4",
                    method="GET",
                    timeout=5,
                )

        self.assertEqual(connected_addresses, [("93.184.216.34", 443)])

    def test_concurrent_manifest_updates_preserve_every_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir)
            manifest_path = download_dir / "manifest.json"
            with patch.object(url_video_fetcher, "DOWNLOAD_DIR", download_dir), patch.object(
                url_video_fetcher, "MANIFEST_PATH", manifest_path
            ):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(
                        lambda index: url_video_fetcher._update_manifest_item(
                            f"key-{index}", {"index": index}
                        ),
                        range(40),
                    ))

                manifest = url_video_fetcher._load_manifest()

        self.assertEqual(len(manifest["items"]), 40)
        self.assertFalse(any(download_dir.glob(".manifest.*.tmp")))

    def test_direct_video_redirect_to_private_host_is_blocked_before_following(self) -> None:
        class Redirect:
            status = 302
            headers = Message()

            def close(self):
                return None

        redirect = Redirect()
        redirect.headers["Location"] = "https://127.0.0.1/private.mp4"

        with patch.object(url_video_fetcher, "_open_pinned_https", return_value=redirect) as opener:
            with self.assertRaisesRegex(ValueError, "内网"):
                url_video_fetcher._open_public_direct_url(
                    "https://cdn.example.com/public.mp4",
                    method="GET",
                    timeout=5,
                )

        opener.assert_called_once()

    def test_failed_concurrent_direct_download_does_not_delete_successful_file(self) -> None:
        successful_write_finished = threading.Event()
        call_lock = threading.Lock()
        call_count = 0

        class Response:
            def __init__(self, fail: bool) -> None:
                self.fail = fail
                self.headers = Message()
                self.headers["Content-Length"] = "4"
                self.read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size: int) -> bytes:
                if self.fail:
                    successful_write_finished.wait(timeout=2)
                    raise OSError("并发下载失败")
                self.read_count += 1
                if self.read_count == 1:
                    return b"data"
                successful_write_finished.set()
                return b""

        def open_url(*_args, **_kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
                return Response(fail=call_count == 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir)
            manifest_path = download_dir / "manifest.json"
            with patch.object(url_video_fetcher, "DOWNLOAD_DIR", download_dir), patch.object(
                url_video_fetcher, "MANIFEST_PATH", manifest_path
            ), patch.object(
                url_video_fetcher, "_fetch_direct_metadata", return_value={"ok": True}
            ), patch.object(url_video_fetcher, "_open_public_direct_url", side_effect=open_url):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(
                        url_video_fetcher._download_direct_video_url,
                        ["https://cdn.example.com/video.mp4"] * 2,
                    ))

                success = next(item for item in results if item["ok"])
                self.assertTrue(Path(success["path"]).exists())
                self.assertEqual({item["status"] for item in results}, {"downloaded", "direct_download_failed"})


if __name__ == "__main__":
    unittest.main()
