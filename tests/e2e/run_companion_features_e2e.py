# -*- coding: utf-8 -*-
"""Companion Phase C/D 专项 E2E — 消费助理 + cs_parttime + 隔离"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import httpx

from tests.e2e.e2e_lib import CaseResult, admin_auth_headers, companion_auth_headers, discover_base, REPORT_DIR, render_report


async def run_companion_features_suite() -> list[CaseResult]:
    results: list[CaseResult] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        base = await discover_base(client, None)
        uid = f"cmp_feat_{int(time.time())}"
        ch = await companion_auth_headers(client, base, uid)

        t0 = time.time()
        pr = await client.put(
            f"{base}/api/v2/companion/persona/{uid}",
            json={"agent_name": "小伴测试", "user_title": "主人", "personality": "gentle", "onboarded": True},
            headers=ch,
        )
        if pr.json().get("companion_token"):
            ch = {"Authorization": f"Bearer {pr.json()['companion_token']}"}
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-persona", pr.json().get("ok"), uid, int((time.time() - t0) * 1000)))

        t0 = time.time()
        wr = await client.post(f"{base}/api/v2/companion/watch/orders", json={"user_id": uid, "order_id": "ORD_E2E_001"}, headers=ch)
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-watch", wr.json().get("ok"), "ORD_E2E_001", int((time.time() - t0) * 1000)))

        t0 = time.time()
        wl = await client.post(f"{base}/api/v2/companion/wishlist", json={"user_id": uid, "product_id": "P002", "note": "e2e"}, headers=ch)
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-wishlist", wl.json().get("ok"), "P002", int((time.time() - t0) * 1000)))

        t0 = time.time()
        sr = await client.get(f"{base}/api/v2/companion/products/search?q=手办", headers=ch)
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-search", sr.json().get("ok") and len(sr.json().get("products", [])) >= 1, str(len(sr.json().get("products", []))), int((time.time() - t0) * 1000)))

        t0 = time.time()
        mr = await client.put(f"{base}/api/v2/companion/persona/{uid}/mode", json={"mode": "cs_parttime"}, headers=ch)
        mode = mr.json().get("persona", {}).get("agent_mode")
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-cs-mode", mr.json().get("ok") and mode == "cs_parttime", mode, int((time.time() - t0) * 1000)))

        t0 = time.time()
        mr2 = await client.put(f"{base}/api/v2/companion/persona/{uid}/mode", json={"mode": "companion"}, headers=ch)
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-mode-reset", mr2.json().get("persona", {}).get("agent_mode") == "companion", "companion", int((time.time() - t0) * 1000)))

        t0 = time.time()
        hr = await client.post(f"{base}/api/v2/companion/handoff/request", json={"user_id": uid, "reason": "e2e隔离"}, headers=ch)
        sid = hr.json().get("session", {}).get("session_id", "")
        ah = await admin_auth_headers(client, base)
        ds = await client.get(f"{base}/api/v1/desk/sessions", headers=ah)
        desk_ids = [s.get("session_id") for s in ds.json().get("sessions", [])]
        isolated = sid and sid not in desk_ids
        results.append(CaseResult("COMP-FEAT", "system", "COMP-desk-isolated", hr.json().get("ok") and isolated, sid, int((time.time() - t0) * 1000)))

        t0 = time.time()
        obs = await client.get(f"{base}/api/v2/companion/observability/summary", headers=ah)
        results.append(CaseResult("COMP-FEAT", "system", "COMP-obs-summary", obs.json().get("ok") and "summary" in obs.json(), str(obs.json().get("summary", {}).get("total_turns")), int((time.time() - t0) * 1000)))

        t0 = time.time()
        await client.put(f"{base}/api/v2/companion/persona/{uid}/mode", json={"mode": "companion"}, headers=ch)
        cr = await client.post(f"{base}/api/v2/companion/chat", json={"user_id": uid, "message": "我的订单物流延迟了要退款"}, headers=ch)
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-cs-intent-chat", cr.status_code == 200, str(cr.status_code), int((time.time() - t0) * 1000)))

        t0 = time.time()
        gp = await client.get(f"{base}/api/v2/companion/persona/{uid}", headers=ch)
        after_mode = gp.json().get("persona", {}).get("agent_mode")
        results.append(CaseResult("COMP-FEAT", "customer", "COMP-cs-intent-mode", after_mode == "cs_parttime", after_mode, int((time.time() - t0) * 1000)))

    return results


def main() -> int:
    from datetime import datetime

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = asyncio.run(run_companion_features_suite())
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    path = REPORT_DIR / f"companion_feat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000")
    path.write_text(render_report(results, base, started), encoding="utf-8")
    print(f"[COMPANION E2E] 通过 {passed}/{total}")
    print(f"[COMPANION E2E] 报告: {path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
