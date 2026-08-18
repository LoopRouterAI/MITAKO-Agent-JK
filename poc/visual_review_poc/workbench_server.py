# -*- coding: utf-8 -*-
"""客服视觉审核工作台：上传/URL -> 本地视频 -> 视觉复核报告。"""
from __future__ import annotations

import json
import logging
import hashlib
import hmac
import math
import os
import re
import secrets
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

LOGGER = logging.getLogger("mitako.visual_review.workbench")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=Path(os.getenv("MITAKO_ENV_FILE") or PROJECT_ROOT / ".env"),
    override=False,
)

from runtime_paths import app_root
from configs.model_governance import runtime_model_keys
from prompts.governance import public_snapshot_metadata
from prompts.visual_review.core import freeze_rule_snapshot
from review_service.media_forensics import inspect_job_media
from review_service.policy_governance import get_active_policy
from review_service.service import ensure_label_isolation, normalize_frame_strategy, postprocess_review
from review_service.resource_guard import CASE_GATE, runtime_diagnostics
from review_service.decision_policy import DEFAULT_PRODUCT_DAMAGE_POLICY_REF
from poc.visual_review_poc.internal_review_ledger import ReviewRequestLedger
from poc.visual_review_poc.media_registry import MediaRegistry
from review_media_safety import (
    FOLDER_SUFFIXES,
    IMAGE_SUFFIXES,
    MEDIA_SUFFIXES,
    VIDEO_SUFFIXES,
    ignored_upload_reason,
    public_skip_reason,
    valid_media_magic,
)
from review_public_safety import redact_public_review_data
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
    from poc.visual_review_poc.model_selection_e2e import (
        MODEL_CONFIGS,
        call_model,
        call_model_chunked,
        call_opening_compliance_verification,
        call_opening_start_verification,
        derive_claim_identity,
        discover_case_videos,
        is_retryable_failure,
        load_case_bundle,
        merge_model_billing,
        merge_opening_compliance_verification,
        merge_opening_start_verification,
        score_result,
    )
    from poc.visual_review_poc.local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from poc.visual_review_poc.official_reference_images import prepare_official_reference_images
    from poc.visual_review_poc.media_preflight import (
        DEFAULT_NATIVE_INLINE_MAX_BYTES,
        build_media_preflight_execution,
        prepare_native_video_proxy,
        resolve_runtime_temp_dir,
        video_proxy_recommendation,
    )
    from poc.visual_review_poc.native_video_perception import run_native_perception_pipeline
    from poc.visual_review_poc.observability import log_visual_event, sanitize_error_text, visual_event_context
    import observability_store
    from poc.visual_review_poc.secure_media_tunnel import open_secure_media_tunnel
    from poc.visual_review_poc.video_role_preflight import (
        build_opening_role_case,
        declared_video_roles,
        extract_opening_role_previews,
        opening_role_batches,
        select_opening_video_candidates,
    )
    from poc.visual_review_poc.unified_model_pass import native_dimension_gaps
    from poc.visual_review_poc.report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )
    from poc.visual_review_poc.sample_evaluation import evaluate_sample_rows, read_sample_rows
except ImportError:
    from model_selection_e2e import (
        MODEL_CONFIGS,
        call_model,
        call_model_chunked,
        call_opening_compliance_verification,
        call_opening_start_verification,
        derive_claim_identity,
        discover_case_videos,
        is_retryable_failure,
        load_case_bundle,
        merge_model_billing,
        merge_opening_compliance_verification,
        merge_opening_start_verification,
        score_result,
    )
    from local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from official_reference_images import prepare_official_reference_images
    from media_preflight import (
        DEFAULT_NATIVE_INLINE_MAX_BYTES,
        build_media_preflight_execution,
        prepare_native_video_proxy,
        resolve_runtime_temp_dir,
        video_proxy_recommendation,
    )
    from native_video_perception import run_native_perception_pipeline
    from observability import log_visual_event, sanitize_error_text, visual_event_context
    import observability_store
    from secure_media_tunnel import open_secure_media_tunnel
    from video_role_preflight import (
        build_opening_role_case,
        declared_video_roles,
        extract_opening_role_previews,
        opening_role_batches,
        select_opening_video_candidates,
    )
    from unified_model_pass import native_dimension_gaps
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
REPORT_DIR = WORKBENCH_DIR / "reports"
PUBLIC_SUMMARY_DIR = REPORT_DIR / "public_summaries"
RUNTIME_MEDIA_DIR = resolve_runtime_temp_dir(ROOT)
UPLOAD_DIR = RUNTIME_MEDIA_DIR / "uploaded_videos"
INDEX_HTML = WORKBENCH_DIR / "workbench.html"
SAMPLE_MATERIAL_DIR = (ROOT / "docs" / "三大审核场景的小量样本").resolve()
ALLOWED_REPORTS: dict[str, Dict[str, Any]] = {}
_INTERNAL_REVIEW_CACHE_MAX = 256
INTERNAL_REVIEW_LEDGER = ReviewRequestLedger(
    REPORT_DIR / "internal" / "internal_review_requests.sqlite3",
    completed_limit=_INTERNAL_REVIEW_CACHE_MAX,
)
PUBLIC_MEDIA_REGISTRY = MediaRegistry(REPORT_DIR / "internal" / "public_media_registry.sqlite3", ROOT)
PUBLIC_WORKBENCH_MEDIA_REGISTRY = MediaRegistry(
    REPORT_DIR / "internal" / "public_workbench_media_registry.sqlite3",
    WORKBENCH_DIR,
)
PUBLIC_RUNTIME_MEDIA_REGISTRY = MediaRegistry(
    REPORT_DIR / "internal" / "public_runtime_media_registry.sqlite3",
    RUNTIME_MEDIA_DIR,
)
_configured_signing_secret = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
REPORT_SIGNING_SECRET_CONFIGURED = bool(_configured_signing_secret)
REPORT_SIGNING_SECRET = _configured_signing_secret.encode("utf-8") if _configured_signing_secret else secrets.token_bytes(32)
REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET = os.getenv(
    "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET", "1"
).strip().lower() in {"1", "true", "yes", "on"}
from prompts.visual_review.contract import REVIEW_CONTRACT_VERSION
try:
    REPORT_URL_TTL_SECONDS = max(1, int(os.getenv("VISUAL_REPORT_URL_TTL_SECONDS", "900") or 900))
except ValueError:
    REPORT_URL_TTL_SECONDS = 900
MAX_UPLOAD_BYTES = int(os.getenv("VISUAL_MAX_UPLOAD_MB", "1024") or 1024) * 1024 * 1024
NATIVE_INLINE_MEDIA_MAX_BYTES = DEFAULT_NATIVE_INLINE_MAX_BYTES
# 外部 URL 仍受供应商 100 MB 请求级限制；预留 5 MB 给容器差异和上游校验。
NATIVE_URL_MEDIA_MAX_BYTES = max(
    NATIVE_INLINE_MEDIA_MAX_BYTES,
    int(os.getenv("VISUAL_NATIVE_URL_PROXY_MAX_MB", "512") or 512) * 1024 * 1024,
)
MAX_FOLDER_BYTES = int(os.getenv("VISUAL_MAX_FOLDER_MB", "2048") or 2048) * 1024 * 1024
MAX_FOLDER_FILES = max(1, int(os.getenv("VISUAL_MAX_FOLDER_FILES", "200") or 200))
try:
    UPLOAD_RETENTION_SECONDS = max(0, int(os.getenv("VISUAL_UPLOAD_RETENTION_HOURS", "72") or 72)) * 60 * 60
except ValueError:
    UPLOAD_RETENTION_SECONDS = 72 * 60 * 60
EVALUATION_CONTEXT_FILENAMES = {"annotation.json", "reply.json", "manifest.json", "sample_labels.json"}
SUPPLEMENTAL_IMAGE_SOFT_LIMIT = min(
    max(1, int(os.getenv("VISUAL_SUPPLEMENTAL_IMAGE_SOFT_LIMIT", "40") or 40)),
    MAX_FOLDER_FILES,
)
MAX_SUPPLEMENTAL_IMAGES = max(
    SUPPLEMENTAL_IMAGE_SOFT_LIMIT,
    min(int(os.getenv("VISUAL_MAX_SUPPLEMENTAL_IMAGES", "200") or 200), MAX_FOLDER_FILES),
)
MAX_BATCH_FOLDERS = max(1, min(int(os.getenv("VISUAL_MAX_BATCH_FOLDERS", "10") or 10), 20))
MAX_BATCH_FILES = max(MAX_FOLDER_FILES, min(int(os.getenv("VISUAL_MAX_BATCH_FILES", "400") or 400), 1000))


def _resource_wait_seconds() -> float:
    try:
        return max(0.0, min(float(os.getenv("REVIEW_RESOURCE_WAIT_SECONDS", "30") or 30), 300.0))
    except (TypeError, ValueError):
        return 30.0


def _run_with_case_slot(fn, *args, **kwargs):
    with CASE_GATE.slot(timeout=_resource_wait_seconds()) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=429,
                detail={
                    "error_type": "review_resource_busy",
                    "message": "审核资源正在处理其他案件，请稍后重试。",
                    "retry_after_seconds": max(1, int(_resource_wait_seconds() or 1)),
                    "resources": runtime_diagnostics(),
                },
                headers={"Retry-After": str(max(1, int(_resource_wait_seconds() or 1)))},
            )
        return fn(*args, **kwargs)


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
    "error",
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
    "standard": {"label": "标准连续性复核", "sampling_mode": "adaptive", "default_max_frames": 24},
    "fast": {"label": "经济初筛", "sampling_mode": "adaptive", "default_max_frames": 12},
    "backup": {"label": "Strong 强化复核", "sampling_mode": "dense", "default_max_frames": 1800},
}


def _cleanup_expired_uploads() -> None:
    if UPLOAD_RETENTION_SECONDS <= 0 or not UPLOAD_DIR.is_dir():
        return
    cutoff = time.time() - UPLOAD_RETENTION_SECONDS
    try:
        candidates = list(UPLOAD_DIR.iterdir())
    except OSError:
        return
    for path in candidates:
        managed = path.name.startswith("folder_") or re.fullmatch(r"\d{8}_\d{6}_\d+", path.name)
        try:
            if managed and path.is_dir() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            continue


def _save_upload(file: UploadFile) -> Path:
    _cleanup_expired_uploads()
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
    accepted_candidates = [
        file for file in files
        if not ignored_upload_reason(file.filename or "")
        and Path((file.filename or "").replace("\\", "/")).name.lower() not in EVALUATION_CONTEXT_FILENAMES
    ]
    if len(accepted_candidates) > MAX_FOLDER_FILES:
        raise HTTPException(status_code=413, detail={
            "code": "too_many_review_assets",
            "received_count": len(accepted_candidates),
            "safe_limit": MAX_FOLDER_FILES,
        })
    _cleanup_expired_uploads()
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
            if display_name.lower() in EVALUATION_CONTEXT_FILENAMES:
                skipped.append({"name": display_name, "reason": "evaluation_label_not_allowed"})
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
                    try:
                        fh.write(chunk)
                    except OSError as exc:
                        if getattr(exc, "errno", None) == 28:
                            raise HTTPException(
                                status_code=507,
                                detail={
                                    "code": "review_storage_insufficient",
                                    "message": "审核暂存空间不足，请清理历史缓存后重试。",
                                },
                            ) from exc
                        raise
            if size <= 0:
                target.unlink(missing_ok=True)
                skipped.append({"name": display_name, "reason": "empty_file"})
                continue
            if suffix in ALLOWED_MEDIA_SUFFIXES and not valid_media_magic(suffix, head):
                target.unlink(missing_ok=True)
                skipped.append({"name": display_name, "reason": "invalid_media_content"})
                continue
            if suffix in {".txt", ".json"}:
                try:
                    content = target.read_text(encoding="utf-8-sig")
                    ensure_label_isolation(json.loads(content) if suffix == ".json" else content)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    target.unlink(missing_ok=True)
                    skipped.append({"name": display_name, "reason": "evaluation_label_not_allowed"})
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
        "capacity_mode": "expanded" if len(accepted) > SUPPLEMENTAL_IMAGE_SOFT_LIMIT else "standard",
        "soft_limit": SUPPLEMENTAL_IMAGE_SOFT_LIMIT,
        "safe_limit": MAX_FOLDER_FILES,
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


