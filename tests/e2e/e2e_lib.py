# -*- coding: utf-8 -*-
"""E2E 共享工具：结果模型、端口发现、专业 HTML 报告"""
from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "tests" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PORT_CANDIDATES = [8000, 8001, 8002, 8003]

LAYER_META = {
    "CODE": ("代码层", "构建产物 · 模块导入 · SQLite · 配置"),
    "COMM": ("通信层", "REST · WebSocket · 增量轮询 · 静态页"),
    "CHAIN": ("链路层", "跨角色编排 · 升级 · 旁听 · 富文本"),
    "ROLE": ("角色层", "API 模拟客户 / 客服 / 管理员"),
    "BROWSER": ("浏览器层", "Playwright 真实点击 · 三端 UI"),
}


@dataclass
class CaseResult:
    layer: str
    role: str
    name: str
    ok: bool
    detail: str
    ms: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


async def admin_auth_headers(client: httpx.AsyncClient, base: str) -> Dict[str, str]:
    """管理员 JWT — E2E 默认 admin/admin123"""
    lr = await client.post(
        f"{base}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123", "tenant_id": "mitako"},
    )
    token = lr.json().get("token") if lr.status_code == 200 else ""
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _probe_handoff_server(client: httpx.AsyncClient, url: str) -> bool:
    """确认端口上的服务可正常处理转人工（排除旧进程 / 半崩溃实例）"""
    try:
        r = await client.get(f"{url}/api/v1/auth/status", timeout=2.0)
        if r.status_code != 200 or not r.json().get("ok"):
            return False
        auth_status = r.json()
        probe_sid = f"e2e_probe_{int(time.time())}"
        pr = await client.post(
            f"{url}/api/v1/handoff/request",
            json={
                "user_id": "probe",
                "session_id": probe_sid,
                "history": [],
                "reason": "e2e probe",
                "last_user_message": "",
                "intent": "",
                "emotion_level": 2,
            },
            timeout=5.0,
        )
        if pr.status_code != 200 or not pr.json().get("ok"):
            return False
        token = pr.json().get("handoff_token") or ""
        status_headers = {"Authorization": f"Bearer {token}"} if token else {}
        sr = await client.get(f"{url}/api/v1/handoff/status/{probe_sid}", headers=status_headers)
        if sr.status_code != 200 or sr.json().get("status") in ("none", None):
            return False
        auth_on = bool(auth_status.get("protected_api_auth_required") or auth_status.get("auth_required"))
        reset_headers = await admin_auth_headers(client, url) if auth_on else {}
        await client.post(
            f"{url}/api/v1/handoff/reset",
            params={"session_id": probe_sid},
            headers=reset_headers,
        )
        return True
    except Exception:
        return False


async def discover_base(client: httpx.AsyncClient, explicit: Optional[str] = None) -> str:
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit.rstrip("/"))
    env = os.getenv("E2E_BASE_URL", "").rstrip("/")
    if env and env not in candidates:
        candidates.append(env)
    candidates.extend(f"http://127.0.0.1:{p}" for p in PORT_CANDIDATES)

    seen: set = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if await _probe_handoff_server(client, url):
            return url
    return candidates[0] if candidates else "http://127.0.0.1:8000"


def hist_l5() -> List[Dict[str, str]]:
    return [
        {"role": "user", "content": "我要起诉你们，再不退现金我就去黑猫投诉曝光"},
        {"role": "assistant", "content": "非常理解您的心情，我已为您整理订单进度…"},
        {"role": "user", "content": "你们就是骗子，必须给 #优先发货特权# 和补偿"},
    ]


async def reset_session(client: httpx.AsyncClient, base: str, sid: str) -> None:
    await client.post(f"{base}/api/v1/handoff/reset", params={"session_id": sid})


async def request_handoff(
    client: httpx.AsyncClient,
    base: str,
    sid: str,
    *,
    emotion: int = 4,
    user_id: str = "usr_e2e",
    intent: str = "投诉",
) -> Dict[str, Any]:
    r = await client.post(
        f"{base}/api/v1/handoff/request",
        json={
            "user_id": user_id,
            "session_id": sid,
            "history": hist_l5(),
            "reason": "E2E 全链路测试",
            "last_user_message": "必须投诉",
            "intent": intent,
            "emotion_level": emotion,
        },
    )
    return r.json()


