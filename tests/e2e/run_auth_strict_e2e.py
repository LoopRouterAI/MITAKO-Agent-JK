# -*- coding: utf-8 -*-
"""MITAKO_AUTH_REQUIRED=1 严格鉴权 E2E — 需在 .env 设 MITAKO_AUTH_REQUIRED=1 并重启 main.py"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import httpx

from tests.e2e.e2e_lib import CaseResult, discover_base, REPORT_DIR, render_report


async def run_auth_strict_suite() -> list[CaseResult]:
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        base = await discover_base(client, None)

        t0 = time.time()
        st = await client.get(f"{base}/api/v1/auth/status")
        auth_required = st.json().get("auth_required") is True
        results.append(CaseResult(
            "AUTH-STRICT", "system", "AUTH-status-read",
            st.status_code == 200,
            f"auth_required={auth_required}",
            int((time.time() - t0) * 1000),
        ))

        if not auth_required:
            results.append(CaseResult(
                "AUTH-STRICT", "system", "AUTH-strict-skipped",
                True,
                "MITAKO_AUTH_REQUIRED=0，严格 401 用例已跳过（设 1 并重启后重跑）",
                0,
            ))
            return results

        # 无 token → 401（含 desk 读接口）
        mutating = [
            ("POST", f"{base}/api/v1/admin/approvals", {"amount": 10, "reason": "t"}),
            ("POST", f"{base}/api/v1/handoff/close?session_id=x&note=y", None),
            ("PUT", f"{base}/api/v1/admin/handoff/routing", {"sla": {}}),
        ]
        reads = [
            f"{base}/api/v1/desk/sessions",
            f"{base}/api/v2/companion/desk/sessions",
        ]
        for i, (method, url, body) in enumerate(mutating, 1):
            t0 = time.time()
            if method == "POST":
                r = await client.post(url, json=body or {})
            else:
                r = await client.put(url, json=body or {})
            ok = r.status_code == 401
            results.append(CaseResult(
                "AUTH-STRICT", "admin", f"AUTH-no-token-401-{i}",
                ok, str(r.status_code), int((time.time() - t0) * 1000),
            ))

        for i, url in enumerate(reads, 1):
            t0 = time.time()
            r = await client.get(url)
            ok = r.status_code == 401
            results.append(CaseResult(
                "AUTH-STRICT", "desk", f"AUTH-desk-read-401-{i}",
                ok, str(r.status_code), int((time.time() - t0) * 1000),
            ))

        t0 = time.time()
        tm = await client.post(
            f"{base}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123", "tenant_id": "bpo-east"},
        )
        results.append(CaseResult(
            "AUTH-STRICT", "admin", "AUTH-tenant-mismatch",
            tm.json().get("error") == "tenant_mismatch",
            tm.json().get("error", ""), int((time.time() - t0) * 1000),
        ))

        # 有效 token → 200
        t0 = time.time()
        lr = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        token = lr.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}"}
        ar = await client.get(f"{base}/api/v1/admin/agents", headers=headers)
        results.append(CaseResult(
            "AUTH-STRICT", "admin", "AUTH-with-token-200",
            ar.status_code == 200 and ar.json().get("ok"),
            str(ar.status_code), int((time.time() - t0) * 1000),
        ))

        # 错误密码
        t0 = time.time()
        bad = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        results.append(CaseResult(
            "AUTH-STRICT", "admin", "AUTH-bad-password",
            bad.json().get("ok") is not True,
            bad.text[:40], int((time.time() - t0) * 1000),
        ))

    return results


def main() -> int:
    from datetime import datetime

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = asyncio.run(run_auth_strict_suite())
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    path = REPORT_DIR / f"auth_strict_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
    path.write_text(render_report(results, base, started), encoding="utf-8")
    print(f"[AUTH-STRICT E2E] 通过 {passed}/{total}")
    print(f"[AUTH-STRICT E2E] 报告: {path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
