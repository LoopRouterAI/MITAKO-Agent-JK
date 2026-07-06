# -*- coding: utf-8 -*-
"""视觉审核工作台的客服可读报告渲染。"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional


BUSINESS_ACTION_WORDS = ("退款", "退货退款", "退货", "补发", "拒赔", "赔付", "补偿", "予以支持", "直接处理")


def _h(value: Any) -> str:
    text = str(value if value is not None else "")
    text = text.replace("外包装", "包装").replace("外包", "协作")
    return html.escape(text)


def _has_business_action(text: Any) -> bool:
    return any(word in str(text or "") for word in BUSINESS_ACTION_WORDS)


def safe_agent_conclusion(parsed: Dict[str, Any], scenario_label: str) -> str:
    clean_label = scenario_label.replace("审核", "")
    label = str(parsed.get("predicted_label") or "").lower()
    confidence = parsed.get("confidence")
    if label == "positive":
        return f"视觉证据支持{clean_label}诉求，置信度 {confidence}。"
    if label == "negative":
        return f"视觉证据暂不支持用户诉求，置信度 {confidence}。"
    return f"证据不足，需要人工复核，置信度 {confidence}。"


def safe_agent_next_step(text: Any) -> str:
    if _has_business_action(text):
        return "将视觉证据摘要提交人工客服复核；由客服系统结合订单、售后政策和库存记录决定后续业务动作。"
    return str(text or "请人工客服结合订单、售后规则和原始素材处理。")


def _safe_agent_reason(text: Any) -> str:
    chunks = [item.strip() for item in re.split(r"[。；;]\s*", str(text or "")) if item.strip()]
    kept = [item for item in chunks if not _has_business_action(item)]
    return "。".join(kept[:3]) + ("。" if kept else "")


def _public_verdict(parsed: Dict[str, Any], scenario_label: str) -> str:
    visual = parsed.get("visual_qc_conclusion") or {}
    verdict = visual.get("verdict")
    if verdict and verdict not in {"positive", "negative", "review"}:
        return str(verdict)
    label = str(parsed.get("predicted_label") or "").lower()
    if label == "positive":
        return "支持" + scenario_label.replace("审核", "") + "诉求"
    if label == "negative":
        return "暂不支持用户诉求"
    return "需要人工复核"


def _public_yes_no(parsed: Dict[str, Any]) -> str:
    value = str(parsed.get("system_yes_no") or parsed.get("predicted_label") or "").lower()
    if value in {"yes", "y", "positive", "support"}:
        return "YES"
    if value in {"no", "n", "negative", "reject"}:
        return "NO"
    return "REVIEW"


def _usage_label(result: Dict[str, Any]) -> str:
    usage = result.get("usage") or {}
    return " / ".join(_h(usage.get(key) or "-") for key in ("input_tokens", "output_tokens", "total_tokens"))


def _spend_label(result: Dict[str, Any]) -> str:
    cost = result.get("cost") or {}
    if cost.get("amount") is not None and cost.get("currency"):
        return f"{_h(cost.get('amount'))} {_h(cost.get('currency'))}"
    if cost.get("estimated_usd") is not None:
        return f"${_h(cost.get('estimated_usd'))}"
    return "-"


def _source_label(value: Any) -> str:
    mapping = {
        "supplementary_image": "补充图片",
        "supplemental_image": "补充图片",
        "video_frame": "视频帧",
        "frame": "视频帧",
        "video": "视频",
        "image": "图片",
    }
    return mapping.get(str(value or "").strip().lower(), str(value or "证据"))


def _evidence_items(items: Any, media_gallery: Optional[Dict[str, Any]] = None) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="muted">模型没有给出可采信证据，建议人工查看原始素材。</p>'
    media_gallery = media_gallery or {}
    frame_map: Dict[str, Dict[str, Any]] = {}
    for frame in media_gallery.get("frames") or []:
        for key in (frame.get("global_frame_index"), frame.get("frame_index")):
            if key is not None:
                frame_map[str(key)] = frame
    image_map = {
        str(item.get("image_index")): item
        for item in media_gallery.get("images") or []
        if item.get("image_index") is not None
    }

    def media_preview(item: Dict[str, Any]) -> str:
        frame_key = item.get("global_frame_index") or item.get("frame_index")
        image_key = item.get("image_index")
        media = frame_map.get(str(frame_key)) if frame_key is not None else None
        media_label = "查看视频时间点"
        if media is None and image_key is not None:
            media = image_map.get(str(image_key))
            media_label = "查看补充图片"
        if not media or not media.get("url"):
            return ""
        video_link = ""
        if media.get("video_url"):
            video_link = (
                f'<button class="jump preview-trigger" type="button" data-preview-kind="video" '
                f'data-preview-src="{_h(media.get("video_url"))}" data-preview-title="原视频 {_h(media.get("timestamp") or "")}">'
                f'预览原视频 {_h(media.get("timestamp") or "")}</button>'
            )
        return (
            '<div class="evidence-media">'
            f'<button class="thumb preview-trigger" type="button" data-preview-kind="image" '
            f'data-preview-src="{_h(media.get("url"))}" data-preview-title="{_h(media.get("file") or media_label)}">'
            f'<img src="{_h(media.get("url"))}" alt="{_h(media.get("file") or "证据素材")}"></button>'
            f"{video_link}"
            "</div>"
        )

    cards: List[str] = []
    for index, item in enumerate(items[:8], start=1):
        if not isinstance(item, dict):
            continue
        source = item.get("timestamp") or item.get("file") or item.get("source_type") or f"证据 {index}"
        fact = item.get("fact") or item.get("description") or item.get("why_it_matters") or item
        confidence = item.get("confidence")
        cards.append(
            '<article class="evidence-card">'
            f'<small>{_h(_source_label(item.get("source_type")))} · {_h(source)}</small>'
            f"{media_preview(item)}"
            f"<p>{_h(fact)}</p>"
            f'<b>{_h(confidence if confidence not in (None, "") else "已采信")}</b>'
            "</article>"
        )
    return "".join(cards) or '<p class="muted">模型没有给出可采信证据，建议人工查看原始素材。</p>'


def _gallery_items(items: List[Dict[str, Any]], kind: str) -> str:
    html_items: List[str] = []
    for item in items[:24]:
        if not item.get("url"):
            continue
        subtitle = item.get("timestamp") or item.get("file") or "-"
        video_link = ""
        if item.get("video_url"):
            video_link = (
                f'<button class="inline-preview preview-trigger" type="button" data-preview-kind="video" '
                f'data-preview-src="{_h(item.get("video_url"))}" data-preview-title="视频时间点 {_h(item.get("timestamp") or "")}">'
                "预览视频时间点</button>"
            )
        html_items.append(
            '<figure class="media-tile">'
            f'<button class="preview-trigger" type="button" data-preview-kind="image" data-preview-src="{_h(item.get("url"))}" data-preview-title="{_h(item.get("file") or kind)}">'
            f'<img src="{_h(item.get("url"))}" alt="{_h(item.get("file") or kind)}"></button>'
            f"<figcaption><b>{_h(kind)}</b><span>{_h(subtitle)}</span>{video_link}</figcaption>"
            "</figure>"
        )
    return "".join(html_items) or '<p class="muted">本轮报告没有可预览素材。</p>'


def render_public_report(data: Dict[str, Any]) -> str:
    if data.get("agent_report"):
        return _render_agent_report(data)
    summary = data.get("summary") or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>视觉审核复核摘要</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
  <main class="shell">
    <section class="hero simple">
      <span class="badge">视觉审核复核摘要</span>
      <h1>{_h(data.get("review_label") or "审核结果")}</h1>
      <p class="lead">本页仅展示客服可复核的业务摘要和处理建议。最终处理结论仍需人工复核确认。</p>
    </section>
    <section class="metrics">
      <div class="metric"><small>审核样本</small><b>{_h(summary.get("cases") or "-")}</b></div>
      <div class="metric"><small>复核次数</small><b>{_h(summary.get("total_reviews") or 0)}</b></div>
      <div class="metric"><small>成功返回</small><b>{_h(summary.get("successful_reviews") or 0)}</b></div>
      <div class="metric"><small>生成时间</small><b>{_h(data.get("generated_at"))}</b></div>
	    </section>
	    <section class="panel conclusion-card"><h2>处理建议</h2><p>{_h(data.get("conclusion"))}</p></section>
	  </main>
{_LIGHTBOX_HTML}
</body>
</html>"""


