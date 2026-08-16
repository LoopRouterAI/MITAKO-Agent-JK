# -*- coding: utf-8 -*-
"""
自联调脚本 — MITAKO 对接甲方模拟终端（不 import MITAKO 业务模块）

前置:
  1. python tools/partner_lab/mock_idp_server.py
  2. python tools/partner_lab/mock_chatwoot_server.py
  3. MITAKO main.py 已配置 lab 环境变量（见 docs/delivery/integration-lab.md）
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

MITAKO = "http://127.0.0.1:8000"
MOCK_IDP = "http://127.0.0.1:9101"
MOCK_CW = "http://127.0.0.1:9102"
MOCK_BIZ = "http://127.0.0.1:9103"


def _get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:200]}


def _post(url: str, data: dict, headers: dict | None = None) -> tuple[int, dict]:
    raw = json.dumps(data).encode("utf-8")
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=raw, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:200]}


def main() -> int:
    ok_count = 0
    total = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal ok_count, total
        total += 1
        mark = "PASS" if cond else "FAIL"
        if cond:
            ok_count += 1
        print(f"  [{mark}] {name} {detail}")

    print("=== 甲方模拟终端健康检查 ===")
    for name, base in [("MockIdP", MOCK_IDP), ("MockChatwoot", MOCK_CW), ("MockBiz", MOCK_BIZ)]:
        code, body = _get(f"{base}/health")
        check(name, code == 200 and body.get("ok"), str(body)[:60])

    print("\n=== Mock 业务 API 契约 ===")
    code, body = _get(f"{MOCK_BIZ}/api/v1/orders/PT20240602002")
    check("Biz-order", code == 200 and body.get("order", {}).get("refund_status") == "processing")
    code, body = _post(f"{MOCK_BIZ}/api/v1/refund/card", {"order_id": "PT20240602002"})
    check("Biz-refund-card", code == 200 and body.get("card_available") is True)

    print("\n=== MITAKO 服务 ===")
    code, body = _get(f"{MITAKO}/api/v1/auth/status")
    check("MITAKO-up", code == 200 and body.get("ok"))

    print("\n=== SSO 联调（Mock IdP -> MITAKO callback）===")
    code, ar = _get(f"{MITAKO}/api/v1/auth/sso/bpo-east/authorize")
    state = ar.get("state", "")
    check("SSO-authorize", code == 200 and bool(state), f"mode={ar.get('mode')}")
    if state and ar.get("mode") == "oidc":
        code, cb = _post(f"{MITAKO}/api/v1/auth/sso/callback", {
            "tenant_id": "bpo-east",
            "code": "lab_oidc_code",
            "state": state,
        })
        check("SSO-callback", code == 200 and cb.get("ok") and bool(cb.get("token")), cb.get("error", "")[:40])
    else:
        check("SSO-callback-skipped", True, "Demo 模式或未配置 OIDC lab tenant")

    print("\n=== Chatwoot Live 联调（需 CHATWOOT_MOCK=0 + BASE=9102）===")
    code, st = _get(f"{MITAKO}/api/v1/auth/status")
    code, lr = _post(f"{MITAKO}/api/v1/auth/login", {"username": "admin", "password": "admin123"})
    token = lr.get("token", "")
    ah = {"Authorization": f"Bearer {token}"} if token else {}
    import time
    sid = f"lab_cw_{int(time.time())}"
    _post(f"{MITAKO}/api/v1/handoff/reset?session_id={sid}", {}, headers=ah)
    code, hr = _post(
        f"{MITAKO}/api/v1/handoff/request",
        {
            "user_id": "lab_user",
            "session_id": sid,
            "history": [],
            "reason": "partner lab handoff",
            "intent": "物流",
            "emotion_level": 2,
        },
    )
    check("Handoff-request", hr.get("ok") is True, sid)
    code, cw_events = _get(f"{MOCK_CW}/events")
    code, ops = _get(f"{MITAKO}/api/v1/ops/snapshot", headers=ah)
    cw_mode = ((ops.get("snapshot") or {}).get("chatwoot") or {}).get("mode", "")
    n_conv = sum(1 for e in cw_events.get("events", []) if e.get("type") == "conversation_created")
    if cw_mode == "mock":
        check("Chatwoot-mock-received", True, "skip: 请以 CHATWOOT_MOCK=0 BASE=9102 重启 MITAKO 后重测 Live")
    else:
        check("Chatwoot-mock-received", n_conv >= 1, f"events={n_conv}")

    print(f"\n=== 结果 {ok_count}/{total} ===")
    return 0 if ok_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
