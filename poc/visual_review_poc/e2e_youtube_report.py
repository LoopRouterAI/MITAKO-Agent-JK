# -*- coding: utf-8 -*-
"""Gemini YouTube URL 视觉审核 E2E：生成 HTML 报告，有 Key 则真实调用。"""
from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = Path(__file__).resolve().parent / "reports"
MODEL = "gemini-3.5-flash"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


YOUTUBE_CASES = [
    {
        "case_id": "yt_damaged_package_unboxing",
        "scenario": "video_unboxing",
        "title": "损坏包裹开箱短视频",
        "url": "https://www.youtube.com/shorts/Axuc_UE8TlA",
        "source_note": "公开 YouTube 搜索结果：Unboxing The Most Damaged Package We've Ever Gotten Back",
        "review_focus": ["包裹是否损坏", "商品是否离镜", "是否能作为售后证据", "是否需要人工复核"],
    },
    {
        "case_id": "yt_blind_box_unboxing",
        "scenario": "video_unboxing",
        "title": "盲盒开箱长视频",
        "url": "https://www.youtube.com/watch?v=c6y0Rr7HlPI",
        "source_note": "公开 YouTube 搜索结果：ULTIMATE 600 BLIND BAG & BLIND BOX UNBOXING",
        "review_focus": ["是否持续展示开箱过程", "商品主体是否清晰", "是否适合做抽帧审核", "爆单时是否可自动初筛"],
    },
    {
        "case_id": "yt_damaged_product_claim",
        "scenario": "product_damage",
        "title": "损坏商品退换货教程视频",
        "url": "https://www.youtube.com/watch?v=fXcUPGAK45o",
        "source_note": "公开 YouTube 搜索结果：How To Make Unboxing Video For Claim Return Any Received Damaged Product",
        "review_focus": ["用户应提交哪些材料", "损伤证据是否清晰", "是否需要补拍", "不能自动定责"],
    },
]


OFFICIAL_REFERENCES = [
    {
        "title": "Gemini API Video Understanding",
        "url": "https://ai.google.dev/gemini-api/docs/video-understanding",
        "note": "官方文档：Interactions API 支持 YouTube URLs；公开视频可直接作为 video uri 输入，并可按时间戳提问。",
    },
    {
        "title": "Google Developers Blog: Gemini video understanding",
        "url": "https://developers.googleblog.com/en/gemini-2-5-video-understanding/",
        "note": "官方博客：YouTube 视频支持可通过 Gemini API 和 Google AI Studio 使用。",
    },
]


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_prompt(case: Dict[str, Any]) -> str:
    focus = "、".join(case["review_focus"])
    return f"""你是电商客服视觉审核质检助手。请分析前面提供的公开 YouTube 视频，按甲方售后审核视角只输出严格 JSON，不要输出 Markdown。
场景：{case['scenario']}
标题：{case['title']}
审核重点：{focus}
必须输出字段：
case_id, scenario, decision, confidence, issues, evidence, timestamps, next_step, human_required, boundary
decision 只能是 pass/suspect/fail/manual_review/request_more_material。
要求：
- evidence 必须说明视频中能看到或看不到什么。
- timestamps 尽量给出关键时间点；如果无法定位，返回空数组并说明原因。
- 只做辅助初筛；不得自动定责、拒赔、退款、补发。
- 公开 YouTube 视频不是甲方真实样本，boundary 必须写明仍需甲方脱敏样本盲测。"""


def fetch_youtube_metadata(url: str) -> Dict[str, Any]:
    encoded = httpx.QueryParams({"url": url, "format": "json"})
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(f"https://www.youtube.com/oembed?{encoded}")
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "error": str(exc),
        }

    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": response.text[:600],
        }

    data = response.json()
    return {
        "ok": True,
        "status_code": response.status_code,
        "title": data.get("title") or "",
        "author_name": data.get("author_name") or "",
        "provider_name": data.get("provider_name") or "",
        "thumbnail_url": data.get("thumbnail_url") or "",
    }


