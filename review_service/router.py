# -*- coding: utf-8 -*-
"""甲方系统调用的独立审核服务 API。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import suppress
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import ValidationError

from auth.jwt_utils import dev_auth_bypass_enabled, protected_api_auth_required
from auth.middleware import get_current_user_optional, require_roles, tenant_allowed
from auth.roles import ADMIN_MUTATE_ROLES
from auth.roles import Role
import observability_store

from . import service, store
from .input_readiness import assess_input_readiness
from .schemas import (
    ReviewCaseMetadata,
    ReviewBatchResponse,
    ReviewContractResponse,
    ReviewErrorResponse,
    ReviewJobListResponse,
    ReviewJobResponse,
    ReviewMetadataValidationResponse,
    ReviewMetricsResponse,
    ReviewSamplingPlanRequest,
    ReviewSamplingPlanResponse,
)


router = APIRouter(prefix="/api/v1/review", tags=["review-service"])
LOGGER = logging.getLogger("mitako.review_service")
_RECOVERY_TASK: asyncio.Task | None = None
_PRIVATE_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _structured_error_detail(detail: str):
    try:
        parsed = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        return detail
    return parsed if isinstance(parsed, dict) else detail


async def _recover_expired_jobs_forever() -> None:
    interval = max(10, min(int(os.getenv("REVIEW_RECOVERY_INTERVAL_SECONDS", "30") or 30), 300))
    while True:
        await asyncio.sleep(interval)
        try:
            service.recover_jobs()
        except Exception:
            LOGGER.exception("review_job_recovery_failed")


def _integration_user():
    return require_roles(ADMIN_MUTATE_ROLES, require_tenant=True)


def _optional_integration_user(request: Request) -> Optional[Dict]:
    user = get_current_user_optional(request)
    if user and user.get("role") not in ADMIN_MUTATE_ROLES:
        raise HTTPException(status_code=403, detail="权限不足")
    if user and not str(user.get("tenant_id") or "").strip():
        raise HTTPException(status_code=403, detail="tenant_claim_required")
    return user


@router.on_event("startup")
async def startup() -> None:
    global _RECOVERY_TASK
    store.init_db()
    service.recover_jobs()
    if _RECOVERY_TASK is None or _RECOVERY_TASK.done():
        _RECOVERY_TASK = asyncio.create_task(_recover_expired_jobs_forever())


@router.on_event("shutdown")
async def shutdown() -> None:
    global _RECOVERY_TASK
    if _RECOVERY_TASK is not None:
        _RECOVERY_TASK.cancel()
        with suppress(asyncio.CancelledError):
            await _RECOVERY_TASK
        _RECOVERY_TASK = None


@router.get("/contracts", response_model=ReviewContractResponse)
async def contracts(user=_integration_user()):
    return {"ok": True, "contract": service.contract()}


@router.get("/batches/{batch_id}", response_model=ReviewBatchResponse)
async def batch_detail(
    batch_id: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=_integration_user(),
):
    if not batch_id.strip() or len(batch_id) > 160:
        raise HTTPException(status_code=422, detail="invalid_review_batch_id")
    result = service.batch_status(user["tenant_id"], batch_id, limit=limit, offset=offset)
    if not result["summary"]["total"]:
        raise HTTPException(status_code=404, detail="review_batch_not_found")
    return {"ok": True, **result}


@router.post("/metadata/validate", response_model=ReviewMetadataValidationResponse)
async def validate_metadata(metadata: ReviewCaseMetadata, user=_integration_user()):
    try:
        service.ensure_label_isolation(metadata.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "metadata": metadata,
        "readiness": assess_input_readiness(metadata.model_dump(mode="json")),
    }


@router.post("/sampling-plan", response_model=ReviewSamplingPlanResponse)
async def plan_sampling(payload: ReviewSamplingPlanRequest, user=_integration_user()):
    return {
        "ok": True,
        "plan": service.sampling_plan(
            payload.duration_seconds,
            payload.source_bytes,
            payload.video_count,
            payload.sampling_policy.model_dump(mode="json"),
            payload.scenario,
            payload.continuity_policy.model_dump(mode="json"),
            payload.damage_causality_policy.model_dump(mode="json"),
        ),
    }


@router.post(
    "/jobs",
    response_model=ReviewJobResponse,
    status_code=202,
    responses={
        status: {"model": ReviewErrorResponse}
        for status in (400, 409, 413, 415, 422)
    },
)
async def create_job(
    metadata: str = Form(...),
    files: List[UploadFile] = File(...),
    idempotency_key: str = Header("", alias="Idempotency-Key"),
    user=_integration_user(),
):
    try:
        case = ReviewCaseMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    try:
        job, created = await service.create_job_from_uploads(
            case,
            files,
            user["tenant_id"],
            idempotency_key,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "idempotency_key_conflict":
            status = 409
        elif detail == "review_queue_full":
            status = 429
        elif detail in {"review_asset_too_large", "review_case_too_large"} or "too_many_review_assets" in detail:
            status = 413
        elif detail in {"unsupported_review_asset", "invalid_review_asset_content", "invalid_review_json_asset"}:
            status = 415
        elif detail == "evaluation_label_not_allowed":
            status = 422
        else:
            status = 400
        raise HTTPException(status_code=status, detail=_structured_error_detail(detail)) from exc
    return {"ok": True, "created": created, "job": service.public_job(job)}


@router.get("/jobs", response_model=ReviewJobListResponse)
async def list_jobs(
    status: str = Query("", max_length=32),
    scenario: str = Query("", max_length=32),
    limit: int = Query(50, ge=1, le=200),
    user=_integration_user(),
):
    return {
        "ok": True,
        "jobs": [service.public_job(job) for job in store.list_jobs(
            user["tenant_id"],
            status=status,
            scenario=scenario,
            limit=limit,
        )],
    }


@router.get("/jobs/{job_id}", response_model=ReviewJobResponse)
async def job_detail(job_id: str, user=_integration_user()):
    job = store.get_job(job_id)
    if not job or job.get("tenant_id") != user["tenant_id"]:
        raise HTTPException(status_code=404, detail="review_job_not_found")
    return {"ok": True, "created": False, "job": service.public_job(job)}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    detail: str = Query("redacted", pattern="^(redacted|internal)$"),
    limit: int = Query(100, ge=1, le=500),
    since_id: int = Query(0, ge=0),
    user=_integration_user(),
):
    job = store.get_job(job_id)
    if not job or job.get("tenant_id") != user["tenant_id"]:
        raise HTTPException(status_code=404, detail="review_job_not_found")
    if detail == "internal" and user.get("role") != Role.SUPER_ADMIN.value:
        raise HTTPException(status_code=403, detail="internal_observability_forbidden")
    visibility = "internal" if detail == "internal" else "redacted"
    events = observability_store.list_events(
        user["tenant_id"],
        job_id=job_id,
        visibility=visibility,
        limit=limit,
        since_id=since_id,
    )
    return {
        "ok": True,
        "job_id": job_id,
        "visibility": visibility,
        "events": events,
        "next_since_id": events[-1]["id"] if events else since_id,
    }


@router.get(
    "/jobs/{job_id}/report",
    response_class=HTMLResponse,
    responses={404: {"model": ReviewErrorResponse}, 409: {"model": ReviewErrorResponse}},
)
async def job_report(job_id: str, user=_integration_user()):
    job = store.get_job(job_id)
    if not job or job.get("tenant_id") != user["tenant_id"]:
        raise HTTPException(status_code=404, detail="review_job_not_found")
    if not service.html_report_requested(job):
        raise HTTPException(status_code=409, detail="review_report_not_requested")
    if job.get("status") != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="review_report_not_ready")
    return HTMLResponse(service.render_job_report(job), headers=_PRIVATE_RESPONSE_HEADERS)


_BINARY_MEDIA_CONTENT = {
    media_type: {"schema": {"type": "string", "format": "binary"}}
    for media_type in ("image/jpeg", "image/png", "image/webp", "video/mp4", "video/webm", "application/octet-stream")
}


@router.get(
    "/jobs/{job_id}/media/{media_id}",
    response_class=StreamingResponse,
    responses={
        200: {"content": _BINARY_MEDIA_CONTENT},
        206: {"content": _BINARY_MEDIA_CONTENT, "description": "Range 分段媒体响应"},
        404: {"model": ReviewErrorResponse},
        502: {"model": ReviewErrorResponse},
    },
)
async def job_media(
    job_id: str,
    media_id: str,
    request: Request,
    expires: str = Query(""),
    sig: str = Query(""),
    user=Depends(_optional_integration_user),
):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="review_job_not_found")
    signed_request = bool(expires or sig)
    if signed_request:
        if not service.verify_job_media_signature(
            str(job.get("tenant_id") or "mitako"), job_id, media_id, expires, sig
        ):
            raise HTTPException(status_code=403, detail="review_media_signature_invalid")
    elif user:
        if not tenant_allowed(user, str(job.get("tenant_id") or "mitako")):
            raise HTTPException(status_code=404, detail="review_job_not_found")
    elif protected_api_auth_required() or not dev_auth_bypass_enabled():
        raise HTTPException(status_code=401, detail="protected_api_token_required")
    local_media = service.resolve_job_media_path(job, media_id)
    if local_media:
        path, media_type = local_media
        return FileResponse(path, media_type=media_type, headers=_PRIVATE_RESPONSE_HEADERS)
    try:
        source_url = service.resolve_job_media_url(job, media_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0), trust_env=False)
    headers = {"Range": request.headers["range"]} if request.headers.get("range") else {}
    try:
        upstream = await client.send(client.build_request("GET", source_url, headers=headers), stream=True)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="review_media_upstream_unavailable") from exc
    if upstream.status_code >= 400:
        status_code = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"review_media_upstream_{status_code}")

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        name: upstream.headers[name]
        for name in ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
        if name in upstream.headers
    }
    response_headers.update(_PRIVATE_RESPONSE_HEADERS)
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type") or "application/octet-stream",
        headers=response_headers,
    )


@router.post("/jobs/{job_id}/retry", response_model=ReviewJobResponse, status_code=202)
async def retry_job(job_id: str, user=_integration_user()):
    existing = store.get_job(job_id)
    if not existing or existing.get("tenant_id") != user["tenant_id"]:
        raise HTTPException(status_code=404, detail="review_job_not_found")
    try:
        job = service.retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "created": False, "job": service.public_job(job)}


@router.get("/metrics", response_model=ReviewMetricsResponse)
async def review_metrics(user=_integration_user()):
    return {"ok": True, "metrics": service.metrics(user["tenant_id"])}


@router.get("/readiness")
async def review_readiness(user=_integration_user()):
    result = service.runtime_readiness()
    if not result["ready"]:
        raise HTTPException(status_code=503, detail=result)
    return {"ok": True, **result}
