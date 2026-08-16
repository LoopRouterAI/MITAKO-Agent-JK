# -*- coding: utf-8 -*-
"""仅在上下文生命周期内公开单个媒体文件的临时安全隧道。"""
from __future__ import annotations

import hashlib
import os
import queue
import re
import secrets
import ssl
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route


_BIND_HOST = "127.0.0.1"
_TRY_CLOUDFLARE_URL = re.compile(
    r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.trycloudflare\.com(?![a-z0-9.-])",
    re.IGNORECASE,
)


class SecureMediaTunnel:
    __slots__ = ("_url", "_diagnostics")

    def __init__(self, url: str, diagnostics: Dict[str, Any]) -> None:
        self._url = url
        self._diagnostics = dict(diagnostics)

    @property
    def url(self) -> str:
        """仅供受控供应商请求使用，不应写入日志或持久化报告。"""
        return self._url

    @property
    def diagnostics(self) -> Dict[str, Any]:
        return dict(self._diagnostics)

    def __repr__(self) -> str:
        return f"SecureMediaTunnel(diagnostics={self._diagnostics!r})"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _media_app(media_path: Path, route_path: str) -> Starlette:
    async def serve_media(_: Request) -> FileResponse:
        return FileResponse(
            media_path,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app = Starlette(routes=[Route(route_path, serve_media, methods=["GET", "HEAD"])])
    app.router.redirect_slashes = False
    return app


def _bound_socket() -> tuple[socket.socket, int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((_BIND_HOST, 0))
    listener.listen(128)
    listener.setblocking(False)
    return listener, int(listener.getsockname()[1])


def _start_server(app: Starlette, listener: socket.socket, port: int, timeout: float):
    config = uvicorn.Config(
        app,
        host=_BIND_HOST,
        port=port,
        access_log=False,
        log_level="critical",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    errors = []

    def run() -> None:
        try:
            server.run(sockets=[listener])
        except BaseException as exc:  # 后台线程必须把启动错误传回调用方
            errors.append(exc)

    thread = threading.Thread(target=run, name="secure-media-origin", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=1)
        error_type = type(errors[0]).__name__ if errors else "startup_timeout"
        raise RuntimeError(f"本地安全媒体服务启动失败：{error_type}")
    return server, thread


def _stop_server(server: Any, thread: threading.Thread, listener: socket.socket) -> None:
    server.should_exit = True
    thread.join(timeout=5)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=2)
    try:
        listener.close()
    except OSError:
        pass


def _cloudflared_command(executable: str, local_origin: str) -> list[str]:
    return [executable, "tunnel", "--url", local_origin, "--no-autoupdate"]


def _resolve_cloudflared_executable(configured: str) -> str:
    environment_path = os.getenv("CLOUDFLARED_PATH", "").strip()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    candidates = [environment_path]
    if local_app_data:
        candidates.append(
            str(Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe")
        )
    candidates.extend([configured, shutil.which(configured) or ""])
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path.resolve())
        if candidate == configured and not path.parent.name:
            return candidate
    return configured


def _start_cloudflared(
    executable: str,
    local_origin: str,
    process_factory: Callable[..., Any],
):
    return process_factory(
        _cloudflared_command(executable, local_origin),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _read_public_origin(process: Any, timeout: float) -> str:
    output = process.stdout
    if output is None:
        raise RuntimeError("cloudflared 未提供可读取输出")
    found: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read_output() -> None:
        reported = False
        try:
            for line in iter(output.readline, ""):
                match = _TRY_CLOUDFLARE_URL.search(line)
                if match and not reported:
                    found.put(match.group(0).lower())
                    reported = True
        finally:
            if not reported and found.empty():
                found.put(None)

    threading.Thread(target=read_output, name="cloudflared-origin-reader", daemon=True).start()
    try:
        public_origin = found.get(timeout=timeout)
    except queue.Empty as exc:
        raise RuntimeError("等待 trycloudflare 临时地址超时") from exc
    if not public_origin:
        raise RuntimeError("cloudflared 未返回有效 trycloudflare 临时地址")
    return public_origin


def _stop_process(process: Any) -> None:
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
    finally:
        output = getattr(process, "stdout", None)
        if output is not None:
            try:
                output.close()
            except OSError:
                pass


def _probe_public_media(url: str, timeout: float) -> None:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "MITAKO-Media-Probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=max(0.2, timeout)) as response:
        if int(getattr(response, "status", 0) or 0) not in {200, 206}:
            raise OSError("临时媒体地址尚不可用")


def _wait_public_media_ready(
    url: str,
    process: Any,
    timeout: float,
    probe: Callable[[str, float], None],
) -> tuple[int, float, str]:
    started_at = time.monotonic()
    deadline = started_at + timeout
    attempts = 0
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("cloudflared 在公网媒体地址就绪前退出")
        attempts += 1
        remaining = max(0.2, deadline - time.monotonic())
        try:
            probe(url, min(5.0, remaining))
            return attempts, round(time.monotonic() - started_at, 3), "ready"
        except (OSError, TimeoutError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            reason = getattr(exc, "reason", None)
            if attempts >= 3 and isinstance(reason, ssl.SSLEOFError):
                return attempts, round(time.monotonic() - started_at, 3), "local_tls_unavailable"
        time.sleep(min(1.0, 0.2 * attempts))
    error_type = type(last_error).__name__ if last_error else "startup_timeout"
    raise RuntimeError(f"等待临时媒体公网地址可达超时：{error_type}")


@contextmanager
def open_secure_media_tunnel(
    media_path: Path | str,
    *,
    cloudflared_executable: str = "cloudflared",
    process_factory: Callable[..., Any] = subprocess.Popen,
    readiness_probe: Callable[[str, float], None] = _probe_public_media,
    startup_timeout: float = 60.0,
) -> Iterator[SecureMediaTunnel]:
    """启动本机单文件源站和 Quick Tunnel，并在任何退出路径清理两者。"""
    source = Path(media_path)
    if not source.exists():
        raise FileNotFoundError(source)
    source = source.resolve()
    if not source.is_file():
        raise ValueError("媒体路径必须是普通文件")
    timeout = max(0.1, float(startup_timeout))
    token = secrets.token_urlsafe(32)
    route_path = f"/media/{token}"
    app = _media_app(source, route_path)
    listener, port = _bound_socket()
    server = None
    server_thread = None
    process = None
    try:
        server, server_thread = _start_server(app, listener, port, timeout)
        local_origin = f"http://{_BIND_HOST}:{port}"
        process = _start_cloudflared(
            _resolve_cloudflared_executable(cloudflared_executable),
            local_origin,
            process_factory,
        )
        public_origin = _read_public_origin(process, timeout)
        public_url = f"{public_origin}{route_path}"
        probe_attempts, probe_seconds, probe_status = _wait_public_media_ready(
            public_url,
            process,
            timeout,
            readiness_probe,
        )
        diagnostics = {
            "status": "ready",
            "bind_host": _BIND_HOST,
            "bind_port": port,
            "route_count": 1,
            "allowed_methods": ["GET", "HEAD"],
            "cache_control": "no-store",
            "access_log_enabled": False,
            "public_origin": "https://***.trycloudflare.com",
            "public_probe_attempts": probe_attempts,
            "public_probe_seconds": probe_seconds,
            "public_probe_status": probe_status,
            "route_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest()[:12],
            "media_bytes": source.stat().st_size,
            "media_sha256": _sha256_file(source),
        }
        yield SecureMediaTunnel(public_url, diagnostics)
    finally:
        _stop_process(process)
        if server is not None and server_thread is not None:
            _stop_server(server, server_thread, listener)
        else:
            try:
                listener.close()
            except OSError:
                pass