def call_gemini_youtube(case: Dict[str, Any], api_key: str, model: str) -> Dict[str, Any]:
    # 官方最佳实践：单视频请求中将视频放在文本提示词之前。
    payload = {
        "model": model,
        "input": [
            {"type": "video", "uri": case["url"]},
            {"type": "text", "text": build_prompt(case)},
        ],
    }
    started = time.time()
    with httpx.Client(timeout=180) as client:
        response = client.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
    elapsed = round(time.time() - started, 2)
    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "latency_seconds": elapsed,
            "endpoint": "POST https://generativelanguage.googleapis.com/v1beta/interactions",
            "request_shape": "input=[video uri, text prompt]",
            "error": response.text[:1600],
        }
    data = response.json()
    text = data.get("output_text") or _extract_interaction_text(data)
    try:
        parsed = json.loads(text)
        parse_status = "parsed_json"
    except Exception:
        parsed = {"raw_text": text}
        parse_status = "raw_text_fallback"
    return {
        "ok": True,
        "status_code": response.status_code,
        "latency_seconds": elapsed,
        "endpoint": "POST https://generativelanguage.googleapis.com/v1beta/interactions",
        "request_shape": "input=[video uri, text prompt]",
        "parse_status": parse_status,
        "result": parsed,
    }


def _extract_interaction_text(data: Dict[str, Any]) -> str:
    parts = []
    for step in data.get("steps") or []:
        for item in step.get("content") or []:
            if isinstance(item, dict) and item.get("text"):
                parts.append(item["text"])
    return "\n".join(parts)


def build_report() -> Dict[str, Any]:
    load_env()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    model = os.getenv("GEMINI_MODEL") or MODEL
    cases = []
    for case in YOUTUBE_CASES:
        row = dict(case)
        row["youtube_metadata"] = fetch_youtube_metadata(case["url"])
        if api_key:
            row["api_result"] = call_gemini_youtube(case, api_key, model)
        else:
            row["api_result"] = {
                "ok": False,
                "blocked": "missing_gemini_api_key",
                "message": "当前 .env 未配置 GEMINI_API_KEY/GOOGLE_API_KEY，未发起真实 Gemini YouTube 请求。",
                "endpoint": "POST https://generativelanguage.googleapis.com/v1beta/interactions",
                "request_shape": "input=[video uri, text prompt]",
                "parse_status": "not_called",
            }
        cases.append(row)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "goal": "用公开 YouTube 开箱/损坏商品视频验证 Gemini 视频审核 E2E 可行性",
        "model": model,
        "api_key_configured": bool(api_key),
        "run_status": "real_api_called" if api_key else "blocked_missing_gemini_api_key",
        "official_references": OFFICIAL_REFERENCES,
        "cases": cases,
        "conclusion": {
            "technical_path": "官方接口路径可行：Gemini 文档支持公开 YouTube URL 视频输入；本脚本已固定视频 URL、Prompt、报告输出和 HTML 展示。",
            "current_blocker": "" if api_key else "缺少 GEMINI_API_KEY/GOOGLE_API_KEY，当前未发起 Gemini 真实请求，也未验证当前 Key、模型和 URL 的真实返回。",
            "next_step": "配置 Gemini Key 后重跑；再替换为甲方脱敏开箱视频/损伤视频做盲测，并用人工标注结果统计召回率、误判率和复核节省时间。",
            "business_boundary": "报告只验证 POC 路径，不自动定责、不自动拒赔、不自动退款或补发；公开视频不代表甲方真实业务分布。",
        },
    }


