# -*- coding: utf-8 -*-
"""客服视觉审核工作台：上传/URL -> 本地视频 -> 视觉复核报告。"""
from __future__ import annotations

import json
import hashlib
import hmac
import math
import os
import re
import secrets
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(
    dotenv_path=Path(os.getenv("MITAKO_ENV_FILE") or PROJECT_ROOT / ".env"),
    override=False,
)

from runtime_paths import app_root
from review_service.advisory_assessment import attach_advisory_assessment
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
    from poc.visual_review_poc.official_reference_images import prepare_official_reference_images
    from poc.visual_review_poc.report_renderer import (
        render_public_report as _render_public_report,
        safe_agent_conclusion as _safe_agent_conclusion,
        safe_agent_next_step as _safe_agent_next_step,
    )
    from poc.visual_review_poc.sample_evaluation import evaluate_sample_rows, read_sample_rows
except ImportError:
    from model_selection_e2e import MODEL_CONFIGS, call_model_chunked, load_case_bundle, score_result
    from local_video_triage_demo import apply_frontdesk_context, load_env as load_visual_env
    from official_reference_images import prepare_official_reference_images
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
PUBLIC_MEDIA_INDEX: dict[str, str] = {}
PUBLIC_MEDIA_INDEX_LOCK = threading.Lock()
PUBLIC_MEDIA_INDEX_PATH = REPORT_DIR / "internal" / "public_media_registry.json"
LEGACY_PUBLIC_MEDIA_INDEX_PATH = REPORT_DIR / "public_media_registry.json"


def _migrate_public_media_index() -> None:
    if not LEGACY_PUBLIC_MEDIA_INDEX_PATH.is_file():
        return
    PUBLIC_MEDIA_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PUBLIC_MEDIA_INDEX_PATH.exists():
        os.replace(LEGACY_PUBLIC_MEDIA_INDEX_PATH, PUBLIC_MEDIA_INDEX_PATH)
        return

    merged: dict[str, str] = {}
    for path in (PUBLIC_MEDIA_INDEX_PATH, LEGACY_PUBLIC_MEDIA_INDEX_PATH):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            merged.update({str(key): str(value) for key, value in payload.items() if isinstance(value, str)})
    temp_path = PUBLIC_MEDIA_INDEX_PATH.with_name(f".{PUBLIC_MEDIA_INDEX_PATH.name}.{uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, PUBLIC_MEDIA_INDEX_PATH)
    LEGACY_PUBLIC_MEDIA_INDEX_PATH.unlink(missing_ok=True)


_migrate_public_media_index()
_configured_signing_secret = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
REPORT_SIGNING_SECRET_CONFIGURED = bool(_configured_signing_secret)
REPORT_SIGNING_SECRET = _configured_signing_secret.encode("utf-8") if _configured_signing_secret else secrets.token_bytes(32)
REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET = os.getenv(
    "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET", "0"
).strip().lower() in {"1", "true", "yes", "on"}
try:
    REPORT_URL_TTL_SECONDS = max(1, int(os.getenv("VISUAL_REPORT_URL_TTL_SECONDS", "900") or 900))
except ValueError:
    REPORT_URL_TTL_SECONDS = 900
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


_MINOR_PUBLIC_PARSED_SCHEMA = {
    "decision": True,
    "predicted_label": True,
    "system_yes_no": True,
    "confidence": True,
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
            }],
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
    "business_follow_up_reason": True,
    "next_step": True,
    "model_limitations": [True],
    "confidence_components": {
        "material_image_coverage": True,
        "required_category_completeness": True,
        "final_decision": True,
        "calibration_status": True,
        "interpretation": True,
    },
}
_MINOR_IDENTIFIER_PATTERNS = (
    re.compile(r"(?<!\d)\d{17}[\dXx](?![\dXx])"),
    re.compile(r"(?<!\d)\d{15}(?!\d)"),
    re.compile(r"(?<!\d)1[3-9](?:[ -]?\d){9}(?!\d)"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]\d{7,9}(?![A-Za-z0-9])"),
)
_LABELED_NAME_PATTERN = re.compile(
    r"((?:申请人姓名|监护人姓名|收件人姓名|申请人|监护人|收件人|姓名)\s*[：:]\s*)[\u4e00-\u9fff·]{2,12}"
)
_LABELED_ADDRESS_PATTERN = re.compile(
    r"((?:收货地址|家庭住址|联系地址|住址|地址)\s*[：:]\s*)[^，,。；;\n]{4,120}"
)