def _render_agent_report(data: Dict[str, Any]) -> str:
    report = data.get("agent_report") or {}
    parsed = report.get("parsed") or {}
    overall = parsed.get("overall_audit") or {}
    visual = parsed.get("visual_qc_conclusion") or {}
    video = parsed.get("video_audit_conclusion") or parsed.get("continuity_assessment") or {}
    runtime = report.get("runtime") or {}
    quality = report.get("quality") or {}
    media_gallery = report.get("media_gallery") or {}
    evidence_package = report.get("evidence_package") or {}
    scenario_label = report.get("scenario_label") or str(data.get("review_label") or "当前审核").split("/", 1)[0].strip()
    public_brief = report.get("public_brief") or {}
    conclusion = public_brief.get("conclusion") or safe_agent_conclusion(parsed, scenario_label)
    confidence = overall.get("confidence") or parsed.get("confidence") or "-"
    core_reason = _safe_agent_reason(overall.get("core_reason") or parsed.get("confidence_reason") or "")
    if not core_reason:
        core_reason = parsed.get("visual_evidence_verdict") or visual.get("reason") or ""
    next_step = public_brief.get("next_step") or safe_agent_next_step(overall.get("business_follow_up_suggestion") or parsed.get("next_step"))
    material_gaps = parsed.get("material_gaps") or []
    gap_text = "；".join(str(x) for x in material_gaps[:5]) if isinstance(material_gaps, list) and material_gaps else "当前证据可进入人工复核；如需最终处置，仍需核对订单、库存和售后规则。"
    yes_no = _public_yes_no(parsed)
    latency = runtime.get("latency_seconds") or "-"
    video_count = len(evidence_package.get("videos") or [])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_h(scenario_label)} Agent 报告</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
