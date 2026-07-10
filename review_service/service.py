# -*- coding: utf-8 -*-
"""审核案件上传、排队与视觉工作台调用。"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from uuid import uuid4

import httpx
from fastapi import UploadFile

from runtime_paths import data_dir
from poc.visual_review_poc.report_renderer import render_public_report

from . import store
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
EVALUATION_LABEL_KEYS = {
    "expected_predicted_label",
    "human_conclusion",
    "previous_human_conclusion",
    "ground_truth",
    "groundtruth",
    "ground_truth_label",
    "expected_label",
    "manual_label",
    "reference_label",
    "final_label",
    "gold_label",
    "人工结论",
    "标准答案",
    "样本标签",
}
EVALUATION_LABEL_MARKERS = (
    "expected_predicted_label",
    "human_conclusion",
    "ground_truth",
    "标准答案：",
    "标准答案=",
    "正确答案：",
    "正确答案=",
    "正向样本",
    "负向样本",
)


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


def _valid_magic(suffix: str, head: bytes) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    if suffix in {".mp4", ".mov", ".m4v"}:
        return b"ftyp" in head[:32]
    if suffix in {".webm", ".mkv"}:
        return head.startswith(b"\x1aE\xdf\xa3")
    return suffix in {".txt", ".json"}


def ensure_label_isolation(value: Any) -> None:
    """评测标签只能在模型返回后离线比对，禁止进入审核输入。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in EVALUATION_LABEL_KEYS:
                raise ValueError("evaluation_label_not_allowed")
            ensure_label_isolation(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            ensure_label_isolation(item)
        return
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in EVALUATION_LABEL_MARKERS):
            raise ValueError("evaluation_label_not_allowed")


def _request_hash(metadata: ReviewCaseMetadata, uploads: Sequence[UploadFile]) -> str:
    basis = {
        "metadata": metadata.model_dump(mode="json"),
        "files": [
            {"name": item.filename or "", "content_type": item.content_type or ""}
            for item in uploads
        ],
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def _save_uploads(job_id: str, metadata: ReviewCaseMetadata, uploads: Sequence[UploadFile]) -> List[Dict[str, Any]]:
    if not uploads:
        raise ValueError("review_assets_required")
    if len(uploads) > int(os.getenv("REVIEW_MAX_ASSETS", "40") or 40):
        raise ValueError("too_many_review_assets")

    max_asset = _limit_bytes("REVIEW_MAX_ASSET_MB", 650)
    max_case = _limit_bytes("REVIEW_MAX_CASE_MB", 750)
    target_dir = upload_root() / job_id
    target_dir.mkdir(parents=True, exist_ok=False)
    assets: List[Dict[str, Any]] = []
    total_case = 0
    try:
        for index, upload in enumerate(uploads, start=1):
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
            if not _valid_magic(suffix, head):
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
    request_hash = _request_hash(metadata, uploads)
    existing = store.get_by_idempotency(tenant_id, idempotency_key)
    if existing:
        if store.request_hash(existing["job_id"]) != request_hash:
            raise ValueError("idempotency_key_conflict")
        return existing, False

    job_id = f"RJ-{uuid4().hex[:16].upper()}"
    assets = await _save_uploads(job_id, metadata, uploads)
    try:
        job = store.create_job(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "client_case_id": metadata.client_case_id,
                "idempotency_key": idempotency_key,
                "scenario": metadata.scenario,
                "metadata": metadata.model_dump(mode="json"),
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
    if isinstance(value, str) and value.startswith("/media/"):
        return _public_workbench_url() + value
    return value


def _review_fields(job: Dict[str, Any]) -> Dict[str, str]:
    metadata = job.get("metadata") or {}
    return {
        "scenario": SCENARIO_MAP[job["scenario"]],
        "business_scenario": job["scenario"],
        "ticket_id": str(metadata.get("ticket_id") or job["client_case_id"]),
        "user_id": str(metadata.get("user_id") or ""),
        "order_no": str(metadata.get("order_no") or ""),
        "customer_claim": str(metadata.get("customer_claim") or ""),
        "order_item": json.dumps(metadata.get("order_items") or [], ensure_ascii=False),
        "sku": ",".join(str(item.get("sku") or "") for item in metadata.get("order_items") or [] if item.get("sku")),
        "logistics_status": json.dumps(metadata.get("logistics") or {}, ensure_ascii=False),
        "complaint_stage": str(metadata.get("complaint_stage") or ""),
        "product_master_data": json.dumps(metadata.get("product_master_data") or {}, ensure_ascii=False),
        "warehouse_master_data": json.dumps(metadata.get("warehouse_master_data") or {}, ensure_ascii=False),
        "conversation_history": json.dumps(metadata.get("conversation_history") or [], ensure_ascii=False),
        "customer_tone": str(metadata.get("customer_tone") or ""),
        "sop_context": json.dumps(metadata.get("sop_context") or {}, ensure_ascii=False),
        "asset_manifest": json.dumps(job.get("assets") or [], ensure_ascii=False),
        "fps": os.getenv("REVIEW_DEFAULT_FPS", "1.0"),
        "max_frames": os.getenv("REVIEW_MAX_FRAMES_PER_VIDEO", "6"),
        "api_frame_limit": os.getenv("REVIEW_API_FRAME_LIMIT", "12"),
        "probe_seconds": os.getenv("REVIEW_PROBE_SECONDS", "12"),
    }


def _call_workbench(job: Dict[str, Any]) -> Dict[str, Any]:
    job_dir = upload_root() / job["job_id"]
    timeout_seconds = max(30, int(os.getenv("REVIEW_JOB_TIMEOUT_SECONDS", "1800") or 1800))
    with ExitStack() as stack:
        files = []
        for asset in job.get("assets") or []:
            path = job_dir / asset["stored_name"]
            if not path.exists():
                raise FileNotFoundError(f"审核素材不存在：{asset['asset_id']}")
            handle = stack.enter_context(path.open("rb"))
            files.append(("files", (asset["original_name"], handle, asset["mime_type"])))
        timeout = httpx.Timeout(timeout_seconds, connect=10, write=timeout_seconds, read=timeout_seconds)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{_workbench_url()}/api/review-folder", data=_review_fields(job), files=files)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid_visual_review_response")
    return payload


def run_job(job_id: str) -> Dict[str, Any]:
    lease_seconds = max(30, int(os.getenv("REVIEW_JOB_TIMEOUT_SECONDS", "1800") or 1800)) + 60
    if not store.claim_job(job_id, lease_seconds):
        return store.get_job(job_id) or {}
    job = store.get_job(job_id) or {}
    try:
        payload = _call_workbench(job)
        review = dict(payload.get("review")) if isinstance(payload.get("review"), dict) else {}
        review.pop("report", None)
        review["report"] = {"html_url": f"/api/v1/review/jobs/{job_id}/report"}
        diagnostics = review.get("diagnostics") or payload.get("diagnostics") or {}
        result = {
            "trace_id": job_id,
            "client_case_id": job.get("client_case_id"),
            "scenario": job.get("scenario"),
            "scenario_label": SCENARIO_LABELS.get(job.get("scenario"), job.get("scenario")),
            "source_status": payload.get("source_status"),
            "review": review,
            "boundary": "审核服务只输出证据、置信度和流程建议；退款、补发、换货、拒绝及最终定责由甲方系统和授权人员执行。",
        }
        status = "SUCCEEDED" if payload.get("ok") is True else "FAILED"
        return store.finish_job(job_id, status=status, result=result, diagnostics=diagnostics)
    except httpx.HTTPStatusError as exc:
        diagnostics = {
            "error_type": "workbench_http_error",
            "status_code": exc.response.status_code,
            "response_tail": exc.response.text[-1200:],
        }
    except Exception as exc:
        diagnostics = {"error_type": exc.__class__.__name__, "message": str(exc)[:1200]}
    return store.finish_job(job_id, status="FAILED", result={}, diagnostics=diagnostics)


def render_job_report(job: Dict[str, Any]) -> str:
    result = job.get("result") or {}
    review = result.get("review") or {}
    agent_report = _public_media_urls(review.get("agent_report") or {})
    brief = review.get("agent_brief") or {}
    data = {
        "ok": job.get("status") == "SUCCEEDED",
        "review_label": review.get("review_label") or result.get("scenario_label") or "审核结果",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job.get("completed_at") or time.time())),
        "summary": review.get("summary") or {},
        "conclusion": brief.get("conclusion") or "本轮审核尚未形成可复核结论。",
        "agent_report": agent_report,
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