def render_html(report: Dict[str, Any]) -> str:
    case_cards = "\n".join(_case_html(case) for case in report["cases"])
    refs = "\n".join(
        f'<li><a href="{html.escape(ref["url"])}" target="_blank" rel="noreferrer">{html.escape(ref["title"])}</a><span>{html.escape(ref["note"])}</span></li>'
        for ref in report["official_references"]
    )
    status_class = "ok" if report["api_key_configured"] else "warn"
    status_text = "已发起真实 Gemini 请求" if report["api_key_configured"] else "未配置 Gemini Key，未发起真实请求"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Gemini YouTube 视频审核 E2E 可行性报告</title>
  <style>
    :root {{ color-scheme: light; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }}
    body {{ margin: 0; background: linear-gradient(135deg, #f7fbff 0%, #f7f0ea 48%, #eefaf4 100%); color: #111827; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }}
    header {{ display: grid; gap: 14px; margin-bottom: 22px; }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 16px 0 8px; font-size: 15px; }}
    p {{ line-height: 1.7; }}
    .badge {{ display: inline-flex; width: fit-content; border-radius: 8px; padding: 6px 10px; font-size: 13px; font-weight: 700; }}
    .ok {{ background: #dcfce7; color: #166534; }}
    .warn {{ background: #fef3c7; color: #92400e; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{ background: rgba(255,255,255,0.86); border: 1px solid rgba(17,24,39,0.08); border-radius: 8px; padding: 18px; box-shadow: 0 12px 28px rgba(15, 23, 42, 0.08); backdrop-filter: blur(12px); }}
    iframe {{ width: 100%; aspect-ratio: 16 / 9; border: 0; border-radius: 8px; background: #111827; }}
    .meta {{ color: #6b7280; font-size: 13px; }}
    code, pre {{ font-family: Consolas, "SFMono-Regular", monospace; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e5e7eb; border-radius: 8px; padding: 12px; font-size: 12px; max-height: 360px; overflow: auto; }}
    ul {{ padding-left: 18px; }}
    li {{ margin: 8px 0; }}
    li span {{ display: block; color: #6b7280; font-size: 13px; margin-top: 2px; }}
    .summary {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
    .pillrow {{ display:flex; flex-wrap:wrap; gap:8px; margin: 10px 0; }}
    .pill {{ border:1px solid #d1d5db; border-radius: 999px; padding:5px 9px; font-size:12px; color:#374151; background:#fff; }}
    .thumb {{ width:100%; border-radius:8px; margin: 10px 0 0; border:1px solid #e5e7eb; }}
    .boundary {{ border-left: 4px solid #f59e0b; padding-left: 12px; color:#374151; }}
    @media (max-width: 640px) {{ main {{ padding: 22px 12px 36px; }} h1 {{ font-size: 22px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <span class="badge {status_class}">{html.escape(status_text)}</span>
    <h1>Gemini YouTube 视频审核 E2E 可行性报告</h1>
    <p>{html.escape(report["goal"])}</p>
    <p class="meta">生成时间：{html.escape(report["generated_at"])} · 模型：{html.escape(report["model"])} · 状态：{html.escape(report["run_status"])}</p>
  </header>

  <section class="card">
    <h2>结论</h2>
    <div class="summary">
      <p>{html.escape(report["conclusion"]["technical_path"])}</p>
      <p>{html.escape(report["conclusion"]["current_blocker"] or "已具备真实调用条件。")}</p>
      <p>{html.escape(report["conclusion"]["next_step"])}</p>
    </div>
    <p class="boundary">{html.escape(report["conclusion"]["business_boundary"])}</p>
  </section>

  <section style="margin-top:16px">
    <div class="grid">
      {case_cards}
    </div>
  </section>

  <section class="card" style="margin-top:16px">
    <h2>官方依据</h2>
    <ul>{refs}</ul>
  </section>
</main>
</body>
</html>"""


def _youtube_embed(url: str) -> str:
    if "/shorts/" in url:
        video_id = url.rstrip("/").split("/shorts/")[-1].split("?")[0]
    elif "watch?v=" in url:
        video_id = url.split("watch?v=")[-1].split("&")[0]
    else:
        video_id = ""
    return f"https://www.youtube.com/embed/{video_id}" if video_id else url


def _case_html(case: Dict[str, Any]) -> str:
    result = case["api_result"]
    result_text = json.dumps(result, ensure_ascii=False, indent=2)
    focus = "".join(f"<li>{html.escape(item)}</li>" for item in case["review_focus"])
    metadata = case.get("youtube_metadata") or {}
    verified = "公开视频可访问" if metadata.get("ok") else "视频可访问性待复核"
    real_title = metadata.get("title") or case["title"]
    author = metadata.get("author_name") or "未知频道"
    thumbnail = metadata.get("thumbnail_url") or ""
    thumb_html = f'<img class="thumb" src="{html.escape(thumbnail)}" alt="{html.escape(real_title)} 缩略图" />' if thumbnail else ""
    api_status = "已真实调用 Gemini" if result.get("ok") else ("缺少 Gemini Key，未真实调用" if result.get("blocked") else "Gemini 调用失败")
    return f"""<article class="card">
  <h2>{html.escape(case["title"])}</h2>
  <div class="pillrow">
    <span class="pill">{html.escape(case["scenario"])}</span>
    <span class="pill">{html.escape(verified)}</span>
    <span class="pill">{html.escape(api_status)}</span>
  </div>
  <iframe src="{html.escape(_youtube_embed(case["url"]))}" allowfullscreen></iframe>
  {thumb_html}
  <p class="meta">{html.escape(case["source_note"])}</p>
  <p class="meta">YouTube 标题：{html.escape(real_title)} · 频道：{html.escape(author)}</p>
  <p><a href="{html.escape(case["url"])}" target="_blank" rel="noreferrer">打开 YouTube 原视频</a></p>
  <h3>审核重点</h3>
  <ul>{focus}</ul>
  <h3>Gemini 返回</h3>
  <pre>{html.escape(result_text)}</pre>
</article>"""


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"gemini_youtube_e2e_{stamp}.json"
    html_path = REPORT_DIR / f"gemini_youtube_e2e_{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    print(json.dumps({"json_report": str(json_path), "html_report": str(html_path), "run_status": report["run_status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
