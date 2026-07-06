# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = ROOT / "tests" / "reports" / "screenshots"


def _fetch_routing(page, base: str) -> dict:
    return page.evaluate(
        """async (baseUrl) => {
            const token = sessionStorage.getItem('mitako_auth_token_v1') || '';
            const r = await fetch(`${baseUrl}/api/v1/admin/handoff/routing`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {}
            });
            return await r.json();
        }""",
        base,
    )


def main() -> int:
    base = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    username = os.getenv("E2E_ADMIN_USERNAME", "admin")
    password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page.goto(f"{base}/admin", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#root", timeout=10000)
        try:
            page.get_by_role("button", name="坐席管理").wait_for(timeout=3000)
        except PlaywrightTimeoutError:
            page.locator('input[type="password"]').first.wait_for(timeout=10000)
            page.locator('input[type="text"]').first.fill(username)
            page.locator('input[type="password"]').first.fill(password)
            with page.expect_response(lambda r: r.url.endswith("/api/v1/auth/login") and r.status == 200):
                page.locator('button[type="submit"]').click()
            try:
                page.get_by_role("button", name="坐席管理").wait_for(timeout=10000)
            except PlaywrightTimeoutError as exc:
                raise AssertionError(f"admin login did not reach shell: url={page.url} text={page.locator('body').inner_text()[:500]}") from exc

        expected = {
            "坐席管理": "坐席管理",
            "路由策略": "默认接单层级",
            "队列监控": "队列监控",
            "服务记录": "服务记录",
            "运营报表": "导出报表",
            "7×24 运维": "系统状态",
        }
        for label, marker in expected.items():
            page.get_by_role("button", name=label).click()
            page.wait_for_timeout(300)
            assert marker in page.locator("main").first.inner_text(), label

        page.get_by_role("button", name="路由策略").click()
        page.wait_for_selector('[data-testid="admin-save-config"]', timeout=10000)
        original = _fetch_routing(page, base)["config"]
        first_response = int((original.get("sla") or {}).get("first_response_seconds") or 180)
        probe_value = first_response + 1 if first_response != 181 else 182
        try:
            page.locator('input[type="number"]').first.fill(str(probe_value))
            with page.expect_response(lambda r: r.url.endswith("/api/v1/admin/handoff/routing") and r.request.method == "PUT" and r.status == 200):
                page.locator('[data-testid="admin-save-config"]').click()
            deadline = time.time() + 3
            while time.time() < deadline:
                saved = _fetch_routing(page, base)["config"]
                if int((saved.get("sla") or {}).get("first_response_seconds") or 0) == probe_value:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("routing save did not persist")
        finally:
            page.evaluate(
                """async ({ baseUrl, config }) => {
                    const token = sessionStorage.getItem('mitako_auth_token_v1') || '';
                    await fetch(`${baseUrl}/api/v1/admin/handoff/routing`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                        body: JSON.stringify(config)
                    });
                }""",
                {"baseUrl": base, "config": original},
            )

        page.screenshot(path=str(SCREENSHOT_DIR / "admin_browser_smoke.png"), full_page=False)
        browser.close()
    print("admin browser smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
