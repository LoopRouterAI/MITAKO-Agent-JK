# -*- coding: utf-8 -*-
"""
MITAKO 全链路 E2E — 代码 / 通信 / 链路 × 客户 / 客服 / 管理员

用法:
  python tests/e2e/run_full_pipeline_e2e.py
  E2E_BASE_URL=http://127.0.0.1:8002 python tests/e2e/run_full_pipeline_e2e.py

前置: npm run build && python main.py
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
E2E_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(E2E_DIR))

from e2e_lib import (  # noqa: E402
    REPORT_DIR,
    CaseResult,
    admin_auth_headers,
    discover_base,
    hist_l5,
    render_report,
    request_handoff,
    reset_session,
)


def handoff_headers(data: dict) -> dict:
    token = data.get("handoff_token") or ""
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------------------------------------------------------------------
# 代码层 — 不依赖运行中后端（部分需 dist）
# ---------------------------------------------------------------------------
def run_code_tests(results: list[CaseResult]) -> None:
    dist = ROOT / "dist"
    for name in ("index.html", "desk.html", "admin.html"):
        t0 = time.time()
        p = dist / name
        ok = p.is_file() and p.stat().st_size > 200
        results.append(CaseResult("CODE", "system", f"C-build-{name}", ok, f"size={p.stat().st_size if p.is_file() else 0}", int((time.time() - t0) * 1000)))

    modules = ("handoff_store", "handoff_service", "handoff_routing", "handoff_ws", "handoff_observer")
    for mod in modules:
        t0 = time.time()
        try:
            importlib.import_module(mod)
            ok = True
            detail = "import ok"
        except Exception as e:
            ok = False
            detail = str(e)[:120]
        results.append(CaseResult("CODE", "system", f"C-import-{mod}", ok, detail, int((time.time() - t0) * 1000)))

    t0 = time.time()
    try:
        from handoff_store import _ensure_db  # noqa: WPS433
        from handoff_store import _connect

        _ensure_db()
        with _connect() as conn:
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='handoff_sessions'").fetchone()
        ok = row is not None
        detail = "handoff_sessions table exists"
    except Exception as e:
        ok = False
        detail = str(e)[:120]
    results.append(CaseResult("CODE", "system", "C-sqlite-schema", ok, detail, int((time.time() - t0) * 1000)))

    t0 = time.time()
    try:
        from handoff_routing import load_routing_config

        cfg = load_routing_config()
        ok = "rules" in cfg and "sla" in cfg and cfg.get("default_required_tier") == "standard"
        detail = f"tier={cfg.get('default_required_tier')}, rules={len(cfg.get('rules', []))}"
    except Exception as e:
        ok = False
        detail = str(e)[:120]
    results.append(CaseResult("CODE", "system", "C-routing-config", ok, detail, int((time.time() - t0) * 1000)))


# ---------------------------------------------------------------------------
# 通信层
# ---------------------------------------------------------------------------
async def run_comm_tests(client: httpx.AsyncClient, base: str, results: list[CaseResult]) -> None:
    endpoints = [
        ("GET", "/api/v1/auth/status", None),
        ("GET", "/api/v1/desk/agents", None),
        ("GET", "/api/v1/desk/sessions", None),
        ("GET", "/", None),
        ("GET", "/desk", None),
        ("GET", "/admin", None),
    ]
    for method, path, _ in endpoints:
        t0 = time.time()
        try:
            r = await client.request(method, f"{base}{path}")
            ok = r.status_code == 200
            if path == "/":
                ok = ok and ("main-" in r.text or "index-" in r.text or "root" in r.text)
            if path in ("/desk", "/admin"):
                ok = ok and len(r.text) > 300
            results.append(CaseResult("COMM", "system", f"M-{method}{path}", ok, f"status={r.status_code}", int((time.time() - t0) * 1000)))
        except Exception as e:
            results.append(CaseResult("COMM", "system", f"M-{method}{path}", False, str(e)[:120], int((time.time() - t0) * 1000)))

    sid = f"comm_none_{int(time.time())}"
    t0 = time.time()
    r = await client.get(f"{base}/api/v1/handoff/status/{sid}")
    d = r.json()
    ok = r.status_code == 200 and d.get("status") == "none"
    results.append(CaseResult("COMM", "system", "M-status-unknown-session", ok, str(d.get("status")), int((time.time() - t0) * 1000)))

    t0 = time.time()
    r = await client.post(f"{base}/api/v1/handoff/connect", params={"session_id": sid})
    d = r.json()
    ok = not d.get("ok") and d.get("status") in ("none", None)
    results.append(CaseResult("COMM", "customer", "M-connect-before-session", ok, str(d), int((time.time() - t0) * 1000)))


async def run_ws_tests(client: httpx.AsyncClient, base: str, results: list[CaseResult]) -> None:
    sid = f"comm_ws_{int(time.time())}"
    await reset_session(client, base, sid)
    received: list = []

    async def listen():
        import websockets

        uri = base.replace("http", "ws") + f"/api/v1/handoff/ws/{sid}"
        async with websockets.connect(uri) as ws:
            await request_handoff(client, base, sid, emotion=3, intent="物流")
            await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-0816"})
            deadline = time.time() + 6
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                    received.append(json.loads(raw))
                    if any(x.get("type") == "message" for x in received):
                        break
                except asyncio.TimeoutError:
                    continue
            await client.post(
                f"{base}/api/v1/desk/session/{sid}/reply",
                json={"content": "WS 测试回复 #优先发货特权#", "agent_id": "CS-0816"},
            )
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                received.append(json.loads(raw))
            except asyncio.TimeoutError:
                pass

    t0 = time.time()
    try:
        import websockets  # noqa: F401

        await listen()
        has_status = any(x.get("type") == "status" for x in received)
        has_msg = any(x.get("type") == "message" for x in received)
        ok = has_status and has_msg
        results.append(
            CaseResult(
                "COMM",
                "customer",
                "W-ws-status-and-message",
                ok,
                f"events={len(received)} status={has_status} msg={has_msg}",
                int((time.time() - t0) * 1000),
            )
        )
    except ImportError:
        results.append(CaseResult("COMM", "customer", "W-ws-status-and-message", False, "websockets 未安装", 0))
    except Exception as e:
        results.append(CaseResult("COMM", "customer", "W-ws-status-and-message", False, str(e)[:160], int((time.time() - t0) * 1000)))

    t0 = time.time()
    since = 0.0
    await reset_session(client, base, sid + "_p")
    sid2 = sid + "_p"
    handoff = await request_handoff(client, base, sid2, emotion=2)
    headers = handoff_headers(handoff)
    r1 = await client.get(f"{base}/api/v1/handoff/messages/{sid2}", params={"since": since}, headers=headers)
    d1 = r1.json()
    await client.post(f"{base}/api/v1/desk/session/{sid2}/accept", json={"agent_id": "CS-0816"})
    latest = d1.get("latest_ts", since)
    r2 = await client.get(f"{base}/api/v1/handoff/messages/{sid2}", params={"since": latest}, headers=headers)
    d2 = r2.json()
    ok = d1.get("ok") and d2.get("ok") and len(d2.get("messages", [])) >= 1
    results.append(CaseResult("COMM", "customer", "M-messages-incremental-poll", ok, f"delta={len(d2.get('messages', []))}", int((time.time() - t0) * 1000)))


# ---------------------------------------------------------------------------
# 角色：客户
# ---------------------------------------------------------------------------
async def run_customer_role(client: httpx.AsyncClient, base: str, results: list[CaseResult]) -> tuple[str, dict]:
    sid = f"role_user_{int(time.time())}"
    await reset_session(client, base, sid)

    t0 = time.time()
    data = await request_handoff(client, base, sid, emotion=4)
    headers = handoff_headers(data)
    ok = data.get("ok") and data.get("queue")
    results.append(CaseResult("ROLE", "customer", "U-request-handoff", ok, f"tier={data.get('queue', {}).get('required_tier')}", int((time.time() - t0) * 1000)))

    t0 = time.time()
    st = (await client.get(f"{base}/api/v1/handoff/status/{sid}", headers=headers)).json()
    ok = st.get("ok") and st.get("status") == "queuing"
    results.append(CaseResult("ROLE", "customer", "U-status-queuing", ok, st.get("status", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    conn = (await client.post(f"{base}/api/v1/handoff/connect", params={"session_id": sid}, headers=headers)).json()
    ok = not conn.get("ok")
    results.append(CaseResult("ROLE", "customer", "U-no-fake-connect", ok, str(conn.get("status")), int((time.time() - t0) * 1000)))

    t0 = time.time()
    um = (await client.post(
        f"{base}/api/v1/handoff/user-message",
        json={"session_id": sid, "content": "还在吗", "user_id": "usr_e2e"},
        headers=headers,
    )).json()
    queued_user_messages = [m for m in um.get("messages", []) if m.get("role") == "user"]
    ok = um.get("ok") is True and any("还在吗" in (m.get("content") or "") for m in queued_user_messages)
    results.append(CaseResult(
        "ROLE",
        "customer",
        "U-user-msg-allowed-before-accept",
        ok,
        f"queued_messages={len(queued_user_messages)}",
        int((time.time() - t0) * 1000),
    ))

    return sid, headers


# ---------------------------------------------------------------------------
# 角色：VIP客服
# ---------------------------------------------------------------------------
async def run_agent_role(client: httpx.AsyncClient, base: str, sid: str, customer_headers: dict, results: list[CaseResult]) -> None:
    t0 = time.time()
    sessions = (await client.get(f"{base}/api/v1/desk/sessions")).json()
    found = any(s.get("session_id") == sid for s in sessions.get("sessions", []))
    ok = sessions.get("ok") and found
    results.append(CaseResult("ROLE", "agent", "A-list-sees-session", ok, f"total={len(sessions.get('sessions', []))}", int((time.time() - t0) * 1000)))

    t0 = time.time()
    detail = (await client.get(f"{base}/api/v1/desk/session/{sid}")).json()
    brief = detail.get("brief") or {}
    ok = detail.get("ok") and brief.get("summary") and detail.get("can_accept") is True
    results.append(CaseResult("ROLE", "agent", "A-brief-before-accept", ok, (brief.get("summary") or "")[:80], int((time.time() - t0) * 1000)))

    t0 = time.time()
    reply = (await client.post(
        f"{base}/api/v1/desk/session/{sid}/reply",
        json={"content": "不应成功", "agent_id": "CS-0816"},
    )).json()
    ok = not reply.get("ok") and reply.get("error") == "not_accepted"
    results.append(CaseResult("ROLE", "agent", "A-reply-blocked-before-accept", ok, reply.get("error", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    acc = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-0816"})).json()
    ok = acc.get("ok") and acc.get("status") == "connected"
    results.append(CaseResult("ROLE", "agent", "A-accept-connected", ok, acc.get("agent", {}).get("agent_id", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    await client.post(
        f"{base}/api/v1/desk/session/{sid}/reply",
        json={"content": "您好，已为您加急 #优先发货特权#", "agent_id": "CS-0816"},
    )
    msgs = (await client.get(f"{base}/api/v1/handoff/messages/{sid}", headers=customer_headers)).json()
    ok = any("优先发货" in (m.get("content") or "") for m in msgs.get("messages", []) if m.get("role") == "human")
    results.append(CaseResult("ROLE", "agent", "A-reply-reaches-customer", ok, f"msgs={len(msgs.get('messages', []))}", int((time.time() - t0) * 1000)))

    t0 = time.time()
    tr = (await client.post(
        f"{base}/api/v1/desk/session/{sid}/transfer",
        json={"from_agent_id": "CS-0816", "to_agent_id": "CS-0922", "note": "E2E转交"},
    )).json()
    ok = tr.get("ok") and tr.get("status") == "transferring"
    results.append(CaseResult("ROLE", "agent", "A-transfer-colleague", ok, str(tr.get("pending_agent", {}).get("agent_id")), int((time.time() - t0) * 1000)))

    t0 = time.time()
    acc2 = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-0922"})).json()
    ok = acc2.get("ok") and acc2.get("agent", {}).get("agent_id") == "CS-0922"
    results.append(CaseResult("ROLE", "agent", "A-colleague-accept", ok, acc2.get("agent", {}).get("agent_id", ""), int((time.time() - t0) * 1000)))


# ---------------------------------------------------------------------------
# 角色：管理员
# ---------------------------------------------------------------------------
async def run_admin_role(client: httpx.AsyncClient, base: str, results: list[CaseResult]) -> None:
    headers = await admin_auth_headers(client, base)
    t0 = time.time()
    cfg_resp = (await client.get(f"{base}/api/v1/admin/handoff/routing", headers=headers)).json()
    cfg = cfg_resp.get("config") or {}
    ok = cfg_resp.get("ok") and isinstance(cfg.get("rules"), list)
    results.append(CaseResult("ROLE", "admin", "AD-get-routing", ok, f"rules={len(cfg.get('rules', []))}", int((time.time() - t0) * 1000)))

    backup = json.loads(json.dumps(cfg))
    t0 = time.time()
    cfg["sla"] = {**(cfg.get("sla") or {}), "first_response_seconds": 179}
    put = (await client.put(f"{base}/api/v1/admin/handoff/routing", headers=headers, json=cfg)).json()
    get = (await client.get(f"{base}/api/v1/admin/handoff/routing", headers=headers)).json()
    ok = put.get("ok") and get.get("config", {}).get("sla", {}).get("first_response_seconds") == 179
    results.append(CaseResult("ROLE", "admin", "AD-put-routing-persist", ok, "sla=179", int((time.time() - t0) * 1000)))

    t0 = time.time()
    for rule in cfg.get("rules", []):
        if rule.get("id") == "high_emotion_supervisor":
            rule["enabled"] = True
    await client.put(f"{base}/api/v1/admin/handoff/routing", headers=headers, json=cfg)
    sid = f"admin_l5_{int(time.time())}"
    await reset_session(client, base, sid)
    data = await request_handoff(client, base, sid, emotion=5)
    tier = data.get("queue", {}).get("required_tier") or data.get("brief", {}).get("required_tier")
    bad = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-0816"})).json()
    good = (await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-1024"})).json()
    ok = (tier == "supervisor" or bad.get("error") == "need_supervisor") and not bad.get("ok") and good.get("ok")
    results.append(
        CaseResult(
            "ROLE",
            "admin",
            "AD-rule-affects-new-session",
            ok,
            f"tier={tier}, std={bad.get('error')}, sup={good.get('ok')}",
            int((time.time() - t0) * 1000),
        )
    )
    await client.put(f"{base}/api/v1/admin/handoff/routing", headers=headers, json=backup)

    t0 = time.time()
    page = await client.get(f"{base}/admin")
    ok = page.status_code == 200 and ("admin-" in page.text or "HandoffAdmin" in page.text or "转VIP客服" in page.text)
    results.append(CaseResult("ROLE", "admin", "AD-admin-page-load", ok, f"len={len(page.text)}", int((time.time() - t0) * 1000)))


# ---------------------------------------------------------------------------
# 链路层 — 跨角色编排
# ---------------------------------------------------------------------------
async def run_chain_tests(client: httpx.AsyncClient, base: str, results: list[CaseResult]) -> None:
    sid = f"chain_full_{int(time.time())}"
    await reset_session(client, base, sid)

    t0 = time.time()
    handoff = await request_handoff(client, base, sid, emotion=4)
    headers = handoff_headers(handoff)
    st = (await client.get(f"{base}/api/v1/handoff/status/{sid}", headers=headers)).json()
    ok = st.get("status") == "queuing"
    results.append(CaseResult("CHAIN", "customer", "L-queue-before-accept", ok, st.get("status", ""), int((time.time() - t0) * 1000)))

    await client.post(f"{base}/api/v1/desk/session/{sid}/accept", json={"agent_id": "CS-0816"})
    t0 = time.time()
    conn = (await client.post(f"{base}/api/v1/handoff/connect", params={"session_id": sid}, headers=headers)).json()
    ok = conn.get("ok") and conn.get("status") == "connected" and conn.get("welcome")
    results.append(CaseResult("CHAIN", "customer", "L-connect-after-accept", ok, "welcome ok", int((time.time() - t0) * 1000)))

    t0 = time.time()
    obs = (await client.post(
        f"{base}/api/v1/handoff/user-message",
        json={"session_id": sid, "content": "@虾饺 帮我和专员确认发货时间", "user_id": "usr_e2e"},
        headers=headers,
    )).json()
    messages = obs.get("messages") or []
    observer = [m for m in messages if m.get("role") == "observer"]
    text = observer[0].get("content", "") if observer else ""
    bad = any(w in text for w in ("退现金", "全额退款", "一定赔"))
    ok = obs.get("ok") and len(observer) >= 1 and not bad
    results.append(CaseResult("CHAIN", "customer", "L-observer-xiaojiao", ok, text[:90], int((time.time() - t0) * 1000)))

    sid2 = f"chain_esc_{int(time.time())}"
    await reset_session(client, base, sid2)
    await request_handoff(client, base, sid2, emotion=3)
    await client.post(f"{base}/api/v1/desk/session/{sid2}/accept", json={"agent_id": "CS-0816"})
    t0 = time.time()
    esc = (await client.post(
        f"{base}/api/v1/desk/session/{sid2}/escalate",
        json={"note": "用户威胁投诉"},
    )).json()
    detail = (await client.get(f"{base}/api/v1/desk/session/{sid2}")).json()
    ok = esc.get("ok") and esc.get("status") == "escalated" and detail.get("required_tier") == "supervisor"
    results.append(CaseResult("CHAIN", "agent", "L-escalate-to-supervisor", ok, esc.get("status", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    acc = (await client.post(f"{base}/api/v1/desk/session/{sid2}/accept", json={"agent_id": "CS-1024"})).json()
    ok = acc.get("ok") and acc.get("status") == "connected"
    results.append(CaseResult("CHAIN", "agent", "L-supervisor-accept-escalated", ok, acc.get("agent", {}).get("agent_id", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    r = await request_handoff(client, base, f"chain_tag_{int(time.time())}", emotion=2, intent="物流")
    brief = r.get("brief") or {}
    tag_ok = "#优先发货特权#" in str(brief.get("ai_dialogue_summary", "")) or "#优先发货特权#" in str(brief.get("conversation_snippet", ""))
    results.append(CaseResult("CHAIN", "system", "L-brief-richtext-tag", tag_ok, (brief.get("ai_dialogue_summary") or "")[:80], int((time.time() - t0) * 1000)))


async def run_customer_after_agent(client: httpx.AsyncClient, base: str, sid: str, customer_headers: dict, results: list[CaseResult]) -> None:
    t0 = time.time()
    conn = (await client.post(f"{base}/api/v1/handoff/connect", params={"session_id": sid}, headers=customer_headers)).json()
    ok = conn.get("ok") and conn.get("status") == "connected"
    results.append(CaseResult("ROLE", "customer", "U-connect-after-agent-accept", ok, conn.get("status", ""), int((time.time() - t0) * 1000)))

    t0 = time.time()
    msgs = (await client.get(f"{base}/api/v1/handoff/messages/{sid}", headers=customer_headers)).json()
    human = [m for m in msgs.get("messages", []) if m.get("role") == "human"]
    ok = msgs.get("ok") and len(human) >= 1
    results.append(CaseResult("ROLE", "customer", "U-messages-after-accept", ok, f"human={len(human)}", int((time.time() - t0) * 1000)))


async def run_api_suite(results: list[CaseResult]) -> tuple[str, int]:
    """API/通信/链路测试；返回 (base, exit_code_if_early_fail)"""
    from datetime import datetime

    explicit = os.getenv("E2E_BASE_URL", "").rstrip("/") or None
    async with httpx.AsyncClient(timeout=60.0) as client:
        base = await discover_base(client, explicit)
        try:
            ping = await client.get(f"{base}/api/v1/auth/status")
            if ping.status_code != 200 or not ping.json().get("ok"):
                print(f"[FAIL] 后端不可达: {base}")
                return base, 1
        except Exception as e:
            print(f"[FAIL] 无法连接后端: {e}")
            print("请先: npm run build && python main.py")
            started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fail_base = explicit or "http://127.0.0.1:8001"
            path = REPORT_DIR / f"full_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            path.write_text(render_report(results, fail_base, started), encoding="utf-8")
            return fail_base, 1

        print(f"[E2E] API 套件 base={base}")

        await run_comm_tests(client, base, results)
        await run_ws_tests(client, base, results)

        sid, customer_headers = await run_customer_role(client, base, results)
        await run_agent_role(client, base, sid, customer_headers, results)
        await run_customer_after_agent(client, base, sid, customer_headers, results)
        await run_admin_role(client, base, results)
        await run_chain_tests(client, base, results)

    return base, 0


def main() -> int:
    from datetime import datetime
    from browser_e2e import run_browser_e2e

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results: list[CaseResult] = []

    run_code_tests(results)

    base, early = asyncio.run(run_api_suite(results))
    if early:
        for r in results:
            if not r.ok:
                print(f"  [FAIL] {r.name}")
        return early

    print("[E2E] 启动 Playwright 浏览器验收…")
    browser_results, _ = run_browser_e2e(base)
    results.extend(browser_results)

    path = REPORT_DIR / f"full_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_id = path.stem.replace("full_pipeline_", "")
    path.write_text(render_report(results, base, started, report_id), encoding="utf-8")

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print(f"[E2E] 专业 HTML 报告: {path.resolve()}")
    print(f"[E2E] 通过 {passed}/{total}")
    for layer in ("CODE", "COMM", "CHAIN", "ROLE", "BROWSER"):
        lp = sum(1 for r in results if r.layer == layer and r.ok)
        lt = sum(1 for r in results if r.layer == layer)
        if lt:
            print(f"  {layer}: {lp}/{lt}")
    for r in results:
        if not r.ok:
            print(f"  [FAIL] {r.name}: {r.detail[:100]}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
