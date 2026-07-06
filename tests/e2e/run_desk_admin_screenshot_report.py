# -*- coding: utf-8 -*-
"""Playwright 演示级截图验收：/desk 与 /admin。

该脚本不是探活冒烟：它会真实登录、加载演示数据、进入客服工作台、
接手/转派会话、切换后台多页签，并生成带截图的 HTML 报告。
"""
from __future__ import annotations

import base64
import html
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - 环境缺依赖时给出清晰错误
    raise SystemExit("缺少 Playwright：请先执行 pip install playwright && playwright install chromium") from exc


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "tests" / "reports"
SCREENSHOT_ROOT = REPORT_DIR / "screenshots"
TOKEN_KEY = "mitako_auth_token_v1"
USER_KEY = "mitako_auth_user_v1"


@dataclass
class ScreenshotCase:
    area: str
    name: str
    ok: bool
    detail: str
    url: str = ""
    image_path: Path | None = None
    ms: int = 0
    assertions: List[str] = field(default_factory=list)


def _base_url() -> str:
    return os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def _login(client: httpx.Client, base: str, username: str, passwords: List[str]) -> Dict[str, Any]:
    last = ""
    for password in passwords:
        r = client.post(
            f"{base}/api/v1/auth/login",
            json={"username": username, "password": password, "tenant_id": "mitako"},
        )
        last = r.text
        if r.status_code == 200:
            data = r.json()
            if data.get("ok") and data.get("token"):
                return data
    raise RuntimeError(f"账号 {username} 登录失败：{last[:200]}")


def _new_context(browser, session: Dict[str, Any], viewport: Dict[str, int]):
    ctx = browser.new_context(viewport=viewport, locale="zh-CN")
    payload = json.dumps({"token": session["token"], "user": session["user"]}, ensure_ascii=False)
    ctx.add_init_script(
        f"""(() => {{
          const {{ token, user }} = {payload};
          window.sessionStorage.setItem('mitako_auth_token_v1', token);
          window.sessionStorage.setItem('mitako_auth_user_v1', JSON.stringify(user));
        }})()"""
    )
    return ctx


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value)[:96]


def _screenshot(page, shot_dir: Path, name: str) -> Path:
    shot_dir.mkdir(parents=True, exist_ok=True)
    path = shot_dir / f"{_safe_name(name)}.png"
    page.screenshot(path=str(path), full_page=False)
    return path


def _body_text(page) -> str:
    return page.locator("body").inner_text(timeout=8000)


def _contains_all(page, markers: List[str]) -> tuple[bool, str]:
    text = _body_text(page)
    missing = [m for m in markers if m not in text]
    if missing:
        return False, "缺少：" + "、".join(missing)
    return True, "命中：" + "、".join(markers)


def _contains_none(page, markers: List[str]) -> tuple[bool, str]:
    text = _body_text(page)
    bad = [m for m in markers if m in text]
    if bad:
        return False, "不应出现：" + "、".join(bad)
    return True, "未出现：" + "、".join(markers)


def _record_case(
    cases: List[ScreenshotCase],
    *,
    page,
    shot_dir: Path,
    area: str,
    name: str,
    markers: List[str],
    started: float,
    detail_prefix: str = "",
) -> None:
    ok, detail = _contains_all(page, markers)
    path = _screenshot(page, shot_dir, name)
    cases.append(
        ScreenshotCase(
            area=area,
            name=name,
            ok=ok,
            detail=(detail_prefix + detail)[:260],
            url=page.url,
            image_path=path,
            ms=int((time.time() - started) * 1000),
            assertions=markers,
        )
    )


def _record_negative_case(
    cases: List[ScreenshotCase],
    *,
    page,
    shot_dir: Path,
    area: str,
    name: str,
    hidden_markers: List[str],
    visible_markers: List[str],
    started: float,
) -> None:
    visible_ok, visible_detail = _contains_all(page, visible_markers)
    hidden_ok, hidden_detail = _contains_none(page, hidden_markers)
    path = _screenshot(page, shot_dir, name)
    cases.append(
        ScreenshotCase(
            area=area,
            name=name,
            ok=visible_ok and hidden_ok,
            detail=f"{visible_detail}；{hidden_detail}"[:260],
            url=page.url,
            image_path=path,
            ms=int((time.time() - started) * 1000),
            assertions=[*visible_markers, *[f"隐藏：{m}" for m in hidden_markers]],
        )
    )


