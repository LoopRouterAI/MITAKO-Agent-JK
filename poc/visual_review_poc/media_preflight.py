# -*- coding: utf-8 -*-
"""模型送审前的图片与视频质量预算入口。"""
from __future__ import annotations

import io
import logging
import hashlib
import mimetypes
import os
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from poc.visual_review_poc.native_video_proxy import (
    prepare_native_video_proxy,
    video_proxy_recommendation,
    video_proxy_recommendation_from_metadata,
)


LOGGER = logging.getLogger("mitako.visual_review.media_preflight")
DEFAULT_IMAGE_MAX_EDGE = 2560
DEFAULT_IMAGE_RESIZE_TRIGGER_EDGE = 3840
DEFAULT_IMAGE_LOSSY_QUALITY = 90
DEFAULT_NATIVE_INLINE_MAX_BYTES = 70 * 1024 * 1024
DEFAULT_RUNTIME_TEMP_ROOT = Path(r"E:\MITAKO_Agent_Runtime")


def _runtime_directory_available(path: Path) -> bool:
    probe = path / f".mitako-runtime-{os.getpid()}-{time.time_ns()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def resolve_runtime_temp_dir(
    project_root: Path,
    *,
    preferred_root: Path = DEFAULT_RUNTIME_TEMP_ROOT,
) -> Path:
    """解析重型媒体运行目录：显式配置、E 盘、项目内安全回退。"""
    configured = os.getenv("VISUAL_RUNTIME_MEDIA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if _runtime_directory_available(preferred_root):
        return preferred_root.resolve()
    root = project_root.resolve()
    fallback = (root / "tmp" / "visual_review_runtime").resolve()
    if root not in fallback.parents:
        raise RuntimeError("runtime_temp_fallback_outside_project")
    return fallback


def build_media_preflight_execution(
    *,
    native_source: Dict[str, Any] | None,
    native_status: str,
    native_sampling_fps: float | None,
    frame_fallback_used: bool,
    sampled_frame_count: int,
    supplemental_image_count: int,
    frame_sampling_fps: float = 1.0,
    image_execution: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """从真实执行状态生成可公开摘要，不携带路径、URL 或隧道诊断。"""
    source = native_source if isinstance(native_source, dict) else {}
    proxy = source.get("proxy") if isinstance(source.get("proxy"), dict) else {}
    recommendation = (
        source.get("quality_recommendation")
        if isinstance(source.get("quality_recommendation"), dict)
        else {}
    )
    video: Dict[str, Any] = {}
    if source:
        video = {
            "submitted_source": "quality_proxy" if proxy else "original",
            "delivery": "https_url" if source.get("file_uri") else "inline_data",
            "native_review_status": "completed" if native_status == "success" else "failed",
            "native_sampling_fps": native_sampling_fps if native_status == "success" else None,
        }
        for key in (
            "codec_profile", "source_sha256", "proxy_sha256", "cache_hit",
            "source_width", "source_height", "source_fps",
            "source_bitrate_bps", "source_bytes", "source_duration_seconds",
            "proxy_width", "proxy_height", "proxy_fps", "proxy_bitrate_bps",
            "proxy_bytes", "proxy_duration_seconds",
        ):
            if proxy.get(key) not in (None, ""):
                public_key = {
                    "proxy_width": "submitted_width",
                    "proxy_height": "submitted_height",
                    "proxy_fps": "submitted_fps",
                    "proxy_bitrate_bps": "submitted_bitrate_bps",
                    "proxy_bytes": "submitted_bytes",
                    "proxy_duration_seconds": "submitted_duration_seconds",
                }.get(key, key)
                video[public_key] = proxy[key]
        video["quality_reasons"] = [
            str(item)
            for item in recommendation.get("reasons") or []
            if str(item)
        ]
    image_rows = [dict(item) for item in image_execution or [] if isinstance(item, dict)]
    attempted_count = len(image_rows) if image_rows else max(0, int(supplemental_image_count or 0))
    prepared_count = (
        sum(1 for item in image_rows if item.get("status") == "prepared")
        if image_rows
        else max(0, int(supplemental_image_count or 0))
    )
    failed_count = sum(1 for item in image_rows if item.get("status") == "failed")
    status = "failed" if attempted_count and not prepared_count else "partial" if failed_count else "completed"
    return {
        "status": status,
        "video": video,
        "images": {
            "representation": "individual_webp",
            "attempted_count": attempted_count,
            "prepared_count": prepared_count,
            "failed_count": failed_count,
            "assets": image_rows,
            "max_long_edge": DEFAULT_IMAGE_MAX_EDGE,
            "resize_trigger_long_edge": DEFAULT_IMAGE_RESIZE_TRIGGER_EDGE,
            "encoding_order": ["lossless", f"quality_{DEFAULT_IMAGE_LOSSY_QUALITY}"],
            "collage_used": False,
        },
        "frame_fallback": {
            "used": bool(frame_fallback_used),
            "representation": "individual_webp" if frame_fallback_used else "not_used",
            "sampling_fps": float(frame_sampling_fps) if frame_fallback_used else None,
            "frame_count": max(0, int(sampled_frame_count or 0)) if frame_fallback_used else 0,
        },
    }


def build_media_preflight_plan(
    assets: List[Dict[str, Any]],
    *,
    media_forensics: Dict[str, Any] | None = None,
    inline_video_max_bytes: int = DEFAULT_NATIVE_INLINE_MAX_BYTES,
) -> Dict[str, Any]:
    """根据已取得的技术事实生成送审计划，不冒充已经执行。"""
    forensic_assets = {
        str(item.get("asset_id") or ""): item
        for item in (media_forensics or {}).get("assets") or []
        if isinstance(item, dict)
    }
    rows: List[Dict[str, Any]] = []
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        name = str(asset.get("original_name") or asset.get("stored_name") or "")
        mime = str(asset.get("mime_type") or "").lower()
        suffix = Path(name).suffix.lower()
        size = max(0, int(asset.get("size") or 0))
        if mime.startswith("video/") or suffix in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
            forensic = forensic_assets.get(asset_id) or {}
            container = forensic.get("container") if isinstance(forensic.get("container"), dict) else {}
            video_stream = next(
                (
                    item
                    for item in forensic.get("streams") or []
                    if isinstance(item, dict) and item.get("type") == "video"
                ),
                {},
            )
            long_edge = max(
                int(video_stream.get("width") or 0),
                int(video_stream.get("height") or 0),
            )
            fps = float(
                video_stream.get("average_fps")
                or video_stream.get("declared_fps")
                or 0.0
            )
            bitrate = int(container.get("bit_rate") or 0)
            recommendation = video_proxy_recommendation_from_metadata({
                "width": long_edge,
                "height": 0,
                "fps": fps,
                "bit_rate_bps": bitrate,
                "source_bytes": size,
            })
            reasons = list(recommendation["reasons"])
            rows.append({
                "asset_id": asset_id,
                "media_kind": "video",
                "quality_action": "create_quality_proxy" if reasons else "keep_original",
                "quality_reasons": reasons,
                "delivery": "https_url" if size > inline_video_max_bytes else "inline_data",
                "max_long_edge": 2560,
                "minimum_short_edge": 1080,
                "target_fps": 24,
                "max_bitrate_bps": 6_000_000,
                "preferred_codecs": ["vp9"],
            })
        elif mime.startswith("image/") or suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}:
            rows.append({
                "asset_id": asset_id,
                "media_kind": "image",
                "quality_action": "individual_webp",
                "resize_trigger_long_edge": DEFAULT_IMAGE_RESIZE_TRIGGER_EDGE,
                "max_long_edge": DEFAULT_IMAGE_MAX_EDGE,
                "encoding_order": ["lossless", f"quality_{DEFAULT_IMAGE_LOSSY_QUALITY}"],
                "collage_allowed": False,
            })
        else:
            rows.append({
                "asset_id": asset_id,
                "media_kind": "document",
                "quality_action": "keep_original",
            })
    return {
        "status": "planned",
        "execution_claimed": False,
        "assets": rows,
        "boundary": "这里只记录送审计划；实际使用原片、保真代理、URL 或独立 WebP 由执行结果另行记录。",
    }


def mime_for(path: Path) -> str:
    if path.suffix.lower() == ".webp":
        return "image/webp"
    return mimetypes.guess_type(str(path))[0] or "image/jpeg"


def compress_image(
    src: Path,
    dest: Path,
    max_edge: int = DEFAULT_IMAGE_MAX_EDGE,
    quality: int = DEFAULT_IMAGE_LOSSY_QUALITY,
    *,
    lossless_webp: bool = True,
    resize_trigger_edge: int = DEFAULT_IMAGE_RESIZE_TRIGGER_EDGE,
    encoding_diagnostics: Dict[str, Any] | None = None,
) -> Path:
    """图片独立转 WebP；严格超过 4K 才缩至 2K。"""
    raw = np.fromfile(str(src), dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if image is None:
        body = raw.tobytes()
        if body.startswith(b"\xff\xd8") and not body.endswith(b"\xff\xd9"):
            body += b"\xff\xd9"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(body)) as source:
                    width, height = source.size
                    if width <= 0 or height <= 0 or width * height > 40_000_000:
                        raise ValueError("image_pixel_limit")
                    source.load()
                    rgb = ImageOps.exif_transpose(source).convert("RGB")
                    image = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            ValueError,
            MemoryError,
        ) as exc:
            raise ValueError(f"无法安全解码图片：{src.name}") from exc

    source_height, source_width = image.shape[:2]
    source_long_edge = max(source_height, source_width)
    should_resize = source_long_edge > max(1, int(resize_trigger_edge))
    if max_edge < DEFAULT_IMAGE_MAX_EDGE:
        should_resize = source_long_edge > max_edge
    scale = min(1.0, max_edge / source_long_edge) if should_resize else 1.0
    if scale < 1.0:
        image = cv2.resize(
            image,
            (int(source_width * scale), int(source_height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    extension = ".webp" if lossless_webp else ".jpg"
    encode_options = (
        [cv2.IMWRITE_WEBP_QUALITY, 101]
        if lossless_webp
        else [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    encoded_ok, encoded = cv2.imencode(extension, image, encode_options)
    if not encoded_ok:
        raise ValueError(f"无法编码送审图片：{src.name}")
    actual_lossless = bool(lossless_webp)
    actual_quality = None if lossless_webp else max(1, min(int(quality), 100))
    if lossless_webp and len(encoded) >= src.stat().st_size:
        fallback_ok, fallback = cv2.imencode(
            ".webp",
            image,
            [cv2.IMWRITE_WEBP_QUALITY, max(1, min(int(quality), 100))],
        )
        if fallback_ok:
            encoded = fallback
            actual_lossless = False
            actual_quality = max(1, min(int(quality), 100))
    output = dest.with_suffix(".webp") if lossless_webp else dest.with_suffix(".jpg")
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(output))
    if encoding_diagnostics is not None:
        encoding_diagnostics.update({
            "submitted_encoding": "webp" if lossless_webp else "jpeg",
            "submitted_webp_lossless": actual_lossless if lossless_webp else None,
            "submitted_webp_quality": actual_quality if lossless_webp else None,
        })
    return output


def prepare_image_detail_crop(
    item: Dict[str, Any],
    box_2d: List[int],
    media_dir: Path,
    *,
    padding_ratio: float = 0.06,
    max_edge: int = DEFAULT_IMAGE_MAX_EDGE,
) -> Dict[str, Any]:
    """从原图裁出完整材料区域；边界无效或解码失败时保留全图。"""
    if (
        len(box_2d) != 4
        or any(not isinstance(value, int) or not 0 <= value <= 1000 for value in box_2d)
        or box_2d[0] >= box_2d[2]
        or box_2d[1] >= box_2d[3]
    ):
        return dict(item)
    source = Path(item.get("path") or item.get("api_path") or "")
    raw = np.fromfile(str(source), dtype=np.uint8) if source.is_file() else np.array([], dtype=np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR) if raw.size else None
    if image is None:
        return dict(item)
    height, width = image.shape[:2]
    ymin, xmin, ymax, xmax = box_2d
    top = int(height * ymin / 1000)
    left = int(width * xmin / 1000)
    bottom = int(np.ceil(height * ymax / 1000))
    right = int(np.ceil(width * xmax / 1000))
    padding = int(max(bottom - top, right - left) * max(0.0, min(padding_ratio, 0.2)))
    top, left = max(0, top - padding), max(0, left - padding)
    bottom, right = min(height, bottom + padding), min(width, right + padding)
    if bottom - top < 64 or right - left < 64:
        return dict(item)
    detail = image[top:bottom, left:right]
    detail_height, detail_width = detail.shape[:2]
    scale = min(1.0, max_edge / max(detail_height, detail_width))
    if scale < 1.0:
        detail = cv2.resize(
            detail,
            (max(1, int(detail_width * scale)), max(1, int(detail_height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".webp", detail, [cv2.IMWRITE_WEBP_QUALITY, 101])
    if not ok:
        return dict(item)
    image_index = int(item.get("image_index") or 0)
    output = media_dir / f"{image_index:03d}_detail.webp"
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(output))
    cropped = dict(item)
    cropped.update({
        "api_path": str(output),
        "api_mime_type": "image/webp",
        "api_bytes": output.stat().st_size,
        "detail_crop_box_2d": list(box_2d),
    })
    return cropped


def prepare_image_media(
    items: List[Dict[str, Any]],
    media_dir: Path,
    *,
    max_edge: int = DEFAULT_IMAGE_MAX_EDGE,
    quality: int = DEFAULT_IMAGE_LOSSY_QUALITY,
    lossless_webp: bool = True,
    diagnostics: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """逐张准备独立图片，禁止把多帧拼成大图。"""
    prepared = []
    for index, item in enumerate(items, start=1):
        src = Path(item["path"])
        asset_ref = (
            f"supplemental_image_{item['image_index']}"
            if item.get("image_index") not in (None, "")
            else f"video_{item.get('video_index') or 1}_frame_{item.get('global_frame_index') or index}"
        )
        source_bytes = src.stat().st_size if src.is_file() else 0
        source_sha256 = _file_sha256(src) if src.is_file() else ""
        encoding_diagnostics: Dict[str, Any] = {}
        try:
            api_path = compress_image(
                src,
                media_dir / f"{index:03d}_{src.stem}{'.webp' if lossless_webp else '.jpg'}",
                max_edge=max_edge,
                quality=quality,
                lossless_webp=lossless_webp,
                encoding_diagnostics=encoding_diagnostics,
            )
        except ValueError:
            LOGGER.warning("跳过无法安全解码的审核图片：%s", src.name)
            if diagnostics is not None:
                diagnostics.append({
                    "asset_ref": asset_ref,
                    "status": "failed",
                    "source_bytes": source_bytes,
                    "source_sha256": source_sha256,
                    "error_type": "image_decode_failed",
                })
            continue
        copied = dict(item)
        copied["api_path"] = str(api_path)
        copied["api_mime_type"] = mime_for(api_path)
        copied["api_bytes"] = api_path.stat().st_size if api_path.exists() else None
        prepared.append(copied)
        if diagnostics is not None:
            source_width, source_height = _image_dimensions(src)
            submitted_width, submitted_height = _image_dimensions(api_path)
            diagnostics.append({
                "asset_ref": asset_ref,
                "status": "prepared",
                "source_bytes": source_bytes,
                "submitted_bytes": int(copied.get("api_bytes") or 0),
                "source_width": source_width,
                "source_height": source_height,
                "submitted_width": submitted_width,
                "submitted_height": submitted_height,
                "source_sha256": source_sha256,
                "submitted_sha256": _file_sha256(api_path),
                **encoding_diagnostics,
            })
    return prepared


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as image:
            width, height = image.size
        return int(width), int(height)
    except (OSError, UnidentifiedImageError, ValueError):
        return None, None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 兼容旧调用名，产品代码与实验脚本共用同一实现。
prepare_media = prepare_image_media


__all__ = [
    "DEFAULT_IMAGE_LOSSY_QUALITY",
    "DEFAULT_IMAGE_MAX_EDGE",
    "DEFAULT_IMAGE_RESIZE_TRIGGER_EDGE",
    "DEFAULT_NATIVE_INLINE_MAX_BYTES",
    "DEFAULT_RUNTIME_TEMP_ROOT",
    "build_media_preflight_execution",
    "build_media_preflight_plan",
    "compress_image",
    "mime_for",
    "prepare_image_media",
    "prepare_media",
    "prepare_native_video_proxy",
    "resolve_runtime_temp_dir",
    "video_proxy_recommendation",
]
