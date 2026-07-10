# -*- coding: utf-8 -*-
"""甲方系统调用的独立审核服务 API。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from auth.middleware import require_roles
from auth.roles import ADMIN_MUTATE_ROLES

from . import service, store
from .schemas import (
    ReviewCaseMetadata,
    ReviewBatchResponse,
    ReviewContractResponse,
    ReviewJobListResponse,
    ReviewJobResponse,
    ReviewMetadataValidationResponse,
    ReviewMetricsResponse,
    ReviewSamplingPlanRequest,
    ReviewSamplingPlanResponse,
)


router = APIRouter(prefix="/api/v1/review", tags=["review-service"])


def _integration_user():
    return require_roles(ADMIN_MUTATE_ROLES)


@router.on_event("startup")
async def startup() -> None:
    store.init_db()
    service.recover_jobs()


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
    result = service.batch_status(user.get("tenant_id") or "mitako", batch_id, limit=limit, offset=offset)
    if not result["summary"]["total"]:
        raise HTTPException(status_code=404, detail="review_batch_not_found")
    return {"ok": True, **result}


@router.post("/metadata/validate", response_model=ReviewMetadataValidationResponse)
async def validate_metadata(metadata: ReviewCaseMetadata, user=_integration_user()):
    try:
        service.ensure_label_isolation(metadata.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "metadata": metadata}


@router.post("/sampling-plan", response_model=ReviewSamplingPlanResponse)
async def plan_sampling(payload: ReviewSamplingPlanRequest, user=_integration_user()):
    return {
        "ok": True,
        "plan": service.sampling_plan(
            payload.duration_seconds,
            payload.source_bytes,
            payload.video_count,
            payload.sampling_policy.model_dump(mode="json"),
        ),
    }


@router.post("/jobs", response_model=ReviewJobResponse, status_code=202)
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
            user.get("tenant_id") or "mitako",
            idempotency_key,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "idempotency_key_conflict":
            status = 409
        elif detail in {"review_asset_too_large", "review_case_too_large"}:
            status = 413
        elif detail in {"unsupported_review_asset", "invalid_review_asset_content", "invalid_review_json_asset"}:
            status = 415
        elif detail == "evaluation_label_not_allowed":
            status = 422
        else:
            status = 400
        raise HTTPException(status_code=status, detail=detail) from exc
    return {"ok": True, "created": created, "job": job}


@router.get("/jobs", response_model=ReviewJobListResponse)
async def list_jobs(
    status: str = Query("", max_length=32),
    scenario: str = Query("", max_length=32),
    limit: int = Query(50, ge=1, le=200),
    user=_integration_user(),
):
    return {
        "ok": True,
        "jobs": store.list_jobs(
            user.get("tenant_id") or "mitako",
            status=status,
            scenario=scenario,
            limit=limit,
        ),
    }


@router.get("/jobs/{job_id}", response_model=ReviewJobResponse)
async def job_detail(job_id: str, user=_integration_user()):
    job = store.get_job(job_id)
    if not job or job.get("tenant_id") != (user.get("tenant_id") or "mitako"):
        raise HTTPException(status_code=404, detail="review_job_not_found")
    return {"ok": True, "created": False, "job": job}


@router.get("/jobs/{job_id}/report", response_class=HTMLResponse)
async def job_report(job_id: str, user=_integration_user()):
    job = store.get_job(job_id)
    if not job or job.get("tenant_id") != (user.get("tenant_id") or "mitako"):
        raise HTTPException(status_code=404, detail="review_job_not_found")
    return HTMLResponse(service.render_job_report(job))


@router.post("/jobs/{job_id}/retry", response_model=ReviewJobResponse, status_code=202)
async def retry_job(job_id: str, user=_integration_user()):
    existing = store.get_job(job_id)
    if not existing or existing.get("tenant_id") != (user.get("tenant_id") or "mitako"):
        raise HTTPException(status_code=404, detail="review_job_not_found")
    try:
        job = service.retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "created": False, "job": job}


@router.get("/metrics", response_model=ReviewMetricsResponse)
async def review_metrics(user=_integration_user()):
    return {"ok": True, "metrics": service.metrics(user.get("tenant_id") or "mitako")}