def _setup_demo(client: httpx.Client, base: str, admin_token: str) -> None:
    h = _headers(admin_token)
    client.post(f"{base}/api/v1/admin/demo/clear", headers=h)
    loaded = client.post(f"{base}/api/v1/admin/demo/load", headers=h).json()
    if not loaded.get("ok") or loaded.get("session_count", 0) < 3:
        raise RuntimeError(f"演示数据加载失败：{loaded}")


def _seed_extra_handoff(client: httpx.Client, base: str, report_id: str) -> str:
    sid = "session_usr_e2e"
    user_id = "usr_e2e"
    customer_auth = client.post(
        f"{base}/api/v1/auth/customer-session",
        json={"user_id": user_id, "session_id": sid, "tenant_id": "mitako"},
    )
    if customer_auth.status_code != 200 or not customer_auth.json().get("ok"):
        raise RuntimeError(f"客户会话 token 获取失败：{customer_auth.text[:200]}")
    token = customer_auth.json()["token"]
    client.post(f"{base}/api/v1/handoff/reset", headers=_headers(token), params={"session_id": sid})
    body = {
        "user_id": user_id,
        "session_id": sid,
        "history": [
            {"role": "user", "content": "这个订单拖太久了，我已经很生气，要找 12315 投诉。"},
            {"role": "assistant", "content": "我先为您核对订单和物流节点，并转人工继续跟进。"},
        ],
        "reason": "用户主动要求人工并提到 12315",
        "last_user_message": "再不给解释我就去 12315 投诉。",
        "intent": "投诉升级与物流进度咨询",
        "emotion_level": 5,
        "tenant_id": "mitako",
    }
    r = client.post(f"{base}/api/v1/handoff/request", headers=_headers(token), json=body)
    if r.status_code != 200 or not r.json().get("ok"):
        raise RuntimeError(f"12315 转人工种子失败：{r.text[:200]}")
    return sid


def _api_transfer_to_xiaotang(client: httpx.Client, base: str, desk_token: str, session_id: str) -> Dict[str, Any]:
    return client.post(
        f"{base}/api/v1/desk/session/{session_id}/transfer",
        headers=_headers(desk_token),
        json={"from_agent_id": "CS-0816", "to_agent_id": "CS-0922", "note": "截图验收：转交给晓棠复核售后材料"},
    ).json()


