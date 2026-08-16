# -*- coding: utf-8 -*-
"""基于 0816 四场景密封盲测清单执行真实浏览器验收。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "tests" / "reports"
ACCEPTANCE_PATH = REPORT_DIR / "review_0816_four_scenario_blind_results_latest.json"
SCREENSHOT_DIR = REPORT_DIR / "screenshots" / "final_review_qa_20260816"
BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8015").rstrip("/")
CONTRACT_VERSION = "MITAKO-FOUR-SCENE@20260814.1"
REQUIRED_CASES_PER_SCENE = 2
SCENE_MARKERS = {
    "product_damage": ("商品有伤", "开箱视频九项核对", "主视频损伤存在性", "诉求支持度"),
    "wrong_item": ("发错货", "发错货应收与实收核对", "身份定义属性", "同包裹证据"),
    "missing_item": ("漏发货", "漏发货应发与实收核对", "用户证据路线", "最终事实依据"),
    "minor_refund": ("未成年人退款", "未成年人退款五类材料核对", "视觉字段一致性初审"),
}


def _login() -> dict[str, Any]:
    response = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_id": "mitako"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _load_acceptance_cases(path: Path = ACCEPTANCE_PATH) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 0816 四场景盲测清单：{path}") from exc
    if payload.get("contract_version") != CONTRACT_VERSION or payload.get("label_state") != "sealed":
        raise ValueError("四场景盲测清单不是当前密封业务契约")
    checks = payload.get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
        raise ValueError("0816 四场景盲测门禁尚未全部通过")
    for key in (
        "all_required_random_cases_present",
        "all_current_business_contracts_valid",
        "api_html_same_job",
    ):
        if checks.get(key) is not True:
            raise ValueError(f"0816 四场景盲测缺少当前门禁：{key}")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("0816 四场景盲测清单缺少 cases")

    counts = {scenario: 0 for scenario in SCENE_MARKERS}
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("0816 四场景盲测清单包含无效 case")
        scenario = str(case.get("scenario") or "")
        case_id = str(case.get("case_id") or "")
        job_id = str(case.get("job_id") or "")
        paths = (str(case.get("report_json") or ""), str(case.get("report_html") or ""))
        if (
            not job_id or not case_id or case_id in case_ids or scenario not in SCENE_MARKERS
            or any(key in case for key in ("expected_label", "manual_baseline", "manual_source"))
        ):
            raise ValueError(f"0816 四场景盲测 case 字段无效：{case_id or '-'}")
        if any("review_0816_blind_" not in item or any(old in item for old in ("0809", "0812", "0813", "0815")) for item in paths):
            raise ValueError(f"0816 四场景盲测 case 引用了过期报告：{case_id}")
        counts[scenario] += 1
        case_ids.add(case_id)
    if len(cases) != len(SCENE_MARKERS) * REQUIRED_CASES_PER_SCENE or any(
        count != REQUIRED_CASES_PER_SCENE for count in counts.values()
    ):
        raise ValueError("0816 四场景盲测必须恰好包含每场景 2 个密封 Case")
    return cases


def _safe_name(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "case")).strip("_") or "case"


def _requires_video_preview(case: dict[str, Any]) -> bool:
    return bool((case.get("evidence_preview") or {}).get("video"))


def _requires_media_preview(case: dict[str, Any]) -> bool:
    preview = case.get("evidence_preview") or {}
    return bool(preview.get("video") or preview.get("image"))


def _open_business_rules(page, viewport: tuple[int, int]) -> None:
    if viewport[0] < 768:
        page.get_by_role("combobox", name="选择管理功能").select_option("businessRules")
    else:
        page.get_by_role("button", name="业务规则").click()


def _capture_qa_screenshot(page, target: Path) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(
        path=str(target),
        full_page=False,
        mask=[page.locator(".preview-trigger img")],
        mask_color="#e5e7eb",
        animations="disabled",
    )


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
        _open_business_rules(page, viewport)
        page.wait_for_function(
            "markers => markers.every(marker => document.body.innerText.includes(marker))",
            arg=list(markers),
            timeout=10_000,
        )
    else:
        page.locator("details").evaluate_all("nodes => nodes.forEach(node => { node.open = true; })")
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
            preview_ok = page.locator("#mediaLightbox[open]").count() == 1
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
    _capture_qa_screenshot(page, screenshot)
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


def _report_check(browser, session: dict[str, Any], case: dict[str, Any], viewport: tuple[int, int]) -> dict[str, Any]:
    scenario = str(case["scenario"])
    scene_label, *detail_markers = SCENE_MARKERS[scenario]
    scene_contract = case.get("scene_contract") or {}
    conditional_markers = []
    if scenario == "product_damage" and scene_contract.get("severe_alert_eligible") is True:
        conditional_markers.append("严重商品质量问题")
    if scenario == "minor_refund" and (
        (scene_contract.get("payment_capability_risk") or {}).get("low_age") is True
    ):
        conditional_markers.append("低龄支付过程核验")
    size_label = "mobile" if viewport[0] < 600 else "desktop"
    return _check_page(
        browser,
        session,
        name=(
            f"{scenario}_{_safe_name(case.get('case_id'))}_{size_label}"
        ),
        url=f"{BASE_URL}/api/v1/review/jobs/{case['job_id']}/report",
        markers=(
            f"当前{scene_label}场景下的用户材料是否齐全",
            "证据结论",
            *detail_markers,
            *conditional_markers,
        ),
        forbidden=(
            "GEMINI_API_KEY",
            "baidubce.com",
            "system prompt",
            "System Prompt",
        ),
        viewport=viewport,
        require_preview=_requires_media_preview(case),
        require_video_preview=_requires_video_preview(case),
    )


def main() -> int:
    cases = _load_acceptance_cases()
    session = _login()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        checks = [_report_check(browser, session, case, (1440, 1000)) for case in cases]
        for scenario in SCENE_MARKERS:
            representative = next(
                case for case in cases
                if case["scenario"] == scenario
            )
            checks.append(_report_check(browser, session, representative, (390, 844)))
        checks.extend((
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
        ))
        browser.close()
    result = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "acceptance_manifest": str(ACCEPTANCE_PATH.relative_to(ROOT)),
        "browser": "Playwright Chromium（真实 API 与公开报告）",
        "checks": checks,
        "passed": sum(item["ok"] for item in checks),
        "total": len(checks),
    }
    (REPORT_DIR / "final_ui_qa_20260816.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
