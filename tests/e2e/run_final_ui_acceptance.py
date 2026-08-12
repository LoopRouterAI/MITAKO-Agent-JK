# -*- coding: utf-8 -*-
"""最终报告与业务规则后台的真实浏览器验收。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "tests" / "reports"
SCREENSHOT_DIR = REPORT_DIR / "screenshots" / "final_review_qa_20260809_v2"
BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015").rstrip("/")


def _login() -> dict[str, Any]:
    response = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_id": "mitako"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _job_id(report_name: str) -> str:
    data = json.loads((REPORT_DIR / report_name).read_text(encoding="utf-8"))
    return str(data["job"]["job_id"])


def _check_page(
    browser,
    session: dict[str, Any],
    *,
    name: str,
    url: str,
    markers: tuple[str, ...],
    forbidden: tuple[str, ...] = (),
    viewport: tuple[int, int] = (1440, 1000),
    business_rules: bool = False,
    require_preview: bool = False,
    require_video_preview: bool = False,
) -> dict[str, Any]:
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale="zh-CN",
        extra_http_headers={"Authorization": f"Bearer {session['token']}"},
    )
    if business_rules:
        payload = json.dumps({"token": session["token"], "user": session["user"]}, ensure_ascii=False)
        context.add_init_script(
            f"const s={payload};"
            "sessionStorage.setItem('mitako_auth_token_v1',s.token);"
            "sessionStorage.setItem('mitako_auth_user_v1',JSON.stringify(s.user));"
        )
    page = context.new_page()
    errors: list[str] = []
    media_statuses: list[int] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on(
        "response",
        lambda item: media_statuses.append(item.status)
        if item.request.resource_type == "media"
        else None,
    )
    response = page.goto(url, wait_until="networkidle", timeout=30_000)
    if business_rules:
        page.get_by_role("button", name="业务规则").click()
        page.get_by_text("安全与权限边界不可编辑").wait_for(timeout=10_000)
    body = page.locator("body").inner_text()
    marker_ok = all(marker in body for marker in markers)
    forbidden_ok = all(item not in body for item in forbidden)
    fits = bool(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))
    preview_ok = True
    video_preview_ok = True
    video_preview_detail: dict[str, Any] = {}
    preview_count = page.locator(".preview-trigger").count()
    if require_preview:
        preview_ok = preview_count > 0
        if preview_ok:
            page.locator(".preview-trigger").first.click()
            preview_ok = page.locator("#mediaLightbox:not([hidden])").count() == 1
            page.keyboard.press("Escape")
        video_trigger = page.locator('.preview-trigger[data-preview-kind="video"]').first
        if preview_ok and require_video_preview and video_trigger.count() == 1:
            expected_seconds = float(video_trigger.get_attribute("data-preview-seconds") or 0)
            video_trigger.click()
            video = page.locator("#lightboxBody video")
            video.wait_for(state="attached", timeout=10_000)
            page.wait_for_function(
                "document.querySelector('#lightboxBody video')?.readyState >= 1",
                timeout=15_000,
            )
            page.wait_for_function(
                "expected => Math.abs((document.querySelector('#lightboxBody video')?.currentTime || 0) - expected) <= 1.5",
                arg=expected_seconds,
                timeout=10_000,
            )
            video_state = video.evaluate(
                "node => ({currentTime: node.currentTime, controls: node.controls, "
                "videoWidth: node.videoWidth, fullscreen: typeof node.requestFullscreen === 'function' "
                "|| typeof node.webkitEnterFullscreen === 'function'})"
            )
            video_preview_ok = bool(
                video_state["controls"]
                and video_state["videoWidth"] > 0
                and video_state["fullscreen"]
                and abs(float(video_state["currentTime"]) - expected_seconds) <= 1.5
                and any(status in {200, 206} for status in media_statuses)
            )
            video_preview_detail = {
                **video_state,
                "expected_seconds": expected_seconds,
                "media_statuses": media_statuses,
            }
            page.keyboard.press("Escape")
        elif preview_ok and require_video_preview:
            video_preview_ok = False
            video_preview_detail = {"reason": "missing_video_preview_trigger"}
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(screenshot), full_page=False)
    status = response.status if response else 0
    result = {
        "name": name,
        "ok": status == 200 and marker_ok and forbidden_ok and fits and preview_ok and video_preview_ok and not errors,
        "detail": {
            "status": status,
            "markers": marker_ok,
            "forbidden": forbidden_ok,
            "fits": fits,
            "preview": preview_ok,
            "preview_count": preview_count,
            "video_preview": video_preview_ok,
            "video_preview_detail": video_preview_detail,
            "errors": errors,
        },
        "screenshot": str(screenshot.relative_to(ROOT)),
    }
    context.close()
    return result


def main() -> int:
    session = _login()
    jobs = {
        "598089": _job_id("review_0812_598089_gemini36_native.json"),
        "606669": _job_id("review_0809_pd_r04_final_latest.json"),
        "568689": _job_id("review_0809_missing_568689_final_latest.json"),
    }
    common_forbidden = ("GEMINI_API_KEY", "baidubce.com", "system prompt", "直接支持用户诉求")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        checks = [
            _check_page(
                browser,
                session,
                name="598089_desktop",
                url=f"{BASE_URL}/api/v1/review/jobs/{jobs['598089']}/report",
                markers=("现有证据支持用户诉求", "文件夹正面在灯光倾斜下显现表面划痕折痕", "初次开箱视频证据", "通过", "建议抽检"),
                forbidden=common_forbidden + ("Evidence is robust",),
                require_preview=True,
                require_video_preview=True,
            ),
            _check_page(
                browser,
                session,
                name="598089_mobile",
                url=f"{BASE_URL}/api/v1/review/jobs/{jobs['598089']}/report",
                markers=("现有证据支持用户诉求", "文件夹正面在灯光倾斜下显现表面划痕折痕", "通过", "建议抽检"),
                forbidden=common_forbidden,
                viewport=(390, 844),
                require_preview=True,
                require_video_preview=True,
            ),
            _check_page(
                browser,
                session,
                name="606669_desktop",
                url=f"{BASE_URL}/api/v1/review/jobs/{jobs['606669']}/report",
                markers=("开箱材料不合规", "面单可核验", "不符合", "建议抽检"),
                forbidden=common_forbidden + ("重复补件",),
                require_preview=True,
                require_video_preview=True,
            ),
            _check_page(
                browser,
                session,
                name="568689_desktop",
                url=f"{BASE_URL}/api/v1/review/jobs/{jobs['568689']}/report",
                markers=("确定未漏发", "无需人工复审", "仓库终核"),
                forbidden=common_forbidden + ("必须人工复审", "需人工确认", "疑似缺失：摆件"),
                require_preview=True,
            ),
            _check_page(
                browser,
                session,
                name="568689_mobile",
                url=f"{BASE_URL}/api/v1/review/jobs/{jobs['568689']}/report",
                markers=("确定未漏发", "无需人工复审"),
                forbidden=common_forbidden + ("必须人工复审", "需人工确认"),
                viewport=(390, 844),
            ),
            _check_page(
                browser,
                session,
                name="140592_desktop",
                url=(REPORT_DIR / "review_0809_minor_final_latest.html").resolve().as_uri(),
                markers=("无需人工复审", "只补充缺少或看不清的材料", "监护关系证明"),
                forbidden=("低龄支付过程核验", "待人工确认", "人工终审"),
            ),
            _check_page(
                browser,
                session,
                name="business_rules_desktop",
                url=f"{BASE_URL}/admin",
                markers=("安全与权限边界不可编辑", "本次修改原因（必填）", "版本留档", "发布新版本"),
                forbidden=("GEMINI_API_KEY", "baidubce.com"),
                business_rules=True,
            ),
            _check_page(
                browser,
                session,
                name="business_rules_mobile",
                url=f"{BASE_URL}/admin",
                markers=("安全与权限边界不可编辑", "本次修改原因（必填）", "版本留档"),
                forbidden=("GEMINI_API_KEY", "baidubce.com"),
                viewport=(390, 844),
                business_rules=True,
            ),
        ]
        browser.close()
    result = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "browser": "Playwright Chromium（真实 API 与公开报告）",
        "checks": checks,
        "passed": sum(item["ok"] for item in checks),
        "total": len(checks),
    }
    (REPORT_DIR / "final_ui_qa_20260809.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