def contract() -> Dict[str, Any]:
    return {
        "version": "v1",
        "submission": "每个案件独立提交；批量任务由调用方并发提交，案件之间独立重试和查询。",
        "endpoint": "POST /api/v1/review/jobs",
        "metadata_validation_endpoint": "POST /api/v1/review/metadata/validate",
        "html_report_endpoint": "GET /api/v1/review/jobs/{job_id}/report",
        "content_type": "multipart/form-data",
        "auth": "Bearer 集成账号 Token",
        "idempotency_header": "Idempotency-Key",
        "supported_scenarios": list(SCENARIO_MAP),
        "required_metadata": ["client_case_id", "scenario"],
        "business_fields": [
            "ticket_id", "user_id", "order_no", "customer_claim", "order_items",
            "product_master_data", "warehouse_master_data", "logistics",
            "conversation_history", "sop_context", "asset_fields",
        ],
        "asset_types": sorted(ALLOWED_SUFFIXES),
        "input_isolation": "人工结论、标准答案和评测标签不得进入 metadata 或素材文件。",
        "media_processing": {
            "model_input": "服务端对全时轴抽帧并压缩为 JPEG，原视频不直接发送给多模态模型。",
            "single_asset_limit_mb": _limit_bytes("REVIEW_MAX_ASSET_MB", 650) // (1024 * 1024),
            "case_limit_mb": _limit_bytes("REVIEW_MAX_CASE_MB", 750) // (1024 * 1024),
            "large_batch": "120GB 级生产批次应由对象存储直传、云转码/故事板服务和案件引用适配层承接；当前未伪装为已接入。",
        },
        "statuses": ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RETRYING"],
        "result_fields": ["predicted_label", "confidence", "agent_report", "agent_brief", "diagnostics", "boundary"],
        "boundary": "不自动退款、补发、换货、拒绝或最终定责。",
    }