def _clamp_float(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return max(low, min(high, parsed))


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
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
            "needs_human_review": bool(summary.get("needs_human_review")),
        }
    ok = bool(raw_report.get("ok"))
    return {
        "cases": summary.get("cases") or 1,
        "total_reviews": summary.get("total_reviews") or 1,
        "successful_reviews": summary.get("successful_reviews") if summary.get("successful_reviews") is not None else (1 if ok else 0),
        "needs_human_review": bool(summary.get("needs_human_review")),
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
    if isinstance(value, str) and re.search(
        r"(?i)(?:file://|[a-z]:[\\/]|\\\\|/(?:home|users|tmp|var|opt|mnt|private|workspace)(?:/|$))",
        value,
    ):
        return ""
    return value


_MINOR_PUBLIC_PARSED_SCHEMA = {
    "decision": True,
    "predicted_label": True,
    "system_yes_no": True,
    "confidence": True,
    "processing_status": True,
    "system_action": True,
    "overall_audit": {
        "conclusion": True,
        "confidence": True,
        "core_reason": True,
        "business_follow_up_suggestion": True,
    },
    "visual_evidence_verdict": True,
    "visual_qc_conclusion": {"verdict": True, "confidence": True, "core_reason": True},
    "confidence_reason": True,
    "minor_material_assessment": {
        "sop_version": True,
        "readiness": True,
        "visual_precheck_status": True,
        "declared_image_count": True,
        "accepted_image_count": True,
        "processed_image_count": True,
        "processed_image_indices": [True],
        "unclassified_image_indices": [True],
        "coverage_ratio": True,
        "coverage_complete": True,
        "ingestion_complete": True,
        "processing_status": True,
        "system_action": True,
        "material_inventory": [{
            "image_index": True,
            "asset_ref": True,
            "document_type": True,
            "subject_role": True,
            "document_side": True,
            "issuing_country_or_region": True,
            "readability": True,
            "document_state": True,
            "sop_eligibility": True,
            "quality_issues": [True],
            "editing_evidence_codes": [True],
        }],
        "checklist": [{
            "requirement_id": True,
            "label": True,
            "status": True,
            "quality_status": True,
            "evidence_refs": [True],
            "evidence_image_indices": [True],
            "rule_note": True,
            "validation_status": True,
        }],
        "field_consistency": {
            "schema_version": True,
            "status": True,
            "verdict": True,
            "message": True,
            "checks": [{
                "check_id": True,
                "relationship_evidence_type": True,
                "status": True,
                "message": True,
                "field_results": [{
                    "field_name": True,
                    "status": True,
                    "visibility": True,
                    "evidence_image_indices": [True],
                }],
                "tamper_risk": True,
                "risk_reason_codes": [True],
                "evidence_image_indices": [True],
                "coverage_complete": True,
                "segment_count": True,
                "payment_capability_risk": True,
            }],
        },
        "required_materials": [True],
        "payment_capability_risk": {
            "level": True,
            "effect": True,
            "evidence_image_indices": [True],
            "low_age": True,
            "under_nine": True,
            "age_confidence": True,
            "process_evidence_status": True,
            "requires_review": True,
            "requires_more_material": True,
        },
        "authenticity_assessment": {
            "severity": True,
            "risk_score": True,
            "risk_percent": True,
            "blocks_visual_precheck": True,
            "evidence_image_indices": [True],
            "missing_exif_image_indices": [True],
            "unknown_exif_image_indices": [True],
            "editor_metadata_image_indices": [True],
            "conclusion": True,
            "boundary": True,
        },
        "authoritative_verification": {
            "status": True,
            "checks": [{"verification_id": True, "integration_status": True}],
            "boundary": True,
        },
        "process_evidence": [{
            "video_index": True,
            "global_frame_index": True,
            "timestamp": True,
            "asset_ref": True,
            "process_type": True,
            "evidence_quality": True,
        }],
        "privacy_boundary": True,
        "business_boundary": True,
    },
    "supporting_evidence": [{
        "source_type": True,
        "image_index": True,
        "asset_ref": True,
        "description": True,
        "confidence": True,
    }],
    "adopted_evidence": [{
        "source_type": True,
        "image_index": True,
        "asset_ref": True,
        "description": True,
        "confidence": True,
    }],
    "challenging_evidence": [{
        "source_type": True,
        "image_index": True,
        "asset_ref": True,
        "description": True,
        "confidence": True,
    }],
    "material_gaps": [True],
    "audit_methods": [True],
    "business_action_allowed": True,
    "human_required": True,
    "pass_integrity_status": True,
    "specialized_pass_warning": True,
    "business_follow_up_reason": True,
    "next_step": True,
    "confidence_components": {
        "material_image_coverage": True,
        "required_category_completeness": True,
        "final_decision": True,
        "calibration_status": True,
        "interpretation": True,
    },
}
# 所有场景只公开报告实际消费的受控字段；未知模型字段一律丢弃。
_PUBLIC_PARSED_FIELD_NAMES = {
    "decision", "predicted_label", "system_yes_no", "confidence", "overall_audit", "conclusion",
    "processing_status", "system_action",
    "atomic_facts", "value",
    "all_items_shown", "continuous", "has_edit", "has_offscreen", "has_speed_change",
    "issue_visible", "overall_video_result", "sealed_start", "waybill_visible", "field_confidences",
    "opening_action_assessment",
    "opening_video_evidence", "present", "sop_compliant", "status", "validated_requirements",
    "core_reason", "business_follow_up_suggestion", "visual_evidence_verdict", "visual_qc_conclusion",
    "verdict", "confidence_reason", "video_audit_conclusion", "continuity_score", "continuity_reason",
    "swap_risk_level", "edit_or_cut_risk", "opening_integrity", "opening_integrity_source", "sampling_boundary_status",
    "playback_speed", "segment_playback_speed_values", "sampling_fps", "speed_review_impact",
    "critical_evidence_observable", "affected_review_items", "evidence_refs", "opening_video_compliance",
    "sealed_start", "waybill_visible", "single_take_continuity", "issue_visible_in_continuous_opening",
    "validated_fields", "field", "field_sources", "result", "source",
    "technical_timeline_status", "evidence_continuity_status", "object_continuity_assessment",
    "tracked_subjects", "subject_id", "description", "tracking_start", "tracking_end",
    "first_exposed_timestamp", "visibility_coverage", "out_of_frame_events", "start_timestamp",
    "end_timestamp", "duration_seconds", "duration_basis", "duration_is_exact",
    "duration_lower_bound_seconds", "duration_upper_bound_seconds", "sampling_resolution_seconds",
    "visibility", "before_evidence", "out_of_frame_evidence",
    "after_evidence", "identity_reestablished", "reason", "continuity_verdict",
    "longest_out_of_frame_seconds", "longest_out_of_frame_lower_bound_seconds",
    "longest_out_of_frame_upper_bound_seconds", "total_unobserved_seconds", "critical_events", "policy",
    "claimed_item_reference_status", "claimed_item_timeline_complete", "claimed_item_never_exposed",
    "identity_match", "identity_basis", "damage_visible", "within_required_display_window",
    "customer_claim_parse", "expected_item", "claimed_received_item",
    "claimed_mismatch_type", "expected_order_item", "actual_received_item", "audit_methods",
    "frame_findings", "video_index", "global_frame_index", "frame_index", "timestamp", "visible_facts",
    "risk", "subject_visibility", "state", "adopted_evidence", "supporting_evidence",
    "challenging_evidence", "source_type", "image_index", "reference_index", "reference_id", "asset_ref", "fact", "why_it_matters",
    "same_item_linkage", "temporal_linkage", "authenticity_assessment", "size_sku_assessment",
    "issue_timestamps", "skeptical_questions", "material_gaps", "conclusion_argument", "support",
    "challenge", "why_not_final_business_decision", "business_action_allowed", "human_required",
    "human_required_for_business_action", "business_follow_up_reason", "next_step",
    "damage_causality_assessment", "damage_presence", "supplemental_damage_presence", "damage_type_and_location", "first_visible_evidence",
    "main_video_detail_sufficient", "severity_assessment", "level", "structural_failure",
    "pre_opening_state_visible", "opening_action_visible", "damage_change_observed", "damage_timing",
    "possible_origins", "origin", "most_likely_origin", "origin_confidence", "causal_evidence_level",
    "appearance_difference", "business_defect_qualification", "special_product_rule",
    "claim_support", "before_action_evidence", "action_evidence", "after_action_evidence", "subject",
    "location", "chain_id", "alternative_explanations", "cannot_conclude_reason", "damage_observability",
    "status", "claimed_region_closeup", "required_view_coverage", "conflicting_evidence", "missing_views",
    "evidence_source_summary", "primary_video", "scope", "supplemental_images", "provided_count",
    "referenced_count", "referenced_image_indices", "unreferenced_image_indices", "linkage_status", "evidence_findings",
    "claim_fact_assessment", "atomic_claim_results", "claim_id", "subject_ref", "support_status",
    "damage_type", "main_video_visibility", "supplemental_visibility", "condition_at_unboxing",
    "severity_level", "severity_confidence",
    "order_linkage", "expected_package_fact", "observed_package_fact", "scene_match", "claimed_scene",
    "observed_scene", "assembly", "reassembly_result", "permanent_damage",
    "decision_boundary", "key_evidence", "fulfillment_reconciliation", "baseline_version", "expected_items",
    "observed_items", "suspected_missing_items", "unexpected_items", "unconfirmed_items",
    "package_observations", "package_coverage", "all_packages_uploaded", "all_items_displayed",
    "warehouse_verification", "resolution_basis", "evidence_sufficiency", "observation_confidence",
    "evidence_route", "visual_coverage_verified", "static_materials_verified", "user_materials_complete",
    "submitted_package_mapping_complete", "selection_rules_complete", "benefit_rules_complete",
    "unknown_package_refs", "evidence_conflicts", "product_composition_resolution",
    "warehouse_check", "outcome", "scenario_transition",
    "claimed_item", "is_expected", "resolution_ref", "required_received_item_refs",
    "post_decision_reminders", "type", "item_refs", "message", "affects_verdict",
    "verification_ref",
    "evidence_timestamps", "item_ref", "sku", "product_name", "specification", "expected_quantity",
    "item_role", "series", "edition", "physical_form", "included_parts", "visible_identifiers",
    "descriptive_dimensions",
    "observed_quantity", "package_ref", "opening_complete", "all_contents_laid_out",
    "waybill_matches_order", "received_group_photo_complete", "green_bag_visible",
    "confidence_components", "main_segment_mean", "damage_origin", "continuity_visibility_coverage",
    "final_decision", "calibration_status", "interpretation", "decision_policy_audit", "version", "mode",
    "policy_ref", "policy_source", "requested_overrides_ignored", "applied", "rule_id", "claim_scope",
    "evidence_verdict_before_policy",
    "stage", "issue_types", "excluded_issue_types", "active_claim_ids", "split_status", "ready",
    "evidence_gate", "video_present", "model_confidence", "media_forensics_status",
    "media_forensics_risk_level", "supplemental_linkage_status", "business_boundary", "failed_conditions",
    "minimum_visibility_coverage", "minimum_confidence", "minimum_required_view_coverage", "fully_observable",
    "claimed_item_longest_out_of_frame_seconds", "maximum_forensic_risk",
    "pass_integrity_status", "specialized_pass_guard_reason", "specialized_pass_warning",
    "aggregation_warnings", "code", "chunk_index", "alleged_end", "later_sampled_evidence_seconds",
    "global_review_summary", "sampled_start_seconds", "sampled_end_seconds", "source_duration_seconds",
    "claimed_item_first_exposed_timestamp", "timeline_coverage_ratio",
    "chunk_narratives_excluded_from_public_conclusion", "quality_issues", "tamper_risk", "risk_reason_codes",
    "input_readiness_guard", "missing_required",
    "material_readiness", "scenario", "checklist", "requirement_id", "label", "required",
    "missing_items", "warnings",
}


def _redact_minor_identifiers(value: Any) -> Any:
    return redact_public_review_data(value)


def _project_public_parsed_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _project_public_parsed_fields(item)
            for key, item in value.items()
            if str(key) in _PUBLIC_PARSED_FIELD_NAMES
        }
    if isinstance(value, list):
        return [_project_public_parsed_fields(item) for item in value]
    return _redact_minor_identifiers(value)


def _project_public_dto(value: Any, schema: Any) -> Any:
    if schema is True:
        return _redact_minor_identifiers(value)
    if isinstance(schema, list):
        return [_project_public_dto(item, schema[0]) for item in value] if isinstance(value, list) else []
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            return {}
        return {
            key: _project_public_dto(value[key], child_schema)
            for key, child_schema in schema.items()
            if key in value
        }
    return None


def _public_minor_material_parsed(parsed: Dict[str, Any]) -> Dict[str, Any]:
    return _project_public_dto(parsed, _MINOR_PUBLIC_PARSED_SCHEMA)


def _public_parsed(parsed: Dict[str, Any], scenario: str) -> Dict[str, Any]:
    if scenario in {"minor_material", "minor_refund"}:
        return _public_minor_material_parsed(parsed)
    return _project_public_parsed_fields(parsed)


def _public_url_signature(path: str, expires: int) -> str:
    message = f"{path}\n{expires}".encode("utf-8")
    return hmac.new(REPORT_SIGNING_SECRET, message, hashlib.sha256).hexdigest()


def _sign_public_url(path: str, *, expires: Optional[int] = None) -> str:
    split = urlsplit(path)
    expires_at = int(expires if expires is not None else time.time() + REPORT_URL_TTL_SECONDS)
    signed = f"{split.path}?expires={expires_at}&sig={_public_url_signature(split.path, expires_at)}"
    return signed + (f"#{split.fragment}" if split.fragment else "")


def _internal_request_authorized(token: str) -> bool:
    expected = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
    return bool(expected and token and hmac.compare_digest(token, expected))


def _claim_internal_review_request(request_id: str, tenant_id: str) -> tuple[str, Any]:
    request_id = str(request_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", request_id):
        return "disabled", None
    wait_seconds = max(
        30,
        min(int(os.getenv("REVIEW_JOB_TIMEOUT_SECONDS", "1800") or 1800) + 30, 3630),
    )
    state, response = INTERNAL_REVIEW_LEDGER.claim(tenant_id, request_id)
    if state == "completed":
        return "cached", deepcopy(response or {})
    if state == "owner":
        return "owner", (tenant_id, request_id)
    if state == "failed":
        raise HTTPException(status_code=409, detail="internal_review_request_failed")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(0.2)
        state, response = INTERNAL_REVIEW_LEDGER.lookup(tenant_id, request_id)
        if state == "completed":
            return "cached", deepcopy(response or {})
        if state in {"failed", "missing"}:
            raise HTTPException(status_code=409, detail="internal_review_request_failed")
    raise HTTPException(status_code=504, detail="internal_review_request_timeout")


def _complete_internal_review_request(key: Any, response: Dict[str, Any]) -> None:
    if not key:
        return
    tenant_id, request_id = key
    INTERNAL_REVIEW_LEDGER.complete(tenant_id, request_id, response)


def _fail_internal_review_request(key: Any) -> None:
    if not key:
        return
    tenant_id, request_id = key
    INTERNAL_REVIEW_LEDGER.fail(tenant_id, request_id)


def _resolve_rule_tenant_id(value: str, internal_request: bool) -> str:
    if not internal_request:
        return "mitako"
    tenant_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", tenant_id):
        raise HTTPException(status_code=422, detail="invalid_rule_tenant_id")
    return tenant_id


def _require_public_signature(path: str, expires: str, sig: str) -> None:
    try:
        expires_at = int(expires)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    expected = _public_url_signature(path, expires_at)
    if expires_at < int(time.time()) or not sig or not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail="forbidden")


