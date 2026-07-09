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
    }
    missing = sorted(required_paths - paths)
    _case(results, "OPENAPI-required-paths", code == 200 and not missing, f"paths={len(paths)} missing={missing}", t0)

    t0 = time.time()
    schemas = openapi.get("components", {}).get("schemas", {})
    typed = all(name in schemas for name in ("GroupMessageIn", "ProductEventIn", "ReviewTaskUploadResponse"))
    _case(results, "OPENAPI-private-domain-schemas", typed, f"schemas={','.join(name for name in schemas if name in ('GroupMessageIn', 'ProductEventIn', 'ReviewTaskUploadResponse'))}", t0)

    t0 = time.time()
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
    _case(results, "AUTH-admin-token", code == 200 and bool(admin_token), auth.get("error", "token ok"), t0)

    t0 = time.time()
    code, contracts = _request("GET", f"{base}/api/v1/private-domain/contracts", token=admin_token)
    _case(results, "PRIVATE-contracts", code == 200 and contracts.get("ok") is True, f"items={len(contracts.get('integration_contracts') or [])}", t0)

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
    _case(results, "METRICS-json", code == 200 and "handoff_queuing" in metrics, f"keys={sorted(metrics.keys())}", t0)

    t0 = time.time()
    status, prometheus = _request("GET", f"{base}/metrics/prometheus", token=admin_token)
    text = prometheus.get("detail", "")
    _case(results, "METRICS-prometheus", status == 200 and "mitako_handoff_queuing" in text, text.splitlines()[0] if text else "", t0)

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