# 所有场景只公开报告实际消费的受控字段；未知模型字段一律丢弃。
_PUBLIC_PARSED_FIELD_NAMES = {
    "decision", "predicted_label", "system_yes_no", "confidence", "overall_audit", "conclusion",
    "core_reason", "business_follow_up_suggestion", "visual_evidence_verdict", "visual_qc_conclusion",
    "verdict", "confidence_reason", "video_audit_conclusion", "continuity_score", "continuity_reason",
    "swap_risk_level", "edit_or_cut_risk", "opening_integrity", "opening_integrity_source", "sampling_boundary_status",
    "technical_timeline_status", "evidence_continuity_status", "object_continuity_assessment",
    "tracked_subjects", "subject_id", "description", "tracking_start", "tracking_end",
    "first_exposed_timestamp", "visibility_coverage", "out_of_frame_events", "start_timestamp",
    "end_timestamp", "duration_seconds", "visibility", "before_evidence", "out_of_frame_evidence",
    "after_evidence", "identity_reestablished", "reason", "continuity_verdict",
    "longest_out_of_frame_seconds", "total_unobserved_seconds", "critical_events", "policy",
    "out_of_frame_warning_seconds", "customer_claim_parse", "expected_item", "claimed_received_item",
    "claimed_mismatch_type", "expected_order_item", "actual_received_item", "audit_methods",
    "frame_findings", "video_index", "global_frame_index", "frame_index", "timestamp", "visible_facts",
    "risk", "subject_visibility", "state", "adopted_evidence", "supporting_evidence",
    "challenging_evidence", "source_type", "image_index", "reference_index", "reference_id", "asset_ref", "fact", "why_it_matters",
    "same_item_linkage", "temporal_linkage", "authenticity_assessment", "size_sku_assessment",
    "issue_timestamps", "skeptical_questions", "material_gaps", "conclusion_argument", "support",
    "challenge", "why_not_final_business_decision", "business_action_allowed", "human_required",
    "human_required_for_business_action", "business_follow_up_reason", "next_step", "model_limitations",
    "damage_causality_assessment", "damage_presence", "damage_type_and_location", "first_visible_evidence",
    "pre_opening_state_visible", "opening_action_visible", "damage_change_observed", "damage_timing",
    "possible_origins", "origin", "most_likely_origin", "origin_confidence", "causal_evidence_level",
    "claim_support", "before_action_evidence", "action_evidence", "after_action_evidence", "subject",
    "location", "chain_id", "alternative_explanations", "cannot_conclude_reason", "damage_observability",
    "status", "claimed_region_closeup", "required_view_coverage", "conflicting_evidence", "missing_views",
    "evidence_source_summary", "primary_video", "scope", "supplemental_images", "provided_count",
    "referenced_count", "referenced_image_indices", "unreferenced_image_indices", "linkage_status", "evidence_findings",
    "decision_boundary", "key_evidence", "fulfillment_reconciliation", "baseline_version", "expected_items",
    "observed_items", "suspected_missing_items", "unexpected_items", "unconfirmed_items",
    "package_observations", "package_coverage", "all_packages_uploaded", "all_items_displayed",
    "evidence_timestamps", "item_ref", "sku", "product_name", "specification", "expected_quantity",
    "observed_quantity", "package_ref", "opening_complete", "all_contents_laid_out",
    "confidence_components", "main_segment_mean", "damage_origin", "continuity_visibility_coverage",
    "final_decision", "calibration_status", "interpretation", "decision_policy_audit", "version", "mode",
    "policy_ref", "policy_source", "requested_overrides_ignored", "applied", "rule_id", "claim_scope",
    "stage", "issue_types", "excluded_issue_types", "active_claim_ids", "split_status", "ready",
    "evidence_gate", "video_present", "model_confidence", "media_forensics_status",
    "media_forensics_risk_level", "supplemental_linkage_status", "business_boundary", "failed_conditions",
    "minimum_visibility_coverage", "minimum_confidence", "minimum_required_view_coverage", "fully_observable",
    "max_unobserved_seconds", "claimed_item_longest_out_of_frame_seconds", "maximum_forensic_risk",
    "pass_integrity_status", "specialized_pass_guard_reason",
    "aggregation_warnings", "code", "chunk_index", "alleged_end", "later_sampled_evidence_seconds",
    "global_review_summary", "sampled_start_seconds", "sampled_end_seconds", "source_duration_seconds",
    "claimed_item_first_exposed_timestamp", "timeline_coverage_ratio",
    "chunk_narratives_excluded_from_public_conclusion", "quality_issues", "tamper_risk", "risk_reason_codes",
}


