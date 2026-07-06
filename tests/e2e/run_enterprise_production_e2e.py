# -*- coding: utf-8 -*-
"""010 企业级生产 E2E — SSO / Chatwoot / Ops / 鉴权"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.dirname(__file__))

import httpx

from e2e_lib import CaseResult, admin_auth_headers, discover_base, REPORT_DIR, render_report


async def run_enterprise_suite() -> list[CaseResult]:
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        base = await discover_base(client, None)

        t0 = time.time()
        tr = await client.get(f"{base}/api/v1/auth/tenants")
        tenants = tr.json().get("tenants") or []
        results.append(CaseResult("ENT", "system", "TENANTS-list", tr.json().get("ok") and len(tenants) >= 1, str(len(tenants)), int((time.time() - t0) * 1000)))

        st = await client.get(f"{base}/api/v1/auth/status")
        status = st.json() if st.status_code == 200 else {}
        sso_demo = bool(status.get("sso_local_enabled"))

        t0 = time.time()
        ar = await client.get(f"{base}/api/v1/auth/sso/bpo-east/authorize")
        authorize = ar.json() if ar.status_code == 200 else {}
        state = authorize.get("state", "")
        if sso_demo:
            authorize_ok = (
                authorize.get("ok") is True
                and bool(state)
                and bool(authorize.get("authorize_url") or authorize.get("local_callback_url"))
            )
            cb = await client.get(
                f"{base}/api/v1/auth/sso/local/complete",
                params={"tenant_id": "bpo-east", "state": state},
            ) if authorize_ok else None
            body = cb.json() if cb is not None else {}
            ok = authorize_ok and body.get("ok") and bool(body.get("token"))
            detail = body.get("user", {}).get("tenant_id", "") if body else f"authorize_failed:{authorize.get('error')}"
        elif authorize.get("ok") is False:
            ok = authorize.get("error") == "oidc_not_configured"
            detail = authorize.get("error", "authorize_failed")
        elif authorize.get("ok") is True and state and authorize.get("authorize_url"):
            cb = await client.post(
                f"{base}/api/v1/auth/sso/callback",
                json={"tenant_id": "bpo-east", "code": "demo_ok", "state": state},
            )
            body = cb.json()
            ok = body.get("error") in ("demo_disabled", "oidc_not_configured", "token_exchange_failed", "real_partner_api_blocked")
            detail = body.get("error", "production_oidc_expected")
        else:
            ok = False
            detail = f"bad_authorize_contract:{authorize}"
        results.append(CaseResult("ENT", "admin", "SSO-flow", ok, detail, int((time.time() - t0) * 1000)))

        sid = f"ent_cw_{int(time.time())}"
        headers = await admin_auth_headers(client, base)
        t0 = time.time()
        await client.post(f"{base}/api/v1/handoff/reset", params={"session_id": sid}, headers=headers)
        ops = await client.get(f"{base}/api/v1/ops/snapshot", headers=headers)
        snap = ops.json().get("snapshot") or {}
        results.append(CaseResult("ENT", "admin", "OPS-snapshot", ops.json().get("ok") and "uptime_seconds" in snap, snap.get("status", ""), int((time.time() - t0) * 1000)))
        hr = await client.post(f"{base}/api/v1/handoff/request", json={
            "user_id": "u_ent", "session_id": sid, "history": [], "reason": "chatwoot sync test", "intent": "g", "emotion_level": 2,
        })
        st2 = await client.get(f"{base}/api/v1/handoff/status/{sid}")
        brief = st2.json().get("brief") or {}
        cw_id = brief.get("chatwoot_conversation_id", "")
        cw_mode = (snap.get("chatwoot") or {}).get("mode", "")
        sync_ok = bool(cw_id) if cw_mode == "mock" else hr.json().get("ok")
        results.append(CaseResult("ENT", "system", "CHATWOOT-mock-sync", hr.json().get("ok") and sync_ok, cw_id[:30] or cw_mode, int((time.time() - t0) * 1000)))

        t0 = time.time()
        import jwt
        token = headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            lr = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
            token = lr.json().get("token", "")
        payload = jwt.decode(token, options={"verify_signature": False}) if token else {}
        results.append(CaseResult("ENT", "admin", "JWT-tenant-claim", "tenant_id" in payload, payload.get("tenant_id", ""), int((time.time() - t0) * 1000)))

        t0 = time.time()
        has_ht = bool(hr.json().get("handoff_token"))
        results.append(CaseResult("ENT", "customer", "HANDOFF-user-token", has_ht or not status.get("auth_required"), str(has_ht), int((time.time() - t0) * 1000)))

    return results


def main() -> int:
    from datetime import datetime

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = asyncio.run(run_enterprise_suite())
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    path = REPORT_DIR / f"enterprise_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
    path.write_text(render_report(results, base, started), encoding="utf-8")
    print(f"[ENTERPRISE E2E] 通过 {passed}/{total}")
    print(f"[ENTERPRISE E2E] 报告: {path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
