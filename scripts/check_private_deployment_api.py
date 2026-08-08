# -*- coding: utf-8 -*-
"""私有化部署 API 验收烟测：不依赖前端页面。"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "tests" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _base_url() -> str:
    return os.getenv("E2E_BASE_URL", os.getenv("MITAKO_BASE_URL", "http://127.0.0.1:8015")).rstrip("/")


def _request(method: str, url: str, *, token: str = "", json_body: Dict[str, Any] | None = None, timeout: int = 15) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8-sig")
            if not raw:
                return res.status, {}
            try:
                return res.status, json.loads(raw)
            except json.JSONDecodeError:
                return res.status, {"detail": raw}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8-sig", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"detail": raw[:200]}
        return exc.code, body


def _case(results: List[Dict[str, Any]], name: str, ok: bool, detail: str, started: float) -> None:
    results.append({"name": name, "ok": ok, "detail": detail, "ms": int((time.time() - started) * 1000)})


def main() -> int:
    base = _base_url()
    results: List[Dict[str, Any]] = []

    t0 = time.time()
    code, openapi = _request("GET", f"{base}/openapi.json")
    paths = set((openapi.get("paths") or {}).keys())
    required_paths = {
        "/api/v1/chat",
        "/api/v1/auth/login",
        "/api/v1/auth/customer-session",
        "/api/v1/ops/snapshot",
        "/metrics",
        "/metrics/prometheus",
        "/api/v1/private-domain/contracts",
        "/api/v1/private-domain/group-message",
        "/api/v1/private-domain/product-event",
        "/api/v1/private-domain/review-tasks",
        "/api/v1/private-domain/review-tasks/{task_id}",
        "/api/v1/review/contracts",
        "/api/v1/review/batches/{batch_id}",
        "/api/v1/review/metadata/validate",
        "/api/v1/review/sampling-plan",
        "/api/v1/review/jobs",
        "/api/v1/review/jobs/{job_id}",
        "/api/v1/review/jobs/{job_id}/report",
        "/api/v1/review/jobs/{job_id}/retry",
        "/api/v1/review/metrics",
        "/api/v1/review/readiness",
    }
    missing = sorted(required_paths - paths)
    _case(results, "OPENAPI-required-paths", code == 200 and not missing, f"paths={len(paths)} missing={missing}", t0)

    t0 = time.time()
    schemas = openapi.get("components", {}).get("schemas", {})
    required_schemas = (
        "GroupMessageIn", "ProductEventIn", "ReviewTaskUploadResponse", "ReviewCaseMetadata",
        "ReviewClaimScope", "ReviewDecisionPolicy", "ReviewSamplingPolicy", "ReviewSamplingPlanRequest",
        "ReviewSamplingPlanResponse", "ReviewJobResponse", "ReviewBatchResponse",
        "ReviewAdvisoryAssessment", "ReviewHumanReviewAdvice", "ReviewAdvisorySignal",
        "ReviewAdvisoryPolicy", "ReviewReportReference",
    )
    typed = all(name in schemas for name in required_schemas)
    _case(results, "OPENAPI-typed-schemas", typed, f"schemas={','.join(name for name in schemas if name in required_schemas)}", t0)

    t0 = time.time()
    status_code, auth_status = _request("GET", f"{base}/api/v1/auth/status")
    auth_required = bool(
        auth_status.get("protected_api_auth_required", auth_status.get("auth_required", True))
    )
    admin_token = ""
    if auth_required:
        code, auth = _request(
            "POST",
            f"{base}/api/v1/auth/login",
            json_body={
                "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
                "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
                "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
            },
        )
        admin_token = auth.get("token") or ""
        auth_ok = code == 200 and bool(admin_token)
        auth_detail = auth.get("error", "strict auth token ok")
    else:
        auth_ok = status_code == 200 and auth_status.get("ok") is True
        auth_detail = "demo bypass declared by auth status; protected endpoints verified without token"
    _case(results, "AUTH-runtime-mode", auth_ok, auth_detail, t0)

    t0 = time.time()
    code, contracts = _request("GET", f"{base}/api/v1/private-domain/contracts", token=admin_token)
    _case(results, "PRIVATE-contracts", code == 200 and contracts.get("ok") is True, f"items={len(contracts.get('integration_contracts') or [])}", t0)

    t0 = time.time()
    code, review_contract = _request("GET", f"{base}/api/v1/review/contracts", token=admin_token)
    supported = (review_contract.get("contract") or {}).get("supported_scenarios") or []
    media_processing = (review_contract.get("contract") or {}).get("media_processing") or {}
    sampling_presets = (review_contract.get("contract") or {}).get("sampling_presets") or {}
    _case(
        results,
        "REVIEW-contract",
        code == 200
        and set(supported) >= {"product_damage", "wrong_item", "missing_item", "minor_refund"}
        and bool(media_processing.get("model_input"))
        and set(sampling_presets) >= {"adaptive", "strict", "forensic", "custom"},
        f"scenarios={supported} media_processing={bool(media_processing)} sampling={sorted(sampling_presets)}",
        t0,
    )

    t0 = time.time()
    code, sampling = _request(
        "POST",
        f"{base}/api/v1/review/sampling-plan",
        token=admin_token,
        json_body={
            "duration_seconds": 452.5,
            "source_bytes": 543351335,
            "video_count": 1,
            "scenario": "product_damage",
            "sampling_policy": {"preset": "strict", "frames_per_model_call": 24},
        },
    )
    sampling_plan = sampling.get("plan") or {}
    channel_calls = sampling_plan.get("estimated_channel_calls") or {}
    unified_multitask = sampling_plan.get("unified_multitask") or {}
    fallback_calls = unified_multitask.get("fallback_channel_calls") or {}
    _case(
        results,
        "REVIEW-sampling-plan",
        code == 200
        and sampling_plan.get("fps") == 1.0
        and sampling_plan.get("estimated_frames_per_video", 0) >= 453
        and sampling_plan.get("main_review_frames") == sampling_plan.get("estimated_total_frames")
        and sampling_plan.get("main_review_strategy") == "unified_dense_multitask"
        and sampling_plan.get("estimated_model_segments") == channel_calls.get("main_review")
        and channel_calls.get("main_review", 0) > 0
        and channel_calls.get("object_continuity") == 0
        and channel_calls.get("damage_causality") == 0
        and sampling_plan.get("estimated_total_model_calls") == sum(channel_calls.values())
        and unified_multitask.get("enabled") is True
        and unified_multitask.get("primary_transport") == "gemini_native"
        and fallback_calls.get("object_continuity", 0) > 0
        and fallback_calls.get("damage_causality", 0) > 0
        and sampling_plan.get("transcode_recommended") is True,
        f"plan={sampling_plan}",
        t0,
    )

    t0 = time.time()
    code, adaptive_sampling = _request(
        "POST",
        f"{base}/api/v1/review/sampling-plan",
        token=admin_token,
        json_body={
            "duration_seconds": 452.5,
            "source_bytes": 543351335,
            "video_count": 1,
            "scenario": "product_damage",
            "sampling_policy": {"preset": "adaptive", "frames_per_model_call": 24},
        },
    )
    adaptive_plan = adaptive_sampling.get("plan") or {}
    adaptive_channels = adaptive_plan.get("estimated_channel_calls") or {}
    _case(
        results,
        "REVIEW-product-damage-adaptive-bounded-pass",
        code == 200
        and adaptive_plan.get("sampling_mode") == "adaptive"
        and adaptive_plan.get("fps") == 1.0
        and 0 < adaptive_plan.get("estimated_frames_per_video", 0) <= 24
        and adaptive_channels.get("main_review") == 1
        and adaptive_channels.get("object_continuity") == 0
        and adaptive_channels.get("damage_causality") == 0
        and adaptive_plan.get("estimated_total_model_calls") == sum(adaptive_channels.values()),
        f"plan={adaptive_plan}",
        t0,
    )

    t0 = time.time()
    code, missing_item_metadata = _request(
        "POST",
        f"{base}/api/v1/review/metadata/validate",
        token=admin_token,
        json_body={
            "client_case_id": "api-smoke-missing-item",
            "scenario": "missing_item",
            "customer_claim": "订单有两件商品，用户称只收到一件；本项只校验接口字段，不作为准确率样本。",
            "fulfillment_baseline": {
                "baseline_version": "api-smoke-order@v1",
                "expected_items": [
                    {"item_ref": "line-1", "sku": "api-smoke-sku", "expected_quantity": 2}
                ],
                "expected_package_count": 1,
                "packages": [
                    {"package_ref": "pkg-1", "tracking_no": "api-smoke-tracking-1", "expected_item_refs": ["line-1"]}
                ],
                "benefit_rules_complete": True,
                "selection_rules_complete": True,
            },
            "evidence_coverage": {
                "submitted_package_refs": ["pkg-1"],
                "submitted_tracking_nos": ["api-smoke-tracking-1"],
                "all_packages_uploaded": True,
                "all_items_displayed": True,
            },
            "logistics": {
                "source": "customer_logistics_system",
                "snapshot_at": "2026-07-23T10:00:00+08:00",
                "all_packages_delivered": True,
                "packages": [
                    {"package_ref": "pkg-1", "tracking_ref": "api-smoke-tracking-1", "shipment_status": "delivered"}
                ],
            },
        },
    )
    _case(
        results,
        "REVIEW-missing-item-metadata",
        code == 200
        and (missing_item_metadata.get("metadata") or {}).get("scenario") == "missing_item"
        and (missing_item_metadata.get("readiness") or {}).get("full_review_ready") is True,
        f"status={code} readiness={(missing_item_metadata.get('readiness') or {}).get('status')}",
        t0,
    )

    t0 = time.time()
    code, group = _request(
        "POST",
        f"{base}/api/v1/private-domain/group-message",
        token=admin_token,
        json_body={
            "group_id": "api_smoke_group_001",
            "group_name": "API验收烟测群",
            "owner_id": "api_smoke_owner",
            "member_count": 128,
            "user_id": "api_smoke_user",
            "external_user_id": "wx_api_smoke_user",
            "content": "蓝色监狱吧唧想蹲补货，但之前退款太慢，想确认售后规则。",
            "message_id": f"api-smoke-msg-{int(time.time())}",
            "source": "api_smoke",
        },
    )
    _case(results, "PRIVATE-group-message", code == 200 and group.get("ok") is True, f"decision={(group.get('analysis') or {}).get('decision')}", t0)

    t0 = time.time()
    code, product = _request(
        "POST",
        f"{base}/api/v1/private-domain/product-event",
        token=admin_token,
        json_body={
            "event_id": f"api-smoke-product-{int(time.time())}",
            "event_type": "stock_arrived",
            "item_id": "api_smoke_item_001",
            "ip_name": "蓝色监狱",
            "character_name": "凪诚士郎",
            "category": "吧唧",
            "stock": 24,
            "risk_flag": "",
        },
    )
    _case(results, "PRIVATE-product-event", code == 200 and product.get("ok") is True, f"candidates={len(product.get('candidates') or [])}", t0)

    t0 = time.time()
    code, ops = _request("GET", f"{base}/api/v1/ops/snapshot", token=admin_token)
    snapshot = ops.get("snapshot") or {}
    _case(results, "OPS-snapshot", code == 200 and ops.get("ok") is True and "status" in snapshot, f"status={snapshot.get('status')}", t0)

    t0 = time.time()
    code, metrics = _request("GET", f"{base}/metrics", token=admin_token)
    review_metrics = metrics.get("review_service") or {}
    _case(
        results,
        "METRICS-json",
        code == 200
        and "handoff_queuing" in metrics
        and "inference_total_tokens" in review_metrics
        and "inference_estimated_usd" in review_metrics,
        f"keys={sorted(metrics.keys())} review_keys={sorted(review_metrics.keys())}",
        t0,
    )

    t0 = time.time()
    status, prometheus = _request("GET", f"{base}/metrics/prometheus", token=admin_token)
    text = prometheus.get("detail", "")
    _case(
        results,
        "METRICS-prometheus",
        status == 200
        and "mitako_handoff_queuing" in text
        and "mitako_review_jobs_queued" in text
        and "mitako_review_inference_total_tokens" in text
        and "mitako_review_inference_estimated_usd" in text,
        text.splitlines()[0] if text else "",
        t0,
    )

    t0 = time.time()
    code, customer = _request(
        "POST",
        f"{base}/api/v1/auth/customer-session",
        json_body={"user_id": "usr_e2e", "session_id": "session_usr_e2e", "tenant_id": "mitako"},
    )
    _case(results, "AUTH-customer-session", code == 200 and bool(customer.get("token")), customer.get("error", "token ok"), t0)

    passed = sum(1 for item in results if item["ok"])
    report = {
        "base_url": base,
        "generated_at": time.time(),
        "passed": passed,
        "total": len(results),
        "results": results,
        "note": "本检查只验证我方可交付 FastAPI/OpenAPI 服务面，不代表企微、飞书、商品库、订单系统已真实接入。",
    }
    path = REPORT_DIR / f"private_deployment_api_smoke_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in results:
        print(f"[{'PASS' if item['ok'] else 'FAIL'}] {item['name']} {item['detail']} ({item['ms']}ms)")
    print(f"[API SMOKE] {passed}/{len(results)} report={path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
