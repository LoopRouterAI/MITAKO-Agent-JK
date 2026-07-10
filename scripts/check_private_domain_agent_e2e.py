# -*- coding: utf-8 -*-
"""私域 Agent API 业务闭环验收。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "tests" / "reports"


def main() -> int:
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015").rstrip("/")
    checks: List[Dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    with httpx.Client(timeout=30) as client:
        auth = client.post(
            f"{base}/api/v1/auth/login",
            json={
                "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
                "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
                "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
            },
        )
        auth.raise_for_status()
        token = auth.json().get("token") or ""
        headers = {"Authorization": f"Bearer {token}"}
        suffix = str(int(time.time()))

        normal_group_id = f"pd-e2e-normal-{suffix}"
        normal = client.post(
            f"{base}/api/v1/private-domain/group-message",
            headers=headers,
            json={
                "group_id": normal_group_id,
                "group_name": "私域验收兴趣群",
                "member_count": 320,
                "user_id": "pd-e2e-user-normal",
                "content": "蓝色监狱凪诚士郎吧唧想蹲补货，有货时提醒一下。",
                "message_id": f"pd-normal-{suffix}",
                "source": "private_domain_e2e",
            },
        )
        normal.raise_for_status()
        normal_body = normal.json()
        record(
            "群兴趣与许愿分层",
            normal_body.get("risk_level") == 0
            and "蓝色监狱" in ((normal_body.get("tags") or {}).get("ip") or [])
            and bool((normal_body.get("tags") or {}).get("wish")),
            {"risk_level": normal_body.get("risk_level"), "tags": normal_body.get("tags")},
        )

        product = client.post(
            f"{base}/api/v1/private-domain/product-event",
            headers=headers,
            json={
                "event_id": f"pd-product-{suffix}",
                "event_type": "stock_arrived",
                "item_id": "blue-lock-nagi-badge",
                "ip_name": "蓝色监狱",
                "character_name": "凪诚士郎",
                "category": "吧唧",
                "stock": 24,
            },
        )
        product.raise_for_status()
        candidates = product.json().get("candidates") or []
        matched = next((item for item in candidates if item.get("group_id") == normal_group_id), {})
        record(
            "商品事件生成待审核候选",
            matched.get("decision") == "review" and int(matched.get("match_score") or 0) >= 60,
            matched,
        )

        risk_group_id = f"pd-e2e-risk-{suffix}"
        risk = client.post(
            f"{base}/api/v1/private-domain/group-message",
            headers=headers,
            json={
                "group_id": risk_group_id,
                "group_name": "私域验收客诉群",
                "member_count": 180,
                "user_id": "pd-e2e-user-risk",
                "external_user_id": "wx-pd-e2e-risk",
                "content": "你们一直不退款，我要去12315投诉并在小红书曝光。",
                "message_id": f"pd-risk-{suffix}",
                "source": "private_domain_e2e",
            },
        )
        risk.raise_for_status()
        risk_body = risk.json()
        record(
            "高危舆情暂停营销并转客服",
            risk_body.get("risk_level") == 4
            and risk_body.get("need_disable_marketing") is True
            and risk_body.get("need_customer_service") is True
            and risk_body.get("need_supervisor_alert") is True
            and bool(risk_body.get("customer_service_task")),
            {
                "risk_level": risk_body.get("risk_level"),
                "risk_type": risk_body.get("risk_type"),
                "task_id": (risk_body.get("customer_service_task") or {}).get("task_id"),
            },
        )

        dashboard = client.get(f"{base}/api/v1/private-domain/dashboard", headers=headers)
        dashboard.raise_for_status()
        data = dashboard.json()
        group_ids = {item.get("group_id") for item in data.get("groups") or []}
        task_groups = {item.get("group_id") for item in data.get("customer_service_tasks") or []}
        contract_keys = {item.get("key") for item in data.get("integration_contracts") or []}
        record(
            "后台可复盘群、客服任务和审核服务契约",
            normal_group_id in group_ids
            and risk_group_id in group_ids
            and risk_group_id in task_groups
            and "review_job_service" in contract_keys,
            {
                "groups": len(data.get("groups") or []),
                "tasks": len(data.get("customer_service_tasks") or []),
                "contract_keys": sorted(contract_keys),
            },
        )

    report = {
        "ok": all(item["ok"] for item in checks),
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
        "checks": checks,
        "boundary": "本验收验证我方规则、任务和接口闭环，不代表企微、飞书、商品库或订单系统已真实接入。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORT_DIR / "private_domain_agent_e2e_latest.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