def _redact_minor_identifiers(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_minor_identifiers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_minor_identifiers(item) for item in value]
    if isinstance(value, str):
        for pattern in _MINOR_IDENTIFIER_PATTERNS:
            value = pattern.sub("[已脱敏]", value)
        value = _LABELED_NAME_PATTERN.sub(r"\1[已脱敏]", value)
        value = _LABELED_ADDRESS_PATTERN.sub(r"\1[已脱敏]", value)
    return value


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
    if scenario == "minor_material":
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


def _require_public_signature(path: str, expires: str, sig: str) -> None:
    try:
        expires_at = int(expires)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="forbidden") from exc
    expected = _public_url_signature(path, expires_at)
    if expires_at < int(time.time()) or not sig or not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail="forbidden")


def _refresh_signed_urls(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _refresh_signed_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_refresh_signed_urls(item) for item in value]
    if isinstance(value, str) and urlsplit(value).path.startswith(("/reports/", "/media/", "/media-item/")):
        return _sign_public_url(value)
    return value


def _sanitize_public_report_data(data: Dict[str, Any]) -> Dict[str, Any]:
    public = _strip_private_report_fields(data)
    agent_report = public.get("agent_report") if isinstance(public.get("agent_report"), dict) else {}
    scenario = str(agent_report.get("scenario") or "")
    agent_report["parsed"] = _public_parsed(agent_report.get("parsed") or {}, scenario)
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
            for key in ("video_index", "duration_seconds", "native_fps", "fps_requested", "sampled_frames")
            if item.get(key) not in (None, "")
        }
        duration = float(item.get("duration_seconds") or 0)
        if duration > 0 and item.get("sampled_frames") not in (None, ""):
            video["effective_sample_fps"] = round(float(item["sampled_frames"]) / duration, 4)
        public_videos.append(video)
    structured = case.get("structured_business_context") or {}
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
    }
    parsed = _public_parsed(parsed, str(case.get("scenario") or ""))
    public_conclusion = _redact_minor_identifiers(public_conclusion)
    public_next_step = _redact_minor_identifiers(public_next_step)
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
    media_id = hmac.new(
        REPORT_SIGNING_SECRET,
        f"media\n{rel}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    with PUBLIC_MEDIA_INDEX_LOCK:
        PUBLIC_MEDIA_INDEX[media_id] = rel
        PUBLIC_MEDIA_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = PUBLIC_MEDIA_INDEX_PATH.with_name(
            f".{PUBLIC_MEDIA_INDEX_PATH.name}.{uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(PUBLIC_MEDIA_INDEX, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            for attempt in range(1, 6):
                try:
                    os.replace(temp_path, PUBLIC_MEDIA_INDEX_PATH)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.05 * attempt)
        finally:
            temp_path.unlink(missing_ok=True)
    return _sign_public_url(f"/media-item/{media_id}")


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
    return bool(parsed.get("predicted_label")) and parsed.get("confidence") not in (None, "")


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


def _configured_model_keys(requested_model_key: str) -> List[str]:
    if requested_model_key != "auto":
        resolved = _model_key_from_identifier(requested_model_key)
        return [resolved] if resolved else []
    identifiers = [os.getenv("VISUAL_REVIEW_PRIMARY_MODEL", "gemini-3.5-flash")]
    identifiers.extend(
        item.strip()
        for item in os.getenv("VISUAL_REVIEW_FALLBACK_MODELS", "").split(",")
        if item.strip()
    )
    keys: List[str] = []
    for identifier in identifiers:
        key = _model_key_from_identifier(identifier)
        if key and key not in keys:
            keys.append(key)
    return keys or ["gemini35"]


def _call_model_chunked_with_fallback(
    requested_model_key: str,
    case: Dict[str, Any],
    timeout: int,
    retries: int,
) -> Dict[str, Any]:
    model_keys = _configured_model_keys(requested_model_key)
    if not model_keys:
        return {"status": "skipped", "error": "unknown_review_model", "cost_status": "not_incurred"}
    wall_started = time.time()
    attempts: List[Dict[str, Any]] = []
    prior_unknown_calls = 0
    prior_model_calls = 0
    prior_model_latency = 0.0
    blocked_providers = set()
    last_result: Dict[str, Any] = {"status": "skipped", "error": "no_available_review_model"}
    for route_index, model_key in enumerate(model_keys, start=1):
        config = MODEL_CONFIGS[model_key]
        if config.get("provider") in blocked_providers:
            attempts.append({"route_index": route_index, "status": "skipped", "reason": "transport_circuit_open"})
            continue
        current = call_model_chunked(config, case, timeout=timeout, retries=retries)
        current_chunking = current.get("chunking") if isinstance(current.get("chunking"), dict) else {}
        current_calls = int(current_chunking.get("total_model_calls") or 0)
        current_unknown = int(current.get("unknown_cost_calls") or 0)
        attempts.append({
            "route_index": route_index,
            "status": str(current.get("status") or "failed"),
            "status_code": current.get("status_code"),
            "error_type": str(current.get("error_type") or ""),
            "model_calls": current_calls,
        })
        if current.get("status") == "success":
            result = dict(current)
            chunking = dict(current_chunking)
            chunking["total_model_calls"] = current_calls + prior_model_calls
            result["chunking"] = chunking
            result["unknown_cost_calls"] = int(result.get("unknown_cost_calls") or 0) + prior_unknown_calls
            if prior_unknown_calls:
                result["cost_status"] = "partial_unknown"
            result["model_latency_seconds_sum"] = round(
                float(result.get("model_latency_seconds_sum") or 0) + prior_model_latency,
                2,
            )
            result["latency_seconds"] = round(time.time() - wall_started, 2)
            result["route_fallback_count"] = sum(1 for item in attempts[:-1] if item.get("status") != "skipped")
            result["route_attempts"] = attempts
            return result
        last_result = current
        prior_model_calls += current_calls
        prior_unknown_calls += current_unknown
        prior_model_latency += float(current.get("model_latency_seconds_sum") or current.get("latency_seconds") or 0)
        if current.get("status_code") is None and current.get("error_type") == "hard":
            blocked_providers.add(config.get("provider"))
    result = dict(last_result)
    chunking = dict(result.get("chunking") or {})
    chunking["total_model_calls"] = prior_model_calls
    result["chunking"] = chunking
    result["unknown_cost_calls"] = prior_unknown_calls
    result["cost_status"] = "unknown" if prior_unknown_calls else str(result.get("cost_status") or "not_incurred")
    result["model_latency_seconds_sum"] = round(prior_model_latency, 2)
    result["latency_seconds"] = round(time.time() - wall_started, 2)
    result["route_fallback_count"] = max(0, sum(1 for item in attempts if item.get("status") != "skipped") - 1)
    result["route_attempts"] = attempts
    return result


def _internal_inference_estimate(result: Dict[str, Any]) -> Dict[str, Any]:
    """仅供受保护审核 API 和内部运维汇总，公开 HTML 不引用该对象。"""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = result.get("cost") if isinstance(result.get("cost"), dict) else {}
    chunking = result.get("chunking") if isinstance(result.get("chunking"), dict) else {}
    channels = chunking.get("channels") if isinstance(chunking.get("channels"), dict) else {}
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
        "route_fallback_count": int(result.get("route_fallback_count") or 0),
        "route_attempts": result.get("route_attempts") if isinstance(result.get("route_attempts"), list) else [],
        "total_frames": int(chunking.get("total_frames") or 0),
        "main_review_frames": int(chunking.get("main_review_frames") or 0),
        "total_model_calls": int(chunking.get("total_model_calls") or 1),
        "segment_count": int(chunking.get("segment_count") or 1),
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
    prepare_official_reference_images(case)
    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    result = _call_model_chunked_with_fallback(
        "auto",
        case,
        timeout=model_timeout,
        retries=model_retries,
    )
    review = _agent_report_response(
        case,
        video.parent,
        result,
        "agent_single",
        profile["label"],
        include_html_report=include_html_report,
    )
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
    include_html_report: bool = True,
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
    structured = case.get("structured_business_context") or {}
    normalized = attach_advisory_assessment(
        {
            "summary": data["summary"],
            "agent_report": data["agent_report"],
            "agent_brief": {
                "conclusion": public_conclusion,
                "confidence": data["summary"].get("confidence"),
                "system_yes_no": parsed.get("system_yes_no"),
                "next_step": public_next_step,
            },
            "diagnostics": data.get("diagnostics") or {},
        },
        {
            "scenario": structured.get("business_scenario") or case.get("scenario") or "",
            "review_routing_policy": structured.get("review_routing_policy") or {},
        },
        succeeded=ok,
    )
    data["summary"] = normalized["summary"]
    data["agent_report"] = normalized["agent_report"]
    data["advisory_assessment"] = normalized["advisory_assessment"]
    data = _sanitize_public_report_data(data)
    if include_html_report:
        ALLOWED_REPORTS[report_name] = data
        PUBLIC_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        (PUBLIC_SUMMARY_DIR / _report_data_name(report_name)).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "advisory_assessment": data.get("advisory_assessment") or normalized["advisory_assessment"],
        "media_warnings": data.get("media_warnings") or [],
        "agent_brief": normalized["agent_brief"],
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
    if model_key != "auto" and model_key not in MODEL_CONFIGS:
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
    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    result = _call_model_chunked_with_fallback(model_key, case, timeout=model_timeout, retries=model_retries)
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


def _run_folder_agent_review(folder_dir: Path, scenario: str, model_key: str, evidence_context: Dict[str, Any], sampling_mode: str, fps: float, max_frames: int, api_frame_limit: int, probe_seconds: int, include_internal_metrics: bool = False, include_html_report: bool = True) -> Dict[str, Any]:
    if model_key != "auto" and model_key not in MODEL_CONFIGS:
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
    prepare_official_reference_images(case)
    model_timeout = max(30, min(int(os.getenv("REVIEW_MODEL_TIMEOUT_SECONDS", "180") or 180), 600))
    model_retries = max(0, min(int(os.getenv("REVIEW_MODEL_RETRIES", "1") or 1), 2))
    result = _call_model_chunked_with_fallback(
        model_key,
        case,
        timeout=model_timeout,
        retries=model_retries,
    )
    review = _agent_report_response(
        case,
        folder_dir,
        result,
        "agent_folder",
        include_internal_metrics=include_internal_metrics,
        include_html_report=include_html_report,
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
    signing_ready = REPORT_SIGNING_SECRET_CONFIGURED or not REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET
    return {
        "ok": signing_ready,
        "service": "visual_review_workbench",
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
        "access_control": "生产部署必须由主服务或反向代理执行租户鉴权",
        "report_signing_secret_configured": REPORT_SIGNING_SECRET_CONFIGURED,
        "persistent_report_signing_required": REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET,
        "model_media_transport": {
            "mode": "inline_base64_images",
            "supplier_file_uri_required": False,
            "accepted_model_media_types": ["image/jpeg", "image/webp"],
            "strategy": "服务端本地抽帧、压缩和分段并发；原视频不直接发送给多模态供应商",
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


@app.get("/media/{rel_path:path}")
def media_asset(rel_path: str, expires: str = "", sig: str = "") -> FileResponse:
    try:
        rel = unquote(rel_path).replace("\\", "/")
        _require_public_signature("/media/" + quote(rel), expires, sig)
        path = (ROOT / rel).resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="素材不存在") from exc
    allowed_roots = [WORKBENCH_DIR.resolve(), SAMPLE_MATERIAL_DIR, RUNTIME_MEDIA_DIR]
    if not any(path == base or base in path.parents for base in allowed_roots):
        raise HTTPException(status_code=404, detail="素材不存在")
    if not path.exists() or path.suffix.lower() not in ALLOWED_MEDIA_SUFFIXES:
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(path)


@app.get("/media-item/{media_id}")
def opaque_media_asset(media_id: str, expires: str = "", sig: str = "") -> FileResponse:
    if not re.fullmatch(r"[a-f0-9]{32}", media_id):
        raise HTTPException(status_code=404, detail="素材不存在")
    _require_public_signature(f"/media-item/{media_id}", expires, sig)
    with PUBLIC_MEDIA_INDEX_LOCK:
        rel = PUBLIC_MEDIA_INDEX.get(media_id)
        if not rel and PUBLIC_MEDIA_INDEX_PATH.is_file():
            try:
                stored = json.loads(PUBLIC_MEDIA_INDEX_PATH.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                stored = {}
            if isinstance(stored, dict):
                PUBLIC_MEDIA_INDEX.update(
                    {
                        str(key): str(value)
                        for key, value in stored.items()
                        if re.fullmatch(r"[a-f0-9]{32}", str(key)) and isinstance(value, str)
                    }
                )
            rel = PUBLIC_MEDIA_INDEX.get(media_id)
    if not rel:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        path = (ROOT / rel).resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="素材不存在") from exc
    allowed_roots = [WORKBENCH_DIR.resolve(), SAMPLE_MATERIAL_DIR, RUNTIME_MEDIA_DIR]
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
    return JSONResponse(_run_sample_agent_review(
        payload.get("sample_id", "sample_003"),
        payload.get("scenario", "product_damage"),
        payload.get("model_key", "auto"),
    ))


@app.post("/api/review-samples-batch")
def review_samples_batch(payload: Dict[str, str]) -> JSONResponse:
    return JSONResponse(_run_sample_batch_agent_review(payload.get("model_key", "auto")))


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
    review_routing_policy: str = Form(""),
    include_html_report: bool = Form(True),
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
        "review_routing_policy": review_routing_policy,
    }
    response = _run_folder_agent_review(
        folder_dir,
        scenario,
        "auto",
        evidence_context,
        sampling_mode,
        fps,
        max_frames,
        api_frame_limit,
        probe_seconds,
        include_internal_metrics=x_mitako_internal_metrics == "1",
        include_html_report=include_html_report,
    )
    response["ingestion"] = ingestion
    return JSONResponse(response)


@app.post("/api/review-folders-batch")
def review_folders_batch(
    scenario: str = Form("video_unboxing"),
    customer_claim: str = Form(""),
    product_master_data: str = Form(""),
    conversation_history: str = Form(""),
    review_routing_policy: str = Form(""),
    include_html_report: bool = Form(True),
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
        "review_routing_policy": review_routing_policy,
    }
    cases = []
    for case_id, case_files in groups.items():
        try:
            folder_dir, ingestion = _save_folder_uploads(case_files)
            result = _run_folder_agent_review(
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
    review_routing_policy: str = Form(""),
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
        "review_routing_policy": review_routing_policy,
    }
    result = _run_review(
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
    if result.get("diagnostics"):
        response["diagnostics"] = result["diagnostics"]
    return JSONResponse(response)


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(__import__("os").getenv("VISUAL_WORKBENCH_PORT", "7861")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
