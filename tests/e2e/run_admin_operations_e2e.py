# -*- coding: utf-8 -*-
"""008 管理员运营后台专项 E2E — 审批 / 报表 / 队列"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import httpx

from tests.e2e.e2e_lib import CaseResult, admin_auth_headers, companion_auth_headers, discover_base, REPORT_DIR, render_report


async def run_admin_ops_suite() -> list[CaseResult]:
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        base = await discover_base(client, None)
        lr = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        token = lr.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        # ADMIN-OPS-1 创建补偿审批
        t0 = time.time()
        ar = await client.post(
            f"{base}/api/v1/admin/approvals",
            headers=headers,
            json={"session_id": "admin_e2e_sess", "user_id": "usr_001", "amount": 50, "reason": "E2E 免邮券"},
        )
        aid = ar.json().get("approval", {}).get("id")
        results.append(CaseResult("ADMIN-OPS", "admin", "APPROVAL-create", ar.json().get("ok") is True, f"id={aid}", int((time.time() - t0) * 1000)))

        # ADMIN-OPS-2 列表 pending
        t0 = time.time()
        ls = await client.get(f"{base}/api/v1/admin/approvals?status=pending", headers=headers)
        pending = ls.json().get("approvals") or []
        results.append(CaseResult("ADMIN-OPS", "admin", "APPROVAL-list-pending", ls.json().get("ok") and len(pending) >= 1, str(len(pending)), int((time.time() - t0) * 1000)))

        # ADMIN-OPS-3 批准
        t0 = time.time()
        if aid:
            sr = await client.post(f"{base}/api/v1/auth/login", json={"username": "supervisor", "password": "super123"})
            sh = {"Authorization": f"Bearer {sr.json().get('token')}"} if sr.json().get("token") else headers
            dr = await client.post(f"{base}/api/v1/admin/approvals/{aid}/decide", headers=sh, json={"decision": "approved"})
            ok = dr.json().get("ok") and dr.json().get("approval", {}).get("status") == "approved"
        else:
            ok = False
        results.append(CaseResult("ADMIN-OPS", "admin", "APPROVAL-approve", ok, "approved", int((time.time() - t0) * 1000)))

        # ADMIN-OPS-4 二级审批阈值
        t0 = time.time()
        big = await client.post(
            f"{base}/api/v1/admin/approvals",
            headers=headers,
            json={"amount": 150, "reason": "E2E 大额", "user_id": "usr_003"},
        )
        lvl = big.json().get("approval", {}).get("approval_level")
        results.append(CaseResult("ADMIN-OPS", "admin", "APPROVAL-level2", big.json().get("ok") and lvl == 2, f"level={lvl}", int((time.time() - t0) * 1000)))

        # ADMIN-OPS-5 报表 summary
        t0 = time.time()
        rr = await client.get(f"{base}/api/v1/admin/reports/summary?days=7", headers=headers)
        sm = rr.json().get("summary") or {}
        results.append(CaseResult("ADMIN-OPS", "admin", "REPORT-summary", rr.json().get("ok") and "total_sessions" in sm, str(sm.get("total_sessions")), int((time.time() - t0) * 1000)))

        # ADMIN-OPS-6 CSV 导出
        t0 = time.time()
        cr = await client.get(f"{base}/api/v1/admin/reports/export.csv?days=7", headers=headers)
        results.append(CaseResult("ADMIN-OPS", "admin", "REPORT-csv-export", cr.status_code == 200 and "metric,value" in cr.text, cr.text[:30], int((time.time() - t0) * 1000)))

        # ADMIN-OPS-7 审计事件
        t0 = time.time()
        ev = await client.get(f"{base}/api/v1/admin/audit/events?limit=5", headers=headers)
        results.append(CaseResult("ADMIN-OPS", "admin", "AUDIT-events", ev.json().get("ok"), f"count={len(ev.json().get('events', []))}", int((time.time() - t0) * 1000)))

        # ADMIN-OPS-8 强制转交 API 存在性（无会话时 error 可接受）
        t0 = time.time()
        rs = await client.post(
            f"{base}/api/v1/admin/queue/none_sess/reassign",
            headers=headers,
            json={"to_agent_id": "CS-0816", "note": "e2e"},
        )
        results.append(CaseResult("ADMIN-OPS", "admin", "QUEUE-reassign-api", rs.status_code == 200, rs.json().get("error", rs.json().get("ok")), int((time.time() - t0) * 1000)))

        # COMPANION Phase C/D
        uid = f"cmp_ops_{int(time.time())}"
        ch = await companion_auth_headers(client, base, uid)
        t0 = time.time()
        pr = await client.get(f"{base}/api/v2/companion/products/search?q=排球", headers=ch)
        results.append(CaseResult("COMPANION-OPS", "customer", "COMP-products-search", pr.json().get("ok"), str(len(pr.json().get("products", []))), int((time.time() - t0) * 1000)))

        t0 = time.time()
        wr = await client.post(f"{base}/api/v2/companion/watch/orders", json={"user_id": uid, "order_id": "ORD20240601001"}, headers=ch)
        results.append(CaseResult("COMPANION-OPS", "customer", "COMP-watch-order", wr.json().get("ok"), uid, int((time.time() - t0) * 1000)))

        t0 = time.time()
        wl = await client.post(f"{base}/api/v2/companion/wishlist", json={"user_id": uid, "product_id": "P001", "note": "e2e"}, headers=ch)
        results.append(CaseResult("COMPANION-OPS", "customer", "COMP-wishlist-add", wl.json().get("ok"), str(wl.json().get("item", {}).get("id")), int((time.time() - t0) * 1000)))

        t0 = time.time()
        hr = await client.post(f"{base}/api/v2/companion/handoff/request", json={"user_id": uid, "reason": "需要人工陪伴"}, headers=ch)
        sid = hr.json().get("session", {}).get("session_id", "")
        results.append(CaseResult("COMPANION-OPS", "operator", "COMP-handoff-request", hr.json().get("ok"), sid, int((time.time() - t0) * 1000)))

        t0 = time.time()
        cop = await client.post(f"{base}/api/v1/auth/login", json={"username": "comp_ops", "password": "comp123"})
        cop_h = {"Authorization": f"Bearer {cop.json().get('token')}"} if cop.json().get("token") else headers
        obs = await client.get(f"{base}/api/v2/companion/observability/summary", headers=cop_h)
        results.append(CaseResult("COMPANION-OPS", "operator", "COMP-obs-summary", obs.json().get("ok"), str(obs.json().get("summary", {}).get("total_turns")), int((time.time() - t0) * 1000)))

        t0 = time.time()
        tr = await client.get(f"{base}/api/v2/companion/observability/traces?limit=5", headers=cop_h)
        results.append(CaseResult("COMPANION-OPS", "operator", "COMP-obs-traces", tr.json().get("ok"), str(len(tr.json().get("traces", []))), int((time.time() - t0) * 1000)))

        # AUTH 无效登录
        t0 = time.time()
        bad = await client.post(f"{base}/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        results.append(CaseResult("PROD", "admin", "AUTH-bad-password", bad.json().get("ok") is not True, bad.text[:40], int((time.time() - t0) * 1000)))

        # METRICS ws_connections 字段
        t0 = time.time()
        mr = await client.get(f"{base}/metrics")
        results.append(CaseResult("PROD", "system", "METRICS-ws-field", "ws_connections" in mr.json(), str(mr.json().get("ws_connections")), int((time.time() - t0) * 1000)))

    return results


def main() -> int:
    from datetime import datetime

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = asyncio.run(run_admin_ops_suite())
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    path = REPORT_DIR / f"admin_ops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
    path.write_text(render_report(results, base, started), encoding="utf-8")
    print(f"[ADMIN E2E] 通过 {passed}/{total}")
    print(f"[ADMIN E2E] 报告: {path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
