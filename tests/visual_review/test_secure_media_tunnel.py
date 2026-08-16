# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import io
import json
import logging
import re
import subprocess
import ssl
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlsplit

import httpx


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "poc" / "visual_review_poc" / "secure_media_tunnel.py"


def load_module():
    if not MODULE_PATH.is_file():
        raise AssertionError("安全临时媒体隧道模块尚未实现")
    spec = importlib.util.spec_from_file_location("secure_media_tunnel_under_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("无法加载安全临时媒体隧道模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCloudflaredProcess:
    def __init__(self, output: str, *, wait_timeout: bool = False) -> None:
        self.stdout = io.StringIO(output)
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.wait_timeout:
            self.returncode = 0

    def wait(self, timeout=None):
        if self.wait_timeout and not self.killed:
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class ProcessFactory:
    def __init__(self, process: FakeCloudflaredProcess) -> None:
        self.process = process
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.process


class SecureMediaTunnelTest(unittest.TestCase):
    def test_single_token_route_supports_get_head_range_and_no_store(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("https://unit-test.trycloudflare.com\n")
        factory = ProcessFactory(process)
        access_records = []

        class Capture(logging.Handler):
            def emit(self, record) -> None:
                access_records.append(record)

        handler = Capture()
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.addHandler(handler)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                media = Path(temp_dir) / "evidence.mp4"
                media.write_bytes(b"0123456789")
                with module.open_secure_media_tunnel(
                    media,
                    process_factory=factory,
                    readiness_probe=lambda _url, _timeout: None,
                    startup_timeout=2,
                ) as tunnel:
                    public = urlsplit(tunnel.url)
                    local_url = (
                        f"http://127.0.0.1:{tunnel.diagnostics['bind_port']}"
                        f"{public.path}"
                    )
                    with httpx.Client(timeout=2, trust_env=False) as client:
                        full = client.get(local_url)
                        head = client.head(local_url)
                        ranged = client.get(local_url, headers={"Range": "bytes=2-5"})
                        trailing = client.get(f"{local_url}/", follow_redirects=False)
                        unknown = client.get(
                            f"http://127.0.0.1:{tunnel.diagnostics['bind_port']}/media/not-the-token"
                        )
                        posted = client.post(local_url)

                    self.assertEqual(full.status_code, 200)
                    self.assertEqual(full.content, b"0123456789")
                    self.assertEqual(full.headers["cache-control"], "no-store")
                    self.assertEqual(head.status_code, 200)
                    self.assertEqual(head.content, b"")
                    self.assertEqual(head.headers["content-length"], "10")
                    self.assertEqual(ranged.status_code, 206)
                    self.assertEqual(ranged.content, b"2345")
                    self.assertEqual(ranged.headers["content-range"], "bytes 2-5/10")
                    self.assertEqual(trailing.status_code, 404)
                    self.assertEqual(unknown.status_code, 404)
                    self.assertEqual(posted.status_code, 405)
                    self.assertRegex(public.path, r"^/media/[A-Za-z0-9_-]{40,}$")
                    self.assertNotIn(media.name, public.path)
                    self.assertEqual(tunnel.diagnostics["bind_host"], "127.0.0.1")
                    self.assertGreater(tunnel.diagnostics["bind_port"], 0)
                    self.assertFalse(tunnel.diagnostics["access_log_enabled"])
                    self.assertNotIn(tunnel.url, json.dumps(tunnel.diagnostics, ensure_ascii=False))
                    self.assertNotIn(tunnel.url, repr(tunnel))
        finally:
            access_logger.removeHandler(handler)

        self.assertFalse(access_records)
        self.assertTrue(process.terminated)
        command, kwargs = factory.calls[0]
        self.assertEqual(command[1:3], ["tunnel", "--url"])
        self.assertTrue(command[3].startswith("http://127.0.0.1:"))
        self.assertIn("--no-autoupdate", command)
        self.assertIs(kwargs["stderr"], subprocess.STDOUT)

    def test_context_failure_still_terminates_cloudflared(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess(
            "https://failure-test.trycloudflare.com\n",
            wait_timeout=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "evidence.mp4"
            media.write_bytes(b"video")
            with self.assertRaisesRegex(RuntimeError, "业务失败"):
                with module.open_secure_media_tunnel(
                    media,
                    process_factory=ProcessFactory(process),
                    readiness_probe=lambda _url, _timeout: None,
                    startup_timeout=2,
                ):
                    raise RuntimeError("业务失败")

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)

    def test_waits_until_public_media_url_is_reachable_before_ready(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("https://dns-race.trycloudflare.com\n")
        attempts = []

        def probe(url: str, timeout: float) -> None:
            attempts.append((url, timeout))
            if len(attempts) < 3:
                raise OSError("DNS 尚未传播")

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            module.time, "sleep", return_value=None
        ):
            media = Path(temp_dir) / "evidence.mp4"
            media.write_bytes(b"video")
            with module.open_secure_media_tunnel(
                media,
                process_factory=ProcessFactory(process),
                readiness_probe=probe,
                startup_timeout=2,
            ) as tunnel:
                self.assertEqual(len(attempts), 3)
                self.assertEqual(tunnel.diagnostics["public_probe_attempts"], 3)
                self.assertEqual(urlsplit(attempts[-1][0]).hostname, "dns-race.trycloudflare.com")

    def test_local_tls_eof_is_reported_without_reopening_the_tunnel(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("https://tls-loopback.trycloudflare.com\n")
        attempts = []

        def probe(_url: str, _timeout: float) -> None:
            attempts.append(True)
            raise urllib.error.URLError(ssl.SSLEOFError(8, "unexpected eof"))

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            module.time, "sleep", return_value=None
        ):
            media = Path(temp_dir) / "evidence.webm"
            media.write_bytes(b"video")
            with module.open_secure_media_tunnel(
                media,
                process_factory=ProcessFactory(process),
                readiness_probe=probe,
                startup_timeout=2,
            ) as tunnel:
                self.assertEqual(len(attempts), 3)
                self.assertEqual(tunnel.diagnostics["public_probe_status"], "local_tls_unavailable")


    def test_missing_trycloudflare_url_fails_closed_and_terminates_process(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("cloudflared started without public URL\n")
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "evidence.mp4"
            media.write_bytes(b"video")
            with self.assertRaisesRegex(RuntimeError, "trycloudflare"):
                with module.open_secure_media_tunnel(
                    media,
                    process_factory=ProcessFactory(process),
                    startup_timeout=0.2,
                ):
                    self.fail("缺少安全公网地址时不得进入业务上下文")

        self.assertTrue(process.terminated)

    def test_rejects_trycloudflare_hostname_prefix_spoof(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("https://unit-test.trycloudflare.com.evil.invalid\n")
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "evidence.mp4"
            media.write_bytes(b"video")
            with self.assertRaisesRegex(RuntimeError, "trycloudflare"):
                with module.open_secure_media_tunnel(
                    media,
                    process_factory=ProcessFactory(process),
                    startup_timeout=0.2,
                ):
                    self.fail("伪装主机不得进入业务上下文")

        self.assertTrue(process.terminated)

    def test_rejects_missing_or_non_file_media_before_starting_process(self) -> None:
        module = load_module()
        process = FakeCloudflaredProcess("https://unused.trycloudflare.com\n")
        factory = ProcessFactory(process)
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                with module.open_secure_media_tunnel(
                    Path(temp_dir) / "missing.mp4",
                    process_factory=factory,
                ):
                    pass
            with self.assertRaises(ValueError):
                with module.open_secure_media_tunnel(
                    Path(temp_dir),
                    process_factory=factory,
                ):
                    pass

        self.assertEqual(factory.calls, [])


if __name__ == "__main__":
    unittest.main()
