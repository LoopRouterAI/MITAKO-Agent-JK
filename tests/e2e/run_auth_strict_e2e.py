# -*- coding: utf-8 -*-
"""严格鉴权 E2E — 需开启后台 API 保护并重启 main.py"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.dirname(__file__))

import httpx

from e2e_lib import CaseResult, discover_base, REPORT_DIR, render_report


async def run_auth_strict_suite() -> list[CaseResult]:
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        base = await discover_base(client, None)

        t0 = time.time()
        st = await client.get(f"{base}/api/v1/auth/status")
        auth_required = st.json().get("auth_required") is True or st.json().get("protected_api_auth_required") is True
        results.append(CaseResult(
            "AUTH-STRICT", "system", "AUTH-status-read",
            st.status_code == 200,
            f"protected={auth_required}",
            int((time.time() - t0) * 1000),
        ))

        if not auth_required:
            results.append(CaseResult(
                "AUTH-STRICT", "system", "AUTH-strict-skipped",
                True,
                "后台 API 保护未启用，严格 401 用例已跳过",
                0,
            ))
            return results

        cleanup_login = await client.post(
            f"{base}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123", "tenant_id": "mitako"},
        )
        cleanup_token = str(cleanup_login.json().get("token") or "")
        if cleanup_token:
            await client.post(
                f"{base}/api/v1/handoff/reset",
                params={"session_id": "session_usr_001"},
                headers={"Authorization": f"Bearer {cleanup_token}"},
            )

        # 无 token → 401（含 desk 读接口）
        mutating = [
            ("POST", f"{base}/api/v1/admin/approvals", {"amount": 10, "reason": "t"}),
            ("POST", f"{base}/api/v1/handoff/close?session_id=x&note=y", None),
            ("PUT", f"{base}/api/v1/admin/handoff/routing", {"sla": {}}),
        ]
        reads = [
            f"{base}/api/v1/desk/sessions",
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

        # 客户前台链路：严格模式下无 token 应拒绝，有客户会话 token 才能发起聊天。
        chat_body = {
            "user_id": "usr_001",
            "session_id": "session_usr_001",
            "content": "我想查一下订单进度",
            "history": [],
            "model_id": "standard-service",
        }
        t0 = time.time()
        no_customer = await client.post(f"{base}/api/v1/chat", json=chat_body)
        results.append(CaseResult(
            "AUTH-STRICT", "customer", "AUTH-chat-no-token-401",
            no_customer.status_code == 401,
            str(no_customer.status_code), int((time.time() - t0) * 1000),
        ))

        t0 = time.time()
        customer_auth = await client.post(
            f"{base}/api/v1/auth/customer-session",
            json={"user_id": "usr_001", "session_id": "session_usr_001", "tenant_id": "mitako"},
        )
        customer_token = customer_auth.json().get("token", "")
        chat_status = 0
        chat_content_type = ""
        if customer_token:
            async with client.stream(
                "POST",
                f"{base}/api/v1/chat",
                json=chat_body,
                headers={"Authorization": f"Bearer {customer_token}"},
            ) as chat:
                chat_status = chat.status_code
                chat_content_type = chat.headers.get("content-type", "")
        results.append(CaseResult(
            "AUTH-STRICT", "customer", "AUTH-chat-customer-token-sse",
            customer_auth.status_code == 200 and bool(customer_token) and chat_status == 200 and "text/event-stream" in chat_content_type,
            f"auth={customer_auth.status_code} chat={chat_status}",
            int((time.time() - t0) * 1000),
        ))

        for name, payload in (
            ("AUTH-customer-token-forged-user-403", {"user_id": "evil", "session_id": "session_evil", "tenant_id": "mitako"}),
            ("AUTH-customer-token-forged-tenant-403", {"user_id": "usr_001", "session_id": "session_usr_001", "tenant_id": "guard_b"}),
        ):
            t0 = time.time()
            forged = await client.post(f"{base}/api/v1/auth/customer-session", json=payload)
            results.append(CaseResult(
                "AUTH-STRICT", "customer", name,
                forged.status_code == 403,
                str(forged.status_code), int((time.time() - t0) * 1000),
            ))

        t0 = time.time()
        tm = await client.post(
            f"{base}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123", "tenant_id": "bpo-east"},
        )
        results.append(CaseResult(
            "AUTH-STRICT", "admin", "AUTH-tenant-mismatch",
            tm.json().get("error") in {"tenant_mismatch", "invalid_credentials"},
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
