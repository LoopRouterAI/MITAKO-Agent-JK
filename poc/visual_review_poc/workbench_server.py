# -*- coding: utf-8 -*-
"""客服视觉审核工作台：上传/URL -> 本地视频 -> 视觉复核报告。"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_paths import app_root
from review_media_safety import (
    FOLDER_SUFFIXES,
    IMAGE_SUFFIXES,
    MEDIA_SUFFIXES,
    VIDEO_SUFFIXES,
    ignored_upload_reason,
    public_skip_reason,
    valid_media_magic,
)
try:
    from poc.visual_review_poc.url_video_fetcher import (
        detect_platform,
        download_video_url,
        extract_video_url,
        fetch_metadata,
    )
except ImportError:
    from url_video_fetcher import detect_platform, download_video_url, extract_video_url, fetch_metadata

try:
    from poc.visual_review_poc.model_selection_e2e import MODEL_CONFIGS, call_model_chunked, load_case_bundle, score_result
    from poc.visual_review_poc.local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from poc.visual_review_poc.report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )
    from poc.visual_review_poc.sample_evaluation import evaluate_sample_rows, read_sample_rows
except ImportError:
    from model_selection_e2e import MODEL_CONFIGS, call_model_chunked, load_case_bundle, score_result
    from local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )
    from sample_evaluation import evaluate_sample_rows, read_sample_rows

ROOT = app_root()
def _env_name(*parts: str) -> str:
    return "_".join(parts)


WORKBENCH_DIR = Path(os.getenv(_env_name("MITAKO", "VISUAL", "WORKBENCH", "DIR")) or ROOT / "poc" / "visual_review_poc").resolve()
UPLOAD_DIR = WORKBENCH_DIR / "uploaded_videos"
REPORT_DIR = WORKBENCH_DIR / "reports"
PUBLIC_SUMMARY_DIR = REPORT_DIR / "public_summaries"
RUNTIME_MEDIA_DIR = (ROOT / "tmp" / "visual_review_workbench").resolve()
INDEX_HTML = WORKBENCH_DIR / "workbench.html"
SAMPLE_MATERIAL_DIR = (ROOT / "docs" / "三大审核场景的小量样本").resolve()
ALLOWED_REPORTS: dict[str, Dict[str, Any]] = {}
MAX_UPLOAD_BYTES = int(os.getenv("VISUAL_MAX_UPLOAD_MB", "650") or 650) * 1024 * 1024
MAX_FOLDER_BYTES = int(os.getenv("VISUAL_MAX_FOLDER_MB", "800") or 800) * 1024 * 1024
MAX_SUPPLEMENTAL_IMAGES = max(1, min(int(os.getenv("VISUAL_MAX_SUPPLEMENTAL_IMAGES", "40") or 40), 80))
MAX_FOLDER_FILES = max(1, int(os.getenv("VISUAL_MAX_FOLDER_FILES", "200") or 200))
MAX_BATCH_FOLDERS = max(1, min(int(os.getenv("VISUAL_MAX_BATCH_FOLDERS", "10") or 10), 20))
MAX_BATCH_FILES = max(MAX_FOLDER_FILES, min(int(os.getenv("VISUAL_MAX_BATCH_FILES", "400") or 400), 1000))
PRIVATE_REPORT_KEYS = {
    "model",
    "display_model",
    "model_key",
    "model_name",
    "provider",
    "channel",
    "usage",
    "tokens",
    "token_usage",
    "usage_metadata",
    "cost",
    "pricing",
    "raw_response",
    "raw",
    "raw_text",
    "thoughtSignature",
    "thought_signature",
    "thoughtsTokenCount",
    "system_prompt",
    "user_prompt",
    "prompt",
    "status_code",
    "error_type",
    "path",
    "api_path",
    "uri",
    "inference_estimate",
    "estimated_usd",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "model_calls",
    "channels",
}
ALLOWED_VIDEO_SUFFIXES = VIDEO_SUFFIXES
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-m4v"}
ALLOWED_MEDIA_SUFFIXES = MEDIA_SUFFIXES
ALLOWED_FOLDER_SUFFIXES = FOLDER_SUFFIXES

app = FastAPI(
    title="MITAKO 视觉审核工作台",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

REVIEW_MODEL_PROFILES = {
    "standard": {"label": "标准连续性复核", "sampling_mode": "dense", "default_max_frames": 1200},
    "fast": {"label": "经济初筛", "sampling_mode": "adaptive", "default_max_frames": 12},
    "backup": {"label": "Strong 强化复核", "sampling_mode": "dense", "default_max_frames": 1800},
}


def _save_upload(file: UploadFile) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original_name = file.filename or "upload.mp4"
    if ignored_upload_reason(original_name):
        raise HTTPException(status_code=400, detail="所选文件是系统隐藏文件，请选择原始视频")
    suffix = Path(original_name).suffix or ".mp4"
    suffix = suffix.lower()
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES or (content_type and content_type not in ALLOWED_VIDEO_TYPES and not content_type.startswith("video/")):
        raise HTTPException(status_code=415, detail="仅支持常见视频文件")
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(file.filename or "upload").stem).strip("._-")[:60] or "upload"
    case_dir = UPLOAD_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
    case_dir.mkdir(parents=True, exist_ok=False)
    target = case_dir / f"{stem}{suffix}"
    total = 0
    head = b""
    try:
        with target.open("wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                if len(head) < 32:
                    head = (head + chunk)[:32]
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="视频文件过大，请先压缩后再上传")
                fh.write(chunk)
        if total <= 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if not valid_media_magic(suffix, head):
            raise HTTPException(status_code=400, detail="视频内容无法识别，请上传原始视频而不是系统资源副本")
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise
    return target


def _safe_basename(name: str, fallback: str) -> str:
    basename = Path(str(name or fallback).replace("\\", "/")).name
    stem = re.sub(r"[^a-zA-Z0-9._\-\u4e00-\u9fff]+", "_", Path(basename).stem).strip("._-")[:60]
    suffix = Path(basename).suffix.lower()
    stem = stem or fallback
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if stem.upper() in reserved:
        stem = f"file_{stem}"
    return stem + suffix


def _save_folder_uploads(files: List[UploadFile]) -> tuple[Path, Dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="请选择工单素材文件夹")
    if len(files) > MAX_FOLDER_FILES:
        raise HTTPException(status_code=413, detail=f"单次最多接收 {MAX_FOLDER_FILES} 个文件，请拆分工单素材")
    target_dir = UPLOAD_DIR / f"folder_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:12]}"
    target_dir.mkdir(parents=True, exist_ok=False)
    total = 0
    accepted: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    used_names: set[str] = set()
    try:
        for index, file in enumerate(files, start=1):
            original_name = file.filename or f"material_{index}"
            display_name = Path(original_name.replace("\\", "/")).name or f"material_{index}"
            reason = ignored_upload_reason(original_name)
            suffix = Path(display_name).suffix.lower()
            if reason:
                skipped.append({"name": display_name, "reason": reason})
                continue
            if suffix not in ALLOWED_FOLDER_SUFFIXES:
                skipped.append({"name": display_name, "reason": "unsupported_suffix"})
                continue
            name = _safe_basename(display_name, f"material_{index}")
            if name in used_names:
                name = f"{index:03d}_{name}"
            used_names.add(name)
            target = target_dir / name
            size = 0
            head = b""
            with target.open("wb") as fh:
                while chunk := file.file.read(1024 * 1024):
                    if len(head) < 32:
                        head = (head + chunk)[:32]
                    size += len(chunk)
                    total += len(chunk)
                    if total > MAX_FOLDER_BYTES:
                        raise HTTPException(status_code=413, detail="文件夹素材过大，请拆分工单或先截取关键片段")
                    fh.write(chunk)
            if size <= 0:
                target.unlink(missing_ok=True)
                skipped.append({"name": display_name, "reason": "empty_file"})
                continue
            if suffix in ALLOWED_MEDIA_SUFFIXES and not valid_media_magic(suffix, head):
                target.unlink(missing_ok=True)
                skipped.append({"name": display_name, "reason": "invalid_media_content"})
                continue
            accepted.append({"name": name, "kind": "video" if suffix in ALLOWED_VIDEO_SUFFIXES else "image" if suffix in IMAGE_SUFFIXES else "context"})
        if not accepted:
            raise HTTPException(status_code=400, detail="文件夹内没有可用视频、图片或文本材料")
        if not any(item["kind"] in {"video", "image"} for item in accepted):
            raise HTTPException(status_code=400, detail="文件夹内没有可审核的视频或图片")
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    summary = {
        "received_count": len(files),
        "accepted_count": len(accepted),
        "video_count": sum(item["kind"] == "video" for item in accepted),
        "image_count": sum(item["kind"] == "image" for item in accepted),
        "context_count": sum(item["kind"] == "context" for item in accepted),
        "skipped_count": len(skipped),
        "skipped_files": [
            {"name": item["name"], "reason": public_skip_reason(item["reason"]), "reason_code": item["reason"]}
            for item in skipped[:50]
        ],
    }
    return target_dir, summary


def _group_batch_folder_uploads(files: List[UploadFile]) -> Dict[str, List[UploadFile]]:
    """把父目录上传按一级子目录拆成互相隔离的工单。"""
    if not files:
        raise HTTPException(status_code=400, detail="请选择包含多个工单子文件夹的父目录")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=413, detail=f"批量目录最多接收 {MAX_BATCH_FILES} 个文件")
    rows: List[tuple[UploadFile, List[str]]] = []
    for file in files:
        original_name = str(file.filename or "").replace("\\", "/")
        if ignored_upload_reason(original_name):
            continue
        parts = [part for part in original_name.split("/") if part and part not in {".", ".."}]
        if parts:
            rows.append((file, parts))
    if not rows:
        raise HTTPException(status_code=400, detail="批量目录内没有可审核文件")
    top_levels = {parts[0] for _, parts in rows}
    strip_selected_root = len(top_levels) == 1 and all(len(parts) >= 2 for _, parts in rows)
    groups: Dict[str, List[UploadFile]] = {}
    case_ids: Dict[str, str] = {}
    used_case_ids: set[str] = set()
    for file, parts in rows:
        relative = parts[1:] if strip_selected_root else parts
        case_name = relative[0] if len(relative) >= 2 else "根目录工单"
        if case_name not in case_ids:
            base_case = re.sub(r"[^a-zA-Z0-9._\-\u4e00-\u9fff]+", "_", case_name).strip("._-")[:72] or "case"
            safe_case = base_case
            suffix = 2
            while safe_case in used_case_ids:
                safe_case = f"{base_case}_{suffix}"
                suffix += 1
            case_ids[case_name] = safe_case
            used_case_ids.add(safe_case)
        safe_case = case_ids[case_name]
        groups.setdefault(safe_case, []).append(file)
    if len(groups) > MAX_BATCH_FOLDERS:
        raise HTTPException(status_code=413, detail=f"单批最多审核 {MAX_BATCH_FOLDERS} 个工单文件夹")
    return groups


def _clamp_float(value: float, low: float, high: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return max(low, min(high, parsed))


def _clamp_int(value: int, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, parsed))


def _public_summary(raw_report: Dict[str, Any]) -> Dict[str, Any]:
    summary = raw_report.get("summary") or {}
    if "actual_predicted_label" in summary or "hit" in summary:
        return {
            "cases": 1,
            "total_reviews": 1,
            "successful_reviews": 1 if raw_report.get("ok", True) else 0,
            "predicted_label": summary.get("actual_predicted_label"),
            "report_evaluation": "命中" if summary.get("hit") else "未命中" if summary.get("available") else "未评测",
            "needs_human_review": True,
        }
    ok = bool(raw_report.get("ok"))
    return {
        "cases": summary.get("cases") or 1,
        "total_reviews": summary.get("total_reviews") or 1,
        "successful_reviews": summary.get("successful_reviews") if summary.get("successful_reviews") is not None else (1 if ok else 0),
        "needs_human_review": True,
        "review_status": "completed" if ok else "failed",
    }


def _strip_private_report_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_private_report_fields(item)
            for key, item in value.items()
            if str(key) not in PRIVATE_REPORT_KEYS
        }
    if isinstance(value, list):
        return [_strip_private_report_fields(item) for item in value]
    return value


def _public_agent_report_payload(
    *,
    case: Dict[str, Any],
    sample_dir: Path,
    parsed: Dict[str, Any],
    result: Dict[str, Any],
    quality: Dict[str, Any],
    public_conclusion: str,
    public_next_step: str,
) -> Dict[str, Any]:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = result.get("cost") if isinstance(result.get("cost"), dict) else {}
    chunking = result.get("chunking") if isinstance(result.get("chunking"), dict) else {}
    evidence_package = {
        "videos": case.get("videos") or [],
        "frames_sent": len(case.get("frames") or []),
        "supplemental_images_sent": len(case.get("supplemental_images") or []),
    }
    payload = {
        "case_id": case.get("case_id") or sample_dir.name,
        "scenario": case["scenario"],
        "scenario_label": case["scenario_label"],
        "parsed": parsed,
        "quality": {
            key: value
            for key, value in (quality or {}).items()
            if key in {"score", "structured_success", "evidence_score", "stability_score"}
        },
        "runtime": {
            "latency_seconds": result.get("latency_seconds"),
            "model_latency_seconds_sum": result.get("model_latency_seconds_sum"),
            "status": result.get("status"),
        },
        "inference_estimate": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "estimated_usd": cost.get("estimated_usd"),
            "segment_count": chunking.get("total_model_calls") or chunking.get("segment_count"),
            "main_segment_count": chunking.get("segment_count"),
            "channels": chunking.get("channels") or {},
            "frames_per_segment": chunking.get("frames_per_segment"),
            "total_frames": chunking.get("total_frames"),
        },
        "public_brief": {
            "conclusion": public_conclusion,
            "next_step": public_next_step,
        },
        "evidence_package": evidence_package,
        "media_gallery": _media_gallery(case, sample_dir),
    }
    return _strip_private_report_fields(payload)


def _media_url(path_value: Any) -> str:
    if not path_value:
        return ""
    try:
        path = Path(str(path_value)).resolve()
    except OSError:
        return ""
    if path.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
        return ""
    allowed_roots = [ROOT.resolve(), WORKBENCH_DIR.resolve()]
    if not any(path == base or base in path.parents for base in allowed_roots):
        return ""
    rel = path.relative_to(ROOT.resolve()).as_posix()
    return "/media/" + quote(rel)


def _media_gallery(case: Dict[str, Any], sample_dir: Optional[Path] = None) -> Dict[str, Any]:
    def public_media_item(item: Dict[str, Any], url: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        allowed = {
            "video_index",
            "global_frame_index",
            "frame_index",
            "image_index",
            "timestamp",
            "timestamp_seconds",
            "file",
            "video_file",
            "width",
            "height",
            "bytes",
        }
        data = {key: item.get(key) for key in allowed if item.get(key) not in (None, "")}
        data["url"] = url
        if extra:
            data.update({key: value for key, value in extra.items() if value not in (None, "")})
        return data

    videos = []
    for item in case.get("videos") or []:
        video_path = (sample_dir / item.get("file")).resolve() if sample_dir and item.get("file") else None
        videos.append(public_media_item(item, _media_url(video_path)))
    frames = []
    for item in case.get("frames") or []:
        frame_url = _media_url(item.get("api_path") or item.get("path"))
        video_file = item.get("video_file") or (case.get("video_file") if len(videos) == 1 else "")
        video_path = (sample_dir / video_file).resolve() if sample_dir and video_file else None
        video_url = _media_url(video_path)
        timestamp = float(item.get("timestamp_seconds") or 0)
        frames.append(public_media_item(item, frame_url, {"video_url": f"{video_url}#t={timestamp:.2f}" if video_url else ""}))
    images = [
        public_media_item(item, _media_url(item.get("api_path") or item.get("path")))
        for item in case.get("supplemental_images") or []
    ]
    return {"videos": videos, "frames": frames, "images": images}


def _public_metadata(url: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    if not meta.get("ok"):
        status = str(meta.get("status") or "")
        if "platform" in status or "unsupported" in status:
            message = "当前平台或链接格式暂不支持，请改为公开视频分享链接、视频直链或本地上传。"
            public_status = "unsupported_source"
        elif "large" in status or "too_large" in status:
            message = "视频文件过大，请截取关键片段后本地上传。"
            public_status = "source_too_large"
        elif "private" in status or "blocked" in status:
            message = "不支持内网、本机或非公开链接，请改为公开视频链接或本地上传。"
            public_status = "source_unavailable"
        else:
            message = "暂时无法读取该视频，请改为本地上传或更换公开视频链接。"
            public_status = "source_unavailable"
        return {
            "ok": False,
            "status": public_status,
            "platform_label": "公开视频",
            "message": message,
        }
    return {
        "ok": True,
        "status": "metadata_ready",
        "platform_label": "公开视频",
        "preview": {
            "title": meta.get("title") or "公开视频素材",
            "author": meta.get("author") or "未提供",
            "duration": meta.get("duration") or "",
            "thumbnail_url": meta.get("thumbnail_url") or "",
        },
    }


def _report_data_name(report_name: str) -> str:
    path = Path(report_name)
    if path.suffix == ".html":
        return path.with_suffix(".json").name
    return path.name


def _structured_review_ok(parsed: Dict[str, Any]) -> bool:
    return bool(parsed.get("predicted_label")) and parsed.get("confidence") not in (None, "")


def _internal_inference_estimate(result: Dict[str, Any]) -> Dict[str, Any]:
    """仅供受保护审核 API 和内部运维汇总，公开 HTML 不引用该对象。"""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = result.get("cost") if isinstance(result.get("cost"), dict) else {}
    chunking = result.get("chunking") if isinstance(result.get("chunking"), dict) else {}
    channels = chunking.get("channels") if isinstance(chunking.get("channels"), dict) else {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "estimated_usd": round(float(cost.get("estimated_usd") or 0.0), 6),
        "total_model_calls": int(chunking.get("total_model_calls") or 1),
        "segment_count": int(chunking.get("segment_count") or 1),
        "channels": {
            key: {
                "model_calls": int((value or {}).get("model_calls") or 0),
                "total_tokens": int((value or {}).get("total_tokens") or 0),
                "estimated_usd": round(float((value or {}).get("estimated_usd") or 0.0), 6),
            }
            for key, value in channels.items()
            if isinstance(value, dict)
        },
        "boundary": "估算值用于容量与成本比较，不等同于供应商最终账单。",
    }


def _public_failure_reason(result: Dict[str, Any], structured_ok: bool) -> Dict[str, Any]:
    status = str(result.get("status") or "")
    diagnostics_text = json.dumps(result.get("diagnostics") or {}, ensure_ascii=False)
    if "未找到 Gemini 渠道 Key" in diagnostics_text:
        return {
            "stage": "服务配置",
            "message": "视觉审核服务尚未配置可用凭证，本轮未发起审核。",
            "operator_hint": "请联系系统管理员检查视觉审核服务配置；当前工单先转VIP客服复核。",
        }
    if status == "success" and not structured_ok:
        return {
            "stage": "系统复核",
            "message": "系统复核暂未生成可用摘要，本轮不能作为业务判断依据。",
            "operator_hint": "请保留原始素材并重试；若连续出现，请联系系统管理员排查。",
        }
    if status == "skipped":
        return {
            "stage": "系统复核",
            "message": "系统复核暂不可用，当前工单请先进入VIP客服复核。",
            "operator_hint": "请检查部署环境配置；当前工单先进入VIP客服复核。",
        }
    gemini = result.get("gemini") if isinstance(result.get("gemini"), dict) else {}
    attempts = gemini.get("attempts") if isinstance(gemini.get("attempts"), list) else []
    last_attempt = attempts[-1] if attempts else {}
    status_code = result.get("status_code") or last_attempt.get("status_code")
    error_type = str(result.get("error_type") or last_attempt.get("error_type") or "")
    if status_code == 429:
        message = "系统复核服务繁忙，本轮重试后仍未完成审核。"
    elif error_type == "soft":
        message = "系统复核超时或服务临时不可用，本轮重试后仍未完成审核。"
    elif status_code:
        message = "系统复核暂未完成，本轮不能作为业务判断依据。"
    else:
        message = "系统复核请求未完成，可能是网络、服务或运行环境异常。"
    return {
        "stage": "系统复核",
        "message": message,
        "operator_hint": "这不是业务上的“证据不足”；请重试或转VIP客服处理，并保留该失败样本供系统管理员排查。",
    }


def _run_review(
    video: Path,
    scenario: str,
    fps: float,
    max_frames: int,
    api_frame_limit: int,
    probe_seconds: int,
    review_model: str,
    evidence_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    profile = REVIEW_MODEL_PROFILES.get(review_model) or REVIEW_MODEL_PROFILES["standard"]
    load_visual_env()
    effective_fps = fps
    effective_max_frames = max_frames
    if review_model == "fast":
        effective_fps = min(fps, 0.5)
        effective_max_frames = min(max_frames, int(profile["default_max_frames"]))
    elif review_model == "standard":
        effective_fps = max(fps, 1.0)
        effective_max_frames = max(max_frames, int(profile["default_max_frames"]))
    elif review_model == "backup":
        effective_fps = max(fps, 2.0)
        effective_max_frames = max(max_frames, int(profile["default_max_frames"]))
    args = SimpleNamespace(
        fps=effective_fps,
        sampling_mode=profile["sampling_mode"],
        max_frames_per_video=effective_max_frames,
        api_frame_limit=api_frame_limit,
        probe_seconds=float(probe_seconds),
        frame_width=960,
        supplemental_image_limit=MAX_SUPPLEMENTAL_IMAGES,
    )
    run_dir = ROOT / "tmp" / "visual_review_workbench" / f"single_{video.parent.name}_{time.time_ns()}"
    try:
        case = load_case_bundle(video.parent, args, run_dir, scenario_override=scenario)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = apply_frontdesk_context(case, scenario, json.dumps(evidence_context or {}, ensure_ascii=False))
    result = call_model_chunked(MODEL_CONFIGS["gemini35"], case, timeout=300, retries=2)
    review = _agent_report_response(case, video.parent, result, "agent_single", profile["label"])
    review["sampling"] = {
        "profile": review_model,
        "label": profile["label"],
        "sampling_mode": profile["sampling_mode"],
        "fps": effective_fps,
        "sampled_frames": len(case.get("frames") or []),
        "model_segments": ((review.get("agent_report") or {}).get("inference_estimate") or {}).get("segment_count"),
        "frames_per_segment": api_frame_limit,
    }
    return {"ok": (review.get("summary") or {}).get("review_status") == "completed", **review}


def _agent_report_response(
    case: Dict[str, Any],
    sample_dir: Path,
    result: Dict[str, Any],
    report_stem: str,
    review_profile_label: str = "标准视觉复核",
    include_internal_metrics: bool = False,
) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    structured_ok = _structured_review_ok(parsed)
    ok = result.get("status") == "success" and structured_ok
    quality = score_result(result)
    failure = {} if ok else _public_failure_reason(result, structured_ok)
    public_conclusion = _safe_agent_conclusion(parsed, case["scenario_label"]) if ok else f"审核未完成：{failure.get('message')}"
    public_next_step = _safe_agent_next_step((parsed.get("overall_audit") or {}).get("business_follow_up_suggestion") or parsed.get("next_step")) if ok else failure.get("operator_hint", "请VIP客服结合订单、售后规则和原始素材处理。")
    report_name = f"{report_stem}_{int(time.time())}_{len(ALLOWED_REPORTS) + 1}.html"
    agent_report = _public_agent_report_payload(
        case=case,
        sample_dir=sample_dir,
        parsed=parsed,
        result=result,
        quality=quality,
        public_conclusion=public_conclusion,
        public_next_step=public_next_step,
    )
    data = {
        "ok": ok,
        "review_label": f"{case['scenario_label']} / {review_profile_label}",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "cases": 1,
            "total_reviews": 1,
            "successful_reviews": 1 if ok else 0,
            "predicted_label": parsed.get("predicted_label"),
            "confidence": parsed.get("confidence"),
            "needs_human_review": True,
            "review_status": "completed" if ok else "failed",
        },
        "conclusion": public_conclusion,
        "agent_report": agent_report,
        "media_warnings": case.get("rejected_videos") or [],
    }
    if failure:
        data["diagnostics"] = {
            "review_status": "failed",
            "failure_stage": failure.get("stage"),
            "failure_reason": failure.get("message"),
            "operator_hint": failure.get("operator_hint"),
            "frames_sent": len(case.get("frames") or []),
            "supplemental_images_sent": len(case.get("supplemental_images") or []),
            "videos_received": len(case.get("videos") or []),
        }
        agent_report["diagnostics"] = data["diagnostics"]
    data = _strip_private_report_fields(data)
    ALLOWED_REPORTS[report_name] = data
    PUBLIC_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_SUMMARY_DIR / _report_data_name(report_name)).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    response = {
        "review_label": data["review_label"],
        "summary": data["summary"],
        "frame_strategy": (
            f"{len(case.get('videos') or [])} 个视频合并为同一证据包，送审 {len(case.get('frames') or [])} 帧，补充图片 {len(case.get('supplemental_images') or [])} 张。"
            + (f"另隔离 {len(case.get('rejected_videos') or [])} 个无法解码的视频。" if case.get("rejected_videos") else "")
        ),
        "report": {"html_url": "/reports/" + report_name},
        "agent_report": data.get("agent_report") or {},
        "media_warnings": data.get("media_warnings") or [],
        "agent_brief": {
            "conclusion": public_conclusion,
            "confidence": data["summary"].get("confidence"),
            "system_yes_no": parsed.get("system_yes_no"),
            "next_step": public_next_step,
        },
    }
    if include_internal_metrics:
        response["agent_report"]["inference_estimate"] = _internal_inference_estimate(result)
    if data.get("diagnostics"):
        response["diagnostics"] = data["diagnostics"]
    return response


def _sample_base() -> Path:
    return (ROOT / "docs" / "三大审核场景的小量样本").resolve()


def _sample_scenarios() -> Dict[str, str]:
    path = _sample_base() / "sample_labels.json"
    try:
        samples = json.loads(path.read_text(encoding="utf-8-sig")).get("samples") or {}
    except Exception:
        samples = {}
    return {str(key): str(value.get("scenario") or "video_unboxing") for key, value in samples.items() if isinstance(value, dict)}


def _run_sample_agent_review(sample_id: str, scenario: str, model_key: str) -> Dict[str, Any]:
    sample_base = _sample_base()
    sample_dir = (sample_base / sample_id).resolve()
    if sample_base not in sample_dir.parents or not sample_dir.exists():
        raise HTTPException(status_code=404, detail="样本不存在")
    if scenario not in {"video_unboxing", "product_damage", "minor_material"}:
        raise HTTPException(status_code=400, detail="未知审核场景")
    if model_key not in MODEL_CONFIGS:
        raise HTTPException(status_code=400, detail="未知审核模型")
    load_visual_env()
    args = SimpleNamespace(
        fps=1.0,
        sampling_mode="adaptive",
        max_frames_per_video=24,
        api_frame_limit=24,
        probe_seconds=0.0,
        frame_width=960,
        supplemental_image_limit=MAX_SUPPLEMENTAL_IMAGES,
    )
    run_dir = ROOT / "tmp" / "visual_review_workbench" / f"workbench_{sample_id}_{int(time.time())}"
    case = load_case_bundle(sample_dir, args, run_dir, scenario_override=scenario)
    case["scenario"] = scenario
    case["scenario_label"] = {"video_unboxing": "开箱/发错货审核", "product_damage": "商品有伤审核", "minor_material": "资料审核"}[scenario]
    result = call_model_chunked(MODEL_CONFIGS[model_key], case, timeout=300, retries=2)
    review = _agent_report_response(case, sample_dir, result, f"agent_{sample_id}")
    return {
        "ok": (review.get("summary") or {}).get("review_status") == "completed",
        "source_status": "sample_ready",
        "review": review,
    }


def _run_sample_batch_agent_review(model_key: str) -> Dict[str, Any]:
    sample_base = _sample_base()
    if not sample_base.is_dir():
        return {
            "ok": False,
            "source_status": "sample_not_packaged",
            "message": "当前交付包未附带内置样本，请使用工单素材文件夹或正式审核 API 测试。",
            "reports": [],
            "summary": {"total": 0, "success": 0, "failed": 0},
        }
    scenarios = _sample_scenarios()
    sample_ids = [p.name for p in sorted(sample_base.iterdir()) if p.is_dir() and p.name.startswith("sample_")]
    reports = []
    for sample_id in sample_ids:
        scenario = scenarios.get(sample_id, "video_unboxing")
        try:
            result = _run_sample_agent_review(sample_id, scenario, model_key)
            review = result.get("review") or {}
            reports.append({
                "sample_id": sample_id,
                "scenario": scenario,
                "ok": bool(result.get("ok")),
                "html_url": (review.get("report") or {}).get("html_url"),
                "conclusion": ((review.get("agent_brief") or {}).get("conclusion") or ""),
                "confidence": ((review.get("agent_brief") or {}).get("confidence") or ""),
                "frame_strategy": review.get("frame_strategy") or "",
            })
        except HTTPException as exc:
            reports.append({"sample_id": sample_id, "scenario": scenario, "ok": False, "error": exc.detail})
    return {
        "ok": bool(reports) and all(item.get("ok") for item in reports),
        "source_status": "sample_batch_ready",
        "reports": reports,
        "summary": {
            "total": len(reports),
            "success": sum(1 for item in reports if item.get("ok")),
            "failed": sum(1 for item in reports if not item.get("ok")),
        },
    }


def _run_folder_agent_review(folder_dir: Path, scenario: str, model_key: str, evidence_context: Dict[str, Any], sampling_mode: str, fps: float, max_frames: int, api_frame_limit: int, probe_seconds: int, include_internal_metrics: bool = False) -> Dict[str, Any]:
    if model_key not in MODEL_CONFIGS:
        raise HTTPException(status_code=400, detail="未知审核模型")
    load_visual_env()
    args = SimpleNamespace(
        fps=fps,
        sampling_mode=sampling_mode,
        max_frames_per_video=max_frames,
        api_frame_limit=api_frame_limit,
        probe_seconds=float(probe_seconds),
        frame_width=960,
        supplemental_image_limit=MAX_SUPPLEMENTAL_IMAGES,
    )
    run_dir = ROOT / "tmp" / "visual_review_workbench" / f"folder_{folder_dir.name}_{int(time.time())}"
    try:
        case = load_case_bundle(folder_dir, args, run_dir, scenario_override=scenario)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = apply_frontdesk_context(case, scenario, json.dumps(evidence_context or {}, ensure_ascii=False))
    result = call_model_chunked(MODEL_CONFIGS[model_key], case, timeout=300, retries=2)
    review = _agent_report_response(
        case,
        folder_dir,
        result,
        "agent_folder",
        include_internal_metrics=include_internal_metrics,
    )
    return {
        "ok": (review.get("summary") or {}).get("review_status") == "completed",
        "source_status": "folder_ready",
        "review": review,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/video-unboxing", response_class=HTMLResponse)
def video_unboxing_entry() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/product-damage", response_class=HTMLResponse)
def product_damage_entry() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/minor-material", response_class=HTMLResponse)
def minor_material_entry() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    sample_base = _sample_base()
    sample_ids = [path.name for path in sample_base.glob("sample_*") if path.is_dir()] if sample_base.is_dir() else []
    return {
        "ok": True,
        "service": "visual_review_workbench",
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
        "access_control": "生产部署必须由主服务或反向代理执行租户鉴权",
        "built_in_samples_available": bool(sample_ids),
        "built_in_sample_count": len(sample_ids),
    }


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/reports/{name}", response_class=HTMLResponse)
def public_report(name: str) -> str:
    data = ALLOWED_REPORTS.get(name)
    if not data:
        path = (PUBLIC_SUMMARY_DIR / _report_data_name(name)).resolve()
        base = PUBLIC_SUMMARY_DIR.resolve()
        if base in path.parents and path.exists() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data = _strip_private_report_fields(data)
            except json.JSONDecodeError:
                data = None
    if not data:
        raise HTTPException(status_code=404, detail="not_found")
    return _render_public_report(_strip_private_report_fields(data))


@app.get("/ppt-assets/{name}")
def ppt_asset(name: str) -> FileResponse:
    path = (ROOT / "PPT-一部分" / name).resolve()
    base = (ROOT / "PPT-一部分").resolve()
    if base not in path.parents or not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(path)


@app.get("/media/{rel_path:path}")
def media_asset(rel_path: str) -> FileResponse:
    try:
        rel = unquote(rel_path).replace("\\", "/")
        path = (ROOT / rel).resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="素材不存在") from exc
    allowed_roots = [WORKBENCH_DIR.resolve(), SAMPLE_MATERIAL_DIR, RUNTIME_MEDIA_DIR]
    if not any(path == base or base in path.parents for base in allowed_roots):
        raise HTTPException(status_code=404, detail="素材不存在")
    if not path.exists() or path.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(path)


@app.post("/api/url/metadata")
def url_metadata(payload: Dict[str, str]) -> JSONResponse:
    url = extract_video_url(payload.get("url", ""))
    if not url.startswith(("http://", "https://")):
        return JSONResponse({
            "ok": False,
            "status": "invalid_url",
            "message": "请提供公开可访问的视频链接，或改为本地上传。",
        }, status_code=422)
    meta = fetch_metadata(url)
    status_code = 200 if meta.get("ok") else 422
    return JSONResponse(_public_metadata(url, meta), status_code=status_code)


@app.post("/api/evaluate-samples")
def evaluate_samples(file: UploadFile = File(...)) -> JSONResponse:
    return JSONResponse(evaluate_sample_rows(read_sample_rows(file)))


@app.post("/api/review-sample")
def review_sample(payload: Dict[str, str]) -> JSONResponse:
    return JSONResponse(_run_sample_agent_review(
        payload.get("sample_id", "sample_003"),
        payload.get("scenario", "product_damage"),
        payload.get("model_key", "gemini35"),
    ))


@app.post("/api/review-samples-batch")
def review_samples_batch(payload: Dict[str, str]) -> JSONResponse:
    return JSONResponse(_run_sample_batch_agent_review(payload.get("model_key", "gemini35")))


@app.post("/api/review-folder")
def review_folder(
    x_mitako_internal_metrics: str = Header("", alias="X-MITAKO-Internal-Metrics"),
    scenario: str = Form("video_unboxing"),
    business_scenario: str = Form(""),
    ticket_id: str = Form(""),
    user_id: str = Form(""),
    order_no: str = Form(""),
    customer_claim: str = Form(""),
    order_item: str = Form(""),
    sku: str = Form(""),
    logistics_status: str = Form(""),
    complaint_stage: str = Form(""),
    product_master_data: str = Form(""),
    warehouse_master_data: str = Form(""),
    conversation_history: str = Form(""),
    customer_tone: str = Form(""),
    sop_context: str = Form(""),
    source_case: str = Form(""),
    asset_manifest: str = Form(""),
    claim_scope: str = Form(""),
    continuity_policy: str = Form(""),
    damage_causality_policy: str = Form(""),
    fulfillment_baseline: str = Form(""),
    evidence_coverage: str = Form(""),
    sampling_mode: str = Form("adaptive"),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    if scenario not in {"video_unboxing", "product_damage", "minor_material"}:
        raise HTTPException(status_code=400, detail="未知审核场景")
    if sampling_mode not in {"adaptive", "dense"}:
        raise HTTPException(status_code=400, detail="未知抽帧策略")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 1800, 24)
    api_frame_limit = _clamp_int(api_frame_limit, 1, 24, 24)
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    folder_dir, ingestion = _save_folder_uploads(files)
    evidence_context = {
        "business_scenario": business_scenario,
        "ticket_id": ticket_id,
        "user_id": user_id,
        "order_no": order_no,
        "customer_claim": customer_claim,
        "order_item": order_item,
        "sku": sku,
        "logistics_status": logistics_status,
        "complaint_stage": complaint_stage,
        "product_master_data": product_master_data,
        "warehouse_master_data": warehouse_master_data,
        "conversation_history": conversation_history,
        "customer_tone": customer_tone,
        "sop_context": sop_context,
        "source_case": source_case,
        "asset_manifest": asset_manifest,
        "claim_scope": claim_scope,
        "continuity_policy": continuity_policy,
        "damage_causality_policy": damage_causality_policy,
        "fulfillment_baseline": fulfillment_baseline,
        "evidence_coverage": evidence_coverage,
    }
    response = _run_folder_agent_review(
        folder_dir,
        scenario,
        "gemini35",
        evidence_context,
        sampling_mode,
        fps,
        max_frames,
        api_frame_limit,
        probe_seconds,
        include_internal_metrics=x_mitako_internal_metrics == "1",
    )
    response["ingestion"] = ingestion
    return JSONResponse(response)


@app.post("/api/review-folders-batch")
def review_folders_batch(
    scenario: str = Form("video_unboxing"),
    customer_claim: str = Form(""),
    product_master_data: str = Form(""),
    conversation_history: str = Form(""),
    sampling_mode: str = Form("adaptive"),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    if scenario not in {"video_unboxing", "product_damage", "minor_material"}:
        raise HTTPException(status_code=400, detail="未知审核场景")
    if sampling_mode not in {"adaptive", "dense"}:
        raise HTTPException(status_code=400, detail="未知抽帧策略")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 1800, 24)
    api_frame_limit = _clamp_int(api_frame_limit, 1, 24, 24)
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    groups = _group_batch_folder_uploads(files)
    evidence_context = {
        "customer_claim": customer_claim,
        "product_master_data": product_master_data,
        "conversation_history": conversation_history,
    }
    cases = []
    for case_id, case_files in groups.items():
        try:
            folder_dir, ingestion = _save_folder_uploads(case_files)
            result = _run_folder_agent_review(
                folder_dir,
                scenario,
                "gemini35",
                evidence_context,
                sampling_mode,
                fps,
                max_frames,
                api_frame_limit,
                probe_seconds,
            )
            result["ingestion"] = ingestion
            cases.append({"case_id": case_id, **result})
        except HTTPException as exc:
            cases.append({"case_id": case_id, "ok": False, "status": "failed", "message": str(exc.detail)})
        except Exception:
            cases.append({"case_id": case_id, "ok": False, "status": "failed", "message": "工单审核未完成，请单独重试"})
    success = sum(item.get("ok") is True for item in cases)
    reports = []
    for item in cases:
        report = ((item.get("review") or {}).get("report") or {})
        if report.get("html_url"):
            reports.append({"sample_id": item["case_id"], "html_url": report["html_url"], "confidence": ((item.get("review") or {}).get("summary") or {}).get("confidence")})
    return JSONResponse({
        "ok": success == len(cases),
        "source_status": "folder_batch_ready",
        "summary": {"total": len(cases), "success": success, "failed": len(cases) - success, "complete": True},
        "cases": cases,
        "reports": reports,
    })


@app.post("/api/review")
def review(
    source_type: str = Form("upload"),
    video_url: str = Form(""),
    scenario: str = Form("video_unboxing"),
    business_scenario: str = Form(""),
    ticket_id: str = Form(""),
    user_id: str = Form(""),
    order_no: str = Form(""),
    customer_claim: str = Form(""),
    order_item: str = Form(""),
    sku: str = Form(""),
    logistics_status: str = Form(""),
    complaint_stage: str = Form(""),
    product_master_data: str = Form(""),
    warehouse_master_data: str = Form(""),
    conversation_history: str = Form(""),
    customer_tone: str = Form(""),
    sop_context: str = Form(""),
    source_case: str = Form(""),
    asset_manifest: str = Form(""),
    claim_scope: str = Form(""),
    continuity_policy: str = Form(""),
    damage_causality_policy: str = Form(""),
    fulfillment_baseline: str = Form(""),
    evidence_coverage: str = Form(""),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    review_model: str = Form("standard"),
    file: Optional[UploadFile] = File(None),
) -> JSONResponse:
    if source_type not in {"upload", "url"}:
        raise HTTPException(status_code=400, detail="未知素材来源")
    if scenario not in {"video_unboxing", "product_damage", "minor_material"}:
        raise HTTPException(status_code=400, detail="未知审核场景")
    if review_model not in REVIEW_MODEL_PROFILES:
        raise HTTPException(status_code=400, detail="未知审核档位")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 1800, 24)
    api_frame_limit = _clamp_int(api_frame_limit, 1, 24, 24)
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    if source_type == "url":
        downloaded = download_video_url(video_url, seconds=probe_seconds)
        if not downloaded.get("ok"):
            status = str(downloaded.get("status") or "")
            if "large" in status or "too_large" in status:
                message = "公开视频文件过大，请截取关键片段后本地上传。"
                public_status = "source_too_large"
            elif "platform" in status or "unsupported" in status:
                message = "当前平台或链接格式暂不支持，请改为本地上传或更换公开链接。"
                public_status = "unsupported_source"
            elif "private" in status or "blocked" in status:
                message = "不支持内网、本机或非公开链接，请改为公开视频链接或本地上传。"
                public_status = "source_unavailable"
            else:
                message = "公开视频暂时无法读取，请改为本地上传或更换公开视频链接。"
                public_status = "source_unavailable"
            return JSONResponse({
                "ok": False,
                "status": public_status,
                "message": message,
            }, status_code=422)
        video = Path(downloaded["path"])
        source_status = "ready"
    else:
        if file is None:
            raise HTTPException(status_code=400, detail="请选择本地视频或切换 URL 模式")
        video = _save_upload(file)
        source_status = "ready"
    if not damage_causality_policy and scenario == "product_damage":
        damage_causality_policy = json.dumps(
            {
                "force_action_scan": review_model in {"standard", "backup"},
                "dedicated_chunk_frames": 20,
                "context_frames": 6,
            },
            ensure_ascii=False,
        )
    evidence_context = {
        "business_scenario": business_scenario,
        "ticket_id": ticket_id,
        "user_id": user_id,
        "order_no": order_no,
        "customer_claim": customer_claim,
        "order_item": order_item,
        "sku": sku,
        "logistics_status": logistics_status,
        "complaint_stage": complaint_stage,
        "product_master_data": product_master_data,
        "warehouse_master_data": warehouse_master_data,
        "conversation_history": conversation_history,
        "customer_tone": customer_tone,
        "sop_context": sop_context,
        "source_case": source_case,
        "asset_manifest": asset_manifest,
        "claim_scope": claim_scope,
        "continuity_policy": continuity_policy,
        "damage_causality_policy": damage_causality_policy,
        "fulfillment_baseline": fulfillment_baseline,
        "evidence_coverage": evidence_coverage,
    }
    result = _run_review(video, scenario, fps, max_frames, api_frame_limit, probe_seconds, review_model, evidence_context)
    response = {"ok": result["ok"], "source_status": source_status, "review": result}
    if result.get("diagnostics"):
        response["diagnostics"] = result["diagnostics"]
    return JSONResponse(response)


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(__import__("os").getenv("VISUAL_WORKBENCH_PORT", "7861")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
