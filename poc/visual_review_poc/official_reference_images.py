# -*- coding: utf-8 -*-
"""按审核任务安全拉取、压缩并缓存官方商品参考图。"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import queue
import socket
import threading
import time
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError

from poc.visual_review_poc.order_info_adapter import (
    DEFAULT_PRODUCT_IMAGE_BASE_URL,
    product_image_url,
)
from runtime_paths import data_dir
from review_media_safety import valid_media_magic


ALLOWED_IMAGE_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_CACHE_HOUSEKEEPING_LOCK = threading.Lock()


def official_reference_cache_dir() -> Path:
    configured = os.getenv("REVIEW_PRODUCT_IMAGE_CACHE_DIR", "").strip()
    return Path(configured).resolve() if configured else (data_dir() / "visual_review_product_refs").resolve()


def _bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except ValueError:
        value = default
    return max(low, min(value, high))


def _values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _context_sources(case: Dict[str, Any]) -> list[Dict[str, Any]]:
    structured = case.get("structured_business_context") or {}
    if not isinstance(structured, dict):
        return []
    sources = [structured]
    frontdesk = structured.get("frontdesk_evidence_package")
    if isinstance(frontdesk, dict):
        sources.append(frontdesk)
    return sources


def _claimed_item_refs(case: Dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for source in _context_sources(case):
        identity = source.get("continuity_claim_identity") or {}
        if isinstance(identity, dict):
            refs.update(
                str(identity.get(key) or "").strip()
                for key in ("item_ref", "sku")
                if str(identity.get(key) or "").strip()
            )
        scope = source.get("claim_scope") or {}
        if not isinstance(scope, dict):
            continue
        refs.update(str(item or "").strip() for item in scope.get("item_refs") or [] if str(item or "").strip())
        for claim in scope.get("claims") or []:
            if isinstance(claim, dict) and str(claim.get("subject_ref") or "").strip():
                refs.add(str(claim["subject_ref"]).strip())
    return refs


def collect_official_image_references(case: Dict[str, Any]) -> list[Dict[str, str]]:
    collected: list[Dict[str, str]] = []
    by_url: Dict[str, Dict[str, Any]] = {}
    claimed_refs = _claimed_item_refs(case)
    for source in _context_sources(case):
        fulfillment = source.get("fulfillment_baseline") or {}
        expected = fulfillment.get("expected_items") or [] if isinstance(fulfillment, dict) else []
        expected_rows = [item for item in expected if isinstance(item, dict)]
        allowed_refs = {str(item.get("item_ref") or "").strip() for item in expected_rows if str(item.get("item_ref") or "").strip()}
        allowed_skus = {str(item.get("sku") or "").strip() for item in expected_rows if str(item.get("sku") or "").strip()}
        product_master = source.get("product_master_data") or {}
        master_rows = product_master.values() if isinstance(product_master, dict) else []
        rows = expected_rows + [
            item for item in master_rows
            if isinstance(item, dict)
            and (
                str(item.get("item_ref") or "").strip() in allowed_refs
                or str(item.get("sku") or "").strip() in allowed_skus
            )
        ]
        for row in rows:
            urls = list(_values(row.get("master_image_urls")))
            if not urls and row.get("product_image_ref"):
                urls = [str(row["product_image_ref"])]
            for reference in urls:
                parsed_reference = urlsplit(reference)
                url = reference if parsed_reference.scheme or parsed_reference.netloc else product_image_url(reference)
                if not url:
                    continue
                item_ref = str(row.get("item_ref") or "").strip()
                sku = str(row.get("sku") or "").strip()
                product_name = str(row.get("product_name") or row.get("name") or "").strip()
                entry = by_url.setdefault(url, {
                    "url": url,
                    "item_ref": item_ref,
                    "sku": sku,
                    "product_name": product_name,
                    "item_refs": [],
                    "skus": [],
                    "product_names": [],
                })
                for key, value in (("item_refs", item_ref), ("skus", sku), ("product_names", product_name)):
                    if value and value not in entry[key]:
                        entry[key].append(value)
    collected.extend(by_url.values())
    collected.sort(
        key=lambda item: (
            0
            if claimed_refs.intersection(
                set(item.get("item_refs") or []) | set(item.get("skus") or [])
            )
            else 1
        )
    )
    return collected


def _allowed_hosts() -> set[str]:
    base_host = (urlsplit(os.getenv("REVIEW_PRODUCT_IMAGE_BASE_URL", DEFAULT_PRODUCT_IMAGE_BASE_URL)).hostname or "").lower()
    configured = {
        item.strip().lower()
        for item in os.getenv("REVIEW_PRODUCT_IMAGE_ALLOWED_HOSTS", "cdn-qiniu.danhaotuan.com").split(",")
        if item.strip()
    }
    if base_host:
        configured.add(base_host)
    return configured


def _public_host(host: str, port: int) -> bool:
    try:
        literal = ipaddress.ip_address(host)
        return literal.is_global
    except ValueError:
        pass
    result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result_queue.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except OSError:
            result_queue.put(None)

    threading.Thread(target=resolve, daemon=True, name="official-image-dns").start()
    try:
        addresses = result_queue.get(timeout=_bounded_int("REVIEW_PRODUCT_IMAGE_DNS_TIMEOUT_SECONDS", 3, 1, 10))
    except queue.Empty:
        return False
    if not addresses:
        return False
    resolved = []
    for item in addresses:
        try:
            resolved.append(ipaddress.ip_address(item[4][0]))
        except (IndexError, ValueError):
            return False
    return bool(resolved) and all(address.is_global for address in resolved)


def _url_error(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        return "https_required"
    host = (parsed.hostname or "").lower()
    if not host or host not in _allowed_hosts() or parsed.username or parsed.password:
        return "host_not_allowed"
    try:
        port = parsed.port
    except ValueError:
        return "port_not_allowed"
    if port not in (None, 443):
        return "port_not_allowed"
    if not _public_host(host, port or 443):
        return "host_not_public"
    return ""


def _cache_hit(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        ttl = _bounded_int("REVIEW_PRODUCT_IMAGE_CACHE_TTL_SECONDS", 604800, 60, 2592000)
        if time.time() - path.stat().st_mtime > ttl:
            path.unlink(missing_ok=True)
            return False
        with path.open("rb") as stream:
            valid = valid_media_magic(".jpg", stream.read(32))
        if valid:
            os.utime(path, None)
        return valid
    except OSError:
        return False


@lru_cache(maxsize=256)
def _url_lock(cache_key: str) -> threading.Lock:
    return threading.Lock()


def _prune_cache(cache_dir: Path) -> None:
    max_bytes = _bounded_int("REVIEW_PRODUCT_IMAGE_CACHE_MAX_MB", 512, 16, 4096) * 1024 * 1024
    with _CACHE_HOUSEKEEPING_LOCK:
        files = sorted(
            (item for item in cache_dir.glob("*.jpg") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
        )
        total = sum(item.stat().st_size for item in files)
        for item in files:
            if total <= max_bytes:
                break
            size = item.stat().st_size
            item.unlink(missing_ok=True)
            total -= size


def _download_and_compress(
    url: str,
    cache_dir: Path,
    client: httpx.Client,
) -> tuple[Optional[Path], str, bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.jpg"
    cache_key = cache_path.stem
    with _url_lock(cache_key):
        if _cache_hit(cache_path):
            return cache_path, "", True
        error = _url_error(url)
        if error:
            return None, error, False
        _prune_cache(cache_dir)
        return _download_uncached(url, cache_path, client)


def _download_uncached(
    url: str,
    cache_path: Path,
    client: httpx.Client,
) -> tuple[Optional[Path], str, bool]:
    max_bytes = _bounded_int("REVIEW_PRODUCT_IMAGE_MAX_BYTES", 8 * 1024 * 1024, 1024, 32 * 1024 * 1024)
    try:
        with client.stream("GET", url, headers={"User-Agent": "MITAKO-Visual-Review/1.0"}) as response:
            if 300 <= response.status_code < 400:
                return None, "redirect_not_allowed", False
            if response.status_code != 200:
                return None, f"http_status_{response.status_code}", False
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            suffix = ALLOWED_IMAGE_MIME.get(content_type)
            if not suffix:
                return None, "unsupported_content_type", False
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                return None, "response_too_large", False
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    return None, "response_too_large", False
    except httpx.TimeoutException:
        return None, "download_timeout", False
    except (httpx.HTTPError, OSError, ValueError):
        return None, "download_failed", False
    if not valid_media_magic(suffix, bytes(body[:32])):
        return None, "invalid_image_content", False
    max_edge = _bounded_int("REVIEW_PRODUCT_IMAGE_MAX_EDGE", 1280, 320, 1920)
    quality = _bounded_int("REVIEW_PRODUCT_IMAGE_JPEG_QUALITY", 82, 70, 92)
    max_pixels = _bounded_int("REVIEW_PRODUCT_IMAGE_MAX_PIXELS", 20000000, 1000000, 40000000)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as source:
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    return None, "image_pixel_limit", False
                source.load()
                image = source.convert("RGB")
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                encoded = io.BytesIO()
                image.save(encoded, format="JPEG", quality=quality, optimize=True)
                encoded_bytes = encoded.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError, MemoryError):
        return None, "invalid_image_content", False
    temp_path = cache_path.with_name(f".{cache_path.stem}.{uuid4().hex}.tmp")
    try:
        temp_path.write_bytes(encoded_bytes)
        os.replace(temp_path, cache_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        return None, "cache_write_failed", False
    return cache_path, "", False


def prepare_official_reference_images(
    case: Dict[str, Any],
    cache_dir: Optional[Path] = None,
    *,
    client: Optional[httpx.Client] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    cache_dir = Path(cache_dir).resolve() if cache_dir else official_reference_cache_dir()
    references = collect_official_image_references(case)
    claimed_refs = sorted(_claimed_item_refs(case))
    reference_fingerprint = hashlib.sha256(
        "\n".join([*claimed_refs, *(item["url"] for item in references)]).encode("utf-8")
    ).hexdigest()[:16]
    existing_status = case.get("official_reference_status") or {}
    if (
        "official_reference_images" in case
        and isinstance(existing_status, dict)
        and existing_status.get("reference_fingerprint") == reference_fingerprint
    ):
        return case
    configured_limit = _bounded_int("REVIEW_PRODUCT_IMAGE_LIMIT", 6, 0, 12) if limit is None else max(0, min(int(limit), 12))
    selected = references[:max(0, min(configured_limit, 12))]
    images: list[Dict[str, Any]] = []
    failures: list[Dict[str, str]] = []
    owns_client = client is None
    active_client = client or httpx.Client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        for reference in selected:
            path, reason, cache_hit = _download_and_compress(reference["url"], cache_dir, active_client)
            reference_id = hashlib.sha256(reference["url"].encode("utf-8")).hexdigest()[:16]
            if not path:
                failures.append({"reference_id": reference_id, "reason": reason})
                continue
            images.append({
                "reference_index": len(images) + 1,
                "reference_id": reference_id,
                "item_ref": reference.get("item_ref", ""),
                "sku": reference.get("sku", ""),
                "product_name": reference.get("product_name", ""),
                "item_refs": reference.get("item_refs", []),
                "skus": reference.get("skus", []),
                "evidence_role": "official_product_reference",
                "api_path": str(path),
                "api_mime_type": "image/jpeg",
                "api_bytes": path.stat().st_size,
                "cache_hit": cache_hit,
            })
    finally:
        if owns_client:
            active_client.close()
    if not selected:
        status = "not_requested"
    elif images and failures:
        status = "partial"
    elif images:
        status = "available"
    else:
        status = "unavailable"
    summary = {
        "status": status,
        "discovered_count": len(references),
        "requested_count": len(selected),
        "available_count": len(images),
        "failed_count": len(failures),
        "limit": max(0, min(configured_limit, 12)),
        "failures": failures,
        "fallback": "text_order_baseline" if failures else "none",
        "reference_fingerprint": reference_fingerprint,
    }
    case["official_reference_images"] = images
    case["official_reference_status"] = summary
    structured = case.setdefault("structured_business_context", {})
    if isinstance(structured, dict):
        structured["official_reference_summary"] = {
            key: value for key, value in summary.items() if key != "failures"
        }
    return case
