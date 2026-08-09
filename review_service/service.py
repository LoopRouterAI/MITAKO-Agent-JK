# -*- coding: utf-8 -*-
"""审核案件上传、排队与视觉工作台调用。"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import shutil
import sqlite3
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4
from urllib.parse import quote, urlsplit

import httpx
from fastapi import UploadFile

from runtime_paths import data_dir
from poc.visual_review_poc.report_renderer import render_public_report
from poc.visual_review_poc.local_video_triage_demo import adaptive_frame_budget
from review_input_safety import assert_review_input_safe
from review_media_safety import ignored_upload_reason, valid_media_magic

from . import store
from .media_forensics import forensics_timeout_seconds, inspect_job_media, is_video_asset, resolve_ffprobe
from .input_readiness import assess_input_readiness
from .decision_policy import apply_review_decision_policy
from .advisory_assessment import attach_advisory_assessment, html_report_requested
from .schemas import ReviewCaseMetadata


ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".txt", ".json"}
SCENARIO_MAP = {
    "product_damage": "product_damage",
    "wrong_item": "video_unboxing",
    "missing_item": "video_unboxing",
    "minor_refund": "minor_material",
}
SCENARIO_LABELS = {
    "product_damage": "商品有伤",
    "wrong_item": "发错货",
    "missing_item": "漏发货",
    "minor_refund": "未成年人退款资料",
}
MAX_WORKERS = max(1, min(int(os.getenv("REVIEW_JOB_WORKERS", "2") or 2), 8))
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="mitako-review")
REVIEW_CONTRACT_VERSION = "2026-07-31.1"


class WorkbenchRequestError(RuntimeError):
    def __init__(self, status_code: int, attempts: List[Dict[str, Any]]):
        super().__init__(f"workbench_http_{status_code}")
        self.status_code = status_code
        self.attempts = attempts


def _limit_bytes(name: str, default_mb: int) -> int:
    try:
        value = int(os.getenv(name, str(default_mb)) or default_mb)
    except ValueError:
        value = default_mb
    return max(1, value) * 1024 * 1024


def upload_root() -> Path:
    path = data_dir() / "review_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str, fallback: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(name).stem).strip("._-")[:80] or fallback
    return stem + Path(name).suffix.lower()


def ensure_label_isolation(value: Any) -> None:
    """评测标签只能在模型返回后离线比对，禁止进入审核输入。"""
    assert_review_input_safe(value)


def _request_hash(metadata: ReviewCaseMetadata, assets: Sequence[Dict[str, Any]]) -> str:
    basis = {
        "metadata": metadata.model_dump(mode="json"),
        "files": [
            {
                "name": item.get("original_name") or "",
                "content_type": item.get("mime_type") or "",
                "size": int(item.get("size") or 0),
                "sha256": item.get("sha256") or "",
            }
            for item in assets
        ],
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _upload_ingestion_summary(uploads: Sequence[UploadFile]) -> Dict[str, Any]:
    ignored = []
    for item in uploads:
        name = item.filename or ""
        reason = ignored_upload_reason(name)
        if reason:
            ignored.append({"name": Path(name.replace("\\", "/")).name, "reason_code": reason})
    accepted_count = len(uploads) - len(ignored)
    soft_limit, safe_limit = _review_asset_limits()
    return {
        "received_count": len(uploads),
        "accepted_count": accepted_count,
        "ignored_count": len(ignored),
        "ignored_files": ignored[:50],
        "capacity_mode": "expanded" if accepted_count > soft_limit else "standard",
        "soft_limit": soft_limit,
        "safe_limit": safe_limit,
    }


def _review_asset_limits() -> Tuple[int, int]:
    soft_limit = max(1, int(os.getenv("REVIEW_ASSET_SOFT_LIMIT", "40") or 40))
    safe_limit = max(1, int(os.getenv("REVIEW_MAX_ASSETS", "200") or 200))
    if soft_limit > safe_limit:
        raise ValueError("invalid_review_asset_capacity")
    return soft_limit, safe_limit


async def _save_uploads(job_id: str, metadata: ReviewCaseMetadata, uploads: Sequence[UploadFile]) -> List[Dict[str, Any]]:
    accepted_uploads = [item for item in uploads if not ignored_upload_reason(item.filename or "")]
    if not accepted_uploads:
        raise ValueError("review_assets_required")
    _, safe_limit = _review_asset_limits()
    if len(accepted_uploads) > safe_limit:
        raise ValueError(json.dumps({
            "code": "too_many_review_assets",
            "received_count": len(accepted_uploads),
            "safe_limit": safe_limit,
        }, ensure_ascii=False))

    max_asset = _limit_bytes("REVIEW_MAX_ASSET_MB", 650)
    max_case = _limit_bytes("REVIEW_MAX_CASE_MB", 750)
    target_dir = upload_root() / job_id
    target_dir.mkdir(parents=True, exist_ok=False)
    assets: List[Dict[str, Any]] = []
    total_case = 0
    try:
        for index, upload in enumerate(accepted_uploads, start=1):
            original = Path(upload.filename or f"asset_{index}").name
            if original.lower() == "sample_labels.json":
                raise ValueError("evaluation_label_not_allowed")
            suffix = Path(original).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise ValueError("unsupported_review_asset")
            stored = f"{index:03d}_{uuid4().hex[:10]}_{_safe_name(original, f'asset_{index}')}"
            target = target_dir / stored
            digest = hashlib.sha256()
            size = 0
            head = b""
            with target.open("wb") as fh:
                while chunk := await upload.read(1024 * 1024):
                    if len(head) < 32:
                        head = (head + chunk)[:32]
                    size += len(chunk)
                    total_case += len(chunk)
                    if size > max_asset:
                        raise ValueError("review_asset_too_large")
                    if total_case > max_case:
                        raise ValueError("review_case_too_large")
                    digest.update(chunk)
                    fh.write(chunk)
            if size <= 0:
                raise ValueError("empty_review_asset")
            if not valid_media_magic(suffix, head):
                raise ValueError("invalid_review_asset_content")
            if suffix == ".json":
                try:
                    document = json.loads(target.read_text(encoding="utf-8-sig"))
                    ensure_label_isolation(document)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("invalid_review_json_asset") from exc
            elif suffix == ".txt" and size <= 5 * 1024 * 1024:
                try:
                    ensure_label_isolation(target.read_text(encoding="utf-8-sig"))
                except UnicodeDecodeError as exc:
                    raise ValueError("invalid_review_asset_content") from exc
            mime_type = (upload.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream").split(";", 1)[0]
            assets.append(
                {
                    "asset_id": f"RA-{uuid4().hex[:12].upper()}",
                    "original_name": original,
                    "stored_name": stored,
                    "mime_type": mime_type,
                    "size": size,
                    "sha256": digest.hexdigest(),
                    "fields": metadata.asset_fields.get(original, []),
                }
            )
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return assets


async def create_job_from_uploads(
    metadata: ReviewCaseMetadata,
    uploads: Sequence[UploadFile],
    tenant_id: str,
    header_idempotency_key: str = "",
) -> Tuple[Dict[str, Any], bool]:
    store.init_db()
    ensure_label_isolation(metadata.model_dump(mode="json"))
    idempotency_key = (header_idempotency_key or metadata.idempotency_key).strip()
    job_id = f"RJ-{uuid4().hex[:16].upper()}"
    assets = await _save_uploads(job_id, metadata, uploads)
    request_hash = _request_hash(metadata, assets)
    existing = store.get_by_idempotency(tenant_id, idempotency_key)
    if existing:
        shutil.rmtree(upload_root() / job_id, ignore_errors=True)
        if store.request_hash(existing["job_id"]) != request_hash:
            raise ValueError("idempotency_key_conflict")
        return existing, False

    stored_metadata = metadata.model_dump(mode="json")
    stored_metadata["ingestion"] = _upload_ingestion_summary(uploads)
    try:
        job = store.create_job(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "client_case_id": metadata.client_case_id,
                "idempotency_key": idempotency_key,
                "scenario": metadata.scenario,
                "metadata": stored_metadata,
                "assets": assets,
            },
            request_hash,
        )
    except sqlite3.IntegrityError as exc:
        shutil.rmtree(upload_root() / job_id, ignore_errors=True)
        existing = store.get_by_idempotency(tenant_id, idempotency_key)
        if existing and store.request_hash(existing["job_id"]) == request_hash:
            return existing, False
        raise ValueError("idempotency_key_conflict") from exc
    enqueue(job_id)
    return job, True


def _workbench_url() -> str:
    configured = os.getenv("VISUAL_WORKBENCH_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return f"http://127.0.0.1:{os.getenv('VISUAL_WORKBENCH_PORT', '7861').strip() or '7861'}"


def _public_workbench_url() -> str:
    return os.getenv("VISUAL_WORKBENCH_PUBLIC_URL", "").strip().rstrip("/") or _workbench_url()


def _public_media_urls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _public_media_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_media_urls(item) for item in value]
    if isinstance(value, str):
        split = urlsplit(value)
        if split.path.startswith(("/media/", "/media-item/")):
            secret = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
            if secret:
                expires = int(time.time()) + max(
                    60,
                    int(os.getenv("VISUAL_REPORT_URL_TTL_SECONDS", "900") or 900),
                )
                message = f"{split.path}\n{expires}".encode("utf-8")
                signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
                fragment = f"#{split.fragment}" if split.fragment else ""
                return f"{_public_workbench_url()}{split.path}?expires={expires}&sig={signature}{fragment}"
            return _public_workbench_url() + value
    return value


def _job_media_urls(value: Any, job_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _job_media_urls(item, job_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_job_media_urls(item, job_id) for item in value]
    if isinstance(value, str):
        split = urlsplit(value)
        match = re.fullmatch(r"/media-item/([0-9a-f]{32})", split.path)
        if match:
            fragment = f"#{split.fragment}" if split.fragment else ""
            return f"/api/v1/review/jobs/{quote(job_id, safe='')}/media/{match.group(1)}{fragment}"
    return value


def _job_media_signature(tenant_id: str, job_id: str, media_id: str, expires: int) -> str:
    secret = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
    if not secret:
        raise ValueError("review_media_signing_unavailable")
    message = f"review-job-media-v1\n{tenant_id}\n{job_id}\n{media_id}\n{expires}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signed_job_media_url(
    tenant_id: str,
    job_id: str,
    media_id: str,
    *,
    expires: Optional[int] = None,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", media_id):
        raise ValueError("review_media_not_found")
    expires_at = int(expires) if expires is not None else int(time.time()) + max(
        60,
        int(os.getenv("VISUAL_REPORT_URL_TTL_SECONDS", "900") or 900),
    )
    signature = _job_media_signature(tenant_id, job_id, media_id, expires_at)
    path = f"/api/v1/review/jobs/{quote(job_id, safe='')}/media/{media_id}"
    return f"{path}?expires={expires_at}&sig={signature}"


def verify_job_media_signature(
    tenant_id: str,
    job_id: str,
    media_id: str,
    expires: Any,
    signature: str,
) -> bool:
    try:
        expires_at = int(expires)
        if expires_at < int(time.time()) or not signature:
            return False
        expected = _job_media_signature(tenant_id, job_id, media_id, expires_at)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(signature, expected)


def _signed_job_media_urls(value: Any, tenant_id: str, job_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _signed_job_media_urls(item, tenant_id, job_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_signed_job_media_urls(item, tenant_id, job_id) for item in value]
    if isinstance(value, str):
        split = urlsplit(value)
        match = re.fullmatch(r"/media-item/([0-9a-f]{32})", split.path)
        if match:
            fragment = f"#{split.fragment}" if split.fragment else ""
            return signed_job_media_url(tenant_id, job_id, match.group(1)) + fragment
    return value


_PUBLIC_AGENT_REPORT_FIELDS = {
    "case_id", "scenario", "scenario_label", "parsed", "quality", "runtime",
    "public_brief", "evidence_package", "media_gallery",
    "business_rule_version",
}
_PRIVATE_PUBLIC_FIELDS = {
    "api_path", "debug", "debug_info", "diagnostics", "display_model", "error",
    "error_type", "file", "internal", "internal_details", "internal_prompt",
    "internal_url", "local_path", "model", "model_key", "model_name",
    "original_name", "path", "prompt", "provider", "raw", "raw_response",
    "raw_text", "source_record", "stored_name", "supplier_debug", "system_prompt",
    "user_prompt",
}
_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:file://|[a-z]:[\\/]|\\\\|/(?:home|users|tmp|var|opt|mnt|private|workspace)(?:/|$))"
)


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_public_value(item)
            for key, item in value.items()
            if str(key).lower() not in _PRIVATE_PUBLIC_FIELDS
        }
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, str) and _LOCAL_PATH_PATTERN.search(value):
        return ""
    return value


def public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    public_job_fields = {
        "job_id", "client_case_id", "scenario", "status", "attempts",
        "created_at", "started_at", "completed_at", "updated_at",
    }
    public_result_fields = {
        "client_case_id", "scenario", "scenario_label", "source_status",
        "media_forensics", "input_readiness", "boundary", "review",
        "recommended_escalation",
    }
    public_review_fields = {
        "review_label", "summary", "frame_strategy", "media_warnings",
        "agent_brief", "agent_report", "media_forensics", "advisory_assessment",
        "report", "sampling",
    }
    output = {
        key: deepcopy(job[key])
        for key in public_job_fields
        if key in job
    }
    output["assets"] = [
        {
            key: deepcopy(asset[key])
            for key in ("asset_id", "mime_type", "size", "fields")
            if key in asset
        }
        for asset in job.get("assets") or []
        if isinstance(asset, dict)
    ]
    raw_result = job.get("result") if isinstance(job.get("result"), dict) else {}
    output["result"] = {
        key: deepcopy(raw_result[key])
        for key in public_result_fields
        if key in raw_result
    }
    raw_review = output["result"].get("review")
    if isinstance(raw_review, dict):
        output["result"]["review"] = {
            key: deepcopy(raw_review[key])
            for key in public_review_fields
            if key in raw_review
        }
        raw_agent_report = output["result"]["review"].get("agent_report")
        if isinstance(raw_agent_report, dict):
            output["result"]["review"]["agent_report"] = {
                key: deepcopy(raw_agent_report[key])
                for key in _PUBLIC_AGENT_REPORT_FIELDS
                if key in raw_agent_report
            }
    output["result"] = _sanitize_public_value(output["result"])
    output["result"] = _job_media_urls(output.get("result") or {}, str(output.get("job_id") or ""))
    return output


def _find_job_media_source(value: Any, media_id: str) -> str:
    if isinstance(value, dict):
        for item in value.values():
            found = _find_job_media_source(item, media_id)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_job_media_source(item, media_id)
            if found:
                return found
    elif isinstance(value, str) and urlsplit(value).path == f"/media-item/{media_id}":
        return value
    return ""


def resolve_job_media_url(job: Dict[str, Any], media_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", media_id):
        raise ValueError("review_media_not_found")
    source = _find_job_media_source(
        (((job.get("result") or {}).get("review") or {}).get("agent_report") or {}),
        media_id,
    )
    if not source:
        raise ValueError("review_media_not_found")
    split = urlsplit(source)
    secret = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
    if secret:
        expires = int(time.time()) + max(60, int(os.getenv("VISUAL_REPORT_URL_TTL_SECONDS", "900") or 900))
        message = f"{split.path}\n{expires}".encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return f"{_workbench_url()}{split.path}?expires={expires}&sig={signature}"
    if split.query:
        return f"{_workbench_url()}{split.path}?{split.query}"
    raise ValueError("review_media_signing_unavailable")


def _effective_review_policies(metadata: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    continuity = dict(metadata.get("continuity_policy") or {})
    causality = dict(metadata.get("damage_causality_policy") or {})
    continuity.setdefault("out_of_frame_warning_seconds", 3.0)
    preset = str((metadata.get("sampling_policy") or {}).get("preset") or "adaptive")
    scenario = str(metadata.get("scenario") or "")
    if preset in {"strong", "strict", "forensic"}:
        continuity["force_dense_scan"] = True
        if scenario == "product_damage":
            causality["force_action_scan"] = True
    return continuity, causality


def _sampling_fields(metadata: Dict[str, Any]) -> Dict[str, str]:
    policy = metadata.get("sampling_policy") or {}
    preset = str(policy.get("preset") or "adaptive")
    if preset == "strong":
        mode, fps, max_frames = "dense", 2.0, min(int(policy.get("max_frames_per_video") or 1800), 1800)
    elif preset == "strict":
        mode, fps, max_frames = "dense", 1.0, min(int(policy.get("max_frames_per_video") or 1200), 1200)
    elif preset == "forensic":
        mode, fps, max_frames = "dense", 2.0, min(int(policy.get("max_frames_per_video") or 1800), 1800)
    elif preset == "custom":
        mode = "dense"
        fps = max(0.1, min(float(policy.get("fps") or 1.0), 2.0))
        max_frames = max(1, min(int(policy.get("max_frames_per_video") or 1200), 1800))
    else:
        mode, fps, max_frames = "adaptive", 1.0, int(os.getenv("REVIEW_ADAPTIVE_MAX_FRAMES", "24") or 24)
    scenario = str(metadata.get("scenario") or "")
    continuity, causality = _effective_review_policies(metadata)
    if scenario in {"product_damage", "wrong_item", "missing_item"} and continuity.get("force_dense_scan") is True:
        warning_seconds = max(0.5, min(float(continuity.get("out_of_frame_warning_seconds") or 3.0), 30.0))
        required_fps = continuity.get("scan_fps")
        if required_fps in (None, ""):
            required_fps = min(2.0, max(0.2, 2.0 / warning_seconds))
        mode = "dense"
        fps = max(fps if preset != "adaptive" else 0.0, float(required_fps))
        max_frames = max(max_frames, min(int(policy.get("max_frames_per_video") or 1200), 1800))
    if scenario == "product_damage" and causality.get("force_action_scan") is True:
        mode = "dense"
        fps = max(fps, 1.0)
        max_frames = max(max_frames, min(int(policy.get("max_frames_per_video") or 1200), 1800))
    frames_per_call = max(1, min(int(policy.get("frames_per_model_call") or 24), 24))
    return {
        "sampling_mode": mode,
        "fps": str(fps),
        "max_frames": str(max_frames),
        "api_frame_limit": str(frames_per_call),
    }


def sampling_plan(
    duration_seconds: float,
    source_bytes: int,
    video_count: int,
    policy: Dict[str, Any],
    scenario: Optional[str] = None,
    continuity_policy: Optional[Dict[str, Any]] = None,
    damage_causality_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fields = _sampling_fields({
        "sampling_policy": policy,
        "scenario": scenario or "",
        "continuity_policy": continuity_policy or {},
        "damage_causality_policy": damage_causality_policy or {},
    })
    mode = fields["sampling_mode"]
    fps = float(fields["fps"])
    max_frames = int(fields["max_frames"])
    frames_per_call = int(fields["api_frame_limit"])
    frames_per_video = (
        min(max_frames, int(math.ceil(duration_seconds * fps)) + 1)
        if mode == "dense"
        else adaptive_frame_budget(duration_seconds, source_bytes, max_frames)
    )
    total_frames = frames_per_video * video_count
    effective_continuity, effective_causality = _effective_review_policies({
        "sampling_policy": policy,
        "scenario": scenario or "",
        "continuity_policy": continuity_policy or {},
        "damage_causality_policy": damage_causality_policy or {},
    })
    unified_multitask_enabled = (
        scenario == "product_damage"
        and effective_continuity.get("force_dense_scan") is True
        and effective_causality.get("force_action_scan") is True
    )
    representative_main_enabled = False
    main_review_frame_limit = max(
        24,
        min(int(os.getenv("REVIEW_PRODUCT_DAMAGE_MAIN_MAX_FRAMES", "48") or 48), 96),
    )
    main_review_frames = min(total_frames, main_review_frame_limit) if representative_main_enabled else total_frames
    segments = max(1, math.ceil(main_review_frames / frames_per_call))
    continuity_enabled = effective_continuity.get("force_dense_scan") is True and scenario in {
        "wrong_item", "missing_item", "product_damage"
    } and not unified_multitask_enabled
    continuity_chunk_frames = max(
        12,
        min(int(os.getenv("REVIEW_CONTINUITY_FRAMES_PER_CALL", "24") or 24), 24),
    )
    continuity_segments = math.ceil(total_frames / continuity_chunk_frames) if continuity_enabled else 0
    causality_enabled = (
        scenario == "product_damage"
        and effective_causality.get("force_action_scan") is True
        and not unified_multitask_enabled
    )
    causality_chunk_frames = max(8, min(int(effective_causality.get("dedicated_chunk_frames") or 20), 24))
    causality_segments = math.ceil(total_frames / causality_chunk_frames) if causality_enabled else 0
    fallback_continuity_segments = (
        math.ceil(total_frames / continuity_chunk_frames) if unified_multitask_enabled else 0
    )
    fallback_causality_segments = (
        math.ceil(total_frames / causality_chunk_frames) if unified_multitask_enabled else 0
    )
    estimated_total_calls = segments + continuity_segments + causality_segments
    worker_env = "REVIEW_MINOR_WORKERS" if scenario == "minor_refund" else "REVIEW_CHUNK_WORKERS"
    worker_default = "6" if scenario == "minor_refund" else "2"
    worker_cap = 8 if scenario == "minor_refund" else 4
    chunk_workers = max(1, min(int(os.getenv(worker_env, worker_default) or worker_default), worker_cap))
    return {
        "preset": policy.get("preset") or "adaptive",
        "sampling_mode": mode,
        "fps": fps,
        "estimated_frames_per_video": frames_per_video,
        "estimated_total_frames": total_frames,
        "main_review_frames": main_review_frames,
        "main_review_strategy": "unified_dense_multitask" if unified_multitask_enabled else "all_sampled_frames",
        "frames_per_model_call": frames_per_call,
        "continuity_frames_per_call": continuity_chunk_frames,
        "continuity_frames_per_call_by_transport": {
            "gemini_native_individual_frames": continuity_chunk_frames,
            "openai_compatible_individual_frames": continuity_chunk_frames,
        },
        "estimated_model_segments": segments,
        "estimated_channel_calls": {
            "main_review": segments,
            "object_continuity": continuity_segments,
            "damage_causality": causality_segments,
        },
        "estimated_total_model_calls": estimated_total_calls,
        "unified_multitask": {
            "enabled": unified_multitask_enabled,
            "primary_transport": "gemini_native",
            "fallback_policy": "仅补统一结果缺失的结构化维度",
            "fallback_channel_calls": {
                "object_continuity": fallback_continuity_segments,
                "damage_causality": fallback_causality_segments,
            },
        },
        "effective_review_policies": {
            "continuity_policy": effective_continuity,
            "damage_causality_policy": effective_causality,
        },
        "estimated_parallel_waves": math.ceil(estimated_total_calls / chunk_workers),
        "chunk_workers": chunk_workers,
        "transcode_recommended": source_bytes >= 500 * 1024 * 1024 or duration_seconds >= 600,
        "large_media_route": "object_storage_transcode_proxy" if source_bytes >= 500 * 1024 * 1024 or duration_seconds >= 600 else "direct_upload_and_frame_sampling",
    }


def _review_fields(job: Dict[str, Any]) -> Dict[str, str]:
    metadata = job.get("metadata") or {}
    continuity_policy, damage_causality_policy = _effective_review_policies(metadata)
    return {
        "rule_tenant_id": str(job.get("tenant_id") or ""),
        "scenario": SCENARIO_MAP[job["scenario"]],
        "business_scenario": job["scenario"],
        "ticket_id": str(metadata.get("ticket_id") or job["client_case_id"]),
        "user_id": str(metadata.get("user_id") or ""),
        "order_no": str(metadata.get("order_no") or ""),
        "customer_claim": str(metadata.get("customer_claim") or ""),
        "order_item": json.dumps(metadata.get("order_items") or [], ensure_ascii=False),
        "sku": ",".join(str(item.get("sku") or "") for item in metadata.get("order_items") or [] if item.get("sku")),
        "logistics_status": json.dumps(metadata.get("logistics") or {}, ensure_ascii=False),
        "logistics_context": json.dumps(metadata.get("logistics") or {}, ensure_ascii=False),
        "complaint_stage": str(metadata.get("complaint_stage") or ""),
        "product_master_data": json.dumps(metadata.get("product_master_data") or {}, ensure_ascii=False),
        "warehouse_master_data": json.dumps(metadata.get("warehouse_master_data") or {}, ensure_ascii=False),
        "conversation_history": json.dumps(metadata.get("conversation_history") or [], ensure_ascii=False),
        "customer_tone": str(metadata.get("customer_tone") or ""),
        "sop_context": json.dumps(metadata.get("sop_context") or {}, ensure_ascii=False),
        "asset_manifest": json.dumps(
            {
                "assets": job.get("assets") or [],
                "fulfillment_baseline": metadata.get("fulfillment_baseline") or {},
                "evidence_coverage": metadata.get("evidence_coverage") or {},
            },
            ensure_ascii=False,
        ),
        "fulfillment_baseline": json.dumps(metadata.get("fulfillment_baseline") or {}, ensure_ascii=False),
        "evidence_coverage": json.dumps(metadata.get("evidence_coverage") or {}, ensure_ascii=False),
        "claim_scope": json.dumps(metadata.get("claim_scope") or {}, ensure_ascii=False),
        "continuity_policy": json.dumps(continuity_policy, ensure_ascii=False),
        "damage_causality_policy": json.dumps(damage_causality_policy, ensure_ascii=False),
        "review_routing_policy": json.dumps(metadata.get("review_routing_policy") or {}, ensure_ascii=False),
        "minor_refund_policy": json.dumps(metadata.get("minor_refund_policy") or {}, ensure_ascii=False),
        "defer_postprocess": "true",
        "include_html_report": "false",
        **_sampling_fields(metadata),
        "probe_seconds": os.getenv("REVIEW_PROBE_SECONDS", "12"),
    }


def _validate_workbench_health(
    payload: Dict[str, Any],
    *,
    expected_soft_limit: int,
    expected_safe_limit: int,
) -> None:
    capacity = payload.get("asset_capacity") or {}
    if (
        payload.get("ok") is not True
        or payload.get("review_contract_version") != REVIEW_CONTRACT_VERSION
        or capacity.get("soft_limit") != expected_soft_limit
        or capacity.get("safe_limit") != expected_safe_limit
    ):
        raise ValueError("visual_workbench_contract_mismatch")


def _workbench_request_policy() -> tuple[int, int]:
    timeout_seconds = max(30, int(os.getenv("REVIEW_JOB_TIMEOUT_SECONDS", "1800") or 1800))
    retries = max(0, min(int(os.getenv("REVIEW_WORKBENCH_RETRIES", "2") or 2), 4))
    return timeout_seconds, retries


def _workbench_lease_seconds(job: Dict[str, Any]) -> int:
    timeout_seconds, retries = _workbench_request_policy()
    backoff_seconds = sum(min(2 ** attempt, 4) for attempt in range(retries))
    video_count = sum(
        1
        for asset in job.get("assets") or []
        if is_video_asset(asset)
    )
    return (
        video_count * forensics_timeout_seconds()
        + timeout_seconds * (retries + 1)
        + backoff_seconds
        + 60
    )


def _call_workbench(job: Dict[str, Any]) -> Dict[str, Any]:
    job_dir = upload_root() / job["job_id"]
    timeout_seconds, retries = _workbench_request_policy()
    retryable = {429, 502, 503, 504}
    attempts: List[Dict[str, Any]] = []
    payload: Any = None
    internal_token = os.getenv("VISUAL_REPORT_SIGNING_SECRET", "").strip()
    if not internal_token:
        raise ValueError("visual_internal_token_required")
    soft_limit, safe_limit = _review_asset_limits()
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0), trust_env=False) as client:
        health = client.get(f"{_workbench_url()}/api/health")
    if health.status_code != 200:
        raise ValueError("visual_workbench_contract_mismatch")
    _validate_workbench_health(
        health.json(),
        expected_soft_limit=soft_limit,
        expected_safe_limit=safe_limit,
    )
    for attempt in range(1, retries + 2):
        with ExitStack() as stack:
            files = []
            for asset in job.get("assets") or []:
                path = job_dir / asset["stored_name"]
                if not path.exists():
                    raise FileNotFoundError(f"审核素材不存在：{asset['asset_id']}")
                handle = stack.enter_context(path.open("rb"))
                files.append(("files", (asset["original_name"], handle, asset["mime_type"])))
            timeout = httpx.Timeout(timeout_seconds, connect=10, write=timeout_seconds, read=timeout_seconds)
            started = time.time()
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(
                    f"{_workbench_url()}/api/review-folder",
                    headers={
                        "X-Request-ID": f"{job['job_id']}-workbench-{attempt}",
                        "X-MITAKO-Internal-Metrics": "1",
                        "X-MITAKO-Internal-Token": internal_token,
                    },
                    data=_review_fields(job),
                    files=files,
                )
        attempts.append(
            {
                "attempt": attempt,
                "status_code": response.status_code,
                "latency_seconds": round(time.time() - started, 3),
            }
        )
        if response.status_code in retryable and attempt <= retries:
            time.sleep(min(2 ** (attempt - 1), 4))
            continue
        if response.is_error:
            raise WorkbenchRequestError(response.status_code, attempts)
        payload = response.json()
        break
    if not isinstance(payload, dict):
        raise ValueError("invalid_visual_review_response")
    payload["_workbench_transport"] = {"attempts": attempts, "retry_count": max(0, len(attempts) - 1)}
    return payload


def _media_forensics(job: Dict[str, Any]) -> Dict[str, Any]:
    metadata = job.get("metadata") or {}
    policy = metadata.get("sampling_policy") or {}
    configured_checks = policy.get("forensic_checks")
    checks = None if configured_checks is True else ([] if configured_checks is False else configured_checks)
    try:
        return inspect_job_media(
            upload_root() / job["job_id"],
            job.get("assets") or [],
            checks=checks,
        )
    except Exception:
        return {
            "status": "unavailable",
            "checks": checks if isinstance(checks, list) else [],
            "assets": [],
            "summary": {
                "video_assets": sum(
                    1
                    for item in job.get("assets") or []
                    if str(item.get("mime_type") or "").lower().startswith("video/")
                ),
                "analyzed_assets": 0,
                "unavailable_assets": 0,
                "risk_signal_count": 0,
                "risk_level": "none",
            },
            "unavailable_reason": "media_forensics_internal_error",
            "interpretation": "媒体取证本轮不可用，不能据此判断视频是否被剪辑、替换或篡改。",
        }


def _recommended_escalation(
    job: Dict[str, Any],
    review: Dict[str, Any],
    forensics: Dict[str, Any],
) -> Dict[str, Any]:
    metadata = job.get("metadata") or {}
    sampling_policy = metadata.get("sampling_policy") or {}
    preset = str(sampling_policy.get("preset") or "adaptive")
    current_fps = float(_sampling_fields(metadata)["fps"])
    advisory = review.get("advisory_assessment") if isinstance(review.get("advisory_assessment"), dict) else {}
    human_review = advisory.get("human_review") if isinstance(advisory.get("human_review"), dict) else {}
    workflow = str(advisory.get("workflow_recommendation") or "human_review")
    level = str(human_review.get("level") or "required")
    reason_codes = [str(item) for item in human_review.get("reason_codes") or []]
    signals = [item for item in advisory.get("signals") or [] if isinstance(item, dict)]
    reasons = [{"code": code, "message": str(human_review.get("recommendation") or "")} for code in reason_codes]
    reasons.extend(
        {"code": str(item.get("code") or "risk_signal"), "message": str(item.get("effect") or "")}
        for item in signals
        if str(item.get("code") or "") not in reason_codes
    )
    parsed = (
        (review.get("agent_report") or {}).get("parsed")
        if isinstance(review.get("agent_report"), dict)
        else {}
    ) or {}
    video_audit = parsed.get("video_audit_conclusion") if isinstance(parsed, dict) else {}
    video_audit = video_audit if isinstance(video_audit, dict) else {}
    speed_impact = video_audit.get("speed_review_impact")
    speed_impact = speed_impact if isinstance(speed_impact, dict) else {}

    actions: List[Dict[str, Any]] = []
    if workflow == "system_retry":
        actions.append({
            "type": "retry_review_case",
            "full_case_retry": True,
            "may_repeat_model_cost": True,
            "description": "当前请求已完成结构修复和逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型调用成本。",
        })
    elif workflow == "request_more_material":
        actions.append({
            "type": "request_more_material",
            "description": "按缺口清单补充业务证据；增加抽帧强度不能替代缺失材料。",
        })
    elif workflow == "human_review":
        actions.append({
            "type": "human_evidence_review",
            "description": "由授权人员核对原始证据，业务动作仍由甲方规则决定。",
        })
    elif level == "optional":
        actions.append({
            "type": "optional_quality_sampling",
            "description": "甲方可按风险偏好抽检，不要求每单人工复审。",
        })

    visual_signal_codes = {"short_out_of_frame", "identity_reestablishment_unresolved", "media_forensic_risk"}
    if workflow != "request_more_material" and any(str(item.get("code") or "") in visual_signal_codes for item in signals):
        target_preset, target_fps = ("strong", 1.0) if preset == "adaptive" else ("forensic", 2.0)
        if target_fps > current_fps or preset == "adaptive":
            actions.append({
                "type": "increase_sampling_strength",
                "target_preset": target_preset,
                "target_fps": target_fps,
                "bounded": True,
                "description": "仅在疑点可能通过更密抽帧获得新证据时建议强化，不因材料缺口重复烧模型。",
            })

    speed_status = str(speed_impact.get("status") or "none").lower()
    if (
        video_audit.get("playback_speed") == "accelerated"
        and speed_status in {"uncertain", "material"}
        and current_fps < 2.0
        and workflow != "request_more_material"
    ):
        sampling_action = next(
            (item for item in actions if item.get("type") == "increase_sampling_strength"),
            None,
        )
        if sampling_action is None:
            sampling_action = {"type": "increase_sampling_strength"}
            actions.append(sampling_action)
        sampling_action.update({
            "target_preset": "forensic",
            "target_fps": 2.0,
            "bounded": True,
            "description": "疑似加速使关键节点在当前抽帧密度下无法判断，建议受控提升到 2 FPS 强化复核；不因加速本身判负。",
        })

    return {
        "recommended": bool(actions),
        "policy_auto_escalate": bool(sampling_policy.get("auto_escalate")),
        "execution_mode": "recommendation_only",
        "source": "advisory_assessment",
        "automatic_model_retries": 0,
        "current": {"preset": preset, "fps": current_fps},
        "reasons": reasons,
        "actions": actions,
        "boundary": "本计划不自动重复调用模型，也不自动执行退款、补发、换货、拒绝或最终定责。",
    }


def _apply_input_readiness_guard(review: Dict[str, Any], readiness: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(review)
    if readiness.get("full_review_ready") is True:
        return output
    missing = [str(item) for item in readiness.get("missing_required") or []]
    agent_report = dict(output.get("agent_report") or {})
    parsed = dict(agent_report.get("parsed") or {})
    try:
        confidence = min(float(parsed.get("confidence") or 0.5), 0.69)
    except (TypeError, ValueError):
        confidence = 0.5
    parsed.update(
        {
            "predicted_label": "review",
            "system_yes_no": "REVIEW",
            "decision": "request_more_material",
            "confidence": confidence,
            "business_action_allowed": False,
            "human_required": False,
            "input_readiness_guard": {
                "applied": True,
                "missing_required": missing,
                "reason": "缺少支撑该场景确定判断的订单、履约或证据覆盖基准。",
            },
        }
    )
    material_gaps = [str(item) for item in parsed.get("material_gaps") or []]
    parsed["material_gaps"] = list(dict.fromkeys(material_gaps + missing))
    agent_report["parsed"] = parsed
    output["agent_report"] = agent_report
    output["input_readiness_guard"] = parsed["input_readiness_guard"]
    summary = dict(output.get("summary") or {})
    summary.update(
        {
            "predicted_label": "review",
            "system_yes_no": "REVIEW",
            "confidence": confidence,
            "input_readiness_guard_applied": True,
        }
    )
    output["summary"] = summary
    brief = dict(output.get("agent_brief") or {})
    brief["conclusion"] = "当前业务基准或必需材料不完整，现有证据不足以形成明确事实判断。"
    output["agent_brief"] = brief
    return output


def postprocess_review(
    job: Dict[str, Any],
    review: Dict[str, Any],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    media_forensics: Optional[Dict[str, Any]] = None,
    succeeded: bool = True,
) -> Dict[str, Any]:
    """网页工作台和正式 API 共用的审核后处理顺序。"""
    metadata = job.get("metadata") or {}
    resolved_readiness = readiness if readiness is not None else assess_input_readiness(metadata)
    output = dict(review)
    if succeeded:
        output = _apply_input_readiness_guard(output, resolved_readiness)
        output = apply_review_decision_policy(job, output, media_forensics=media_forensics)
    return attach_advisory_assessment(
        output,
        metadata,
        readiness=resolved_readiness,
        media_forensics=media_forensics,
        succeeded=succeeded,
    )


def _sync_final_advisory_brief(review: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(review)
    advisory = output.get("advisory_assessment") if isinstance(output.get("advisory_assessment"), dict) else {}
    assessment = advisory.get("assessment") if isinstance(advisory.get("assessment"), dict) else {}
    human_review = advisory.get("human_review") if isinstance(advisory.get("human_review"), dict) else {}
    conclusion = str(assessment.get("conclusion") or "").strip()
    next_step = str(human_review.get("recommendation") or "").strip()
    if not conclusion and not next_step:
        return output

    brief = dict(output.get("agent_brief") or {})
    if conclusion:
        brief["conclusion"] = conclusion
    if next_step:
        brief["next_step"] = next_step
    output["agent_brief"] = brief

    agent_report = dict(output.get("agent_report") or {})
    public_brief = dict(agent_report.get("public_brief") or {})
    if conclusion:
        public_brief["conclusion"] = conclusion
    if next_step:
        public_brief["next_step"] = next_step
    agent_report["public_brief"] = public_brief
    parsed = dict(agent_report.get("parsed") or {})
    if next_step:
        parsed["next_step"] = next_step
    agent_report["parsed"] = parsed
    output["agent_report"] = agent_report
    return output


def run_job(job_id: str) -> Dict[str, Any]:
    queued_job = store.get_job(job_id) or {}
    if not store.claim_job(job_id, _workbench_lease_seconds(queued_job)):
        return queued_job or store.get_job(job_id) or {}
    job = store.get_job(job_id) or {}
    forensics = _media_forensics(job)
    readiness = assess_input_readiness(job.get("metadata") or {})
    base_result = {
        "trace_id": job_id,
        "client_case_id": job.get("client_case_id"),
        "scenario": job.get("scenario"),
        "scenario_label": SCENARIO_LABELS.get(job.get("scenario"), job.get("scenario")),
        "media_forensics": forensics,
        "input_readiness": readiness,
        "boundary": "审核服务只输出证据、置信度和流程建议；退款、补发、换货、拒绝及最终定责由甲方系统和授权人员执行。",
    }
    try:
        payload = _call_workbench(job)
        workbench_transport = payload.pop("_workbench_transport", {})
        review = dict(payload.get("review")) if isinstance(payload.get("review"), dict) else {}
        review = postprocess_review(
            job,
            review,
            readiness=readiness,
            media_forensics=forensics,
            succeeded=payload.get("ok") is True,
        )
        review = _sync_final_advisory_brief(review)
        review.pop("report", None)
        if html_report_requested(job):
            review["report"] = {
                "requested": True,
                "status": "ready",
                "html_url": f"/api/v1/review/jobs/{job_id}/report",
            }
        else:
            review["report"] = {"requested": False, "status": "not_requested", "html_url": None}
        diagnostics = review.get("diagnostics") or payload.get("diagnostics") or {}
        result = {
            **base_result,
            "source_status": payload.get("source_status"),
            "review": review,
            "recommended_escalation": _recommended_escalation(job, review, forensics),
            "workbench_transport": workbench_transport,
        }
        status = "SUCCEEDED" if payload.get("ok") is True else "FAILED"
        return store.finish_job(job_id, status=status, result=result, diagnostics=diagnostics)
    except WorkbenchRequestError as exc:
        diagnostics = {
            "error_type": "workbench_http_error",
            "status_code": exc.status_code,
            "attempts": exc.attempts,
        }
    except Exception as exc:
        diagnostics = {"error_type": exc.__class__.__name__, "message": str(exc)[:1200]}
    failed_review = attach_advisory_assessment(
        {
            "summary": {"review_status": "failed", "predicted_label": "review"},
            "agent_brief": {"conclusion": "审核服务本轮未完成，不能形成事实判断。"},
            "agent_report": {"parsed": {"predicted_label": "review"}},
            "diagnostics": diagnostics,
        },
        job.get("metadata") or {},
        readiness=readiness,
        media_forensics=forensics,
        succeeded=False,
    )
    if html_report_requested(job):
        failed_review["report"] = {"requested": True, "status": "unavailable", "html_url": None}
    else:
        failed_review["report"] = {"requested": False, "status": "not_requested", "html_url": None}
    base_result["review"] = failed_review
    base_result["recommended_escalation"] = _recommended_escalation(job, failed_review, forensics)
    return store.finish_job(job_id, status="FAILED", result=base_result, diagnostics=diagnostics)


def render_job_report(job: Dict[str, Any]) -> str:
    result = job.get("result") or {}
    review = _sync_final_advisory_brief(result.get("review") or {})
    agent_report = deepcopy(review.get("agent_report") or {})
    agent_report.pop("inference_estimate", None)
    agent_report = _signed_job_media_urls(
        agent_report,
        str(job.get("tenant_id") or "mitako"),
        str(job.get("job_id") or ""),
    )
    brief = review.get("agent_brief") or {}
    data = {
        "ok": job.get("status") == "SUCCEEDED",
        "review_label": review.get("review_label") or result.get("scenario_label") or "审核结果",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job.get("completed_at") or time.time())),
        "summary": review.get("summary") or {},
        "advisory_assessment": review.get("advisory_assessment") or {},
        "conclusion": brief.get("conclusion") or "本轮审核尚未形成可复核结论。",
        "agent_report": agent_report,
        "media_forensics": result.get("media_forensics") or {},
        "diagnostics": job.get("diagnostics") or review.get("diagnostics") or {},
    }
    return render_public_report(data)


def enqueue(job_id: str) -> None:
    EXECUTOR.submit(run_job, job_id)


def recover_jobs() -> None:
    for job_id in store.recover_incomplete():
        enqueue(job_id)


def retry_job(job_id: str) -> Dict[str, Any]:
    job = store.queue_retry(job_id)
    if not job:
        raise ValueError("review_job_not_retryable")
    enqueue(job_id)
    return job


def metrics(tenant_id: str = "") -> Dict[str, Any]:
    return {**store.snapshot(tenant_id), "workers": MAX_WORKERS}


def runtime_readiness() -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    ffprobe = resolve_ffprobe()
    checks["ffprobe"] = {
        "ready": bool(ffprobe),
        "source": "REVIEW_FFPROBE_PATH" if os.getenv("REVIEW_FFPROBE_PATH", "").strip() else "PATH",
    }
    root = upload_root()
    probe = root / f".readiness-{uuid4().hex}"
    try:
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        disk = shutil.disk_usage(root)
        required = _limit_bytes("REVIEW_MAX_CASE_MB", 750) * 3
        checks["upload_storage"] = {
            "ready": disk.free >= required,
            "free_bytes": disk.free,
            "minimum_free_bytes": required,
            "writable": True,
        }
    except OSError as exc:
        checks["upload_storage"] = {
            "ready": False,
            "writable": False,
            "error_type": exc.__class__.__name__,
        }
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0), trust_env=False) as client:
            response = client.get(f"{_workbench_url()}/api/health")
        health_payload = response.json()
        soft_limit, safe_limit = _review_asset_limits()
        _validate_workbench_health(
            health_payload,
            expected_soft_limit=soft_limit,
            expected_safe_limit=safe_limit,
        )
        checks["visual_workbench"] = {
            "ready": response.status_code == 200,
            "status_code": response.status_code,
            "review_contract_version": health_payload.get("review_contract_version"),
        }
    except Exception as exc:
        checks["visual_workbench"] = {"ready": False, "error_type": exc.__class__.__name__}
    return {
        "ready": all(bool(item.get("ready")) for item in checks.values()),
        "checks": checks,
        "acceptance_boundary": "生产编排应只在 ready=true 时接收新审核任务。",
    }


def batch_status(tenant_id: str, batch_id: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    jobs = store.list_batch(tenant_id, batch_id, limit=limit, offset=offset)
    aggregate = store.batch_snapshot(tenant_id, batch_id)
    counts = {str(item.get("status") or "UNKNOWN"): int(item.get("count") or 0) for item in aggregate}
    total_tokens = sum(int(item.get("total_tokens") or 0) for item in aggregate)
    estimated_usd = sum(float(item.get("estimated_usd") or 0) for item in aggregate)
    total = sum(counts.values())
    terminal = counts.get("SUCCEEDED", 0) + counts.get("FAILED", 0)
    return {
        "batch_id": batch_id,
        "summary": {
            "total": total,
            "terminal": terminal,
            "complete": total > 0 and terminal == total,
            "statuses": counts,
            "inference_total_tokens": total_tokens,
            "inference_estimated_usd": round(estimated_usd, 6),
            "returned": len(jobs),
            "offset": offset,
        },
        "jobs": [public_job(job) for job in jobs],
    }


def contract() -> Dict[str, Any]:
    return {
        "version": "v1",
        "submission": "每个案件独立提交；批量任务由调用方并发提交，案件之间独立重试和查询。",
        "endpoint": "POST /api/v1/review/jobs",
        "metadata_validation_endpoint": "POST /api/v1/review/metadata/validate",
        "sampling_plan_endpoint": "POST /api/v1/review/sampling-plan",
        "batch_status_endpoint": "GET /api/v1/review/batches/{batch_id}",
        "html_report_endpoint": "GET /api/v1/review/jobs/{job_id}/report",
        "readiness_endpoint": "GET /api/v1/review/readiness",
        "content_type": "multipart/form-data",
        "auth": "Bearer 集成账号 Token",
        "idempotency_header": "Idempotency-Key",
        "supported_scenarios": list(SCENARIO_MAP),
        "required_metadata": ["client_case_id", "scenario"],
        "scenario_input_readiness": {
            "wrong_item": "需要可唯一确定应收商品的版本化订单基准、显式抽赏规则状态、包裹商品映射和已提交包裹归属；SKU 优先，但可唯一商品组合可替代。",
            "product_damage": "SKU/商品主数据为推荐增信字段，不是识别明显损伤或审核视频连续性的硬门槛。",
            "missing_item": "通常需要完整应发清单、规则状态、包裹映射、证据覆盖和签收快照；甲方提供可追溯仓库终核时，可直接采用该终态。",
            "opening_continuity": "独立于 SKU，按快递包装、商品包装和争议商品分别跟踪离镜时间线。",
        },
        "business_fields": [
            "ticket_id", "user_id", "order_no", "customer_claim", "order_items",
            "product_master_data", "warehouse_master_data", "logistics",
            "conversation_history", "sop_context", "asset_fields", "batch_id", "source_record",
            "claim_scope", "decision_policy", "fulfillment_baseline", "evidence_coverage",
            "sampling_policy", "continuity_policy", "damage_causality_policy",
            "output_options", "review_routing_policy", "minor_refund_policy", "customer_risk_context",
        ],
        "customer_risk_context_policy": {
            "purpose": "仅用于服务端抽检优先级和人工复审路由，不参与本次事实证据结论。",
            "model_input": False,
            "automatic_rejection_allowed": False,
            "privacy": "只接收最小化聚合统计，不接收历史对话正文、手机号、证件号或其他身份明文。",
        },
        "warehouse_verification_policy": {
            "field": "fulfillment_baseline.warehouse_verification",
            "source": "customer_warehouse",
            "terminal_statuses": ["confirmed_missing", "confirmed_not_missing"],
            "required_fields": ["status", "source", "verification_ref"],
            "trust_boundary": "仅甲方提供且可追溯的仓库终核可覆盖历史待核实备注；模型推断和 pending 状态均不得覆盖证据门禁。",
        },
        "asset_types": sorted(ALLOWED_SUFFIXES),
        "input_isolation": "人工结论、标准答案和评测标签不得进入 metadata 或素材文件。",
        "media_processing": {
            "model_input": "服务端本地完成全时轴抽帧、压缩和分段；细节、连续性与成因通道均逐张发送带帧号和时间戳的 JPEG 独立帧。原视频和拼图均不作为模型审核输入。",
            "model_request_transport": "inline_base64_images",
            "supplier_file_uri_required": False,
            "detail_frame_format": "image/jpeg",
            "temporal_sheet_format": "image/webp",
            "official_product_references": {
                "mode": "per_review_on_demand",
                "bulk_download_enabled": False,
                "transport": "服务端白名单下载、校验、压缩后以内联图片发送，不依赖供应商文件 URI。",
                "failure_policy": "下载失败时保留 SKU/应发清单文字基线并输出降级状态。",
            },
            "single_asset_limit_mb": _limit_bytes("REVIEW_MAX_ASSET_MB", 650) // (1024 * 1024),
            "case_limit_mb": _limit_bytes("REVIEW_MAX_CASE_MB", 750) // (1024 * 1024),
            "large_batch": "120GB 级生产批次应由对象存储直传、云转码/故事板服务和案件引用适配层承接；当前未伪装为已接入。",
        },
        "sampling_presets": {
            "adaptive": "按时长和文件大小抽取 6-24 帧并执行一次主审核；专项连续性与损伤成因检查仅由更强档位或显式策略启用。",
            "strong": "固定 2 fps，最多 1800 帧；用于离镜、动作前后和争议时点强化复核。",
            "strict": "固定 1 fps，最多 1200 帧，每 24 帧一个并行模型分段。",
            "forensic": "固定 2 fps，最多 1800 帧，每 24 帧一个并行模型分段。",
            "custom": "甲方配置 0.1-2 fps、单视频帧上限和每次调用帧数。",
        },
        "sampling_policy_fields": {
            "auto_escalate": "仅生成有界的推荐升级计划，不自动重复调用模型。",
            "confidence_threshold": "0-1 的升级建议置信度阈值，默认 0.75。",
            "forensic_checks": "可选的容器完整性、流一致性、帧率、包时间轴和编辑器元数据检查列表。",
        },
        "continuity_policy_fields": {
            "out_of_frame_warning_seconds": "0.5-30 秒，默认 3 秒；达到后建议补充连续原视频，不自动拒绝，也不单独强制人工复核。",
            "require_identity_reestablishment": "主体重新入镜后要求核验是否仍为同一物件。",
            "force_dense_scan": "开启时按离镜阈值反推最低时间分辨率，避免稀疏抽帧声称全程连续。",
            "scan_fps": "可选 0.2-2 FPS；为空时自动使用 min(2, max(0.2, 2/离镜阈值秒数))。",
        },
        "output_options": {
            "include_html_report": "默认 true；设为 false 时只返回结构化 JSON，报告路由返回 review_report_not_requested。",
        },
        "review_routing_policy": {
            "required_below_confidence": "低于该证据分数时建议必须人工复审，默认 0.5。",
            "optional_below_confidence": "低于该证据分数时建议抽检，默认 0.8。",
            "out_of_frame_resubmit_seconds": "连续离镜达到该秒数时建议补充材料，默认 3 秒；离镜本身不等于剪辑、调包或欺诈。",
        },
        "minor_refund_policy": {
            "review_mode": "standard 为 SOP 五类材料和视觉一致性初审；strict 保留更严格的人工抽检策略。",
            "authoritative_verification": "disabled（默认，不因未接接口阻断）、advisory（仅提示）或 required（未完成则必须人工复审）。",
        },
        "decision_policy_fields": {
            "mode": "默认 conservative_review；只有甲方显式选择 classification_recommendation 才评估规则判负。",
            "opening_video_required": "商品有伤是否必须提供开箱视频。",
            "missing_required_opening_video": "review 或 negative；仅影响审核分类建议，不执行拒绝业务动作。",
            "complete_video_no_claimed_damage": "只有完整性、同物关联、主张部位特写、必检视角、无冲突和置信度门槛全部满足时才可 negative。",
            "claim_scope": "明确本次诉求阶段、原子诉求、商品与证据范围，后续追加诉求不得混入当前结论。",
        },
        "media_forensics": "模型调用前执行 ffprobe 元数据检查；不可用时明确降级，风险信号不等同于已证实剪辑。",
        "statuses": ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RETRYING"],
        "result_fields": [
            "predicted_label", "confidence", "agent_report", "agent_brief", "media_forensics",
            "advisory_assessment", "report", "recommended_escalation", "input_readiness", "diagnostics", "boundary",
        ],
        "primary_result_contract": {
            "assessment": "事实结论、证据分数和未校准口径。",
            "human_review": "required、optional、not_required 三级建议。",
            "workflow_recommendation": "human_review、request_more_material、continue_by_customer_policy。",
            "signals": "离镜、证据冲突、材料缺口和媒体取证等可追溯信号。",
            "business_boundary": "所有输出均为建议；不直接执行退款、补发、换货、拒绝或最终定责。",
        },
        "boundary": "不自动退款、补发、换货、拒绝或最终定责。",
    }
