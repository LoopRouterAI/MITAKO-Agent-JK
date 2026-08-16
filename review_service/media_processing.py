# -*- coding: utf-8 -*-
"""正式审核工单的持久送审媒体准备。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Sequence

from poc.visual_review_poc.native_video_proxy import (
    prepare_native_video_proxy,
    video_proxy_recommendation,
)


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


class MediaPreparationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_video(asset: Dict[str, Any]) -> bool:
    mime = str(asset.get("mime_type") or "").lower()
    name = str(asset.get("stored_name") or asset.get("original_name") or "")
    return mime.startswith("video/") or Path(name).suffix.lower() in VIDEO_SUFFIXES


def _load_manifest(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_job_review_manifest(job_dir: Path) -> Dict[str, Any]:
    return _load_manifest(Path(job_dir) / "review_media_derivatives.json")


def media_execution_from_manifest(
    manifest: Dict[str, Any],
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """把内部持久化清单投影为不含路径的公开执行事实。"""
    output = dict(existing or {})
    existing_rows = {
        int(item.get("video_index") or 0): item
        for item in output.get("videos") or []
        if isinstance(item, dict) and int(item.get("video_index") or 0) > 0
    }
    if isinstance(output.get("video"), dict):
        existing_rows.setdefault(1, output["video"])
    rows = []
    for item in manifest.get("videos") or []:
        if not isinstance(item, dict):
            continue
        index = int(item.get("video_index") or 0)
        if index <= 0:
            continue
        row = dict(existing_rows.get(index) or {})
        transform = item.get("transformation") if isinstance(item.get("transformation"), dict) else {}
        derivative = item.get("model_input_kind") == "review_derivative"
        row.update({
            "video_index": index,
            "submitted_source": "quality_proxy" if derivative else "original",
            "source_sha256": item.get("source_sha256"),
            "proxy_sha256": item.get("review_sha256") if derivative else None,
            "source_bytes": item.get("source_bytes"),
            "submitted_bytes": item.get("review_bytes"),
            "preparation_status": item.get("validation_status"),
        })
        for key, value in transform.items():
            if key.startswith("proxy_"):
                row[{"proxy_width": "submitted_width", "proxy_height": "submitted_height",
                     "proxy_fps": "submitted_fps", "proxy_bitrate_bps": "submitted_bitrate_bps",
                     "proxy_duration_seconds": "submitted_duration_seconds"}.get(key, key)] = value
            elif key not in {"review_stored_name"}:
                row[key] = value
        rows.append({key: value for key, value in row.items() if value not in (None, "")})
    if rows:
        output["videos"] = rows
        output["video"] = rows[0] if len(rows) == 1 else {}
    return output


def _write_manifest(path: Path, videos: Sequence[Dict[str, Any]]) -> None:
    temporary = path.with_suffix(".json.part")
    temporary.write_text(
        json.dumps({"version": 2, "videos": list(videos)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _materialize(source: Path, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        os.link(source, temporary)
    except OSError:
        shutil.copy2(source, temporary)
    temporary.replace(target)


def _proxy_limit_bytes() -> int:
    try:
        mb = int(os.getenv("VISUAL_NATIVE_URL_PROXY_MAX_MB", "512") or 512)
    except ValueError:
        mb = 512
    return max(100, min(mb, 2048)) * 1024 * 1024


def prepare_job_review_media(
    job_dir: Path,
    assets: Sequence[Dict[str, Any]],
    cache_dir: Path,
) -> Dict[str, Any]:
    """在模型调用前冻结实际送审文件；同一工单重试复用已验证衍生片。"""
    job_dir = Path(job_dir).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = job_dir / "review_media_derivatives.json"
    existing = {
        int(item.get("video_index") or 0): item
        for item in _load_manifest(manifest_path).get("videos") or []
        if isinstance(item, dict) and int(item.get("video_index") or 0) > 0
    }
    files: Dict[str, str] = {}
    mime_types: Dict[str, str] = {}
    records = []
    video_index = 0

    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        source = (job_dir / str(asset.get("stored_name") or "")).resolve()
        if not source.is_file() or not source.is_relative_to(job_dir):
            raise FileNotFoundError(f"审核素材不存在：{asset_id}")
        files[asset_id] = str(source)
        mime_types[asset_id] = str(asset.get("mime_type") or "application/octet-stream")
        if not _is_video(asset):
            continue

        video_index += 1
        source_sha256 = str(asset.get("sha256") or "") or _sha256(source)
        target = job_dir / f"browser_preview_{video_index:03d}.webm"
        old = existing.get(video_index) or {}
        if (
            old.get("validation_status") == "ready"
            and old.get("source_sha256") == source_sha256
            and old.get("model_input_kind") == "review_derivative"
            and target.is_file()
            and old.get("review_sha256") == _sha256(target)
        ):
            files[asset_id] = str(target)
            mime_types[asset_id] = "video/webm"
            records.append(old)
            continue

        recommendation = video_proxy_recommendation(source)
        if not recommendation.get("recommended"):
            source_metadata = recommendation.get("source_metadata") if isinstance(recommendation.get("source_metadata"), dict) else {}
            records.append({
                "video_index": video_index,
                "source_asset_id": asset_id,
                "source_sha256": source_sha256,
                "review_sha256": source_sha256,
                "source_bytes": source.stat().st_size,
                "review_bytes": source.stat().st_size,
                "model_input_kind": "original",
                "transformation": {
                    "quality_action": "keep_original",
                    "quality_observations": list(recommendation.get("observations") or []),
                    **{
                        f"source_{key}": value
                        for key, value in source_metadata.items()
                        if key in {"width", "height", "fps", "bit_rate_bps", "duration_seconds"}
                        and value not in (None, "")
                    },
                },
                "validation_status": "ready",
                "persisted_at": int(time.time()),
            })
            continue

        proxy = prepare_native_video_proxy(
            source,
            job_dir / "media_processing",
            _proxy_limit_bytes(),
            cache_dir=Path(cache_dir),
        )
        if proxy.get("status") != "ready":
            records.append({
                "video_index": video_index,
                "source_asset_id": asset_id,
                "source_sha256": source_sha256,
                "model_input_kind": "unavailable",
                "validation_status": "failed",
                "error_type": str(proxy.get("error_type") or "video_transcode_failed"),
                "persisted_at": int(time.time()),
            })
            _write_manifest(manifest_path, records)
            raise MediaPreparationError(str(proxy.get("error_type") or "video_transcode_failed"))

        proxy_path = Path(str(proxy.get("path") or "")).resolve()
        if not proxy_path.is_file():
            raise MediaPreparationError("video_transcode_output_missing")
        proxy_sha256 = str(proxy.get("proxy_sha256") or "") or _sha256(proxy_path)
        if not (target.is_file() and _sha256(target) == proxy_sha256):
            _materialize(proxy_path, target)
        if _sha256(target) != proxy_sha256:
            raise MediaPreparationError("video_transcode_hash_mismatch")

        files[asset_id] = str(target)
        mime_types[asset_id] = "video/webm"
        transformation = {
            key: proxy[key]
            for key in (
                "codec_profile", "cache_hit", "source_width", "source_height",
                "source_fps", "source_bitrate_bps", "source_duration_seconds",
                "proxy_width", "proxy_height", "proxy_fps", "proxy_bitrate_bps",
                "proxy_duration_seconds",
            )
            if proxy.get(key) not in (None, "")
        }
        transformation["quality_action"] = "create_quality_proxy"
        transformation["quality_reasons"] = list(recommendation.get("reasons") or [])
        records.append({
            "video_index": video_index,
            "source_asset_id": asset_id,
            "source_sha256": source_sha256,
            "review_sha256": proxy_sha256,
            "source_bytes": source.stat().st_size,
            "review_bytes": target.stat().st_size,
            "model_input_kind": "review_derivative",
            "review_stored_name": target.name,
            "transformation": transformation,
            "validation_status": "ready",
            "persisted_at": int(time.time()),
        })

    _write_manifest(manifest_path, records)
    return {"files": files, "mime_types": mime_types, "manifest": {"version": 2, "videos": records}}
