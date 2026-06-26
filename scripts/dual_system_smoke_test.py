# -*- coding: utf-8 -*-
"""
双系统快速冒烟 — 验证五端可访问 + 系统 A/B 核心 API（非 Playwright 全量 E2E）

用法:
  python scripts/dual_system_smoke_test.py
  python scripts/dual_system_smoke_test.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"

PAGES = [
    ("A-用户端", "/"),
    ("A-坐席台", "/desk"),
    ("A-运营台", "/admin"),
    ("B-Companion", "/companion"),
    ("B-CompanionDesk", "/companion-desk"),
]


def _req(method: str, url: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    h = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, {"html_len": len(raw)}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:120]}


def run(base: str) -> int:
    ok_count = 0
    total = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok_count, total
        total += 1
        mark = "PASS" if cond else "FAIL"
        if cond:
            ok_count += 1
        print(f"  [{mark}] {name} {detail}")

    print(f"=== 双系统冒烟 @ {base} ===\n")

    print("--- 服务与五端页面 ---")
    code, st = _req("GET", f"{base}/api/v1/auth/status")
    check("服务存活", code == 200 and st.get("ok"), f"auth_required={st.get('auth_required')}")
    for label, path in PAGES:
        code, body = _req("GET", f"{base}{path}")
        ok = code == 200 and (body.get("html_len", 0) > 100 or body.get("ok"))
        check(f"页面-{label}", ok, f"{path} -> {code}")

    print("\n--- 系统 A · 智能客服 API ---")
    code, lr = _req(
        "POST",
        f"{base}/api/v1/auth/login",
        {"username": "desk0816", "password": "desk123", "tenant_id": "mitako"},
    )
    desk_token = lr.get("token", "")
    check("A-desk登录", code == 200 and bool(desk_token), lr.get("error", "")[:40])
    dh = {"Authorization": f"Bearer {desk_token}"} if desk_token else {}
    code, ds = _req("GET", f"{base}/api/v1/desk/sessions", headers=dh)
    check("A-desk会话列表", code == 200 and ds.get("ok") is True, f"sessions={len(ds.get('sessions') or [])}")

    code, ar = _req(
        "POST",
        f"{base}/api/v1/auth/login",
        {"username": "admin", "password": "admin123", "tenant_id": "mitako"},
    )
    admin_token = ar.get("token", "")
    check("A-admin登录", code == 200 and bool(admin_token), ar.get("error", "")[:40])
    ah = {"Authorization": f"Bearer {admin_token}"} if admin_token else {}
    code, ag = _req("GET", f"{base}/api/v1/admin/agents", headers=ah)
    check("A-admin坐席", code == 200 and ag.get("ok") is True, f"agents={len(ag.get('agents') or [])}")

    print("\n--- 系统 B · Companion API ---")
    uid = "smoke_companion_user"
    code, pr = _req(
        "PUT",
        f"{base}/api/v2/companion/persona/{uid}",
        {
            "agent_name": "小虾",
            "user_title": "主人",
            "personality": "gentle",
            "onboarded": True,
        },
    )
    check("B-persona", code == 200 and pr.get("ok") is True, uid)
    code, wl = _req("GET", f"{base}/api/v2/companion/wishlist/{uid}")
    check("B-wishlist", code == 200 and wl.get("ok") is True, "")

    code, cr = _req(
        "POST",
        f"{base}/api/v1/auth/login",
        {"username": "comp_ops", "password": "comp123", "tenant_id": "mitako"},
    )
    comp_token = cr.get("token", "")
    check("B-comp_ops登录", code == 200 and bool(comp_token), cr.get("error", "")[:40])
    ch = {"Authorization": f"Bearer {comp_token}"} if comp_token else {}
    code, cs = _req("GET", f"{base}/api/v2/companion/desk/sessions", headers=ch)
    check("B-companion-desk", code == 200 and cs.get("ok") is True, f"sessions={len(cs.get('sessions') or [])}")

    print(f"\n=== 结果 {ok_count}/{total} ===")
    if ok_count == total:
        print("双系统冒烟通过。手工 UAT 见 docs/delivery/testing-guide.md §3")
        return 0
    print("存在失败项，请确认已运行 双系统测试-手工UAT-Windows.bat 或 一键启动-Windows.bat")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description="MITAKO 双系统冒烟测试")
    p.add_argument("--base", default=DEFAULT_BASE, help="MITAKO 基址")
    args = p.parse_args()
    return run(args.base.rstrip("/"))


if __name__ == "__main__":
    sys.exit(main())