<main class="shell">
  <section class="hero">
    <div>
      <span class="badge">{_h(scenario_label)} Agent 报告</span>
      <h1>{_h(conclusion)}</h1>
      <p class="lead">{_h(core_reason or "模型已完成视觉证据整理，请结合下方证据链复核。")}</p>
    </div>
    <aside class="verdict-card">
      <small>系统参考</small>
      <b>{_h(yes_no)}</b>
      <span>置信度 {_h(confidence)}</span>
    </aside>
  </section>

  <section class="panel next-step">
    <h2>给人工客服的下一步</h2>
    <p>{_h(next_step)}</p>
  </section>

  <section class="metrics">
	    <div class="metric hot"><small>视觉质检</small><b>{_h(_public_verdict(parsed, scenario_label))}</b></div>
	    <div class="metric"><small>连续性分数</small><b>{_h(video.get("continuity_score") or "-")}</b></div>
	    <div class="metric"><small>调包风险</small><b>{_h(video.get("swap_risk_level") or "-")}</b></div>
	    <div class="metric"><small>耗时</small><b>{_h(latency)}s</b></div>
	    <div class="metric"><small>送审视频</small><b>{_h(video_count or "-")}</b></div>
	    <div class="metric"><small>送审帧数</small><b>{_h(evidence_package.get("frames_sent") or "-")}</b></div>
	    <div class="metric"><small>补充图片</small><b>{_h(evidence_package.get("supplemental_images_sent") or "-")}</b></div>
	    <div class="metric"><small>报告属性</small><b>人工复核参考</b></div>
	  </section>

	  <section class="panel">
	    <div class="section-head"><h2>模型采信的证据</h2><p>每张图都可以在本页放大查看；带时间点的帧可以直接预览原视频片段。</p></div>
    <div class="evidence-grid">{_evidence_items(parsed.get("adopted_evidence") or parsed.get("supporting_evidence"), media_gallery)}</div>
  </section>

  <section class="panel proof">
    <h2>视频审核论证</h2>
    <p><b>连续性：</b>{_h(video.get("continuity_reason") or video.get("reason") or "本轮没有输出明确连续性理由。")}</p>
    <p><b>剪辑/调包风险：</b>{_h(video.get("edit_or_cut_risk") or "-")} / {_h(video.get("swap_risk_level") or "-")}</p>
  </section>

  <section class="panel">
    <h2>还需要人工知晓</h2>
    <p>{_h(gap_text)}</p>
  </section>

  <section class="panel">
    <div class="section-head"><h2>送审证据画廊</h2><p>用于快速复核模型看到的帧图和用户补充图片。</p></div>
    <h3>视频帧</h3>
    <div class="media-grid">{_gallery_items(media_gallery.get("frames") or [], "视频帧")}</div>
    <h3>补充图片</h3>
    <div class="media-grid">{_gallery_items(media_gallery.get("images") or [], "补充图片")}</div>
	  </section>