def _render_report(cases: List[ScreenshotCase], base: str, report_id: str, started_at: str) -> str:
    passed = sum(1 for item in cases if item.ok)
    total = len(cases)
    pct = int(100 * passed / total) if total else 0

    def img_data(path: Path | None) -> str:
        if not path or not path.exists():
            return ""
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def card(item: ScreenshotCase) -> str:
        status = "通过" if item.ok else "失败"
        status_class = "ok" if item.ok else "fail"
        markers = "".join(f"<li>{html.escape(m)}</li>" for m in item.assertions)
        img = img_data(item.image_path)
        image_html = f'<img src="{img}" alt="{html.escape(item.name)}"/>' if img else ""
        return f"""
        <article class="shot-card {status_class}">
          <div class="shot-meta">
            <span class="pill">{html.escape(item.area)}</span>
            <span class="status">{status}</span>
          </div>
          <h3>{html.escape(item.name)}</h3>
          <p>{html.escape(item.detail)}</p>
          <ul>{markers}</ul>
          <div class="shot">{image_html}</div>
          <footer><code>{html.escape(item.url)}</code><span>{item.ms} ms</span></footer>
        </article>
        """

    rows = "".join(
        f"<tr><td>{html.escape(item.area)}</td><td>{html.escape(item.name)}</td>"
        f"<td class=\"{'ok-text' if item.ok else 'fail-text'}\">{'通过' if item.ok else '失败'}</td>"
        f"<td>{html.escape(item.detail)}</td><td>{item.ms} ms</td></tr>"
        for item in cases
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MITAKO /desk + /admin Playwright 演示截图报告 · {html.escape(report_id)}</title>
<style>
:root {{
  --ink:#14213d; --muted:#667085; --lime:#d7ff4a; --mint:#6ee7b7; --pink:#ff7ab6;
  --violet:#7c5cff; --sky:#69d2ff; --panel:#ffffff; --line:#e7eadf;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family: Inter, "Noto Sans SC", "Microsoft YaHei", sans-serif;
  color:var(--ink);
  background:
    radial-gradient(900px 420px at 10% 0%, rgba(215,255,74,.35), transparent),
    radial-gradient(900px 420px at 90% 4%, rgba(255,122,182,.2), transparent),
    linear-gradient(180deg,#fbfff4 0%,#f7f5ff 54%,#ffffff 100%);
}}
.wrap {{ max-width:1280px; margin:0 auto; padding:30px 22px 70px; }}
.hero {{
  border:1px solid rgba(20,33,61,.08); border-radius:22px; padding:26px 28px;
  background:linear-gradient(135deg,rgba(255,255,255,.9),rgba(255,255,255,.7));
  box-shadow:0 22px 70px rgba(20,33,61,.1); overflow:hidden; position:relative;
}}
.hero:after {{
  content:""; position:absolute; inset:auto -80px -110px auto; width:360px; height:220px;
  background:linear-gradient(135deg,var(--lime),var(--pink),var(--violet)); filter:blur(12px); opacity:.35;
  transform:rotate(-12deg);
}}
.hero h1 {{ margin:0; font-size:28px; letter-spacing:0; }}
.hero p {{ margin:10px 0 0; color:var(--muted); line-height:1.7; }}
.score {{ margin-top:18px; display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
.score strong {{ font-size:44px; line-height:1; }}
.score span {{ border-radius:999px; background:var(--lime); padding:7px 12px; font-weight:800; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:18px; margin-top:22px; }}
.shot-card {{
  border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.9);
  box-shadow:0 16px 44px rgba(20,33,61,.08); padding:16px; overflow:hidden;
}}
.shot-card.fail {{ border-color:rgba(220,38,38,.35); background:#fff8f8; }}
.shot-meta {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
.pill {{ border-radius:999px; background:#eefce1; color:#365314; padding:5px 10px; font-size:12px; font-weight:900; }}
.status {{ border-radius:999px; padding:5px 10px; font-size:12px; font-weight:900; background:#eef2ff; color:#4338ca; }}
.fail .status {{ background:#fee2e2; color:#b91c1c; }}
h3 {{ margin:12px 0 7px; font-size:18px; }}
.shot-card p {{ margin:0; color:#4b5563; font-size:13px; line-height:1.7; min-height:40px; }}
ul {{ margin:10px 0 12px; padding-left:18px; color:#64748b; font-size:12px; line-height:1.6; }}
.shot {{ border-radius:12px; overflow:hidden; border:1px solid #e5e7eb; background:#f8fafc; }}
.shot img {{ width:100%; display:block; }}
footer {{ margin-top:10px; display:flex; justify-content:space-between; gap:12px; align-items:center; color:#64748b; font-size:12px; }}
code {{ font-family:"JetBrains Mono",Consolas,monospace; background:#f3f4f6; border-radius:6px; padding:2px 6px; word-break:break-all; }}
.panel {{ margin-top:22px; background:#fff; border:1px solid var(--line); border-radius:18px; padding:18px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:10px 12px; border-bottom:1px solid #eef2f7; text-align:left; vertical-align:top; }}
th {{ color:#64748b; font-size:12px; background:#f8fafc; }}
.ok-text {{ color:#059669; font-weight:900; }}
.fail-text {{ color:#dc2626; font-weight:900; }}
@media (max-width:720px) {{
  .wrap {{ padding:18px 12px 40px; }}
  .grid {{ grid-template-columns:1fr; }}
  .hero h1 {{ font-size:22px; }}
  .score strong {{ font-size:34px; }}
}}
</style>
</head>
<body>
<main class="wrap">
  <section class="hero">
    <h1>MITAKO Agent · /desk 与 /admin Playwright 演示级截图验收</h1>
    <p>报告编号：<code>{html.escape(report_id)}</code><br/>执行时间：{html.escape(started_at)} · 服务地址：<code>{html.escape(base)}</code><br/>覆盖真实登录、演示数据加载、客服接手/转派状态、后台核心页签与角色入口差异。</p>
    <div class="score"><strong>{passed}/{total}</strong><span>{pct}% 通过</span></div>
  </section>
  <section class="grid">
    {''.join(card(item) for item in cases)}
  </section>
  <section class="panel">
    <h2>验收明细</h2>
    <table>
      <thead><tr><th>区域</th><th>截图/用例</th><th>结果</th><th>断言摘要</th><th>耗时</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</main>
</body>
</html>"""


def _strip_trailing_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def run() -> tuple[int, Path]:
    base = _base_url()
    report_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    shot_dir = SCREENSHOT_ROOT / f"desk_admin_{report_id}"
    cases: List[ScreenshotCase] = []

    with httpx.Client(timeout=30.0) as client:
        admin = _login(client, base, "admin", ["admin123"])
        desk = _login(client, base, "desk0816", ["desk123"])
        supervisor = _login(client, base, "supervisor", ["super123"])
        bpo = _login(client, base, "bpo_mgr", ["bpo123", "bpo@123"])

        _setup_demo(client, base, admin["token"])
        extra_sid = _seed_extra_handoff(client, base, report_id)

        supervisor_demo = client.post(
            f"{base}/api/v1/admin/demo/load",
            headers=_headers(supervisor["token"]),
        )
        bpo_demo = client.post(
            f"{base}/api/v1/admin/demo/load",
            headers=_headers(bpo["token"]),
        )
        if supervisor_demo.status_code != 403 or bpo_demo.status_code != 403:
            raise RuntimeError(f"演示数据权限断言失败：supervisor={supervisor_demo.status_code}, bpo={bpo_demo.status_code}")

        shipping_sid = "demo_poc_mitako_shipping_delay"
        damage_sid = "demo_poc_mitako_damage_claim"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            desk_ctx = _new_context(browser, desk, {"width": 1440, "height": 900})
            desk_page = desk_ctx.new_page()
            started = time.time()
            desk_page.goto(f"{base}/desk", wait_until="domcontentloaded", timeout=30000)
            desk_page.wait_for_selector("#root", timeout=10000)
            desk_page.get_by_role("button", name="刷新").click()
            desk_page.get_by_test_id(f"desk-session-{shipping_sid}").wait_for(state="visible", timeout=15000)
            desk_page.get_by_test_id(f"desk-session-{shipping_sid}").click()
            desk_page.wait_for_selector('[data-testid="desk-accept-handoff"]', timeout=10000)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 物流慢会话与服务记录",
                markers=["用户催促发货", "服务记录", "请完整阅读右侧服务记录", "情绪 L4"],
                started=started,
            )

            started = time.time()
            desk_page.locator('[data-testid="desk-accept-handoff"]').click()
            desk_page.locator('[data-testid="desk-accept-confirm"]').wait_for(state="visible", timeout=10000)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 接手确认浮层",
                markers=["确认接手当前会话", "确认接手", "先不接手"],
                started=started,
            )
            desk_page.locator('[data-testid="desk-accept-confirm"]').click()
            desk_page.wait_for_timeout(900)

            started = time.time()
            desk_page.locator('[data-testid="desk-reply-input"]').wait_for(state="visible", timeout=10000)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 已接手可回复状态",
                markers=["已接手该会话", "确认转交", "结案归档", "快捷表情"],
                started=started,
            )

            transfer_result = _api_transfer_to_xiaotang(client, base, desk["token"], shipping_sid)
            if not transfer_result.get("ok"):
                raise RuntimeError(f"转派给晓棠失败：{transfer_result}")

            started = time.time()
            desk_page.reload(wait_until="domcontentloaded", timeout=30000)
            desk_page.wait_for_selector("#root", timeout=10000)
            desk_page.get_by_role("button", name="刷新").click()
            desk_page.get_by_test_id(f"desk-session-{shipping_sid}").click()
            desk_page.wait_for_timeout(700)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 转派后身份不匹配禁用提示",
                markers=["当前分配给晓棠", "当前身份不可接手", "待同事确认接管"],
                started=started,
            )

            started = time.time()
            desk_page.get_by_test_id(f"desk-session-{damage_sid}").click()
            desk_page.wait_for_timeout(700)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 商品有伤需高级客服",
                markers=["商品有伤", "需高级客服", "该会话需要高级客服或专项客服接手"],
                started=started,
            )

            started = time.time()
            desk_page.get_by_test_id(f"desk-session-{extra_sid}").click()
            desk_page.wait_for_timeout(700)
            _record_case(
                cases,
                page=desk_page,
                shot_dir=shot_dir,
                area="/desk",
                name="客服工作台 · 12315 高情绪会话同步",
                markers=["12315", "情绪 L5", "投诉升级与物流进度咨询"],
                started=started,
            )

            mobile_ctx = _new_context(browser, desk, {"width": 390, "height": 844})
            mobile_page = mobile_ctx.new_page()
            started = time.time()
            mobile_page.goto(f"{base}/desk", wait_until="domcontentloaded", timeout=30000)
            mobile_page.wait_for_selector("#root", timeout=10000)
            mobile_page.get_by_role("button", name="刷新").click()
            mobile_page.wait_for_timeout(800)
            _record_case(
                cases,
                page=mobile_page,
                shot_dir=shot_dir,
                area="/desk mobile",
                name="移动端客服工作台 · 队列优先操作",
                markers=["队列", "会话", "档案", "待处理会话"],
                started=started,
            )
            mobile_ctx.close()
            desk_ctx.close()

            admin_ctx = _new_context(browser, admin, {"width": 1440, "height": 900})
            admin_page = admin_ctx.new_page()
            started = time.time()
            admin_page.goto(f"{base}/admin", wait_until="domcontentloaded", timeout=30000)
            admin_page.wait_for_selector("#root", timeout=10000)
            _record_case(
                cases,
                page=admin_page,
                shot_dir=shot_dir,
                area="/admin",
                name="运营后台 · 监管大盘",
                markers=["监管大盘", "加载演示数据", "演示数据", "客服运营管理中心"],
                started=started,
            )

            for label, name, markers in [
                ("队列监控", "运营后台 · 队列监控", ["队列监控", "强制转交", "等待"]),
                ("服务记录", "运营后台 · 服务记录", ["服务记录", "选择左侧事件查看回放", "业务记录"]),
                ("服务质检", "运营后台 · 服务质检", ["服务质检", "复盘"]),
                ("补偿审批", "运营后台 · 补偿审批", ["补偿审批", "审批"]),
                ("运营报表", "运营后台 · 运营报表", ["运营报表", "导出报表"]),
                ("7×24 运维", "运营后台 · 7×24 运维健康监测", ["7×24 运维", "系统状态"]),
            ]:
                started = time.time()
                admin_page.get_by_role("button", name=label).click()
                admin_page.wait_for_timeout(700)
                _record_case(
                    cases,
                    page=admin_page,
                    shot_dir=shot_dir,
                    area="/admin",
                    name=name,
                    markers=markers,
                    started=started,
                )
            admin_ctx.close()

            supervisor_ctx = _new_context(browser, supervisor, {"width": 1440, "height": 900})
            supervisor_page = supervisor_ctx.new_page()
            started = time.time()
            supervisor_page.goto(f"{base}/admin", wait_until="domcontentloaded", timeout=30000)
            supervisor_page.wait_for_selector("#root", timeout=10000)
            supervisor_page.wait_for_timeout(700)
            _record_negative_case(
                cases,
                page=supervisor_page,
                shot_dir=shot_dir,
                area="/admin role",
                name="主管后台 · 可审批但不可管理配置/演示数据",
                visible_markers=["监管大盘", "补偿审批", "运营报表"],
                hidden_markers=["加载演示数据", "清空演示数据", "坐席管理", "路由策略", "7×24 运维"],
                started=started,
            )
            supervisor_ctx.close()

            bpo_ctx = _new_context(browser, bpo, {"width": 1440, "height": 900})
            bpo_page = bpo_ctx.new_page()
            started = time.time()
            bpo_page.goto(f"{base}/admin", wait_until="domcontentloaded", timeout=30000)
            bpo_page.wait_for_selector("#root", timeout=10000)
            bpo_page.wait_for_timeout(700)
            _record_negative_case(
                cases,
                page=bpo_page,
                shot_dir=shot_dir,
                area="/admin role",
                name="BPO 经理后台 · 只看运营与队列，不看审批和配置",
                visible_markers=["监管大盘", "队列监控", "服务记录", "运营报表"],
                hidden_markers=["补偿审批", "加载演示数据", "清空演示数据", "坐席管理", "路由策略", "7×24 运维"],
                started=started,
            )
            bpo_ctx.close()
            browser.close()

    html_text = _render_report(cases, base, report_id, started_at)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"desk_admin_playwright_screenshots_{report_id}.html"
    report_path.write_text(_strip_trailing_ws(html_text), encoding="utf-8")
    summary_path = REPORT_DIR / f"desk_admin_playwright_screenshots_{report_id}.md"
    passed = sum(1 for item in cases if item.ok)
    lines = [
        f"# MITAKO /desk + /admin Playwright 演示级截图验收报告 {report_id}",
        "",
        f"- 服务地址：{base}",
        f"- 执行时间：{started_at}",
        f"- 结果：{passed}/{len(cases)} 通过",
        f"- HTML：{report_path}",
        "",
        "| 区域 | 用例 | 结果 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in cases:
        lines.append(f"| {item.area} | {item.name} | {'通过' if item.ok else '失败'} | {item.detail.replace('|', '/')} |")
    summary_path.write_text(_strip_trailing_ws("\n".join(lines)), encoding="utf-8")

    print(f"截图报告已生成：{report_path}")
    print(f"Markdown 摘要：{summary_path}")
    return (0 if passed == len(cases) else 1), report_path


def main() -> int:
    code, _ = run()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
