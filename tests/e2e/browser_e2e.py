# -*- coding: utf-8 -*-
"""Playwright 真实浏览器 E2E — 客户 / 客服 / 管理员三角色"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import List

import httpx

from e2e_lib import CaseResult

SCREENSHOT_DIR = Path(__file__).resolve().parents[1] / "reports" / "screenshots"
USER_ID = "usr_001"
SESSION_ID = f"session_{USER_ID}"


def _shot(page, name: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _case(layer: str, role: str, name: str, ok: bool, detail: str, ms: int, screenshot_b64: str = "") -> CaseResult:
    extra = {"screenshot_b64": screenshot_b64, "mode": "browser"} if screenshot_b64 else {"mode": "browser"}
    return CaseResult(layer, role, name, ok, detail, ms, extra)


def _cleanup_sessions(client: httpx.Client, base: str) -> None:
    try:
        ls = client.get(f"{base}/api/v1/desk/sessions").json()
        for s in ls.get("sessions", []):
            sid = s.get("session_id", "")
            if sid.startswith(("e2e_", "chain_", "role_", "comm_", "admin_", "browser_")):
                client.post(f"{base}/api/v1/handoff/reset", params={"session_id": sid})
    except Exception:
        pass
    client.post(f"{base}/api/v1/handoff/reset", params={"session_id": SESSION_ID})


def _handoff_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _wait_handoff_status(base: str, want: str, token: str = "", timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            st = httpx.get(f"{base}/api/v1/handoff/status/{SESSION_ID}", headers=_handoff_headers(token), timeout=5).json()
            if st.get("status") == want:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _wait_desk_session_status(base: str, session_id: str, want: str, token: str = "", timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    while time.time() < deadline:
        try:
            body = httpx.get(f"{base}/api/v1/desk/sessions", headers=headers, timeout=5).json()
            for item in body.get("sessions", []):
                if item.get("session_id") == session_id and item.get("status") == want:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def run_browser_e2e(base: str) -> tuple[List[CaseResult], bool]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [
            CaseResult("BROWSER", "system", "B-playwright-installed", False,
                       "请 pip install playwright && playwright install chromium", 0, {"mode": "browser"}),
        ], False

    results: List[CaseResult] = []
    with httpx.Client(timeout=30.0) as client:
        _cleanup_sessions(client, base)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        customer = ctx.new_page()
        desk = ctx.new_page()
        admin = ctx.new_page()

        # ── 客户：输入真实高风险售后诉求，触发后端硬路由转人工 ──
        t0 = time.time()
        try:
            customer.goto(f"{base}/", wait_until="domcontentloaded", timeout=30000)
            customer.wait_for_selector("#root", timeout=10000)
            customer.locator('input[name="chat_message"]').fill("这个订单我要退款 980 元，请人工客服继续处理")
            customer.locator('input[name="chat_message"]').press("Enter")
            customer.wait_for_function(
                """() => {
                  const el = document.querySelector('[data-testid="handoff-status-banner"]');
                  if (!el) return false;
                  const text = el.innerText || '';
                  return !text.includes('已接入')
                    && (text.includes('繁忙') || text.includes('联系人工') || text.includes('排队') || text.includes('转接'));
                }""",
                timeout=20000,
            )
            banner = customer.locator('[data-testid="handoff-status-banner"]').inner_text()
            ok = ("繁忙" in banner or "联系人工" in banner or "排队" in banner or "转接" in banner) and "已接入" not in banner
            b64 = _shot(customer, "01_customer_queuing")
            results.append(_case("BROWSER", "customer", "B-customer-queue-banner", ok, banner[:120], int((time.time() - t0) * 1000), b64))
            results.append(_case("BROWSER", "customer", "B-customer-ui-queuing", True, "UI 已进入排队状态", 0))
        except Exception as e:
            results.append(_case("BROWSER", "customer", "B-customer-queue-banner", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── 客服：选会话 → 确认接单 ──
        t0 = time.time()
        try:
            desk.goto(f"{base}/desk", wait_until="domcontentloaded", timeout=30000)
            desk.wait_for_selector("#root", timeout=10000)
            desk.get_by_role("button", name="刷新").click()
            desk.wait_for_timeout(600)
            session_btn = desk.get_by_test_id(f"desk-session-{SESSION_ID}")
            session_btn.wait_for(state="visible", timeout=20000)
            session_btn.click()
            desk.wait_for_selector('[data-testid="desk-accept-handoff"]', timeout=10000)
            brief_ok = "移交简报" in desk.content() or "来访摘要" in desk.content()
            desk.locator('[data-testid="desk-accept-handoff"]').click()
            desk.locator('[data-testid="desk-accept-confirm"]').click()
            desk_token = desk.evaluate("() => sessionStorage.getItem('mitako_auth_token_v1') || ''")
            if not _wait_desk_session_status(base, SESSION_ID, "connected", desk_token, 20):
                raise RuntimeError("坐席会话列表未进入 connected")
            desk.wait_for_timeout(800)
            b64 = _shot(desk, "02_desk_accepted")
            results.append(_case("BROWSER", "agent", "B-desk-brief-visible", brief_ok, "简报已展示", int((time.time() - t0) * 1000), b64))
            results.append(_case("BROWSER", "agent", "B-desk-accept-click", True, "确认阅读并接受转接", 0))
        except Exception as e:
            results.append(_case("BROWSER", "agent", "B-desk-accept-flow", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── 客户：已接入 banner ──
        t0 = time.time()
        try:
            customer.wait_for_function(
                """() => {
                  const el = document.querySelector('[data-testid="handoff-status-banner"]');
                  return el && (el.innerText.includes('已接入') || el.innerText.includes('旁听'));
                }""",
                timeout=25000,
            )
            banner2 = customer.locator('[data-testid="handoff-status-banner"]').inner_text()
            ok = "已接入" in banner2 or "旁听" in banner2
            b64 = _shot(customer, "03_customer_connected")
            results.append(_case("BROWSER", "customer", "B-customer-connected-banner", ok, banner2[:120], int((time.time() - t0) * 1000), b64))
        except Exception as e:
            results.append(_case("BROWSER", "customer", "B-customer-connected-banner", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── 客服：回复 ──
        t0 = time.time()
        reply_text = "浏览器 E2E：已为您加急 #优先发货特权#"
        try:
            desk.locator('[data-testid="desk-reply-input"]').wait_for(state="visible", timeout=10000)
            desk.locator('[data-testid="desk-reply-input"]').fill(reply_text)
            desk.locator('[data-testid="desk-reply-send"]').click()
            desk.wait_for_timeout(1500)
            b64 = _shot(desk, "04_desk_reply")
            results.append(_case("BROWSER", "agent", "B-desk-send-reply", True, reply_text[:80], int((time.time() - t0) * 1000), b64))
        except Exception as e:
            results.append(_case("BROWSER", "agent", "B-desk-send-reply", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── 客户：看到人工回复 ──
        t0 = time.time()
        try:
            customer.wait_for_function(
                """() => document.body.innerText.includes('优先发货')""",
                timeout=20000,
            )
            b64 = _shot(customer, "05_customer_human_msg")
            results.append(_case("BROWSER", "customer", "B-customer-see-desk-reply", True, "含优先发货文案", int((time.time() - t0) * 1000), b64))
        except Exception as e:
            results.append(_case("BROWSER", "customer", "B-customer-see-desk-reply", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── 管理员：保存 SLA ──
        t0 = time.time()
        try:
            admin.goto(f"{base}/admin", wait_until="domcontentloaded", timeout=30000)
            admin.wait_for_selector("#root", timeout=10000)
            admin.get_by_role("button", name="路由策略").click()
            admin.wait_for_selector('[data-testid="admin-save-config"]', timeout=15000)
            admin.locator('input[type="number"]').first.fill("178")
            admin.locator('[data-testid="admin-save-config"]').click()
            admin.wait_for_function(
                """() => document.body.innerText.includes('已保存')""",
                timeout=10000,
            )
            b64 = _shot(admin, "06_admin_saved")
            results.append(_case("BROWSER", "admin", "B-admin-save-routing", True, "SLA=178", int((time.time() - t0) * 1000), b64))
            # 恢复默认 SLA
            token = admin.evaluate("() => sessionStorage.getItem('mitako_auth_token_v1') || ''")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            cfg = httpx.get(f"{base}/api/v1/admin/handoff/routing", headers=headers, timeout=10).json().get("config", {})
            cfg.setdefault("sla", {})["first_response_seconds"] = 180
            httpx.put(f"{base}/api/v1/admin/handoff/routing", headers=headers, json=cfg, timeout=10)
        except Exception as e:
            results.append(_case("BROWSER", "admin", "B-admin-save-routing", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── Admin 运维大屏 ──
        t0 = time.time()
        try:
            admin.get_by_role("button", name="7×24 运维").click()
            admin.wait_for_selector("text=系统状态", timeout=10000)
            b64 = _shot(admin, "09_ops_monitor")
            results.append(_case("BROWSER", "admin", "B-admin-ops-monitor", True, "ops tab", int((time.time() - t0) * 1000), b64))
        except Exception as e:
            results.append(_case("BROWSER", "admin", "B-admin-ops-monitor", False, str(e)[:160], int((time.time() - t0) * 1000)))

        # ── reduced-motion 可访问性 smoke ──
        t0 = time.time()
        try:
            rm_ctx = browser.new_context(
                viewport={"width": 390, "height": 844},
                locale="zh-CN",
                reduced_motion="reduce",
            )
            rm_page = rm_ctx.new_page()
            rm_page.goto(f"{base}/", wait_until="domcontentloaded", timeout=30000)
            rm_page.wait_for_selector("#root", timeout=10000)
            motion = rm_page.evaluate("() => window.matchMedia('(prefers-reduced-motion: reduce)').matches")
            b64 = _shot(rm_page, "07_reduced_motion")
            rm_ctx.close()
            results.append(_case("BROWSER", "customer", "B-reduced-motion", motion is True, "prefers-reduced-motion", int((time.time() - t0) * 1000), b64))
        except Exception as e:
            results.append(_case("BROWSER", "customer", "B-reduced-motion", False, str(e)[:160], int((time.time() - t0) * 1000)))

        browser.close()

    return results, True
