# -*- coding: utf-8 -*-
"""验证评测标签不会通过审核 API 进入模型输入。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "tests" / "reports" / "review_input_isolation_latest.json"


def main() -> int:
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015").rstrip("/")
    with httpx.Client(timeout=30) as client:
        login = client.post(
            f"{base_url}/api/v1/auth/login",
            json={
                "username": os.getenv("E2E_ADMIN_USERNAME", "admin"),
                "password": os.getenv("E2E_ADMIN_PASSWORD", "admin123"),
                "tenant_id": os.getenv("E2E_TENANT_ID", "mitako"),
            },
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        safe_metadata = {
            "client_case_id": "label-isolation-safe",
            "scenario": "wrong_item",
            "customer_claim": "用户称收到的规格与订单不一致。",
        }
        safe = client.post(f"{base_url}/api/v1/review/metadata/validate", headers=headers, json=safe_metadata)
        leaked = client.post(
            f"{base_url}/api/v1/review/metadata/validate",
            headers=headers,
            json={**safe_metadata, "ground_truth": "positive"},
        )
        leaked_file = client.post(
            f"{base_url}/api/v1/review/jobs",
            headers={**headers, "Idempotency-Key": "label-isolation-file"},
            data={"metadata": json.dumps({**safe_metadata, "client_case_id": "label-isolation-file"}, ensure_ascii=False)},
            files={"files": ("sample_labels.json", b'{"expected_predicted_label":"positive"}', "application/json")},
        )

    checks = {
        "safe_metadata_accepted": safe.status_code == 200,
        "metadata_label_rejected": leaked.status_code == 422 and leaked.json().get("detail") == "evaluation_label_not_allowed",
        "label_file_rejected": leaked_file.status_code == 422 and leaked_file.json().get("detail") == "evaluation_label_not_allowed",
    }
    report = {"ok": all(checks.values()), "base_url": base_url, "checks": checks}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
