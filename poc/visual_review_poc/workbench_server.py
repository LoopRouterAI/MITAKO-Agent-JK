# -*- coding: utf-8 -*-
"""客服视觉审核工作台：上传/URL -> 本地视频 -> 视觉复核报告。"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_paths import app_root
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
    from poc.visual_review_poc.model_selection_e2e import MODEL_CONFIGS, call_model, load_case_bundle, score_result
    from poc.visual_review_poc.local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from poc.visual_review_poc.report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )
except ImportError:
    from model_selection_e2e import MODEL_CONFIGS, call_model, load_case_bundle, score_result
    from local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )

ROOT = app_root()
def _env_name(*parts: str) -> str:
    return "_".join(parts)


def _runtime_word(*parts: str) -> str:
    return "".join(parts)


WORKBENCH_DIR = Path(os.getenv(_env_name("MITAKO", "VISUAL", "WORKBENCH", "DIR")) or ROOT / "poc" / "visual_review_poc").resolve()
UPLOAD_DIR = WORKBENCH_DIR / "uploaded_videos"
REPORT_DIR = WORKBENCH_DIR / "reports"
PUBLIC_SUMMARY_DIR = REPORT_DIR / "public_summaries"
INDEX_HTML = WORKBENCH_DIR / "workbench.html"
ALLOWED_REPORTS: dict[str, Dict[str, Any]] = {}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
MAX_FOLDER_BYTES = 800 * 1024 * 1024
SAMPLE_MAX_BYTES = 5 * 1024 * 1024
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
}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-m4v"}
ALLOWED_SAMPLE_SUFFIXES = {".csv", ".json"}
ALLOWED_MEDIA_SUFFIXES = ALLOWED_VIDEO_SUFFIXES | {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_FOLDER_SUFFIXES = ALLOWED_MEDIA_SUFFIXES | {".txt", ".json"}
TARGET_REVIEW_TASKS = ("video_unboxing", "product_damage", "minor_material")
TASK_PUBLIC_NAMES = {
    "video_unboxing": "开箱视频",
    "product_damage": "商品有伤",
    "minor_material": "资料审核",
    "wrong_item": "发错货",
    "unknown": "未识别场景",
}
FIELD_ALIASES = {
    "task": ("task", "scenario", "scene", "queue", "业务队列", "场景", "审核场景", "任务"),
    "human_label": ("human_label", "manual_label", "final_label", "human_result", "result", "人工结论", "最终人工结论", "人工最终结论", "结论"),
    "predicted_label": ("predicted_label", "model_label", "system_label", "review_label", "assistant_label", "辅助结论", "系统结论", "预测结论"),
    "user_text": ("user_text", "customer_text", "claim_text", "诉求", "用户诉求", "用户描述", "客服记录"),
    "human_reason": ("human_reason", "manual_reason", "reason", "人工原因", "人工结论原因", "结论原因", "原因"),
    "order_item": ("order_item", "product_name", "item_name", "商品名", "订单商品名", "商品"),
    "sku": ("sku", "spec", "sku_spec", "variant", "规格", "款式", "SKU", "SKU规格"),
    "material": ("video", "video_url", "image", "image_url", "material", "material_url", "素材", "视频", "图片", "资料"),
}

app = FastAPI(
    title="MITAKO 视觉审核工作台",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

REVIEW_MODEL_PROFILES = {
    "standard": {"label": "标准视觉复核"},
    "fast": {"label": "快速初筛"},
    "backup": {"label": "补充复核"},
}


def _module_entry(name: str) -> str:
    return f"poc.visual_review_poc.{name}"


def _save_upload(file: UploadFile) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.mp4").suffix or ".mp4"
    suffix = suffix.lower()
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES or (content_type and content_type not in ALLOWED_VIDEO_TYPES and not content_type.startswith("video/")):
        raise HTTPException(status_code=415, detail="仅支持常见视频文件")
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(file.filename or "upload").stem).strip("._-")[:60] or "upload"
    target = UPLOAD_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{stem}{suffix}"
    total = 0
    with target.open("wb") as fh:
        while chunk := file.file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                fh.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="视频文件过大，请先压缩后再上传")
            fh.write(chunk)
    if target.stat().st_size <= 0:
        raise HTTPException(status_code=400, detail="上传文件为空")
    return target


def _safe_basename(name: str, fallback: str) -> str:
    basename = Path(str(name or fallback).replace("\\", "/")).name
    stem = re.sub(r"[^a-zA-Z0-9._\-\u4e00-\u9fff]+", "_", Path(basename).stem).strip("._-")[:60]
    suffix = Path(basename).suffix.lower()
    return (stem or fallback) + suffix


def _save_folder_uploads(files: List[UploadFile]) -> Path:
    if not files:
        raise HTTPException(status_code=400, detail="请选择工单素材文件夹")
    target_dir = UPLOAD_DIR / f"folder_{time.strftime('%Y%m%d_%H%M%S')}_{len(ALLOWED_REPORTS) + 1}"
    target_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    saved = 0
    used_names: set[str] = set()
    for index, file in enumerate(files, start=1):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_FOLDER_SUFFIXES:
            continue
        name = _safe_basename(file.filename or f"material_{index}{suffix}", f"material_{index}")
        if name in used_names:
            name = f"{index:03d}_{name}"
        used_names.add(name)
        target = target_dir / name
        with target.open("wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_FOLDER_BYTES:
                    fh.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="文件夹素材过大，请拆分工单或先截取关键片段")
                fh.write(chunk)
        if target.stat().st_size > 0:
            saved += 1
        else:
            target.unlink(missing_ok=True)
    if not saved:
        raise HTTPException(status_code=400, detail="文件夹内没有可用视频、图片或文本材料")
    if not any(path.suffix.lower() in ALLOWED_MEDIA_SUFFIXES for path in target_dir.iterdir() if path.is_file()):
        raise HTTPException(status_code=400, detail="文件夹内没有可审核的视频或图片")
    return target_dir


def _latest_report_from_stdout(stdout: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    for idx, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(stdout[idx:])
            return {k: data.get(k) for k in ("json_report", "html_report", "summary") if k in data}
        except Exception:
            continue
    return {}


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


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
            "status": result.get("status"),
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


def _public_result(ok: bool, review_label: str, report: Dict[str, Any]) -> Dict[str, Any]:
    report = {**(report or {}), "ok": ok}
    summary = _public_summary(report)
    failure = {} if ok else _public_failure_reason(report, False)
    report_name = f"summary_{int(time.time())}_{len(ALLOWED_REPORTS) + 1}.html"
    data = {
        "ok": ok,
        "review_label": review_label,
        "frame_strategy": "按当前抽帧配置生成证据",
        "summary": summary,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "conclusion": "建议VIP客服复核后再做最终业务处置" if ok else f"审核未完成：{failure.get('message')}",
    }
    if failure:
        data["diagnostics"] = {
            "review_status": "failed",
            "failure_stage": failure.get("stage"),
            "failure_reason": failure.get("message"),
            "operator_hint": failure.get("operator_hint"),
            "frames_sent": 0,
            "supplemental_images_sent": 0,
            "videos_received": 1,
        }
    ALLOWED_REPORTS[report_name] = data
    PUBLIC_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_SUMMARY_DIR / _report_data_name(report_name)).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    response = {
        "ok": ok,
        "review_label": review_label,
        "frame_strategy": "按当前抽帧配置生成证据",
        "summary": summary,
        "report": {"html_url": "/reports/" + report_name},
    }
    if data.get("diagnostics"):
        response["diagnostics"] = data["diagnostics"]
    return response


def _structured_review_ok(parsed: Dict[str, Any]) -> bool:
    return bool(parsed.get("predicted_label")) and parsed.get("confidence") not in (None, "")


def _public_failure_reason(result: Dict[str, Any], structured_ok: bool) -> Dict[str, Any]:
    status = str(result.get("status") or "")
    if status == "success" and not structured_ok:
        return {
            "stage": "系统复核",
            "message": "系统复核暂未生成可用摘要，本轮不能作为业务判断依据。",
            "operator_hint": "请保留原始素材并重试；若连续出现，请提交研发排查。",
        }
    if status == "skipped":
        return {
            "stage": "系统复核",
            "message": "系统复核暂不可用，当前工单请先进入VIP客服复核。",
            "operator_hint": "请检查部署环境配置；当前工单先进入VIP客服复核。",
        }
    status_code = result.get("status_code")
    error_type = str(result.get("error_type") or "")
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
        "operator_hint": "这不是业务上的“证据不足”；请重试或转VIP客服处理，并保留该失败样本给研发排查。",
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
    _load_env()
    profile = REVIEW_MODEL_PROFILES.get(review_model) or REVIEW_MODEL_PROFILES["standard"]
    command = [
        sys.executable,
        "-m",
        _module_entry("local_video_triage_demo"),
        "--video",
        str(video),
        "--scenario",
        scenario,
        "--context-json",
        json.dumps(evidence_context or {}, ensure_ascii=False),
        "--fps",
        str(fps),
        "--max-frames",
        str(max_frames),
        "--api-frame-limit",
        str(api_frame_limit),
        "--probe-seconds",
        str(probe_seconds),
        "--frame-width",
        "768",
    ]
    env = os.environ.copy()
    try:
        proc = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return _public_result(False, profile["label"], {"summary": {}, "status": "review_timeout"})
    except OSError:
        return _public_result(False, profile["label"], {"summary": {}, "status": "review_subprocess_error"})
    report = _latest_report_from_stdout(proc.stdout)
    if proc.returncode != 0:
        report.setdefault("status", "review_subprocess_failed")
    elif not report:
        report["status"] = "review_no_report"
    return _public_result(proc.returncode == 0 and bool(report), profile["label"], report)


def _agent_report_response(case: Dict[str, Any], sample_dir: Path, result: Dict[str, Any], report_stem: str) -> Dict[str, Any]:
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
        "review_label": f"{case['scenario_label']} / 标准视觉复核",
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
        "frame_strategy": f"{len(case.get('videos') or [])} 个视频合并为同一证据包，送审 {len(case.get('frames') or [])} 帧，补充图片 {len(case.get('supplemental_images') or [])} 张。",
        "report": {"html_url": "/reports/" + report_name},
        "agent_brief": {
            "conclusion": public_conclusion,
            "confidence": data["summary"].get("confidence"),
            "system_yes_no": parsed.get("system_yes_no"),
            "next_step": public_next_step,
        },
    }
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
        max_frames_per_video=6,
        api_frame_limit=18,
        probe_seconds=0.0,
        frame_width=960,
        supplemental_image_limit=20,
    )
    run_dir = ROOT / "tmp" / "visual_review_workbench" / f"workbench_{sample_id}_{int(time.time())}"
    case = load_case_bundle(sample_dir, args, run_dir)
    case["scenario"] = scenario
    case["scenario_label"] = {"video_unboxing": "开箱/发错货审核", "product_damage": "商品有伤审核", "minor_material": "资料审核"}[scenario]
    result = call_model(MODEL_CONFIGS[model_key], case, timeout=300, retries=2)
    review = _agent_report_response(case, sample_dir, result, f"agent_{sample_id}")
    return {
        "ok": (review.get("summary") or {}).get("review_status") == "completed",
        "source_status": "sample_ready",
        "review": review,
    }


def _run_sample_batch_agent_review(model_key: str) -> Dict[str, Any]:
    scenarios = _sample_scenarios()
    sample_ids = [p.name for p in sorted(_sample_base().iterdir()) if p.is_dir() and p.name.startswith("sample_")]
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
        "ok": any(item.get("ok") for item in reports),
        "source_status": "sample_batch_ready",
        "reports": reports,
        "summary": {
            "total": len(reports),
            "success": sum(1 for item in reports if item.get("ok")),
            "failed": sum(1 for item in reports if not item.get("ok")),
        },
    }


def _run_folder_agent_review(folder_dir: Path, scenario: str, model_key: str, evidence_context: Dict[str, Any], fps: float, max_frames: int, api_frame_limit: int, probe_seconds: int) -> Dict[str, Any]:
    if model_key not in MODEL_CONFIGS:
        raise HTTPException(status_code=400, detail="未知审核模型")
    load_visual_env()
    args = SimpleNamespace(
        fps=fps,
        max_frames_per_video=max_frames,
        api_frame_limit=api_frame_limit,
        probe_seconds=float(probe_seconds),
        frame_width=960,
        supplemental_image_limit=20,
    )
    run_dir = ROOT / "tmp" / "visual_review_workbench" / f"folder_{folder_dir.name}_{int(time.time())}"
    try:
        case = load_case_bundle(folder_dir, args, run_dir)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = apply_frontdesk_context(case, scenario, json.dumps(evidence_context or {}, ensure_ascii=False))
    result = call_model(MODEL_CONFIGS[model_key], case, timeout=300, retries=2)
    review = _agent_report_response(case, folder_dir, result, "agent_folder")
    return {
        "ok": (review.get("summary") or {}).get("review_status") == "completed",
        "source_status": "folder_ready",
        "review": review,
    }


def _row_value(row: Dict[str, Any], aliases: tuple[str, ...]) -> str:
    lookup = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        value = lookup.get(alias.strip().lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_task(value: str) -> str:
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[\s_\-/]+", "", raw)
    if raw in {"video_unboxing", "unboxing", "unboxing_video"} or any(key in compact for key in ("开箱", "拆箱", "unboxing")):
        return "video_unboxing"
    if raw in {"product_damage", "damage", "damaged_item"} or any(key in compact for key in ("有伤", "破损", "划痕", "damage")):
        return "product_damage"
    if raw in {"minor_material", "minor", "minor_refund"} or any(key in compact for key in ("未成年", "监护", "资料", "minor")):
        return "minor_material"
    if raw in {"wrong_item", "wrong_sku", "sku_mismatch"} or any(key in compact for key in ("发错", "错发", "sku", "wrongitem")):
        return "wrong_item"
    return "unknown"


def _normalize_label(value: str) -> str:
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[\s_\-/，。:：；;]+", "", raw)
    if not compact:
        return ""
    negative = {
        "fail", "failed", "no", "n", "false", "invalid", "reject", "rejected", "unsupported",
        "negative", "incomplete", "missing", "mismatch", "nodamage", "不通过", "未通过", "不合格",
        "不合规", "不支持", "拒绝", "无伤", "没伤", "未见损伤", "未破损", "没发错", "未发错",
        "不一致", "资料缺失", "缺失", "不完整", "不成立", "剪辑", "离镜",
    }
    positive = {
        "pass", "passed", "ok", "yes", "y", "true", "valid", "support", "supported", "confirmed",
        "positive", "approved", "approve", "accept", "complete", "match", "compliant", "damage",
        "damaged", "wrong", "通过", "合格", "合规", "支持", "确认", "确认有伤", "有伤", "破损",
        "发错", "错发", "资料完整", "完整", "一致", "同意", "可支持", "可通过", "成立",
    }
    review = {
        "suspect", "manualreview", "review", "uncertain", "unclear", "ambiguous", "needreview",
        "pending", "疑似", "存疑", "人工复核", "待复核", "不确定", "看不清", "需补件", "补件", "待确认",
    }
    if compact in negative:
        return "negative"
    if compact in positive:
        return "positive"
    if compact in review:
        return "review"
    return "unmapped:" + compact[:40]


def _valid_label(value: str) -> bool:
    return value in {"positive", "negative", "review"}


def _public_label(value: str) -> str:
    if value == "positive":
        return "正向"
    if value == "negative":
        return "负向"
    if value == "review":
        return "需复核"
    if value.startswith("unmapped:"):
        return "未映射"
    return "-"


def _read_sample_rows(file: UploadFile) -> List[Dict[str, Any]]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SAMPLE_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 CSV 或 JSON 样本表")
    raw = file.file.read(SAMPLE_MAX_BYTES + 1)
    if len(raw) > SAMPLE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="样本表过大，请拆分后上传")
    if not raw:
        raise HTTPException(status_code=400, detail="样本表为空")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="样本表需要使用 UTF-8 编码") from exc
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV 缺少表头")
        rows = []
        for row in reader:
            if None in row:
                raise HTTPException(status_code=400, detail="CSV 行列数量与表头不一致")
            if any(str(value or "").strip() for value in row.values()):
                rows.append(dict(row))
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON 格式无法解析") from exc
        if isinstance(payload, dict):
            payload = payload.get("samples") or payload.get("rows") or []
        if not isinstance(payload, list):
            raise HTTPException(status_code=400, detail="JSON 需要是数组或包含 samples 数组")
        bad_index = next((index for index, item in enumerate(payload, start=1) if not isinstance(item, dict)), None)
        if bad_index is not None:
            raise HTTPException(status_code=400, detail=f"JSON 第 {bad_index} 条样本不是对象")
        rows = list(payload)
    if not rows:
        raise HTTPException(status_code=400, detail="未读取到有效样本")
    if len(rows) > 5000:
        raise HTTPException(status_code=413, detail="单次最多评测 5000 条样本")
    return [{str(key): value for key, value in row.items()} for row in rows]


def _empty_task_stats() -> Dict[str, Any]:
    return {
        "total": 0,
        "evaluable": 0,
        "correct": 0,
        "accuracy": None,
        "labels": {"positive": 0, "negative": 0, "review": 0, "other": 0},
        "evaluable_labels": {"positive": 0, "negative": 0, "review": 0, "other": 0},
    }


def _evaluate_sample_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks: Dict[str, Dict[str, Any]] = {}
    missing_fields = {name: 0 for name in ("业务场景", "人工结论", "用户诉求", "素材", "商品信息", "规格信息", "人工原因")}
    errors: List[Dict[str, Any]] = []
    unmapped_labels: Dict[str, Dict[str, int]] = {"人工结论": {}, "辅助结论": {}}
    total = len(rows)
    evaluable = 0
    correct = 0
    target_total = 0
    target_evaluable = 0
    target_correct = 0

    for index, row in enumerate(rows, start=1):
        task = _normalize_task(_row_value(row, FIELD_ALIASES["task"]))
        human_label_raw = _row_value(row, FIELD_ALIASES["human_label"])
        predicted_label_raw = _row_value(row, FIELD_ALIASES["predicted_label"])
        human_label = _normalize_label(human_label_raw)
        predicted_label = _normalize_label(predicted_label_raw)
        stats = tasks.setdefault(task, _empty_task_stats())
        stats["total"] += 1
        if task in TARGET_REVIEW_TASKS:
            target_total += 1

        if task == "unknown":
            missing_fields["业务场景"] += 1
        if not human_label:
            missing_fields["人工结论"] += 1
        if not _row_value(row, FIELD_ALIASES["user_text"]):
            missing_fields["用户诉求"] += 1
        if not _row_value(row, FIELD_ALIASES["material"]):
            missing_fields["素材"] += 1
        if not _row_value(row, FIELD_ALIASES["order_item"]):
            missing_fields["商品信息"] += 1
        if not _row_value(row, FIELD_ALIASES["sku"]):
            missing_fields["规格信息"] += 1
        if not _row_value(row, FIELD_ALIASES["human_reason"]):
            missing_fields["人工原因"] += 1

        if human_label.startswith("unmapped:"):
            raw = human_label_raw[:40]
            unmapped_labels["人工结论"][raw] = unmapped_labels["人工结论"].get(raw, 0) + 1
        if predicted_label.startswith("unmapped:"):
            raw = predicted_label_raw[:40]
            unmapped_labels["辅助结论"][raw] = unmapped_labels["辅助结论"].get(raw, 0) + 1

        if human_label and _valid_label(human_label):
            bucket = human_label if human_label in {"positive", "negative", "review"} else "other"
            stats["labels"][bucket] += 1
        elif human_label:
            stats["labels"]["other"] += 1

        if _valid_label(human_label) and _valid_label(predicted_label):
            evaluable += 1
            stats["evaluable"] += 1
            bucket = human_label if human_label in {"positive", "negative", "review"} else "other"
            stats["evaluable_labels"][bucket] += 1
            matched = human_label == predicted_label
            if matched:
                correct += 1
                stats["correct"] += 1
            if task in TARGET_REVIEW_TASKS:
                target_evaluable += 1
                if matched:
                    target_correct += 1
            if not matched and len(errors) < 12:
                errors.append({
                    "row": index,
                    "task": TASK_PUBLIC_NAMES.get(task, task),
                    "human_label": _public_label(human_label),
                    "assistant_label": _public_label(predicted_label),
                })

    for stats in tasks.values():
        if stats["evaluable"]:
            stats["accuracy"] = round(stats["correct"] / stats["evaluable"], 4)

    readiness = {}
    for task in TARGET_REVIEW_TASKS:
        stats = tasks.get(task) or _empty_task_stats()
        labels = stats["evaluable_labels"]
        minimum_ready = labels["positive"] >= 50 and labels["negative"] >= 50
        recommended_ready = labels["positive"] >= 200 and labels["negative"] >= 200
        readiness[task] = {
            "name": TASK_PUBLIC_NAMES[task],
            "positive": labels["positive"],
            "negative": labels["negative"],
            "evaluable": stats["evaluable"],
            "minimum_ready": minimum_ready,
            "recommended_ready": recommended_ready,
        }

    return {
        "ok": True,
        "summary": {
            "total": total,
            "evaluable": evaluable,
            "correct": correct,
            "accuracy": round(correct / evaluable, 4) if evaluable else None,
            "target_total": target_total,
            "target_evaluable": target_evaluable,
            "target_correct": target_correct,
            "target_accuracy": round(target_correct / target_evaluable, 4) if target_evaluable else None,
            "non_target_total": total - target_total,
            "ready_for_accuracy": all(item["minimum_ready"] for item in readiness.values()),
            "minimum_required": "三类主场景每个正向/负向结论至少 50 条",
            "recommended_required": "每个结论类 200-300 条更适合对外验收",
        },
        "tasks": {
            TASK_PUBLIC_NAMES.get(task, task): stats for task, stats in sorted(tasks.items())
        },
        "readiness": readiness,
        "missing_fields": missing_fields,
        "unmapped_labels": unmapped_labels,
        "mismatches": errors,
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
    return {"ok": True, "service": "visual_review_workbench"}


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
    allowed_roots = [ROOT.resolve(), WORKBENCH_DIR.resolve()]
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
    rows = _read_sample_rows(file)
    return JSONResponse(_evaluate_sample_rows(rows))


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
    scenario: str = Form("video_unboxing"),
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
    fps: float = Form(1.0),
    max_frames: int = Form(6),
    api_frame_limit: int = Form(4),
    probe_seconds: int = Form(12),
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    if scenario not in {"video_unboxing", "product_damage", "minor_material"}:
        raise HTTPException(status_code=400, detail="未知审核场景")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 24, 6)
    api_frame_limit = _clamp_int(api_frame_limit, 1, min(12, max_frames), min(4, max_frames))
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    folder_dir = _save_folder_uploads(files)
    evidence_context = {
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
    }
    return JSONResponse(_run_folder_agent_review(folder_dir, scenario, "gemini35", evidence_context, fps, max_frames, api_frame_limit, probe_seconds))


@app.post("/api/review")
def review(
    source_type: str = Form("upload"),
    video_url: str = Form(""),
    scenario: str = Form("video_unboxing"),
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
    fps: float = Form(1.0),
    max_frames: int = Form(6),
    api_frame_limit: int = Form(4),
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
    max_frames = _clamp_int(max_frames, 1, 24, 6)
    api_frame_limit = _clamp_int(api_frame_limit, 1, min(12, max_frames), min(4, max_frames))
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
    evidence_context = {
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
    }
    result = _run_review(video, scenario, fps, max_frames, api_frame_limit, probe_seconds, review_model, evidence_context)
    return JSONResponse({"ok": result["ok"], "source_status": source_status, "review": result})


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(__import__("os").getenv("VISUAL_WORKBENCH_PORT", "7861")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