def _layer_stats(results: List[CaseResult], layer: str) -> tuple[int, int]:
    subset = [r for r in results if r.layer == layer]
    passed = sum(1 for r in subset if r.ok)
    return passed, len(subset)


def render_report(results: List[CaseResult], base: str, started: str, report_id: str = "") -> str:
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    pct = int(100 * passed / total) if total else 0
    failed = [r for r in results if not r.ok]
    report_id = report_id or datetime.now().strftime("%Y%m%d_%H%M%S")

    role_labels = {"system": "系统", "customer": "客户", "agent": "人工客服", "admin": "管理员"}

    def row_html(r: CaseResult) -> str:
        badge = "PASS" if r.ok else "FAIL"
        color = "#059669" if r.ok else "#dc2626"
        bg = "rgba(5,150,105,.08)" if r.ok else "rgba(220,38,38,.06)"
        layer_title = LAYER_META.get(r.layer, (r.layer, ""))[0]
        shot = ""
        b64 = (r.extra or {}).get("screenshot_b64")
        if b64:
            shot = f'<details class="shot"><summary>截图</summary><img alt="screenshot" src="data:image/png;base64,{b64}"/></details>'
        return f"""<tr style="background:{bg}">
          <td><span class="badge" style="background:{color}">{badge}</span></td>
          <td><code>{html.escape(r.layer)}</code><br/><span class="muted">{html.escape(layer_title)}</span></td>
          <td>{html.escape(role_labels.get(r.role, r.role))}</td>
          <td><strong>{html.escape(r.name)}</strong></td>
          <td class="detail">{html.escape(r.detail)}{shot}</td>
          <td class="num">{r.ms}<span class="muted"> ms</span></td>
        </tr>"""

    layer_cards = ""
    for layer, (title, desc) in LAYER_META.items():
        lp, lt = _layer_stats(results, layer)
        if lt == 0:
            continue
        bar = int(100 * lp / lt) if lt else 0
        layer_cards += f"""
        <div class="layer-card">
          <div class="layer-head"><span>{title}</span><span class="layer-score">{lp}/{lt}</span></div>
          <p class="layer-desc">{desc}</p>
          <div class="bar-track"><div class="bar-fill" style="width:{bar}%"></div></div>
        </div>"""

    screenshots_section = ""
    browser_shots = [r for r in results if (r.extra or {}).get("screenshot_b64")]
    if browser_shots:
        gallery = ""
        for r in browser_shots:
            b64 = r.extra.get("screenshot_b64", "")
            gallery += f"""
            <figure class="gallery-item">
              <img src="data:image/png;base64,{b64}" alt="{html.escape(r.name)}"/>
              <figcaption><span class="{'ok' if r.ok else 'fail'}">{'PASS' if r.ok else 'FAIL'}</span> {html.escape(r.name)}</figcaption>
            </figure>"""
        screenshots_section = f"""
        <section class="panel">
          <h2>浏览器验收截图</h2>
          <p class="muted">Playwright Chromium · 1440×900 · 真实 DOM 交互</p>
          <div class="gallery">{gallery}</div>
        </section>"""

    fail_section = ""
    if failed:
        fail_section = f"""
        <section class="panel fail-panel">
          <h2>失败项 ({len(failed)})</h2>
          <ul>{''.join(f'<li><strong>{html.escape(r.name)}</strong> — {html.escape((r.detail or "")[:200])}</li>' for r in failed)}</ul>
        </section>"""

    matrix_rows = ""
    for role in ("customer", "agent", "admin"):
        subset = [r for r in results if r.role == role]
        if not subset:
            continue
        rp = sum(1 for r in subset if r.ok)
        matrix_rows += f"<tr><td>{role_labels[role]}</td><td>{rp}/{len(subset)}</td><td>{int(100*rp/len(subset))}%</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>MITAKO 全链路 E2E 验收报告 · {report_id}</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet"/>
