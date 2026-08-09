# -*- coding: utf-8 -*-
"""公开视频 URL 下载器：吸收 VideoExtractor 中对审核工作台有用的最小能力。"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from threading import RLock, get_ident
from typing import Any, Dict, Optional
from urllib.parse import unquote, urljoin, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_paths import app_root

ROOT = app_root()
POC_DIR = ROOT / "poc" / "visual_review_poc"
DOWNLOAD_DIR = POC_DIR / "uploaded_videos" / "url_downloads"
MANIFEST_PATH = DOWNLOAD_DIR / "manifest.json"
ALLOWED_HOST_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "bilibili.com",
    "b23.tv",
    "douyin.com",
    "iesdouyin.com",
    "tiktok.com",
    "xiaohongshu.com",
    "xhslink.com",
)
DIRECT_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".mkv")
DIRECT_VIDEO_MAX_BYTES = 200 * 1024 * 1024
DIRECT_REDIRECT_CODES = {301, 302, 303, 307, 308}
DIRECT_REDIRECT_LIMIT = 5


_MANIFEST_LOCK = RLock()

URL_PATTERNS = [
    ("douyin", re.compile(r"https?://v\.douyin\.com/[\w-]+/?")),
    ("douyin", re.compile(r"https?://www\.douyin\.com/video/\d+")),
    ("bilibili", re.compile(r"https?://www\.bilibili\.com/video/BV[\w]+")),
    ("bilibili", re.compile(r"https?://b23\.tv/[\w]+")),
    ("tiktok", re.compile(r"https?://www\.tiktok\.com/@[\w.]+/video/\d+")),
    ("xiaohongshu", re.compile(r"https?://www\.xiaohongshu\.com/explore/[\w]+")),
    ("youtube", re.compile(r"https?://www\.youtube\.com/watch\?v=[\w-]+")),
    ("youtube", re.compile(r"https?://youtu\.be/[\w-]+")),
]


def extract_video_url(text: str) -> str:
    """从抖音/小红书等分享文本中提取第一个公开视频 URL。"""
    raw = (text or "").strip()
    for _, pattern in URL_PATTERNS:
        match = pattern.search(raw)
        if match:
            return match.group(0)
    return raw


def detect_platform(url: str) -> str:
    for platform, pattern in URL_PATTERNS:
        if pattern.search(url):
            return platform
    host = urlparse(url).netloc.lower()
    if "youtube" in host or "youtu.be" in host:
        return "youtube"
    if "douyin" in host:
        return "douyin"
    if "bilibili" in host or "b23.tv" in host:
        return "bilibili"
    if "tiktok" in host:
        return "tiktok"
    if "xiaohongshu" in host:
        return "xiaohongshu"
    if _is_direct_video_url(url):
        return "direct_video"
    return "unknown"


def _is_direct_video_url(url: str) -> bool:
    parsed = urlparse(url)
    path = unquote(parsed.path or "").lower()
    return parsed.scheme in {"http", "https"} and any(path.endswith(ext) for ext in DIRECT_VIDEO_EXTENSIONS)


def _is_private_host(host: str, *, resolve_dns: bool = True) -> bool:
    host = (host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    except ValueError:
        pass
    if not resolve_dns:
        return False
    try:
        for item in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(item[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return True
    except OSError:
        return False
    return False


def _resolve_public_ip(host: str, port: int) -> str:
    addresses = []
    try:
        addresses = [item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    except OSError as exc:
        raise ValueError("公开视频直链域名无法解析") from exc
    if not addresses or any(_is_private_host(address, resolve_dns=False) for address in addresses):
        raise ValueError("公开视频直链不允许访问内网或本机地址")
    return addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, *, port: int, timeout: int) -> None:
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _DirectResponse:
    def __init__(self, response: http.client.HTTPResponse, connection: _PinnedHTTPSConnection, url: str) -> None:
        self._response = response
        self._connection = connection
        self._url = url
        self.headers = response.headers
        self.status = response.status

    def read(self, size: int = -1) -> bytes:
        return self._response.read(size)

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self._response.close()
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def validate_public_video_url(url: str) -> Dict[str, Any]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return {"ok": False, "status": "invalid_url", "error": "只支持公开视频链接"}
    if _is_private_host(host, resolve_dns=False):
        return {"ok": False, "status": "blocked_private_host", "error": "不支持内网或本机地址"}
    platform_allowed = any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)
    if not platform_allowed and not _is_direct_video_url(url):
        return {"ok": False, "status": "unsupported_platform", "error": "暂不支持该视频平台"}
    if not platform_allowed and parsed.scheme != "https":
        return {"ok": False, "status": "insecure_direct_url", "error": "公开视频直链仅支持 HTTPS"}
    strict_dns = os.getenv("VISUAL_URL_STRICT_DNS_GUARD", "1").strip().lower() in {"1", "true", "yes"}
    if strict_dns and not platform_allowed and _is_private_host(host):
        return {"ok": False, "status": "blocked_private_host", "error": "不支持内网或本机地址"}
    return {"ok": True}


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    return stem[:80] or "video"


def _url_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _load_manifest() -> Dict[str, Any]:
    with _MANIFEST_LOCK:
        if not MANIFEST_PATH.exists():
            return {"items": {}}
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"items": {}}


def _save_manifest(manifest: Dict[str, Any]) -> None:
    with _MANIFEST_LOCK:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        temporary = MANIFEST_PATH.with_name(f".manifest.{os.getpid()}.{get_ident()}.tmp")
        try:
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(MANIFEST_PATH)
        finally:
            temporary.unlink(missing_ok=True)


def _update_manifest_item(key: str, item: Dict[str, Any]) -> None:
    with _MANIFEST_LOCK:
        manifest = _load_manifest()
        manifest.setdefault("items", {})[key] = item
        _save_manifest(manifest)


def _cookies_args() -> list[str]:
    args: list[str] = []
    cookies_file = os.getenv("VISUAL_URL_COOKIES_FILE", "").strip()
    cookies_browser = os.getenv("VISUAL_URL_COOKIES_BROWSER", "").strip()
    if cookies_file:
        args.extend(["--cookies", cookies_file])
    elif cookies_browser:
        args.extend(["--cookies-from-browser", cookies_browser])
    return args


def _direct_video_max_bytes() -> int:
    raw = os.getenv("VISUAL_URL_DIRECT_MAX_MB", "").strip()
    try:
        mb = int(raw) if raw else 200
    except ValueError:
        mb = 200
    return max(10, min(mb, 1024)) * 1024 * 1024


def _direct_video_title(url: str) -> str:
    name = Path(unquote(urlparse(url).path or "")).name
    return name or "公开直连视频"


def _direct_headers() -> Dict[str, str]:
    return {"User-Agent": "MITAKO-VisualReview/1.0"}


def _validate_direct_request_target(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise ValueError("公开视频直链及其跳转目标必须使用 HTTPS")
    if _is_private_host(host):
        raise ValueError("公开视频直链不允许访问内网或本机地址")


def _open_pinned_https(url: str, *, method: str, timeout: int) -> _DirectResponse:
    parsed = urlparse(url)
    host = str(parsed.hostname or "")
    port = parsed.port or 443
    pinned_ip = _resolve_public_ip(host, port)
    connection = _PinnedHTTPSConnection(host, pinned_ip, port=port, timeout=timeout)
    target = parsed.path or "/"
    if parsed.params:
        target += f";{parsed.params}"
    if parsed.query:
        target += f"?{parsed.query}"
    try:
        connection.request(method, target, headers=_direct_headers())
        return _DirectResponse(connection.getresponse(), connection, url)
    except Exception:
        connection.close()
        raise


def _open_public_direct_url(url: str, *, method: str, timeout: int):
    current_url = url
    for _ in range(DIRECT_REDIRECT_LIMIT + 1):
        _validate_direct_request_target(current_url)
        response = _open_pinned_https(current_url, method=method, timeout=timeout)
        if response.status in DIRECT_REDIRECT_CODES:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("公开视频直链跳转缺少目标地址")
            current_url = urljoin(current_url, location)
            continue
        if response.status >= 400:
            response.close()
            raise ValueError(f"公开视频直链请求失败：HTTP {response.status}")
        return response
    raise ValueError("公开视频直链跳转次数过多")


def _fetch_direct_metadata(url: str) -> Dict[str, Any]:
    started = time.time()
    title = _direct_video_title(url)
    try:
        with _open_public_direct_url(url, method="HEAD", timeout=20) as resp:
            size = int(resp.headers.get("Content-Length") or 0)
            content_type = resp.headers.get("Content-Type") or ""
    except Exception:
        size = 0
        content_type = ""
    return {
        "ok": True,
        "status": "metadata_ready",
        "platform": "direct_video",
        "title": title,
        "author": "公开视频文件",
        "duration": None,
        "thumbnail_url": "",
        "webpage_url": url,
        "extractor": "direct",
        "bytes": size,
        "content_type": content_type,
        "latency_seconds": round(time.time() - started, 2),
    }


def _download_direct_video_url(url: str) -> Dict[str, Any]:
    started = time.time()
    metadata = _fetch_direct_metadata(url)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    key = _url_key(url)
    parsed = urlparse(url)
    suffix = Path(unquote(parsed.path or "")).suffix.lower()
    if suffix not in DIRECT_VIDEO_EXTENSIONS:
        suffix = ".mp4"
    target = DOWNLOAD_DIR / f"{key}_{_safe_stem(parsed.netloc)}{suffix}"
    temp_target = target.with_name(f".{target.name}.{get_ident()}.{time.time_ns()}.part")
    limit = _direct_video_max_bytes()
    total = 0
    try:
        with _open_public_direct_url(url, method="GET", timeout=300) as resp, temp_target.open("wb") as f:
            expected = int(resp.headers.get("Content-Length") or 0)
            if expected > limit:
                return {
                    "ok": False,
                    "status": "direct_file_too_large",
                    "url": url,
                    "platform": "direct_video",
                    "metadata": metadata,
                    "max_bytes": limit,
                    "bytes": expected,
                }
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    try:
                        temp_target.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return {
                        "ok": False,
                        "status": "direct_file_too_large",
                        "url": url,
                        "platform": "direct_video",
                        "metadata": metadata,
                        "max_bytes": limit,
                        "bytes": total,
                    }
                f.write(chunk)
    except Exception:
        try:
            temp_target.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "ok": False,
            "status": "direct_download_failed",
            "url": url,
            "platform": "direct_video",
            "metadata": metadata,
            "latency_seconds": round(time.time() - started, 2),
        }
    if total <= 0:
        temp_target.unlink(missing_ok=True)
        return {"ok": False, "status": "direct_empty_file", "url": url, "platform": "direct_video", "metadata": metadata}
    temp_target.replace(target)
    item = {
        "url": url,
        "platform": "direct_video",
        "path": str(target),
        "bytes": total,
        "metadata": metadata,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _update_manifest_item(key, item)
    return {"ok": True, "status": "downloaded", "latency_seconds": round(time.time() - started, 2), **item}


def _run_ytdlp(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "yt_dlp", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def fetch_metadata(url: str) -> Dict[str, Any]:
    validation = validate_public_video_url(url)
    if not validation.get("ok"):
        return {**validation, "platform": detect_platform(url)}
    if detect_platform(url) == "direct_video":
        return _fetch_direct_metadata(url)
    command = [
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        *(_cookies_args()),
        url,
    ]
    started = time.time()
    try:
        proc = _run_ytdlp(command, timeout=90)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "metadata_timeout", "platform": detect_platform(url)}
    except OSError:
        return {"ok": False, "status": "metadata_subprocess_error", "platform": detect_platform(url)}
    if proc.returncode != 0:
        return {
            "ok": False,
            "status": "metadata_failed",
            "platform": detect_platform(url),
            "latency_seconds": round(time.time() - started, 2),
        }
    try:
        raw = json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "status": "metadata_parse_failed", "platform": detect_platform(url)}
    return {
        "ok": True,
        "status": "metadata_ready",
        "platform": detect_platform(url),
        "title": raw.get("title"),
        "author": raw.get("uploader") or raw.get("channel") or raw.get("creator"),
        "duration": raw.get("duration"),
        "thumbnail_url": raw.get("thumbnail"),
        "webpage_url": raw.get("webpage_url") or url,
        "extractor": raw.get("extractor_key") or raw.get("extractor"),
        "latency_seconds": round(time.time() - started, 2),
    }


def _cached_item(url: str) -> Optional[Dict[str, Any]]:
    item = (_load_manifest().get("items") or {}).get(_url_key(url))
    if not item:
        return None
    path = Path(item.get("path", ""))
    if path.exists() and path.stat().st_size > 0:
        return item | {"cached": True, "bytes": path.stat().st_size}
    return None


def download_video_url(text: str, seconds: int = 60) -> Dict[str, Any]:
    """下载 URL 视频到本地，返回可传给审核脚本的视频路径。"""
    url = extract_video_url(text)
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "status": "invalid_url", "error": "只支持 http/https URL", "input": text}
    validation = validate_public_video_url(url)
    if not validation.get("ok"):
        return {**validation, "url": url, "platform": detect_platform(url)}

    cached = _cached_item(url)
    if cached:
        return {"ok": True, "status": "cached", "url": url, "platform": detect_platform(url), **cached}
    if detect_platform(url) == "direct_video":
        return _download_direct_video_url(url)

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    key = _url_key(url)
    target = DOWNLOAD_DIR / f"{key}_{_safe_stem(urlparse(url).netloc)}.mp4"
    template = str(target.with_suffix(".%(ext)s"))
    metadata = fetch_metadata(url)
    command = [
        "--no-playlist",
        "--no-warnings",
        "--restrict-filenames",
        "--download-sections",
        f"*00:00-00:{max(5, min(seconds, 59)):02d}",
        "--force-keyframes-at-cuts",
        "-f",
        "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        template,
        *(_cookies_args()),
        url,
    ]
    started = time.time()
    try:
        proc = _run_ytdlp(command, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "download_timeout", "url": url, "platform": detect_platform(url), "metadata": metadata}
    except OSError:
        return {"ok": False, "status": "download_subprocess_error", "url": url, "platform": detect_platform(url), "metadata": metadata}
    result: Dict[str, Any] = {
        "ok": proc.returncode == 0,
        "status": "downloaded" if proc.returncode == 0 else "yt_dlp_failed",
        "url": url,
        "platform": detect_platform(url),
        "metadata": metadata,
        "latency_seconds": round(time.time() - started, 2),
    }
    if proc.returncode != 0:
        return result

    candidates = sorted(target.parent.glob(f"{target.stem}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if candidate.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"} and candidate.stat().st_size > 0:
            final = target if candidate.suffix.lower() != ".mp4" else candidate
            if candidate != final:
                candidate.replace(final)
            item = {
                "url": url,
                "platform": detect_platform(url),
                "path": str(final),
                "bytes": final.stat().st_size,
                "metadata": metadata,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            _update_manifest_item(key, item)
            result.update(item)
            return result
    result.update({"ok": False, "status": "download_missing_output"})
    return result


def self_check() -> None:
    sample = "复制口令 https://youtu.be/abc_DEF-123 更多文字"
    assert extract_video_url(sample) == "https://youtu.be/abc_DEF-123"
    assert detect_platform("https://www.bilibili.com/video/BV1xx411c7mD") == "bilibili"
    assert detect_platform("https://v.douyin.com/abc/") == "douyin"
    assert validate_public_video_url("https://www.youtube.com/watch?v=abc_DEF-123")["ok"]
    assert not validate_public_video_url("http://127.0.0.1:7861/")["ok"]
    assert validate_public_video_url("http://127.0.0.1:7861/")["status"] == "blocked_private_host"
    assert validate_public_video_url("http://localhost:7861/")["status"] == "blocked_private_host"
    assert not validate_public_video_url("https://example.com/video")["ok"]
    assert validate_public_video_url("https://cdn.example.com/path/sample.mp4")["ok"]
    assert detect_platform("https://cdn.example.com/path/sample.mp4") == "direct_video"


def main() -> int:
    if len(sys.argv) < 2:
        self_check()
        print("url_video_fetcher self-check passed")
        return 0
    print(json.dumps(download_video_url(sys.argv[1]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