</main>
{_LIGHTBOX_HTML}
</body>
</html>"""


_LIGHTBOX_HTML = """
<div class="lightbox" id="mediaLightbox" hidden>
  <div class="lightbox-backdrop" data-close-preview></div>
  <section class="lightbox-panel" role="dialog" aria-modal="true" aria-label="证据预览">
    <header><b id="lightboxTitle">证据预览</b><button type="button" data-close-preview>关闭</button></header>
    <div id="lightboxBody" class="lightbox-body"></div>
  </section>
</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
  try {
    var box = document.getElementById('mediaLightbox');
    var body = document.getElementById('lightboxBody');
    var title = document.getElementById('lightboxTitle');
    if (!box || !body || !title) return;
    function closePreview() {
      box.hidden = true;
      body.replaceChildren();
    }
    function openPreview(button) {
      var src = button.getAttribute('data-preview-src') || '';
      var kind = button.getAttribute('data-preview-kind') || 'image';
      title.textContent = button.getAttribute('data-preview-title') || '证据预览';
      body.replaceChildren();
      if (kind === 'video') {
        var video = document.createElement('video');
        video.src = src;
        video.controls = true;
        video.playsInline = true;
        body.appendChild(video);
      } else {
        var img = document.createElement('img');
        img.src = src;
        img.alt = title.textContent;
        body.appendChild(img);
      }
      box.hidden = false;
    }
    document.querySelectorAll('[data-preview-src]').forEach(function (button) {
      button.addEventListener('click', function () { openPreview(button); });
    });
    document.querySelectorAll('[data-close-preview]').forEach(function (button) {
      button.addEventListener('click', closePreview);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !box.hidden) closePreview();
    });
  } catch (error) {
    console.error('报告预览初始化失败', error);
  }
});
</script>
"""


_REPORT_CSS = """
:root {
  color-scheme: light;
  --ink:#10131f;
  --ink-2:#252a38;
  --muted:#687083;
  --line:#e8ecdf;
  --paper:#fbfff1;
  --card:#fff;
  --lime:#c8ff1a;
  --green:#8bd600;
  --gold:#ffd43d;
  --rose:#ff75a8;
  --orange:#ff8a1f;
  --violet:#8b5cf6;
  --cyan:#12d6c7;
  --shadow:0 20px 52px rgba(16,19,31,.10);
  font-family:"Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif;
}
* { box-sizing:border-box; }
body {
  margin:0;
  color:var(--ink);
  background:
    radial-gradient(circle at 90% 0%, rgba(200,255,26,.70) 0 130px, transparent 131px),
    radial-gradient(circle at 4% 10%, rgba(255,117,168,.15), transparent 240px),
    radial-gradient(circle at 84% 44%, rgba(18,214,199,.12), transparent 280px),
    linear-gradient(180deg,#fff 0%,#fbfff4 52%,#fff 100%);
}
a { color:inherit; }
button { font:inherit; color:inherit; cursor:pointer; }
.shell { width:min(1180px, calc(100vw - 32px)); margin:0 auto; padding:26px 0 56px; }
.hero > *, .panel, .metric, .evidence-card, .media-tile { min-width:0; }
.hero {
  position:relative;
  display:grid;
  grid-template-columns:minmax(0, 1fr) 220px;
  gap:22px;
  align-items:stretch;
  overflow:hidden;
  padding:30px;
  border:1px solid rgba(16,19,31,.08);
  border-radius:28px;
  background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(248,255,230,.92));
  box-shadow:var(--shadow);
}
.hero.simple { display:block; }
.hero::after {
  content:"";
  position:absolute;
  inset:auto 0 0 0;
  height:10px;
  background:linear-gradient(90deg,var(--lime),var(--gold),var(--rose),var(--violet),var(--cyan));
}
.badge {
  display:inline-flex;
  align-items:center;
  min-height:31px;
  padding:6px 11px;
  border:1px solid rgba(16,19,31,.10);
  border-radius:999px;
  background:linear-gradient(90deg,var(--lime),#efffb2);
  box-shadow:0 10px 24px rgba(139,214,0,.18);
  font-size:12px;
  font-weight:950;
}
h1 {
  max-width:850px;
  margin:16px 0 0;
  font-size:clamp(34px, 4.4vw, 62px);
  line-height:1.02;
  letter-spacing:0;
  text-wrap:pretty;
  overflow-wrap:anywhere;
}
h2 { margin:0 0 12px; font-size:22px; line-height:1.2; }
h3 { margin:20px 0 10px; font-size:16px; }
p { line-height:1.75; }
.lead { max-width:850px; margin:16px 0 0; color:var(--ink-2); font-size:17px; }
.verdict-card {
  display:grid;
  align-content:center;
  gap:8px;
  min-height:190px;
  padding:20px;
  border:1px solid rgba(16,19,31,.10);
  border-radius:24px;
  background:linear-gradient(145deg,var(--lime),#fff6b9);
  box-shadow:0 18px 42px rgba(16,19,31,.14);
}
.verdict-card small, .metric small, .evidence-card small, .muted, .section-head p { color:var(--muted); }
.verdict-card b { font-size:58px; line-height:.95; }
.verdict-card span { font-weight:900; }
.panel, .metric {
  border:1px solid rgba(16,19,31,.08);
  border-radius:24px;
  background:var(--card);
  box-shadow:var(--shadow);
}
.panel { margin-top:16px; padding:22px; }
.next-step { background:linear-gradient(135deg,#f2ffd9,#fff 72%); }
.metrics {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:12px;
  margin-top:16px;
}
.metric {
  min-height:112px;
  padding:16px;
}
.metric.hot { background:linear-gradient(135deg,var(--lime),#fff7a6); }
.metric b { display:block; margin-top:8px; font-size:24px; line-height:1.15; }
.lead, .metric b, .evidence-card p, .media-tile figcaption { overflow-wrap:anywhere; word-break:break-word; }
.section-head {
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:16px;
  margin-bottom:14px;
}
.section-head p { max-width:520px; margin:0; font-size:13px; }
.evidence-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  gap:12px;
}
.evidence-card {
  min-height:210px;
  padding:13px;
  border:1px solid var(--line);
  border-radius:18px;
  background:linear-gradient(135deg,#fff,#fbfff0);
}
.evidence-card p { margin:10px 0; font-size:14px; }
.evidence-card b {
  display:inline-flex;
  padding:5px 9px;
  border-radius:999px;
  background:linear-gradient(90deg,var(--lime),var(--gold));
  font-size:12px;
}
.evidence-media { display:grid; gap:8px; margin:8px 0 10px; }
.thumb {
  display:block;
  width:100%;
  padding:0;
  overflow:hidden;
  border:1px solid rgba(16,19,31,.12);
  border-radius:16px;
  background:#10131f;
}
.thumb img, .media-tile img {
  display:block;
  width:100%;
  aspect-ratio:16/10;
  object-fit:cover;
  background:#10131f;
}
.jump {
  display:inline-flex;
  width:max-content;
  min-height:31px;
  align-items:center;
  padding:6px 10px;
  border:1px solid rgba(16,19,31,.12);
  border-radius:999px;
  background:#fff;
  text-decoration:none;
  font-size:12px;
  font-weight:950;
}
.inline-preview {
  width:max-content;
  padding:0;
  border:0;
  background:transparent;
  color:var(--ink);
  text-align:left;
  font-weight:950;
}
.proof { background:linear-gradient(135deg,#fff,#fff7da); }
.media-grid {
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(168px,1fr));
  gap:12px;
}
.media-tile {
  margin:0;
  overflow:hidden;
  border:1px solid var(--line);
  border-radius:18px;
  background:#fff;
  box-shadow:0 12px 28px rgba(16,19,31,.08);
}
.media-tile > button {
  display:block;
  width:100%;
  padding:0;
  border:0;
  background:#10131f;
}
.media-tile figcaption {
  display:grid;
  gap:4px;
  padding:9px;
  color:var(--muted);
  font-size:12px;
}
.media-tile figcaption a { color:var(--ink); font-weight:950; }
.lightbox[hidden] { display:none; }
.lightbox {
  position:fixed;
  inset:0;
  z-index:50;
  display:grid;
  place-items:center;
  padding:22px;
}
.lightbox-backdrop {
  position:absolute;
  inset:0;
  background:rgba(16,19,31,.72);
  backdrop-filter:blur(10px);
}
.lightbox-panel {
  position:relative;
  z-index:1;
  width:min(1080px, 100%);
  max-height:92vh;
  overflow:hidden;
  border:1px solid rgba(255,255,255,.34);
  border-radius:24px;
  background:#fff;
  box-shadow:0 28px 72px rgba(0,0,0,.32);
}
.lightbox-panel header {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:12px 14px;
  border-bottom:1px solid var(--line);
  background:linear-gradient(90deg,var(--lime),#fff8bd);
}
.lightbox-panel header button {
  min-height:34px;
  padding:6px 12px;
  border:1px solid rgba(16,19,31,.16);
  border-radius:999px;
  background:#fff;
  font-weight:950;
}
.lightbox-body {
  display:grid;
  place-items:center;
  max-height:calc(92vh - 62px);
  padding:12px;
  background:#10131f;
}
.lightbox-body img, .lightbox-body video {
  display:block;
  max-width:100%;
  max-height:calc(92vh - 86px);
  border-radius:16px;
  object-fit:contain;
}
@media (max-width:760px) {
  .shell { width:min(100% - 20px, 1180px); padding-top:12px; }
  .hero { grid-template-columns:1fr; padding:18px; border-radius:22px; }
  h1 { font-size:30px; word-break:break-all; }
  p, .lead { word-break:break-all; }
  .metrics { grid-template-columns:1fr; }
  .metric { min-height:auto; }
  .verdict-card { min-height:130px; }
  .verdict-card b { font-size:44px; }
  .section-head { display:block; }
  .panel { padding:16px; border-radius:20px; }
}
@media (max-width:520px) {
  .shell { width:min(370px, calc(100vw - 20px)); max-width:none; margin-left:10px; margin-right:10px; }
}
"""