<style>
:root {{
  --purple:#7b61ff; --lime:#c8ff1a; --ink:#0f172a; --muted:#64748b;
  --pass:#059669; --fail:#dc2626; --panel:#ffffff; --bg:#f4f2ff;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family:'Outfit','Noto Sans SC',sans-serif;
  background: radial-gradient(1200px 600px at 10% -10%, rgba(123,97,255,.18), transparent),
              radial-gradient(900px 500px at 90% 0%, rgba(200,255,26,.12), transparent),
              var(--bg); color:var(--ink);
}}
.wrap {{ max-width:1200px; margin:0 auto; padding:32px 20px 64px; }}
.hero {{
  background:linear-gradient(135deg,#1e1b4b,#312e81 55%,#4c1d95);
  color:#fff; border-radius:24px; padding:28px 32px; margin-bottom:24px;
  box-shadow:0 24px 60px rgba(49,46,129,.35);
}}
.hero h1 {{ margin:0 0 8px; font-size:1.75rem; font-weight:800; }}
.hero .meta {{ font-size:13px; opacity:.85; line-height:1.6; }}
.hero .big {{ font-size:3rem; font-weight:800; color:var(--lime); margin:16px 0 0; }}
.summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin-bottom:24px; }}
.layer-card {{ background:var(--panel); border-radius:16px; padding:16px 18px; border:1px solid rgba(123,97,255,.12); box-shadow:0 8px 24px rgba(15,23,42,.04); }}
.layer-head {{ display:flex; justify-content:space-between; font-weight:700; }}
.layer-score {{ color:var(--purple); font-family:'JetBrains Mono',monospace; }}
.layer-desc {{ font-size:12px; color:var(--muted); margin:8px 0 12px; }}
.bar-track {{ height:6px; background:#e2e8f0; border-radius:999px; overflow:hidden; }}
.bar-fill {{ height:100%; background:linear-gradient(90deg,var(--purple),#a78bfa); border-radius:999px; }}
.panel {{ background:var(--panel); border-radius:20px; padding:22px 24px; margin-bottom:20px; border:1px solid rgba(15,23,42,.06); box-shadow:0 10px 40px rgba(15,23,42,.05); }}
.panel h2 {{ margin:0 0 16px; font-size:1.1rem; }}
.muted {{ color:var(--muted); font-size:12px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #f1f5f9; vertical-align:top; }}
th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); background:#f8fafc; }}
.badge {{ color:#fff; padding:4px 10px; border-radius:999px; font-size:10px; font-weight:800; letter-spacing:.04em; }}
.detail {{ max-width:420px; word-break:break-word; font-family:'JetBrains Mono',monospace; font-size:12px; }}
.num {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}
.fail-panel {{ border-color:rgba(220,38,38,.2); background:#fef2f2; }}
.gallery {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }}
.gallery-item {{ margin:0; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; background:#fff; }}
.gallery-item img {{ width:100%; display:block; }}
.gallery-item figcaption {{ padding:10px 12px; font-size:12px; }}
.gallery-item .ok {{ color:var(--pass); font-weight:800; }}
.gallery-item .fail {{ color:var(--fail); font-weight:800; }}
.shot summary {{ cursor:pointer; color:var(--purple); font-size:11px; margin-top:6px; }}
.shot img {{ max-width:100%; margin-top:8px; border-radius:8px; border:1px solid #e2e8f0; }}
footer {{ text-align:center; font-size:12px; color:var(--muted); margin-top:32px; }}
code {{ font-family:'JetBrains Mono',monospace; font-size:11px; background:#f1f5f9; padding:2px 6px; border-radius:4px; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>MITAKO Agent · 全链路 E2E 验收报告</h1>
    <p class="meta">
      报告编号 <strong>{html.escape(report_id)}</strong><br/>
      执行时间 {html.escape(started)} · 服务地址 {html.escape(base)}<br/>
      覆盖：代码测试 · 通信测试 · 链路测试 · 三角色 API · Playwright 浏览器
    </p>
    <div class="big">{passed}/{total} PASS · {pct}%</div>
  </header>

  <div class="summary-grid">{layer_cards}</div>

  {fail_section}

  <section class="panel">
    <h2>三角色通过率</h2>
    <table><thead><tr><th>角色</th><th>通过</th><th>通过率</th></tr></thead><tbody>{matrix_rows}</tbody></table>
  </section>

  {screenshots_section}

  <section class="panel">
    <h2>完整用例明细</h2>
    <table>
      <thead><tr><th>结果</th><th>层级</th><th>角色</th><th>用例</th><th>详情</th><th>耗时</th></tr></thead>
      <tbody>{''.join(row_html(r) for r in results)}</tbody>
    </table>
  </section>

  <footer>
    MITAKO_Agent/tests/e2e/run_full_pipeline_e2e.py · 商业交付验收门禁<br/>
    复现：npm run build → python main.py → python tests/e2e/run_full_pipeline_e2e.py
  </footer>
</div>
</body>
</html>"""