def _refresh_signed_urls(value: Any, field_name: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _refresh_signed_urls(item, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_refresh_signed_urls(item, field_name) for item in value]
    if isinstance(value, str):
        split = urlsplit(value)
        if split.scheme or split.netloc:
            return value
        if field_name in {"url", "video_url"} and re.fullmatch(
            r"/media-item/[a-f0-9]{32}", split.path
        ):
            return _sign_public_url(value)
        if field_name == "html_url" and re.fullmatch(
            r"/reports/[A-Za-z0-9._-]{1,180}\.html", split.path
        ):
            return _sign_public_url(value)
    return value


def _sanitize_public_report_data(
    data: Dict[str, Any],
    *,
    include_customer_media: bool = False,
) -> Dict[str, Any]:
    public = _strip_private_report_fields(data)
    agent_report = public.get("agent_report") if isinstance(public.get("agent_report"), dict) else {}
    scenario = str(agent_report.get("scenario") or "")
    agent_report["parsed"] = _public_parsed(agent_report.get("parsed") or {}, scenario)
    gallery = agent_report.get("media_gallery")
    if isinstance(gallery, dict) and not include_customer_media:
        for group in ("videos", "frames", "images"):
            for item in gallery.get(group) or []:
                if isinstance(item, dict):
                    item.pop("url", None)
                    item.pop("video_url", None)
        gallery["restricted_original_evidence"] = True
    return _refresh_signed_urls(_redact_minor_identifiers(public))


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
    public_videos = []
    for item in case.get("videos") or []:
        video = {
            key: item.get(key)
            for key in (
                "video_index",
                "duration_seconds",
                "native_fps",
                "fps_requested",
                "sampled_frames",
                "sampling_strategy",
                "timeline_coverage_ratio",
            )
            if item.get(key) not in (None, "")
        }
        duration = float(item.get("duration_seconds") or 0)
        if duration > 0 and item.get("sampled_frames") not in (None, ""):
            video["effective_sample_fps"] = round(float(item["sampled_frames"]) / duration, 4)
        public_videos.append(video)
    structured = case.get("structured_business_context") or {}
    business_scenario = (
        str(structured.get("business_scenario") or "").strip()
        if isinstance(structured, dict)
        else ""
    ) or str(case.get("scenario") or "")
    frontdesk = structured.get("frontdesk_evidence_package") if isinstance(structured, dict) else {}
    source = frontdesk if isinstance(frontdesk, dict) and frontdesk.get("fulfillment_baseline") else structured
    fulfillment = source.get("fulfillment_baseline") if isinstance(source, dict) else {}
    fulfillment = fulfillment if isinstance(fulfillment, dict) else {}
    expected_items = []
    for item in fulfillment.get("expected_items") or []:
        if not isinstance(item, dict):
            continue
        expected_items.append({
            key: item.get(key)
            for key in ("item_ref", "sku", "product_name", "specification", "expected_quantity", "item_type")
            if item.get(key) not in (None, "")
        })
    logistics = source.get("logistics") if isinstance(source, dict) else {}
    if not logistics and isinstance(structured, dict):
        logistics = structured.get("logistics")
    logistics = logistics if isinstance(logistics, dict) else {}
    order_baseline = {
        "baseline_version": fulfillment.get("baseline_version") or "",
        "expected_items": expected_items[:100],
        "selection_rules_complete": fulfillment.get("selection_rules_complete") is True,
        "benefit_rules_complete": fulfillment.get("benefit_rules_complete") is True,
        "package_mapping_status": fulfillment.get("package_mapping_status") or "",
        "carrier": logistics.get("carrier") or "",
        "tracking_ref": logistics.get("tracking_ref") or "",
    }
    evidence_package = {
        "videos": public_videos,
        "frames_sent": len(case.get("frames") or []),
        "supplemental_images_sent": len(case.get("supplemental_images") or []),
        "official_reference_images_sent": len(case.get("official_reference_images") or []),
        "official_reference_status": case.get("official_reference_status") or {},
        "order_baseline": order_baseline,
        "video_deduplication": {
            key: int((case.get("video_deduplication") or {}).get(key) or 0)
            for key in ("submitted_count", "unique_count", "duplicate_count")
        },
    }
    parsed = _public_parsed(parsed, business_scenario)
    public_conclusion = _redact_minor_identifiers(public_conclusion)
    public_next_step = _redact_minor_identifiers(public_next_step)
    payload = {
        "case_id": case.get("case_id") or sample_dir.name,
        "scenario": business_scenario,
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
    registry_roots = (
        (ROOT.resolve(), PUBLIC_MEDIA_REGISTRY, ""),
        (WORKBENCH_DIR.resolve(), PUBLIC_WORKBENCH_MEDIA_REGISTRY, "workbench\n"),
        (RUNTIME_MEDIA_DIR.resolve(), PUBLIC_RUNTIME_MEDIA_REGISTRY, "runtime\n"),
    )
    for base, registry, namespace in registry_roots:
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            continue
        media_id = hmac.new(
            REPORT_SIGNING_SECRET,
            f"media\n{namespace}{rel}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]
        registry.register(media_id, rel)
        return _sign_public_url(f"/media-item/{media_id}")
    return ""


def _native_video_source(
    video: Path,
    proxy_dir: Optional[Path] = None,
    recommendation: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    mime_type = {
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }.get(video.suffix.lower(), "video/mp4")
    recommendation = recommendation or (
        video_proxy_recommendation(video) if proxy_dir else {"recommended": False}
    )
    if recommendation.get("recommended"):
        proxy = prepare_native_video_proxy(video, proxy_dir, NATIVE_INLINE_MEDIA_MAX_BYTES)
        if proxy.get("status") == "ready" and int(proxy.get("proxy_bytes") or 0) < video.stat().st_size:
            return {
                "video_index": 1,
                "api_path": str(proxy["path"]),
                "api_mime_type": str(proxy.get("mime_type") or "video/mp4"),
                "proxy": {**proxy, "recommendation": recommendation},
            }
        return None
    if video.stat().st_size <= NATIVE_INLINE_MEDIA_MAX_BYTES:
        return {"video_index": 1, "api_path": str(video), "api_mime_type": mime_type}
    configured_url = _configured_original_video_url(video, mime_type)
    if configured_url:
        return configured_url
    proxy = (
        prepare_native_video_proxy(video, proxy_dir, NATIVE_INLINE_MEDIA_MAX_BYTES)
        if proxy_dir and not recommendation.get("recommended")
        else {}
    )
    if proxy.get("status") == "ready":
        return {
            "video_index": 1,
            "api_path": str(proxy["path"]),
            "api_mime_type": str(proxy.get("mime_type") or "video/mp4"),
            "proxy": proxy,
        }
    return None


def _configured_original_video_url(
    video: Path,
    mime_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """把已配置的 HTTPS 媒体域名与签名路径组合成原片送审地址。"""
    public_base = os.getenv("VISUAL_WORKBENCH_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed_base = urlsplit(public_base)
    if (
        parsed_base.scheme != "https"
        or not parsed_base.netloc
        or parsed_base.username
        or parsed_base.password
        or parsed_base.query
        or parsed_base.fragment
        or parsed_base.path not in {"", "/"}
    ):
        public_base = ""
    if public_base:
        signed_path = _media_url(video)
        if signed_path.startswith("/media-item/"):
            return {
                "video_index": 1,
                "file_uri": f"{public_base}{signed_path}",
                "api_mime_type": mime_type or {
                    ".mov": "video/quicktime",
                    ".webm": "video/webm",
                    ".mkv": "video/x-matroska",
                }.get(video.suffix.lower(), "video/mp4"),
            }
    return None


@contextmanager
def _native_video_source_context(
    video: Path,
    proxy_dir: Optional[Path] = None,
    recommendation: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
):
    """视频优先通过受控 HTTPS URL 送审；隧道不可用时才回退内联。"""
    recommendation = recommendation or video_proxy_recommendation(video, policy=policy)
    if recommendation.get("recommended") and proxy_dir:
        with _native_video_proxy_source_context(video, proxy_dir) as proxy_source:
            if proxy_source:
                proxy_source["quality_recommendation"] = deepcopy(recommendation)
                yield proxy_source
                return
        yield None
        return

    if not recommendation.get("recommended"):
        direct = _native_video_source(video)
        if direct and direct.get("file_uri"):
            direct["transport"] = "configured_original_url"
            yield direct
            return
        if direct and direct.get("api_path"):
            direct["transport"] = "raw_original_inline"
            yield direct
            return
    else:
        direct = None

    configured_original = _configured_original_video_url(video)
    if configured_original:
        configured_original["transport"] = "configured_original_url"
        yield configured_original
        return

    tunnel_diagnostics: Dict[str, Any] = {}
    tunnel_enabled = str(
        os.getenv("VISUAL_REVIEW_EPHEMERAL_TUNNEL", "1") or "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    if tunnel_enabled:
        stack = ExitStack()
        try:
            tunnel = stack.enter_context(
                open_secure_media_tunnel(
                    video,
                    cloudflared_executable=(
                        os.getenv("CLOUDFLARED_PATH", "cloudflared") or "cloudflared"
                    ),
                    startup_timeout=60.0,
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            stack.close()
            tunnel_diagnostics = {
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }
        else:
            with stack:
                yield {
                    "video_index": 1,
                    "file_uri": tunnel.url,
                    "api_mime_type": {
                        ".mov": "video/quicktime",
                        ".webm": "video/webm",
                        ".mkv": "video/x-matroska",
                    }.get(video.suffix.lower(), "video/mp4"),
                    "transport": "ephemeral_original_url",
                    "tunnel": tunnel.diagnostics,
                }
            return

    fallback = direct or (
        _native_video_source(video, proxy_dir)
        if not recommendation.get("recommended")
        else None
    )
    if fallback:
        fallback["transport"] = (
            "full_duration_quality_proxy" if fallback.get("proxy") else "raw_original_inline"
        )
        if tunnel_diagnostics:
            fallback["tunnel"] = tunnel_diagnostics
    yield fallback


@contextmanager
def _prepared_folder_video_sources(videos: List[Path], proxy_dir: Path, policy: Optional[Dict[str, Any]] = None):
    native_videos: List[Dict[str, Any]] = []
    execution: List[Dict[str, Any]] = []
    technical_processing_incomplete = False
    try:
        with ExitStack() as stack:
            for index, video in enumerate(videos, start=1):
                recommendation = video_proxy_recommendation(video, policy=policy)
                reasons = [str(item) for item in recommendation.get("reasons") or [] if str(item)]
                source = stack.enter_context(_native_video_source_context(
                    video,
                    proxy_dir / f"video_{index:03d}",
                    recommendation=recommendation,
                    policy=policy,
                ))
                if not source:
                    technical_processing_incomplete = True
                    execution.append({
                        "video_index": index,
                        "submitted_source": "none",
                        "status": "proxy_failed",
                        "quality_reasons": reasons,
                        "error_type": "native_source_unavailable",
                    })
                    continue
                source = dict(source)
                source["video_index"] = index
                proxy = source.get("proxy") if isinstance(source.get("proxy"), dict) else {}
                source_metadata = recommendation.get("source_metadata") or {}
                duration_seconds = (
                    proxy.get("proxy_duration_seconds")
                    or source_metadata.get("duration_seconds")
                )
                if duration_seconds not in (None, ""):
                    source["duration_seconds"] = duration_seconds
                native_videos.append(source)
                execution.append({
                    "video_index": index,
                    "submitted_source": "quality_proxy" if proxy else "original",
                    "status": "ready" if proxy else "not_required",
                    "quality_reasons": reasons,
                    "delivery": "file_uri" if source.get("file_uri") else "inline_data",
                    **{
                        key: proxy[key]
                        for key in (
                            "codec_profile", "source_bytes", "proxy_bytes", "source_sha256",
                            "proxy_sha256", "cache_hit", "source_width", "source_height",
                            "proxy_width", "proxy_height", "source_fps", "proxy_fps",
                            "source_bitrate_bps", "proxy_bitrate_bps",
                            "source_duration_seconds", "proxy_duration_seconds",
                        )
                        if proxy.get(key) not in (None, "")
                    },
                    **({
                        "proxy_codec": proxy.get("codec_profile"),
                        "submitted_width": proxy.get("proxy_width"),
                        "submitted_height": proxy.get("proxy_height"),
                        "submitted_fps": proxy.get("proxy_fps"),
                        "submitted_bitrate": proxy.get("proxy_bitrate_bps"),
                        "submitted_duration_seconds": proxy.get("proxy_duration_seconds"),
                    } if proxy else {}),
                })
            yield {
                "videos": [] if technical_processing_incomplete else list(videos),
                "native_videos": [] if technical_processing_incomplete else native_videos,
                "execution": execution,
                "requires_complete_frame_fallback": False,
                "technical_processing_incomplete": technical_processing_incomplete,
            }
    finally:
        shutil.rmtree(proxy_dir, ignore_errors=True)


def _apply_video_review_order(case: Dict[str, Any], ordered_videos: List[Path]) -> None:
    rows = [item for item in case.get("videos") or [] if isinstance(item, dict)]
    if len(rows) < 2:
        return
    rank = {video.name.lower(): index for index, video in enumerate(ordered_videos)}
    original_position = {id(row): index for index, row in enumerate(rows)}
    ordered_rows = sorted(
        rows,
        key=lambda row: rank.get(
            Path(str(row.get("file") or "")).name.lower(),
            len(rank) + original_position[id(row)],
        ),
    )
    old_to_new = {
        int(row.get("video_index") or index): index
        for index, row in enumerate(ordered_rows, start=1)
    }
    for index, row in enumerate(ordered_rows, start=1):
        row["video_index"] = index
    frames = [item for item in case.get("frames") or [] if isinstance(item, dict)]
    for frame in frames:
        frame["video_index"] = old_to_new.get(
            int(frame.get("video_index") or 0),
            int(frame.get("video_index") or 0),
        )
    frames.sort(key=lambda frame: (
        int(frame.get("video_index") or 0),
        int(frame.get("global_frame_index") or 0),
    ))
    for index, frame in enumerate(frames, start=1):
        frame["global_frame_index"] = index
    case["videos"] = ordered_rows
    case["frames"] = frames


def _native_transport_requires_proxy_retry(result: Dict[str, Any]) -> bool:
    if str(result.get("status") or "").lower() != "failed":
        return False
    if result.get("status_code") in {413, 415}:
        return True
    error = " ".join(
        str(result.get(key) or "")
        for key in ("error", "error_message", "detail")
    ).lower()
    if any(
        marker in error
        for marker in ("response schema", "response_schema", "json schema", "structured output")
    ):
        return False
    return any(
        marker in error
        for marker in (
            "unable to download",
            "failed to download",
            "unable to fetch",
            "failed to fetch",
            "file uri",
            "file_uri",
            "video codec",
            "decode video",
            "video decode",
            "unsupported video",
            "media too large",
            "payload too large",
            "maximum file size",
            "content length",
            "content-type",
            "mime type",
            "100 mb",
        )
    )


@contextmanager
def _native_video_proxy_source_context(video: Path, proxy_dir: Path):
    proxy = prepare_native_video_proxy(
        video,
        proxy_dir,
        NATIVE_URL_MEDIA_MAX_BYTES,
        cache_dir=RUNTIME_MEDIA_DIR / "native_video_proxy_cache",
    )
    if proxy.get("status") != "ready":
        yield None
        return
    proxy_path = Path(str(proxy["path"]))
    mime_type = str(proxy.get("mime_type") or "video/mp4")
    if proxy_path.stat().st_size <= NATIVE_INLINE_MEDIA_MAX_BYTES:
        yield {
            "video_index": 1,
            "api_path": str(proxy_path),
            "api_mime_type": mime_type,
            "transport": "full_duration_quality_proxy",
            "proxy": proxy,
        }
        return
    tunnel_enabled = str(
        os.getenv("VISUAL_REVIEW_EPHEMERAL_TUNNEL", "1") or "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    tunnel_diagnostics: Dict[str, Any] = {}
    if tunnel_enabled:
        for tunnel_attempt in range(1, 2):
            stack = ExitStack()
            try:
                tunnel = stack.enter_context(
                    open_secure_media_tunnel(
                        proxy_path,
                        cloudflared_executable=(
                            os.getenv("CLOUDFLARED_PATH", "cloudflared") or "cloudflared"
                        ),
                        startup_timeout=60.0,
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                stack.close()
                LOGGER.warning(
                    "quality proxy tunnel unavailable (%s/1): %s",
                    tunnel_attempt,
                    type(exc).__name__,
                )
                tunnel_diagnostics = {
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                    "attempts": tunnel_attempt,
                }
                continue
            with stack:
                yield {
                    "video_index": 1,
                    "file_uri": tunnel.url,
                    "api_mime_type": mime_type,
                    "transport": "ephemeral_proxy_url",
                    "proxy": proxy,
                    "tunnel": tunnel.diagnostics,
                }
            return
    if proxy_path.stat().st_size > NATIVE_INLINE_MEDIA_MAX_BYTES:
        yield None
        return
    source = {
        "video_index": 1,
        "api_path": str(proxy_path),
        "api_mime_type": mime_type,
        "transport": "full_duration_quality_proxy",
        "proxy": proxy,
    }
    if tunnel_diagnostics:
        source["tunnel"] = tunnel_diagnostics
    yield source


def _media_gallery(case: Dict[str, Any], sample_dir: Optional[Path] = None) -> Dict[str, Any]:
    def public_media_item(item: Dict[str, Any], url: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        allowed = {
            "video_index",
            "global_frame_index",
            "frame_index",
            "image_index",
            "timestamp",
            "timestamp_seconds",
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
        preview_paths = case.get("_browser_preview_paths") or {}
        preview_path = preview_paths.get(int(item.get("video_index") or 0))
        video_path = Path(str(preview_path)).resolve() if preview_path else (
            (sample_dir / item.get("file")).resolve() if sample_dir and item.get("file") else None
        )
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
    official_references = [
        public_media_item(
            item,
            _media_url(item.get("api_path")),
            {
                "reference_index": item.get("reference_index"),
                "reference_id": item.get("reference_id"),
                "item_ref": item.get("item_ref"),
                "sku": item.get("sku"),
                "product_name": item.get("product_name"),
                "evidence_role": "official_product_reference",
            },
        )
        for item in case.get("official_reference_images") or []
    ]
    return {"videos": videos, "frames": frames, "images": images, "official_references": official_references}


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
    if (
        parsed.get("processing_status") == "technical_processing_incomplete"
        or parsed.get("system_action") == "system_retry"
    ):
        return False
    if not parsed.get("predicted_label"):
        return False
    return parsed.get("confidence") not in (None, "")


def _model_key_from_identifier(identifier: str) -> Optional[str]:
    normalized = str(identifier or "").strip().lower()
    for key, config in MODEL_CONFIGS.items():
        aliases = {
            str(key).lower(),
            str(config.get("model") or "").lower(),
            str(config.get("display_model") or "").lower(),
        }
        if normalized in aliases:
            return key
    return None


def _configured_model_keys(requested_model_key: str, tenant_id: str = "mitako") -> List[str]:
    return runtime_model_keys(tenant_id, requested_model_key)


def _native_perception_enabled(config: Dict[str, Any], scenario: str) -> bool:
    return bool(config.get("native_perception_pipeline")) and scenario == "product_damage"


def _new_review_deadline() -> float:
    try:
        seconds = int(os.getenv("REVIEW_CASE_DEADLINE_SECONDS", "300") or 300)
    except ValueError:
        seconds = 300
    return time.monotonic() + max(60, min(seconds, 900))


def _call_model_chunked_with_fallback(
    requested_model_key: str,
    case: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    tenant_id = str(case.get("_rule_tenant_id") or case.get("tenant_id") or "mitako")
    model_keys = _configured_model_keys(requested_model_key, tenant_id)
    if not model_keys:
        return {"status": "skipped", "error": "unknown_review_model", "cost_status": "not_incurred"}
    wall_started = time.time()
    attempts: List[Dict[str, Any]] = []
    prior_unknown_calls = 0
    prior_model_calls = 0
    prior_model_latency = 0.0
    channel_route_attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {"status": "skipped", "error": "no_available_review_model"}
    for route_index, model_key in enumerate(model_keys, start=1):
        config = MODEL_CONFIGS[model_key]
        current = call_model_chunked(
            config,
            case,
            timeout=timeout,
            retries=retries,
            deadline_at=deadline_at,
        )
        current_chunking = current.get("chunking") if isinstance(current.get("chunking"), dict) else {}
        current_calls = _clamp_int(current_chunking.get("total_model_calls"), 0, 1_000_000, 0)
        current_unknown = _clamp_int(current.get("unknown_cost_calls"), 0, 1_000_000, 0)
        channel_route_attempts.extend(
            item for item in current.get("_channel_route_attempts") or [] if isinstance(item, dict)
        )
        attempts.append({
            "route_index": route_index,
            "status": str(current.get("status") or "failed"),
            "status_code": current.get("status_code"),
            "error_type": str(current.get("error_type") or ""),
            "model_calls": current_calls,
            "decision": "selected" if current.get("status") == "success" else "pending",
        })
        if current.get("status") == "success":
            result = dict(current)
            chunking = dict(current_chunking)
            chunking["total_model_calls"] = current_calls + prior_model_calls
            result["chunking"] = chunking
            result["unknown_cost_calls"] = _clamp_int(
                result.get("unknown_cost_calls"), 0, 1_000_000, 0
            ) + prior_unknown_calls
            if prior_unknown_calls:
                result["cost_status"] = "partial_unknown"
            result["model_latency_seconds_sum"] = round(
                _clamp_float(result.get("model_latency_seconds_sum"), 0.0, 1_000_000.0, 0.0)
                + prior_model_latency,
                2,
            )
            result["latency_seconds"] = round(time.time() - wall_started, 2)
            result["route_fallback_count"] = max(0, len(attempts) - 1)
            result["route_attempts"] = attempts
            result["_channel_route_attempts"] = channel_route_attempts
            return result
        last_result = current
        prior_model_calls += current_calls
        prior_unknown_calls += current_unknown
        prior_model_latency += _clamp_float(
            current.get("model_latency_seconds_sum") or current.get("latency_seconds"),
            0.0,
            1_000_000.0,
            0.0,
        )
        retryable = is_retryable_failure(current)
        provider_unavailable = current.get("status") == "skipped" or current.get("status_code") in {401, 403}
        can_fallback = route_index < len(model_keys) and (retryable or provider_unavailable)
        attempts[-1]["decision"] = (
            "fallback_retryable" if can_fallback and retryable
            else "fallback_provider_unavailable" if can_fallback
            else "exhausted" if retryable
            else "stop_non_retryable"
        )
        if not can_fallback:
            break
    result = dict(last_result)
    chunking = dict(result.get("chunking") or {})
    chunking["total_model_calls"] = prior_model_calls
    result["chunking"] = chunking
    result["unknown_cost_calls"] = prior_unknown_calls
    result["cost_status"] = "unknown" if prior_unknown_calls else str(result.get("cost_status") or "not_incurred")
    result["model_latency_seconds_sum"] = round(prior_model_latency, 2)
    result["latency_seconds"] = round(time.time() - wall_started, 2)
    result["route_fallback_count"] = max(0, len(attempts) - 1)
    result["route_attempts"] = attempts
    result["_channel_route_attempts"] = channel_route_attempts
    return result


def _internal_inference_estimate(result: Dict[str, Any]) -> Dict[str, Any]:
    """仅供受保护审核 API 和内部运维汇总，公开 HTML 不引用该对象。"""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = result.get("cost") if isinstance(result.get("cost"), dict) else {}
    chunking = result.get("chunking") if isinstance(result.get("chunking"), dict) else {}
    channels = chunking.get("channels") if isinstance(chunking.get("channels"), dict) else {}
    native_video = chunking.get("native_video") if isinstance(chunking.get("native_video"), dict) else {}
    degraded_passes: Dict[str, Any] = {}
    for output_name, source_name in (
        ("main_review", "main_review_pass"),
        ("object_continuity", "continuity_pass"),
        ("damage_causality", "damage_causality_pass"),
    ):
        pass_data = chunking.get(source_name) if isinstance(chunking.get(source_name), dict) else {}
        failures = pass_data.get("failures") if isinstance(pass_data.get("failures"), list) else []
        coverage_gaps = pass_data.get("coverage_gaps") if isinstance(pass_data.get("coverage_gaps"), list) else []
        if failures or coverage_gaps:
            degraded_passes[output_name] = {
                "status": str(pass_data.get("status") or "degraded"),
                "failures": [
                    {
                        key: item.get(key)
                        for key in ("chunk_index", "error", "latency_seconds", "cost_status")
                        if item.get(key) not in (None, "")
                    }
                    for item in failures
                    if isinstance(item, dict)
                ],
                "coverage_gaps": [
                    {
                        "chunk_index": item.get("chunk_index"),
                        "missing_target_frame_count": int(item.get("missing_target_frame_count") or 0),
                        "missing_target_frame_indices": item.get("missing_target_frame_indices") or [],
                        "reason": str(item.get("reason") or ""),
                        "assessment_status": str(item.get("assessment_status") or ""),
                    }
                    for item in coverage_gaps
                    if isinstance(item, dict)
                ],
            }
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "estimated_usd": round(float(cost.get("estimated_usd") or 0.0), 6),
        "cost_status": str(result.get("cost_status") or "unknown"),
        "unknown_cost_calls": int(result.get("unknown_cost_calls") or 0),
        "request_profile": {
            key: value
            for key, value in (result.get("request_profile") or {}).items()
            if key in {
                "provider", "model", "thinking_level", "media_resolution",
                "max_output_tokens", "native_video_count", "sampling_fps", "transport",
            }
        },
        "route_fallback_count": int(result.get("route_fallback_count") or 0),
        "route_attempts": result.get("route_attempts") if isinstance(result.get("route_attempts"), list) else [],
        "channel_route_attempts": [
            {
                key: item.get(key)
                for key in ("channel", "model", "status_code", "error_type", "decision")
                if item.get(key) not in (None, "")
            }
            for item in (
                result.get("_channel_route_attempts")
                if isinstance(result.get("_channel_route_attempts"), list)
                else []
            )
            if isinstance(item, dict)
        ],
        "total_frames": int(chunking.get("total_frames") or 0),
        "main_review_frames": int(chunking.get("main_review_frames") or 0),
        "document_detail_crop_count": int(chunking.get("document_detail_crop_count") or 0),
        "total_model_calls": int(chunking.get("total_model_calls") or 1),
        "segment_count": int(chunking.get("segment_count") or 1),
        "concurrency": chunking.get("concurrency") if isinstance(chunking.get("concurrency"), dict) else {},
        "channels": {
            key: {
                "model_calls": int((value or {}).get("model_calls") or 0),
                "repair_calls": int((value or {}).get("repair_calls") or 0),
                "total_tokens": int((value or {}).get("total_tokens") or 0),
                "estimated_usd": round(float((value or {}).get("estimated_usd") or 0.0), 6),
            }
            for key, value in channels.items()
            if isinstance(value, dict)
        },
        "native_video": {
            key: native_video.get(key)
            for key in (
                "status",
                "technical_status",
                "status_code",
                "error_type",
                "error_summary",
                "dimension_gaps",
                "opening_start_verification_status",
                "transport",
                "proxy_status",
                "proxy_bytes",
                "proxy_elapsed_seconds",
            )
            if native_video.get(key) not in (None, "", [], {})
        },
        "degraded_passes": degraded_passes,
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


def _incurred_model_call(result: Any) -> int:
    if not isinstance(result, dict) or not result:
        return 0
    return 0 if str(result.get("status") or "").lower() in {"skipped", "not_run", "not_incurred"} else 1


def _native_model_call_count(result: Any) -> int:
    if not isinstance(result, dict):
        return 0
    try:
        physical_calls = max(0, int(result.get("model_http_request_count") or 0))
    except (TypeError, ValueError, OverflowError):
        physical_calls = 0
    if physical_calls:
        return physical_calls
    pipeline = result.get("perception_pipeline")
    if isinstance(pipeline, dict):
        try:
            model_calls = max(0, int(pipeline.get("model_calls") or 0))
        except (TypeError, ValueError, OverflowError):
            model_calls = 0
        if model_calls:
            return model_calls
    return _incurred_model_call(result)


def _merge_preflight_billing(
    result: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    merged = merge_model_billing(result, [preflight])
    calls = _native_model_call_count(preflight)
    chunking = dict(merged.get("chunking") or result.get("chunking") or {})
    chunking["total_model_calls"] = int(chunking.get("total_model_calls") or 0) + calls
    channels = dict(chunking.get("channels") or {})
    usage = preflight.get("usage") or {}
    channels["video_role_preflight"] = {
        "model_calls": calls,
        "total_tokens": int(usage.get("total_tokens") or 0),
        "estimated_usd": float((preflight.get("cost") or {}).get("estimated_usd") or 0),
    }
    chunking["channels"] = channels
    merged["chunking"] = chunking
    return merged


def _technical_processing_incomplete_result(
    core_reason: str,
    *,
    prior_result: Optional[Dict[str, Any]] = None,
    native_status: str = "not_run",
) -> Dict[str, Any]:
    """技术失败只安排系统重试，不把失败伪装成用户证据不足。"""
    result: Dict[str, Any] = {
        "status": "success",
        "cost_status": "not_incurred",
        "parsed": {
            "processing_status": "technical_processing_incomplete",
            "system_action": "system_retry",
            "predicted_label": "review",
            "system_yes_no": "REVIEW",
            "confidence": None,
            "overall_audit": {
                "conclusion": "本轮未能在保真边界内完成视频送审，暂不形成事实结论。",
                "confidence": None,
                "core_reason": core_reason,
                "business_follow_up_suggestion": "由系统受控重试，不要求用户重复提交材料。",
            },
        },
        "chunking": {
            "total_model_calls": 0,
            "main_review_frames": 0,
            "channels": {},
            "native_video": {
                "status": "technical_processing_incomplete",
                "technical_status": native_status,
                "dimension_gaps": [],
            },
        },
    }
    if not prior_result:
        return result
    result = merge_model_billing(result, [prior_result])
    calls = _native_model_call_count(prior_result)
    chunking = dict(result.get("chunking") or {})
    chunking["total_model_calls"] = calls
    native_video = dict(chunking.get("native_video") or {})
    native_video.update({
        "technical_status": str(prior_result.get("status") or native_status),
        "status_code": prior_result.get("status_code"),
        "error_type": prior_result.get("error_type"),
        "error_summary": sanitize_error_text(prior_result.get("error"), limit=400),
    })
    chunking["native_video"] = native_video
    result["chunking"] = chunking
    return result


def _complete_frame_fallback_args(args: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        fps=1.0,
        sampling_mode="dense",
        max_frames_per_video=1800,
        api_frame_limit=24,
        probe_seconds=args.probe_seconds,
        frame_width=1920,
        supplemental_image_limit=args.supplemental_image_limit,
    )


def _one_fps_frame_fallback_enabled() -> bool:
    return str(
        os.getenv("REVIEW_ENABLE_ONE_FPS_FRAME_FALLBACK", "false") or "false"
    ).strip().lower() in {"1", "true", "yes", "on"}


def _opening_role_preflight_enabled() -> bool:
    """延后视频的补审闭环完成前，候选预检只允许后台受控实验。"""
    return str(
        os.getenv("REVIEW_ENABLE_OPENING_ROLE_PREFLIGHT", "false") or "false"
    ).strip().lower() in {"1", "true", "yes", "on"}


def _native_success_requires_frame_fallback(
    dimension_gaps: List[str],
    parsed: Optional[Dict[str, Any]] = None,
    case: Optional[Dict[str, Any]] = None,
    scenario: str = "",
) -> bool:
    """仅对单个关键事实漏引启用一次高成本 1 FPS 补审。"""
    parsed = parsed if isinstance(parsed, dict) else {}
    case = case if isinstance(case, dict) else {}
    structured = case.get("structured_business_context") or {}
    business_scenario = str(structured.get("business_scenario") or scenario or "")
    if business_scenario != "missing_item":
        return False
    reconciliation = parsed.get("fulfillment_reconciliation") or {}
    if (
        not isinstance(reconciliation, dict)
        or reconciliation.get("evidence_route") != "insufficient"
        or reconciliation.get("resolution_basis") in {
            "warehouse_verification", "trusted_expected_item_resolution"
        }
    ):
        return False
    frontdesk = structured.get("frontdesk_evidence_package") or {}
    baseline = frontdesk.get("fulfillment_baseline") or structured.get("fulfillment_baseline") or {}
    expected_packages = {
        str(item.get("package_ref") or "").strip()
        for item in baseline.get("packages") or []
        if isinstance(item, dict) and str(item.get("package_ref") or "").strip()
    }
    observations = {
        str(item.get("package_ref") or "").strip(): item
        for item in reconciliation.get("package_observations") or []
        if isinstance(item, dict) and str(item.get("package_ref") or "").strip()
    }
    if not expected_packages or not expected_packages.issubset(observations):
        return False
    required_fields = (
        "sealed_start", "waybill_visible", "waybill_matches_order",
        "single_take_continuity", "opening_complete", "all_contents_laid_out",
    )
    missing_video_refs = []
    for package_ref in expected_packages:
        observation = observations[package_ref]
        if not all(observation.get(field) is True for field in required_fields):
            return False
        evidenced = {
            str(ref.get("field") or "")
            for ref in observation.get("evidence_refs") or []
            if isinstance(ref, dict)
            and str(ref.get("asset_ref") or "").startswith(("native_video_", "video_"))
            and str(ref.get("timestamp") or "").strip()
        }
        missing_video_refs.extend(
            (package_ref, field) for field in required_fields if field not in evidenced
        )
    return len(missing_video_refs) == 1


def _run_review(
    video: Path,
    scenario: str,
    fps: float,
    max_frames: int,
    api_frame_limit: int,
    probe_seconds: int,
    review_model: str,
    evidence_context: Optional[Dict[str, Any]] = None,
    include_html_report: bool = True,
    include_internal_metrics: bool = False,
    defer_postprocess: bool = False,
    requested_model_key: str = "auto",
    sampling_mode_override: str = "",
    rule_tenant_id: str = "mitako",
    selected_videos: Optional[List[Path]] = None,
    native_video_sources: Optional[List[Dict[str, Any]]] = None,
    preflight_result: Optional[Dict[str, Any]] = None,
    preflight_billing: Optional[Dict[str, Any]] = None,
    policy_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    deadline_at = _new_review_deadline()
    profile = REVIEW_MODEL_PROFILES.get(review_model) or REVIEW_MODEL_PROFILES["standard"]
    load_visual_env()
    started = time.time()
    log_visual_event(
        LOGGER,
        "visual_review_subprocess_start",
        source="single_review",
        scenario=scenario,
        review_model=review_model,
    )
    policy = dict(policy_snapshot or get_active_policy(rule_tenant_id))
    effective_fps = fps
    effective_max_frames = max_frames
    if review_model == "fast":
        effective_fps = min(fps, 0.5)
        effective_max_frames = min(max_frames, int(profile["default_max_frames"]))
    elif review_model == "standard":
        effective_max_frames = min(max_frames, int(profile["default_max_frames"]))
    elif review_model == "backup":
        effective_fps = max(fps, 2.0)
        effective_max_frames = max(max_frames, int(profile["default_max_frames"]))
    effective_sampling_mode = profile["sampling_mode"]
    if sampling_mode_override in {"adaptive", "dense"}:
        effective_fps = fps
        effective_max_frames = max_frames
        effective_sampling_mode = sampling_mode_override
    args = SimpleNamespace(
        fps=effective_fps,
        sampling_mode=effective_sampling_mode,
        max_frames_per_video=effective_max_frames,
        api_frame_limit=api_frame_limit,
        probe_seconds=float(probe_seconds),
        frame_width=960,
        supplemental_image_limit=MAX_SUPPLEMENTAL_IMAGES,
    )
    run_dir = RUNTIME_MEDIA_DIR / "visual_review_workbench" / f"single_{video.parent.name}_{time.time_ns()}"
    frozen_rule_snapshot: Optional[Dict[str, Any]] = None

    def prepared_case(
        native_video: Optional[Dict[str, Any]] = None,
        *,
        bundle_args: Optional[SimpleNamespace] = None,
    ) -> Dict[str, Any]:
        nonlocal frozen_rule_snapshot
        try:
            native_options: Dict[str, Any] = {}
            if native_video:
                sources = native_video.get("sources")
                if isinstance(sources, list):
                    native_options["native_videos"] = sources
                else:
                    native_options["native_video"] = native_video
            if selected_videos is not None:
                native_options["selected_videos"] = selected_videos
            current = load_case_bundle(
                video.parent,
                bundle_args or args,
                run_dir,
                scenario_override=scenario,
                **native_options,
            )
            if selected_videos is not None:
                _apply_video_review_order(current, selected_videos)
        except SystemExit as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        current = apply_frontdesk_context(
            current,
            scenario,
            json.dumps(evidence_context or {}, ensure_ascii=False),
        )
        if frozen_rule_snapshot is None:
            freeze_rule_snapshot(current, rule_tenant_id)
            frozen_rule_snapshot = dict(current.get("_business_rule_snapshot") or {})
        else:
            current["_rule_tenant_id"] = rule_tenant_id
            current["_business_rule_snapshot"] = dict(frozen_rule_snapshot)
        current.setdefault("structured_business_context", {})["continuity_claim_identity"] = derive_claim_identity([], current)
        prepare_official_reference_images(current)
        return current

    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    model_keys = _configured_model_keys(requested_model_key, rule_tenant_id)
    primary_config = MODEL_CONFIGS[model_keys[0]] if model_keys else {}
    if primary_config.get("native_perception_pipeline"):
        if "REVIEW_MODEL_TIMEOUT_SECONDS" not in os.environ:
            model_timeout = int(primary_config.get("request_timeout_seconds") or model_timeout)
        if "REVIEW_CASE_DEADLINE_SECONDS" not in os.environ:
            deadline_at = time.monotonic() + int(
                primary_config.get("case_deadline_seconds") or 600
            )
    discovered_videos, _ = discover_case_videos(video.parent)
    selected_set = {item.resolve() for item in selected_videos or []}
    case_videos = (
        [item for item in discovered_videos if item.resolve() in selected_set]
        if selected_videos is not None
        else discovered_videos
    )
    supplied_native_sources = [
        dict(item) for item in native_video_sources or [] if isinstance(item, dict)
    ]
    native_bundle = None
    if supplied_native_sources:
        native_bundle = {
            "sources": supplied_native_sources,
            "transport": "multi_native",
            "file_uri": next(
                (str(item.get("file_uri")) for item in supplied_native_sources if item.get("file_uri")),
                "",
            ),
            "proxy": next(
                (dict(item["proxy"]) for item in supplied_native_sources if isinstance(item.get("proxy"), dict)),
                {},
            ),
        }
    native_context = nullcontext(native_bundle)
    native_recommendation: Dict[str, Any] = {}
    if (
        not supplied_native_sources
        and review_model != "backup"
        and scenario in {"video_unboxing", "wrong_item", "missing_item", "product_damage"}
        and primary_config.get("provider") == "gemini_native"
        and len(case_videos) == 1
        and case_videos[0].resolve() == video.resolve()
    ):
        native_recommendation = video_proxy_recommendation(video, policy=policy)
        native_context = _native_video_source_context(
            video,
            run_dir / "native_video_proxy",
            recommendation=native_recommendation,
            policy=policy,
        )

    def call_native_review(current_case: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if _native_perception_enabled(primary_config, scenario):
            return run_native_perception_pipeline(
                current_case,
                video,
                run_dir / "native_candidate_detail",
                lambda candidate_case: call_model(
                    primary_config,
                    candidate_case,
                    timeout=model_timeout,
                    retries=model_retries,
                    deadline_at=deadline_at,
                ),
                sampling_fps=primary_config.get("native_video_sampling_fps"),
            )
        return (
            _call_model_chunked_with_fallback(
                requested_model_key,
                current_case,
                timeout=model_timeout,
                retries=model_retries,
                deadline_at=deadline_at,
            ),
            current_case,
        )

    media_preparation_started = time.monotonic()
    with native_context as native_source:
        native_transport_unavailable = bool(
            native_recommendation.get("recommended") and not native_source
        )
        case = prepared_case(native_source)
        deadline_at += max(0.0, time.monotonic() - media_preparation_started)
        native_result: Dict[str, Any] = {}
        native_gaps: List[str] = []
        opening_verification: Dict[str, Any] = {}
        compliance_verification: Dict[str, Any] = {}
        if native_source:
            native_result, case = call_native_review(case)

    if (
        native_source
        and not native_source.get("sources")
        and _native_transport_requires_proxy_retry(native_result)
    ):
        original_result = native_result
        original_transport = str(native_source.get("transport") or "")
        proxy_preparation_started = time.monotonic()
        with _native_video_proxy_source_context(
            video,
            run_dir / "native_video_proxy_retry",
        ) as proxy_source:
            if proxy_source:
                retry_case = prepared_case(proxy_source)
                deadline_at += max(0.0, time.monotonic() - proxy_preparation_started)
                retry_result, retry_case = call_native_review(retry_case)
                native_result = merge_model_billing(retry_result, [original_result])
                native_result["native_transport_attempts"] = [
                    {
                        "transport": original_transport,
                        "status": original_result.get("status"),
                        "status_code": original_result.get("status_code"),
                        "error_type": original_result.get("error_type"),
                    },
                    {
                        "transport": proxy_source.get("transport"),
                        "status": retry_result.get("status"),
                        "status_code": retry_result.get("status_code"),
                        "error_type": retry_result.get("error_type"),
                    },
                ]
                case = retry_case
                native_source = dict(proxy_source)
    if native_source:
        native_gaps = native_dimension_gaps(native_result.get("parsed") or {}, scenario)
    native_success_needs_frames = (
        native_source
        and native_result.get("status") == "success"
        and (
            _one_fps_frame_fallback_enabled()
            or bool((policy or {}).get("one_fps_frame_fallback"))
        )
        and _native_success_requires_frame_fallback(
            native_gaps,
            native_result.get("parsed") or {},
            case,
            scenario,
        )
    )
    if native_transport_unavailable:
        result = _technical_processing_incomplete_result(
            "质量代理与受控原片 URL 均不可用。",
            native_status="not_run",
        )
    elif native_source and native_result.get("status") == "success" and not native_success_needs_frames:
        proxy = native_source.get("proxy") if isinstance(native_source.get("proxy"), dict) else {}
        opening_result = native_result.get("opening_start_verification") or opening_verification
        compliance_result = native_result.get("opening_compliance_verification") or compliance_verification
        perception_pipeline = (
            native_result.get("perception_pipeline")
            if isinstance(native_result.get("perception_pipeline"), dict)
            else {}
        )
        native_incurred = _native_model_call_count(native_result)
        opening_incurred = _incurred_model_call(opening_result)
        compliance_incurred = _incurred_model_call(compliance_result)
        perception_channels = (
            perception_pipeline.get("channels")
            if isinstance(perception_pipeline.get("channels"), dict)
            else {}
        )
        result = dict(native_result)
        result["chunking"] = {
            "total_model_calls": native_incurred + opening_incurred + compliance_incurred,
            "main_review_frames": 0,
            "channels": {
                "native_video": {
                    **(perception_channels.get("native_video") or {}),
                    "model_calls": native_incurred,
                    "model_images": len(case.get("native_videos") or [case.get("native_video")]) + len(case.get("frames") or []),
                },
                **{
                    key: value
                    for key, value in perception_channels.items()
                    if key != "native_video" and isinstance(value, dict)
                },
                "opening_start_verification": {"model_calls": opening_incurred, "model_images": len(case.get("frames") or [])},
                "opening_compliance_verification": {
                    "model_calls": compliance_incurred,
                    "model_images": len(case.get("frames") or []),
                },
            },
            "native_video": {
                "status": "completed" if not native_gaps else "completed_with_review_gaps",
                "technical_status": native_result.get("status"),
                "status_code": native_result.get("status_code"),
                "dimension_gaps": native_gaps,
                "opening_start_verification_status": (
                    (native_result.get("opening_start_verification") or {}).get("status") or "not_run"
                ),
                "transport": "file_uri" if native_source.get("file_uri") else "inline_data",
                "proxy_status": proxy.get("status"),
                "proxy_bytes": proxy.get("proxy_bytes"),
                "proxy_elapsed_seconds": proxy.get("elapsed_seconds"),
            },
        }
        result["model_latency_seconds_sum"] = round(
            float(result.get("model_latency_seconds_sum") or result.get("latency_seconds") or 0),
            2,
        )
    elif native_source and native_result.get("status") != "success":
        result = _technical_processing_incomplete_result(
            "原生视频模型请求未成功，未自动改用高成本全片抽帧。",
            prior_result=native_result,
            native_status=str(native_result.get("status") or "failed"),
        )
    else:
        if native_success_needs_frames:
            proxy = native_source.get("proxy") if isinstance(native_source.get("proxy"), dict) else {}
            frame_preparation_started = time.monotonic()
            case = prepared_case(bundle_args=_complete_frame_fallback_args(args))
            deadline_at += max(0.0, time.monotonic() - frame_preparation_started)
        result = _call_model_chunked_with_fallback(
            requested_model_key,
            case,
            timeout=model_timeout,
            retries=model_retries,
            deadline_at=deadline_at,
        )
        opening = (
            ((result.get("parsed") or {}).get("video_audit_conclusion") or {}).get(
                "opening_video_compliance"
            )
            or {}
        )
        validated_fields = set(opening.get("validated_fields") or [])
        opening_fields = (
            "sealed_start", "waybill_visible", "single_take_continuity",
            "issue_visible_in_continuous_opening",
        )
        needs_opening_verification = (
            scenario == "product_damage"
            and len(case_videos) > 1
            and result.get("status") == "success"
            and any(
                opening.get(field) is False and field not in validated_fields
                for field in opening_fields
            )
        )
        if needs_opening_verification:
            compliance_verification = call_opening_compliance_verification(
                primary_config,
                case,
                timeout=model_timeout,
                retries=model_retries,
                deadline_at=deadline_at,
            )
            result = merge_opening_compliance_verification(
                result,
                compliance_verification,
                case.get("frames") or [],
                scenario=scenario,
            )
            incurred = _incurred_model_call(compliance_verification)
            chunking = dict(result.get("chunking") or {})
            chunking["total_model_calls"] = int(chunking.get("total_model_calls") or 0) + incurred
            channels = dict(chunking.get("channels") or {})
            usage = compliance_verification.get("usage") or {}
            channels["opening_compliance_verification"] = {
                "model_calls": incurred,
                "total_tokens": int(usage.get("total_tokens") or 0),
                "estimated_usd": float(
                    (compliance_verification.get("cost") or {}).get("estimated_usd") or 0
                ),
            }
            chunking["channels"] = channels
            chunking["opening_compliance_verification_status"] = (
                compliance_verification.get("status") or "not_run"
            )
            result["chunking"] = chunking
        if native_success_needs_frames:
            if opening_verification:
                result = merge_opening_start_verification(
                    result,
                    opening_verification,
                    case.get("frames") or [],
                    scenario=scenario,
                    include_billing=False,
                )
            result = merge_model_billing(result, [native_result])
            chunking = dict(result.get("chunking") or {})
            opening_result = native_result.get("opening_start_verification") or opening_verification
            native_incurred = _native_model_call_count(native_result)
            opening_status = opening_result.get("status") if isinstance(opening_result, dict) else None
            opening_incurred = _incurred_model_call(opening_result)
            chunking["total_model_calls"] = int(chunking.get("total_model_calls") or 0) + native_incurred + opening_incurred
            chunking["native_video"] = {
                "status": "fallback_to_frames",
                "dimension_gaps": native_gaps,
                "technical_status": native_result.get("status"),
                "status_code": native_result.get("status_code"),
                "error_type": native_result.get("error_type"),
                "error_summary": sanitize_error_text(native_result.get("error"), limit=400),
                "opening_start_verification_status": opening_status or "not_run",
                "transport": "file_uri" if native_source.get("file_uri") else "inline_data",
                "proxy_status": proxy.get("status"),
                "proxy_bytes": proxy.get("proxy_bytes"),
                "proxy_elapsed_seconds": proxy.get("elapsed_seconds"),
            }
            result["chunking"] = chunking
    frame_fallback_used = bool(
        case_videos
        and not native_transport_unavailable
        and (
            native_success_needs_frames
            or not native_source
        )
    )
    executed_frame_fps = float(effective_fps)
    if preflight_billing:
        result = _merge_preflight_billing(result, preflight_billing)
    if preflight_result:
        case.setdefault("structured_business_context", {})["video_role_preflight"] = deepcopy(
            preflight_result
        )
    preview_paths = {
        int(source.get("video_index") or index): str((source.get("proxy") or {}).get("path") or "")
        for index, source in enumerate(
            (native_source or {}).get("sources") or [native_source or {}],
            start=1,
        )
        if str((source.get("proxy") or {}).get("path") or "")
        and Path(str((source.get("proxy") or {}).get("path") or "")).is_file()
    }
    if preview_paths:
        case["_browser_preview_paths"] = preview_paths
    case["media_preflight_execution"] = build_media_preflight_execution(
        native_source=native_source,
        native_status=str(native_result.get("status") or "not_run"),
        native_sampling_fps=float(primary_config.get("native_video_sampling_fps") or 1.0),
        frame_fallback_used=frame_fallback_used,
        sampled_frame_count=len(case.get("frames") or []),
        supplemental_image_count=len(case.get("supplemental_images") or []),
        frame_sampling_fps=executed_frame_fps,
        image_execution=case.get("_media_preflight_image_execution") or [],
    )
    if native_transport_unavailable:
        case["media_preflight_execution"]["video"] = {
            "submitted_source": "none",
            "native_review_status": "technical_processing_incomplete",
            "quality_reasons": [
                str(item)
                for item in native_recommendation.get("reasons") or []
                if str(item)
            ],
            "proxy_status": "failed",
        }
    review = _agent_report_response(
        case,
        video.parent,
        result,
        "agent_single",
        profile["label"],
        include_internal_metrics=include_internal_metrics,
        include_html_report=include_html_report,
        defer_postprocess=defer_postprocess,
    )
    review["sampling"] = {
        "profile": review_model,
        "label": profile["label"],
        "sampling_mode": case.get("sampling_mode") or effective_sampling_mode,
        "fps": executed_frame_fps,
        "sampled_frames": len(case.get("frames") or []),
        "model_segments": ((review.get("agent_report") or {}).get("inference_estimate") or {}).get("segment_count"),
        "frames_per_segment": api_frame_limit,
    }
    review["media_preflight_execution"] = case["media_preflight_execution"]
    if native_source and native_result.get("status") == "success":
        review["sampling"]["sampling_mode"] = (
            "native_then_frame_fallback" if native_success_needs_frames else "native_video"
        )
    log_visual_event(
        LOGGER,
        "visual_review_subprocess_finished",
        source="single_review",
        scenario=scenario,
        review_model=review_model,
        status=(result.get("status") or "unknown"),
        review_ok=(review.get("summary") or {}).get("review_status") == "completed",
        frame_count=len(case.get("frames") or []),
        supplemental_image_count=len(case.get("supplemental_images") or []),
        latency_seconds=round(time.time() - started, 2),
    )
    return {"ok": (review.get("summary") or {}).get("review_status") == "completed", **review}


def _agent_report_response(
    case: Dict[str, Any],
    sample_dir: Path,
    result: Dict[str, Any],
    report_stem: str,
    review_profile_label: str = "标准视觉复核",
    include_internal_metrics: bool = False,
    include_html_report: bool = True,
    defer_postprocess: bool = False,
) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    structured_ok = _structured_review_ok(parsed)
    ok = result.get("status") == "success" and structured_ok
    quality = score_result(result)
    failure = {} if ok else _public_failure_reason(result, structured_ok)
    public_conclusion = _safe_agent_conclusion(parsed, case["scenario_label"]) if ok else f"审核未完成：{failure.get('message')}"
    public_next_step = _safe_agent_next_step((parsed.get("overall_audit") or {}).get("business_follow_up_suggestion") or parsed.get("next_step")) if ok else failure.get("operator_hint", "请VIP客服结合订单、售后规则和原始素材处理。")
    if case.get("scenario") == "minor_material":
        public_conclusion = _redact_minor_identifiers(public_conclusion)
        public_next_step = _redact_minor_identifiers(public_next_step)
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
    agent_report["parsed"] = parsed
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
            "needs_human_review": bool(parsed.get("human_required")),
            "review_status": "completed" if ok else "failed",
        },
        "conclusion": public_conclusion,
        "agent_report": agent_report,
        "media_warnings": case.get("rejected_videos") or [],
        "media_preflight_execution": case.get("media_preflight_execution") or {},
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
    structured = case.get("structured_business_context") or {}
    frontdesk = structured.get("frontdesk_evidence_package") or {}
    business_scenario = structured.get("business_scenario") or {
        "video_unboxing": "wrong_item",
        "product_damage": "product_damage",
        "minor_material": "minor_refund",
    }.get(case.get("scenario"), case.get("scenario") or "")
    metadata = {
        "scenario": business_scenario,
        "customer_claim": case.get("customer_claim") or "",
        "order_items": structured.get("order_items") or frontdesk.get("order_item") or [],
        "product_master_data": structured.get("product_master_data") or frontdesk.get("product_master_data") or {},
        "fulfillment_baseline": structured.get("fulfillment_baseline") or frontdesk.get("fulfillment_baseline") or {},
        "logistics": structured.get("logistics") or frontdesk.get("logistics") or {},
        "evidence_coverage": structured.get("evidence_coverage") or frontdesk.get("evidence_coverage") or {},
        "claim_scope": structured.get("claim_scope") or frontdesk.get("claim_scope") or {},
        "sop_context": structured.get("sop_context") or frontdesk.get("sop_context") or {},
        "review_routing_policy": structured.get("review_routing_policy") or {},
        "minor_refund_policy": structured.get("minor_refund_policy") or {},
        "decision_policy": (
            {
                "mode": "classification_recommendation",
                "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
            }
            if business_scenario == "product_damage"
            else {}
        ),
    }
    review_assets = [
        {"mime_type": "video/mp4"}
        for _ in case.get("videos") or []
    ] + [
        {"mime_type": "image/jpeg"}
        for _ in case.get("supplemental_images") or []
    ]
    raw_brief = {
        "conclusion": public_conclusion,
        "confidence": data["summary"].get("confidence"),
        "system_yes_no": parsed.get("system_yes_no"),
        "next_step": public_next_step,
    }
    media_forensics = None
    if not defer_postprocess:
        forensic_assets = [
            {
                "asset_id": f"video-{index}",
                "original_name": Path(str(item.get("file") or "")).name,
                "stored_name": Path(str(item.get("file") or "")).name,
            }
            for index, item in enumerate(case.get("videos") or [], start=1)
            if Path(str(item.get("file") or "")).name
        ]
        media_forensics = inspect_job_media(sample_dir, forensic_assets)
        normalized = postprocess_review(
            {
                "tenant_id": str(case.get("_rule_tenant_id") or "mitako"),
                "scenario": business_scenario,
                "metadata": metadata,
                "assets": review_assets,
            },
            {
                "summary": data["summary"],
                "agent_report": data["agent_report"],
                "agent_brief": raw_brief,
                "diagnostics": data.get("diagnostics") or {},
            },
            media_forensics=media_forensics,
            succeeded=ok,
        )
        data["summary"] = normalized["summary"]
        data["agent_report"] = normalized["agent_report"]
        material_readiness = normalized.get("material_readiness")
        if isinstance(material_readiness, dict):
            data["material_readiness"] = material_readiness
            data["agent_report"].setdefault("parsed", {})["material_readiness"] = material_readiness
        else:
            data.pop("material_readiness", None)
        advisory_assessment = normalized.get("advisory_assessment")
        if isinstance(advisory_assessment, dict):
            data["advisory_assessment"] = advisory_assessment
        else:
            data.pop("advisory_assessment", None)
        raw_brief = normalized["agent_brief"]
        data["conclusion"] = raw_brief.get("conclusion") or data["conclusion"]
        public_brief = data["agent_report"].setdefault("public_brief", {})
        public_brief["conclusion"] = data["conclusion"]
        resolved_next_step = raw_brief.get("next_step") or public_brief.get("next_step")
        if resolved_next_step:
            public_brief["next_step"] = resolved_next_step
        else:
            public_brief.pop("next_step", None)
        data["media_forensics"] = media_forensics
    public_data = _sanitize_public_report_data(data)
    data = _sanitize_public_report_data(data, include_customer_media=True)
    if include_html_report:
        ALLOWED_REPORTS[report_name] = public_data
        PUBLIC_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        (PUBLIC_SUMMARY_DIR / _report_data_name(report_name)).write_text(json.dumps(public_data, ensure_ascii=False, indent=2), encoding="utf-8")
        report = {
            "requested": True,
            "status": "ready",
            "html_url": _sign_public_url("/reports/" + quote(report_name, safe="")),
        }
    else:
        report = {"requested": False, "status": "not_requested", "html_url": None}
    response = {
        "review_label": data["review_label"],
        "summary": data["summary"],
        "frame_strategy": (
            f"{len(case.get('videos') or [])} 个视频合并为同一证据包，送审 {len(case.get('frames') or [])} 帧，补充图片 {len(case.get('supplemental_images') or [])} 张。"
            + (f"另隔离 {len(case.get('rejected_videos') or [])} 个无法解码的视频。" if case.get("rejected_videos") else "")
        ),
        "report": report,
        "agent_report": data.get("agent_report") or {},
        "media_warnings": data.get("media_warnings") or [],
        "media_preflight_execution": data.get("media_preflight_execution") or {},
        "material_readiness": data.get("material_readiness") or {},
        "agent_brief": raw_brief,
    }
    if media_forensics is not None:
        response["media_forensics"] = media_forensics
    if data.get("advisory_assessment"):
        response["advisory_assessment"] = data["advisory_assessment"]
    if include_internal_metrics:
        response["agent_report"]["inference_estimate"] = _internal_inference_estimate(result)
        response["agent_report"]["business_rule_version"] = public_snapshot_metadata(
            case.get("_business_rule_snapshot")
        )
    if data.get("diagnostics"):
        response["diagnostics"] = data["diagnostics"]
    return normalize_frame_strategy(response)


def _sample_base() -> Path:
    return (ROOT / "docs" / "三大审核场景的小量样本").resolve()


def _sample_scenarios() -> Dict[str, str]:
    path = _sample_base() / "sample_labels.json"
    try:
        samples = json.loads(path.read_text(encoding="utf-8-sig")).get("samples") or {}
    except Exception:
        samples = {}
    return {str(key): str(value.get("scenario") or "video_unboxing") for key, value in samples.items() if isinstance(value, dict)}


def _run_sample_agent_review(
    sample_id: str,
    scenario: str,
    model_key: str,
    business_scenario: str = "",
) -> Dict[str, Any]:
    sample_base = _sample_base()
    sample_dir = (sample_base / sample_id).resolve()
    if sample_base not in sample_dir.parents or not sample_dir.exists():
        raise HTTPException(status_code=404, detail="样本不存在")
    scenario, business_scenario = _normalize_review_scenario(scenario, business_scenario)
    if model_key != "auto" and model_key not in MODEL_CONFIGS:
        raise HTTPException(status_code=400, detail="未知审核模型")
    load_visual_env()
    started = time.time()
    log_visual_event(
        LOGGER,
        "visual_review_sample_start",
        sample_id=sample_id,
        scenario=scenario,
        model_key=model_key,
    )
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
    case = apply_frontdesk_context(
        case,
        scenario,
        json.dumps({"business_scenario": business_scenario}, ensure_ascii=False),
    )
    case["scenario"] = scenario
    case["scenario_label"] = {
        "product_damage": "商品有伤审核",
        "wrong_item": "发错货审核",
        "missing_item": "漏发货审核",
        "minor_refund": "未成年人资料审核",
    }.get(business_scenario, "开箱视频审核")
    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    result = _call_model_chunked_with_fallback(
        model_key,
        case,
        timeout=model_timeout,
        retries=model_retries,
        deadline_at=_new_review_deadline(),
    )
    review = _agent_report_response(case, sample_dir, result, f"agent_{sample_id}")
    log_visual_event(
        LOGGER,
        "visual_review_sample_finished",
        sample_id=sample_id,
        scenario=scenario,
        model_key=model_key,
        status=(result.get("status") or "unknown"),
        review_ok=(review.get("summary") or {}).get("review_status") == "completed",
        frame_count=len(case.get("frames") or []),
        supplemental_image_count=len(case.get("supplemental_images") or []),
        latency_seconds=round(time.time() - started, 2),
    )
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
            result = _run_with_case_slot(_run_sample_agent_review, sample_id, scenario, model_key)
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


def _run_folder_agent_review(folder_dir: Path, scenario: str, model_key: str, evidence_context: Dict[str, Any], sampling_mode: str, fps: float, max_frames: int, api_frame_limit: int, probe_seconds: int, include_internal_metrics: bool = False, include_html_report: bool = True, defer_postprocess: bool = False, rule_tenant_id: str = "mitako") -> Dict[str, Any]:
    if model_key != "auto" and model_key not in MODEL_CONFIGS:
        raise HTTPException(status_code=400, detail="未知审核模型")
    started = time.time()
    log_visual_event(
        LOGGER,
        "visual_review_folder_start",
        scenario=scenario,
        model_key=model_key,
        sampling_mode=sampling_mode,
        fps=fps,
        max_frames=max_frames,
        api_frame_limit=api_frame_limit,
        probe_seconds=probe_seconds,
    )

    def log_folder_finished(review: Dict[str, Any], status: str = "") -> None:
        summary = review.get("summary") or {}
        sampling = review.get("sampling") or {}
        frame_count = sampling.get("sampled_frames") or 0
        if not isinstance(frame_count, int):
            frame_count = 0
        log_visual_event(
            LOGGER,
            "visual_review_folder_finished",
            scenario=scenario,
            model_key=model_key,
            status=status or summary.get("review_status") or "unknown",
            review_ok=summary.get("review_status") == "completed",
            frame_count=frame_count,
            supplemental_image_count=int(sampling.get("supplemental_image_count") or 0),
            latency_seconds=round(time.time() - started, 2),
        )
    policy = get_active_policy(rule_tenant_id)
    fps = float(policy.get("native_sampling_fps") or fps)
    max_frames = int(policy.get("max_frames") or max_frames)
    api_frame_limit = int(policy.get("api_frame_limit") or api_frame_limit)
    probe_seconds = int(policy.get("probe_seconds") or probe_seconds)
    videos, _ = discover_case_videos(folder_dir)
    if videos:
        selected_videos = list(videos)
        role_preflight: Dict[str, Any] = {
            "status": "not_needed",
            "strategy": "single_video_direct_review",
            "preview_is_full_compliance": False,
            "routing_decision": "single_video",
            "candidate_count": len(videos),
            "rows": [],
        }
        role_preflight_billing: Optional[Dict[str, Any]] = None
        if len(videos) > 1 and not (_opening_role_preflight_enabled() or bool(policy.get("opening_role_preflight"))):
            role_preflight.update({
                "status": "disabled",
                "strategy": "keep_all_until_deferred_review_is_complete",
                "routing_decision": "disabled_keep_all_videos",
                "deferred_video_indices": [],
                "next_stage_policy": "当前保留全部视频送审；主开箱通过后的补充视频专属审核尚未启用。",
            })
        elif len(videos) > 1:
            preflight_dir = RUNTIME_MEDIA_DIR / f"role_{folder_dir.name}_{time.time_ns()}"
            declared_roles = declared_video_roles(evidence_context, videos)
            keys = _configured_model_keys(model_key, rule_tenant_id)
            config = MODEL_CONFIGS[keys[0]] if keys else {}
            timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
            batch_results: List[Dict[str, Any]] = []
            combined_candidates: List[Dict[str, Any]] = []
            preflight_complete = True
            for batch_number, batch in enumerate(opening_role_batches(videos), start=1):
                batch_indices = [index for index, _video in batch]
                batch_videos = [video_path for _index, video_path in batch]
                previews = extract_opening_role_previews(
                    batch_videos,
                    preflight_dir / f"batch_{batch_number:02d}",
                    video_indices=batch_indices,
                )
                if not previews:
                    preflight_complete = False
                    continue
                preview_case = build_opening_role_case(
                    batch_videos,
                    previews,
                    declared_roles,
                    video_indices=batch_indices,
                )
                batch_result = call_model(
                    config,
                    preview_case,
                    timeout=timeout,
                    retries=0,
                    deadline_at=_new_review_deadline(),
                )
                batch_results.append(batch_result)
                if batch_result.get("status") != "success":
                    preflight_complete = False
                    continue
                combined_candidates.extend(
                    item
                    for item in (batch_result.get("parsed") or {}).get("candidates") or []
                    if isinstance(item, dict)
                )
            if batch_results:
                role_preflight_billing = merge_model_billing(
                    batch_results[0], batch_results[1:]
                )
            selected_result = select_opening_video_candidates(
                videos,
                {"candidates": combined_candidates},
                declared_roles,
            )
            if preflight_complete:
                selected_videos = selected_result.pop("selected_videos")
                role_preflight = selected_result
            else:
                role_preflight = selected_result
                role_preflight.pop("selected_videos", None)
                role_preflight.update({
                    "status": "inconclusive",
                    "routing_decision": "keep_all_candidates",
                })
                selected_videos = list(videos)
            role_preflight["deferred_video_indices"] = []
            role_preflight["next_stage_policy"] = (
                "预筛只调整视频审核顺序；全部视频都在同一任务中完成审核。"
            )
        folder_media_context = (
            _prepared_folder_video_sources(
                selected_videos,
                RUNTIME_MEDIA_DIR / f"folder_proxy_{folder_dir.name}_{time.time_ns()}",
                policy=policy,
            )
            if len(selected_videos) > 1
            else nullcontext({
                "videos": selected_videos,
                "execution": [],
                "requires_complete_frame_fallback": False,
                "technical_processing_incomplete": False,
            })
        )
        with folder_media_context as prepared_videos:
            if prepared_videos.get("technical_processing_incomplete"):
                execution = {
                    "status": "failed",
                    "video": {},
                    "videos": deepcopy(prepared_videos["execution"]),
                    "images": {},
                    "frame_fallback": {
                        "used": False,
                        "representation": "not_used",
                        "sampling_fps": None,
                        "frame_count": 0,
                    },
                }
                review = {
                    "summary": {"review_status": "failed", "predicted_label": "review"},
                    "agent_brief": {
                        "conclusion": "审核服务本轮未完成，不能形成事实判断。",
                        "confidence": None,
                        "system_yes_no": "REVIEW",
                        "next_step": "由系统受控重试，不要求用户重复提交材料。",
                    },
                    "agent_report": {
                        "parsed": _technical_processing_incomplete_result(
                            "一个或多个视频无法在保真边界内完成质量代理。"
                        )["parsed"]
                    },
                    "diagnostics": {
                        "review_status": "failed",
                        "failure_stage": "媒体预处理",
                        "failure_reason": "一个或多个视频无法在保真边界内完成质量代理。",
                        "operator_hint": "由系统受控重试，不要求用户重复提交材料。",
                    },
                    "media_preflight_execution": execution,
                }
                log_folder_finished(review, "failed")
                return {
                    "ok": False,
                    "source_status": "media_preflight_failed",
                    "review": review,
                }
            routed_videos = list(prepared_videos["videos"])
            review = _run_review(
                routed_videos[0],
                scenario,
                fps,
                max_frames,
                api_frame_limit,
                probe_seconds,
                "standard",
                evidence_context,
                include_html_report=include_html_report,
                include_internal_metrics=include_internal_metrics,
                defer_postprocess=defer_postprocess,
                requested_model_key=model_key,
                sampling_mode_override=sampling_mode,
                rule_tenant_id=rule_tenant_id,
                selected_videos=routed_videos,
                native_video_sources=prepared_videos.get("native_videos") or None,
                preflight_result=role_preflight,
                preflight_billing=role_preflight_billing,
                policy_snapshot=policy,
            )
            if prepared_videos["execution"]:
                execution = dict(review.get("media_preflight_execution") or {})
                execution["videos"] = deepcopy(prepared_videos["execution"])
                review["media_preflight_execution"] = execution
        review["video_role_preflight"] = role_preflight
        log_folder_finished(review, "completed" if review.get("ok") else "failed")
        return {"ok": review.get("ok") is True, "source_status": "folder_ready", "review": review}
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
    run_dir = RUNTIME_MEDIA_DIR / f"folder_{folder_dir.name}_{int(time.time())}"
    try:
        case = load_case_bundle(folder_dir, args, run_dir, scenario_override=scenario)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = apply_frontdesk_context(case, scenario, json.dumps(evidence_context or {}, ensure_ascii=False))
    freeze_rule_snapshot(case, rule_tenant_id)
    case.setdefault("structured_business_context", {})["continuity_claim_identity"] = derive_claim_identity([], case)
    prepare_official_reference_images(case)
    case["media_preflight_execution"] = build_media_preflight_execution(
        native_source=None,
        native_status="not_run",
        native_sampling_fps=None,
        frame_fallback_used=bool(case.get("frames")),
        sampled_frame_count=len(case.get("frames") or []),
        supplemental_image_count=len(case.get("supplemental_images") or []),
        frame_sampling_fps=float(fps),
        image_execution=case.get("_media_preflight_image_execution") or [],
    )
    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    result = _call_model_chunked_with_fallback(
        model_key,
        case,
        timeout=model_timeout,
        retries=model_retries,
        deadline_at=_new_review_deadline(),
    )
    review = _agent_report_response(
        case,
        folder_dir,
        result,
        "agent_folder",
        include_internal_metrics=include_internal_metrics,
        include_html_report=include_html_report,
        defer_postprocess=defer_postprocess,
    )
    log_folder_finished(review, str(result.get("status") or "unknown"))
    return {
        "ok": (review.get("summary") or {}).get("review_status") == "completed",
        "source_status": "folder_ready",
        "review": review,
    }


def _normalize_review_scenario(scenario: str, business_scenario: str = "") -> tuple[str, str]:
    business_to_technical = {
        "product_damage": "product_damage",
        "wrong_item": "video_unboxing",
        "missing_item": "video_unboxing",
        "minor_refund": "minor_material",
    }
    normalized_business = business_scenario.strip()
    if normalized_business:
        expected_technical = business_to_technical.get(normalized_business)
        if not expected_technical:
            raise HTTPException(status_code=400, detail="未知业务审核场景")
        supplied_technical = business_to_technical.get(scenario, scenario)
        if supplied_technical != expected_technical:
            raise HTTPException(status_code=422, detail="审核场景与业务场景不一致")
        return expected_technical, normalized_business
    if scenario in business_to_technical:
        return business_to_technical[scenario], scenario
    if scenario in {"video_unboxing", "minor_material"}:
        return scenario, "minor_refund" if scenario == "minor_material" else ""
    raise HTTPException(status_code=400, detail="未知审核场景")


_REVIEW_CONTEXT_FIELDS = (
    "business_scenario", "ticket_id", "user_id", "order_no", "customer_claim",
    "order_item", "sku", "logistics_status", "logistics_context", "complaint_stage",
    "product_master_data", "warehouse_master_data", "conversation_history", "customer_tone",
    "sop_context", "source_case", "asset_manifest", "claim_scope", "continuity_policy",
    "damage_causality_policy", "fulfillment_baseline", "evidence_coverage",
    "review_routing_policy", "minor_refund_policy",
)

_BATCH_SHARED_CONTEXT_FIELDS = {
    "business_scenario",
    "sop_context",
    "continuity_policy",
    "damage_causality_policy",
    "review_routing_policy",
    "minor_refund_policy",
}


def _server_assessment_date() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def _review_evidence_context(values: Dict[str, Any], *, assessment_at: str) -> Dict[str, str]:
    return {
        **{field: str(values.get(field) or "") for field in _REVIEW_CONTEXT_FIELDS},
        "assessment_at": assessment_at,
    }


def _batch_review_evidence_context(values: Dict[str, Any]) -> Dict[str, str]:
    case_specific = [
        field
        for field in _REVIEW_CONTEXT_FIELDS
        if field not in _BATCH_SHARED_CONTEXT_FIELDS and str(values.get(field) or "").strip()
    ]
    if case_specific:
        raise HTTPException(
            status_code=422,
            detail="批量审核的工单、订单、诉求、商品和物流信息必须写入各子目录，不能在批量表单中共用。",
        )
    return _review_evidence_context(
        {
            field: values.get(field) if field in _BATCH_SHARED_CONTEXT_FIELDS else ""
            for field in _REVIEW_CONTEXT_FIELDS
        },
        assessment_at=_server_assessment_date(),
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/video-unboxing", response_class=HTMLResponse)
def video_unboxing_entry() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/wrong-item", response_class=HTMLResponse)
def wrong_item_entry() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/missing-item", response_class=HTMLResponse)
def missing_item_entry() -> str:
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
    signing_ready = REPORT_SIGNING_SECRET_CONFIGURED or not REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET
    probe = RUNTIME_MEDIA_DIR / f".health-{uuid4().hex}"
    try:
        RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
        runtime_storage = {"ready": True, "writable": True}
    except OSError as exc:
        runtime_storage = {"ready": False, "writable": False, "error_type": type(exc).__name__}
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "ok": signing_ready and runtime_storage["ready"],
        "service": "visual_review_workbench",
        "review_contract_version": REVIEW_CONTRACT_VERSION,
        "asset_capacity": {
            "soft_limit": SUPPLEMENTAL_IMAGE_SOFT_LIMIT,
            "safe_limit": MAX_FOLDER_FILES,
        },
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
        "access_control": "生产部署必须由主服务或反向代理执行租户鉴权",
        "report_signing_secret_configured": REPORT_SIGNING_SECRET_CONFIGURED,
        "persistent_report_signing_required": REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET,
        "runtime_media_storage": runtime_storage,
        "resource_budget": CASE_GATE.diagnostics(),
        "model_media_transport": {
            "mode": "adaptive_native_video_or_inline_frames",
            "supplier_file_uri_required": False,
            "accepted_model_media_types": ["video/mp4", "video/quicktime", "video/webm", "image/jpeg", "image/webp"],
            "native_video_max_unique_files": MAX_FOLDER_FILES,
            "strategy": "一个或多个完整视频在同一次原生视频审核中送审；仅在原生结果恰好缺少一个必要时间点且显式启用时，才受控回退 1 FPS 独立 WebP 批次",
        },
        "official_product_references": {
            "mode": "per_review_on_demand",
            "bulk_download_enabled": False,
            "model_transport": "compressed_inline_image",
            "cache_enabled": True,
            "per_review_limit": _clamp_int(os.getenv("REVIEW_PRODUCT_IMAGE_LIMIT", "6"), 0, 12, 6),
            "failure_policy": "保留文字订单基线并报告降级，不伪造图片已核验",
        },
        "built_in_samples_available": bool(sample_ids),
        "built_in_sample_count": len(sample_ids),
    }


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/reports/{name}", response_class=HTMLResponse)
def public_report(name: str, expires: str = "", sig: str = "") -> str:
    _require_public_signature("/reports/" + quote(name, safe=""), expires, sig)
    data = ALLOWED_REPORTS.get(name)
    if not data:
        path = (PUBLIC_SUMMARY_DIR / _report_data_name(name)).resolve()
        base = PUBLIC_SUMMARY_DIR.resolve()
        if base in path.parents and path.exists() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data = _sanitize_public_report_data(data)
            except json.JSONDecodeError:
                data = None
    if not data:
        raise HTTPException(status_code=404, detail="not_found")
    return _render_public_report(_sanitize_public_report_data(data))


@app.get("/ppt-assets/{name}")
def ppt_asset(name: str) -> FileResponse:
    path = (ROOT / "PPT-一部分" / name).resolve()
    base = (ROOT / "PPT-一部分").resolve()
    if base not in path.parents or not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(path)


@app.get("/media-item/{media_id}")
def opaque_media_asset(media_id: str, expires: str = "", sig: str = "") -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}", media_id):
        raise HTTPException(status_code=404, detail="素材不存在")
    _require_public_signature(f"/media-item/{media_id}", expires, sig)
    rel = PUBLIC_MEDIA_REGISTRY.get(media_id)
    base = ROOT
    if not rel:
        rel = PUBLIC_WORKBENCH_MEDIA_REGISTRY.get(media_id)
        base = WORKBENCH_DIR
    if not rel:
        rel = PUBLIC_RUNTIME_MEDIA_REGISTRY.get(media_id)
        base = RUNTIME_MEDIA_DIR
    if not rel:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        path = (base / rel).resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="素材不存在") from exc
    allowed_roots = [ROOT.resolve(), WORKBENCH_DIR.resolve(), SAMPLE_MATERIAL_DIR, RUNTIME_MEDIA_DIR]
    if not any(path == base or base in path.parents for base in allowed_roots):
        raise HTTPException(status_code=404, detail="素材不存在")
    if not path.is_file() or path.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
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
    return JSONResponse(_run_with_case_slot(
        _run_sample_agent_review,
        payload.get("sample_id", "sample_003"),
        payload.get("scenario", "product_damage"),
        payload.get("model_key", "auto"),
        payload.get("business_scenario", ""),
    ))


@app.post("/api/review-samples-batch")
def review_samples_batch(payload: Dict[str, str]) -> JSONResponse:
    return JSONResponse(_run_sample_batch_agent_review(payload.get("model_key", "auto")))


@app.post("/api/review-folder")
def review_folder(
    x_request_id: str = Header("", alias="X-Request-ID"),
    x_mitako_internal_metrics: str = Header("", alias="X-MITAKO-Internal-Metrics"),
    x_mitako_internal_token: str = Header("", alias="X-MITAKO-Internal-Token"),
    scenario: str = Form("video_unboxing"),
    business_scenario: str = Form(""),
    ticket_id: str = Form(""),
    user_id: str = Form(""),
    order_no: str = Form(""),
    customer_claim: str = Form(""),
    order_item: str = Form(""),
    sku: str = Form(""),
    logistics_status: str = Form(""),
    logistics_context: str = Form(""),
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
    review_routing_policy: str = Form(""),
    minor_refund_policy: str = Form(""),
    assessment_at: str = Form(""),
    rule_tenant_id: str = Form(""),
    defer_postprocess: bool = Form(False),
    include_html_report: bool = Form(True),
    sampling_mode: str = Form("adaptive"),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    scenario, business_scenario = _normalize_review_scenario(scenario, business_scenario)
    event_request_id = x_request_id.strip() or f"web-{uuid4().hex[:16]}"
    if sampling_mode not in {"adaptive", "dense"}:
        raise HTTPException(status_code=400, detail="未知抽帧策略")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 1800, 24)
    api_frame_limit = _clamp_int(api_frame_limit, 1, 24, 24)
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    internal_request = _internal_request_authorized(x_mitako_internal_token)
    resolved_rule_tenant = _resolve_rule_tenant_id(rule_tenant_id, internal_request)
    evidence_context = _review_evidence_context(
        locals(),
        assessment_at=assessment_at if internal_request and assessment_at else _server_assessment_date(),
    )
    claim_mode, claim_value = (
        _claim_internal_review_request(x_request_id, resolved_rule_tenant)
        if internal_request
        else ("disabled", None)
    )
    if claim_mode == "cached":
        return JSONResponse(claim_value)
    claim_key = claim_value if claim_mode == "owner" else None
    try:
        folder_dir, ingestion = _save_folder_uploads(files)
        with visual_event_context(
            tenant_id=resolved_rule_tenant,
            request_id=event_request_id,
        ):
            response = _run_with_case_slot(
                _run_folder_agent_review,
                folder_dir,
                scenario,
                "auto",
                evidence_context,
                sampling_mode,
                fps,
                max_frames,
                api_frame_limit,
                probe_seconds,
                include_internal_metrics=internal_request and x_mitako_internal_metrics == "1",
                include_html_report=include_html_report,
                defer_postprocess=internal_request and defer_postprocess,
                rule_tenant_id=resolved_rule_tenant,
            )
        response["ingestion"] = ingestion
        response["observability"] = observability_store.summarize_request(
            event_request_id,
            tenant_id=resolved_rule_tenant,
        )
    except ValueError as exc:
        _fail_internal_review_request(claim_key)
        LOGGER.warning(
            "folder review rejected request_id=%s error_type=%s",
            x_request_id or "missing",
            exc.__class__.__name__,
        )
        raise HTTPException(status_code=422, detail="送审业务字段不是有效 JSON") from exc
    except BaseException as exc:
        _fail_internal_review_request(claim_key)
        LOGGER.exception(
            "folder review failed request_id=%s error_type=%s",
            x_request_id or "missing",
            exc.__class__.__name__,
        )
        raise
    _complete_internal_review_request(claim_key, response)
    return JSONResponse(response)


@app.post("/api/review-folders-batch")
def review_folders_batch(
    x_request_id: str = Header("", alias="X-Request-ID"),
    scenario: str = Form("video_unboxing"),
    business_scenario: str = Form(""),
    ticket_id: str = Form(""),
    user_id: str = Form(""),
    order_no: str = Form(""),
    customer_claim: str = Form(""),
    order_item: str = Form(""),
    sku: str = Form(""),
    logistics_status: str = Form(""),
    logistics_context: str = Form(""),
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
    review_routing_policy: str = Form(""),
    minor_refund_policy: str = Form(""),
    assessment_at: str = Form(""),
    include_html_report: bool = Form(True),
    sampling_mode: str = Form("adaptive"),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    files: List[UploadFile] = File(...),
) -> JSONResponse:
    scenario, business_scenario = _normalize_review_scenario(scenario, business_scenario)
    event_request_id = x_request_id.strip() or f"web-{uuid4().hex[:16]}"
    if sampling_mode not in {"adaptive", "dense"}:
        raise HTTPException(status_code=400, detail="未知抽帧策略")
    fps = _clamp_float(fps, 0.1, 2.0, 1.0)
    max_frames = _clamp_int(max_frames, 1, 1800, 24)
    api_frame_limit = _clamp_int(api_frame_limit, 1, 24, 24)
    probe_seconds = _clamp_int(probe_seconds, 5, 60, 12)
    groups = _group_batch_folder_uploads(files)
    evidence_context = _batch_review_evidence_context(locals())
    cases = []
    for case_id, case_files in groups.items():
        try:
            folder_dir, ingestion = _save_folder_uploads(case_files)
            with visual_event_context(request_id=event_request_id, scenario=scenario):
                result = _run_with_case_slot(
                    _run_folder_agent_review,
                    folder_dir,
                    scenario,
                    "auto",
                    evidence_context,
                    sampling_mode,
                    fps,
                    max_frames,
                    api_frame_limit,
                    probe_seconds,
                    include_html_report=include_html_report,
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
        "observability": observability_store.summarize_request(event_request_id),
    })


@app.post("/api/review")
def review(
    x_request_id: str = Header("", alias="X-Request-ID"),
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
    logistics_context: str = Form(""),
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
    review_routing_policy: str = Form(""),
    minor_refund_policy: str = Form(""),
    include_html_report: bool = Form(True),
    fps: float = Form(1.0),
    max_frames: int = Form(24),
    api_frame_limit: int = Form(24),
    probe_seconds: int = Form(12),
    review_model: str = Form("standard"),
    file: Optional[UploadFile] = File(None),
) -> JSONResponse:
    if source_type not in {"upload", "url"}:
        raise HTTPException(status_code=400, detail="未知素材来源")
    scenario, business_scenario = _normalize_review_scenario(scenario, business_scenario)
    event_request_id = x_request_id.strip() or f"web-{uuid4().hex[:16]}"
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
                "force_action_scan": review_model == "backup",
                "dedicated_chunk_frames": 20,
                "context_frames": 6,
            },
            ensure_ascii=False,
        )
    evidence_context = _review_evidence_context(
        locals(), assessment_at=_server_assessment_date()
    )
    with visual_event_context(request_id=event_request_id, scenario=scenario):
        result = _run_with_case_slot(
            _run_review,
            video,
            scenario,
            fps,
            max_frames,
            api_frame_limit,
            probe_seconds,
            review_model,
            evidence_context,
            include_html_report=include_html_report,
        )
    response = {"ok": result["ok"], "source_status": source_status, "review": result}
    response["observability"] = observability_store.summarize_request(event_request_id)
    if result.get("diagnostics"):
        response["diagnostics"] = result["diagnostics"]
    return JSONResponse(response)


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(__import__("os").getenv("VISUAL_WORKBENCH_PORT", "7861")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
