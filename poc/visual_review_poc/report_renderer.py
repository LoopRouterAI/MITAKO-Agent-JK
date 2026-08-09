# -*- coding: utf-8 -*-
"""视觉审核工作台的客服可读报告渲染。"""
from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, List, Optional

from poc.visual_review_poc.report_assessment_sections import (
    render_confidence_components_panel,
    render_damage_causality_panel,
    render_fulfillment_reconciliation_panel,
    render_claim_fact_panel,
    render_minor_material_panel,
    render_object_continuity_panel,
)


BUSINESS_ACTION_WORDS = (
    "退款",
    "退货退款",
    "退货",
    "补发",
    "拒赔",
    "赔付",
    "补偿",
    "予以支持",
    "直接处理",
    "拒绝",
    "驳回",
    "通过审核",
    "审核通过",
    "同意",
    "定责",
)
SIGNAL_LABELS = {
    "material_gap": "材料缺口",
    "technical_processing_incomplete": "系统处理未完成",
    "short_out_of_frame": "短暂离镜",
    "out_of_frame_over_threshold": "离镜超过补件阈值",
    "identity_reestablishment_unresolved": "重新入镜后是否同一件商品尚未确认",
    "continuity_unresolved": "商品连续性尚未完全确认",
    "evidence_conflict": "证据冲突",
    "media_forensic_risk": "视频技术风险",
    "authoritative_verification_pending": "严格在线验真尚未完成",
    "image_authenticity_risk": "图片真实性风险",
    "minor_payment_process_evidence_gap": "低龄支付过程待补",
    "minor_low_age_process_verified": "低龄支付过程已核对",
    "customer_risk_context": "抽检优先级提示",
}


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _playback_speed_evidence(media_forensics: Any) -> str:
    if not isinstance(media_forensics, dict):
        return '<li>本轮未获得可展示的播放速度取证结果。</li>'
    rows = []
    for asset in media_forensics.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        assessment = asset.get("playback_speed_assessment")
        if not isinstance(assessment, dict):
            continue
        multiplier = assessment.get("constant_speed_multiplier")
        speed = multiplier if assessment.get("status") == "known" and multiplier is not None else "未知"
        method = "非模型推断" if assessment.get("is_model_inference") is False else "推断来源未声明"
        rows.append(
            f'<li>{_h(asset.get("file") or asset.get("asset_id") or "视频")}：'
            f'恒定倍速：{_h(speed)}；{_h(assessment.get("reason") or "未提供原因")}；{method}。</li>'
        )
    return "".join(rows) or '<li>本轮未获得可展示的播放速度取证结果。</li>'


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
    return f"本轮未形成明确事实倾向，证据分数 {confidence}。"


def safe_agent_next_step(text: Any) -> str:
    if _has_business_action(text):
        return "将视觉证据摘要提交VIP客服复核；由客服系统结合订单、售后政策和库存记录决定后续业务动作。"
    return str(text or "请结合本页证据、订单资料和适用 SOP 继续处理。")


def _safe_agent_reason(text: Any) -> str:
    raw_text = str(text or "").strip()
    if raw_text.startswith("未启用商品有伤规则"):
        return ""
    chunks = [item.strip() for item in re.split(r"[。；;]\s*", raw_text) if item.strip()]
    return "。".join(chunks[:3]) + ("。" if chunks else "")


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
    return "本轮未形成明确事实倾向"


def _public_yes_no(parsed: Dict[str, Any]) -> str:
    value = str(parsed.get("system_yes_no") or parsed.get("predicted_label") or "").lower()
    if value in {"yes", "y", "positive", "support"}:
        return "YES"
    if value in {"no", "n", "negative", "reject"}:
        return "NO"
    return "REVIEW"


def _public_status(value: Any) -> str:
    return {
        "completed": "已完成，未发现阻断性技术异常",
        "unavailable": "本轮不可用",
        "not_provided": "未提供",
        "requires_media_forensics": "需要结合媒体技术取证",
        "ffprobe_not_available": "媒体取证工具不可用",
    }.get(str(value or "").strip().lower(), str(value or "未提供"))


def _decision_policy_panel(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    if str(value.get("reason") or "").startswith("未启用商品有伤规则"):
        return ""
    labels = {
        "opening_complete": "开箱过程未被确认完整",
        "sampling_boundary_covered": "抽帧未覆盖源视频首尾边界",
        "continuity_gate": "主体连续性未达到当前策略要求",
        "damage_not_visible": "主视频尚不能明确支持“未见主诉损伤”",
        "claim_not_supported": "主视频尚不能明确判定诉求不受支持",
        "visibility_coverage": "争议商品可见覆盖率低于策略阈值",
        "model_confidence": "审核置信度低于策略阈值",
        "claimed_item_absence_within_limit": "争议商品离镜时间超过策略阈值",
        "damage_observability": "主诉部位可观察性未达到策略阈值",
        "media_forensics": "非 AI 媒体取证未完成或风险超过阈值",
        "supplemental_evidence_resolved": "补充证据关联尚未解决，不能忽略或自动判负",
    }
    failed = [
        labels.get(str(code), str(code))
        for code in value.get("failed_conditions") or []
    ]
    failed_html = "".join(f"<li>{_h(item)}</li>" for item in failed) or "<li>本轮规则已命中或未声明失败条件。</li>"
    gate = value.get("evidence_gate") or {}
    threshold_text = (
        f"争议商品最长离镜 {_h(gate.get('claimed_item_longest_out_of_frame_seconds') if gate.get('claimed_item_longest_out_of_frame_seconds') is not None else '-')} 秒；"
        f"策略上限 {_h(gate.get('max_unobserved_seconds') if gate.get('max_unobserved_seconds') is not None else '-')} 秒；"
        f"媒体取证 {_h(gate.get('media_forensics_status') or '未提供')}。"
    )
    return f"""
  <section class="panel boundary-panel">
    <div class="section-head"><h2>SOP 规则判定说明</h2><p>规则只生成审核倾向，不自动拒绝、退款、补发、换货或定责。</p></div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>规则结果</h3><p><b>{_h("已按 SOP 形成审核倾向" if value.get("applied") else "当前条件不足，保持复核")}</b></p><p>{_h(value.get("reason") or "")}</p></article>
      <article class="boundary-card"><h3>未通过的门槛</h3><ul class="boundary-list">{failed_html}</ul></article>
    </div>
    <p><b>关键阈值：</b>{threshold_text}</p>
  </section>"""


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


def _timestamp_key(value: Any) -> str:
    """将秒数或时分秒时间戳归一化，供证据与画廊回链。"""
    if value in (None, ""):
        return ""
    text = str(value).strip().lower()
    if not text or text in {"n/a", "na", "-"}:
        return ""
    text = re.sub(r"^(?:t\s*=\s*)", "", text)
    text = re.sub(r"\s*(?:seconds?|secs?|s|秒)$", "", text)
    try:
        if ":" not in text:
            seconds = float(text)
        else:
            parts = [float(part) for part in text.split(":")]
            if len(parts) == 2:
                seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            else:
                return text
        return f"{seconds:.3f}"
    except (TypeError, ValueError):
        return text


def _file_key(value: Any) -> str:
    if value in (None, ""):
        return ""
    return os.path.basename(str(value).strip().replace("\\", "/")).casefold()


def _as_text_list(value: Any) -> List[str]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    result: List[str] = []
    for item in values:
        if item in (None, ""):
            continue
        if isinstance(item, dict):
            text = (
                item.get("fact")
                or item.get("description")
                or item.get("reason")
                or item.get("limitation")
                or item.get("gap")
                or item.get("message")
            )
            if text:
                result.append(str(text))
        else:
            result.append(str(item))
    return result


def _list_html(value: Any, empty_text: str) -> str:
    items = _as_text_list(value)
    if not items:
        return f'<p class="muted">{_h(empty_text)}</p>'
    return '<ul class="boundary-list">' + "".join(f"<li>{_h(item)}</li>" for item in items[:8]) + "</ul>"


def _risky_frame_findings(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    no_risk_values = {"", "0", "false", "low", "none", "normal", "无", "无异常", "正常", "未见异常", "低"}
    findings: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk") or "").strip().lower()
        if risk in no_risk_values:
            continue
        findings.append(
            {
                **item,
                "source_type": item.get("source_type") or "video_frame",
                "fact": item.get("fact") or item.get("visible_facts") or item.get("description") or "该帧存在需复核的视觉风险。",
                "why_it_matters": item.get("why_it_matters") or f"风险标记：{item.get('risk')}",
            }
        )
    return findings


def _issue_timestamp_items(value: Any) -> List[Dict[str, Any]]:
    if value in (None, "", []):
        return []
    values = value if isinstance(value, list) else [value]
    result: List[Dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            result.append(
                {
                    **item,
                    "source_type": item.get("source_type") or "video_frame",
                    "fact": item.get("fact") or item.get("description") or item.get("visible_facts") or item.get("reason") or "该时间点被标记为问题位置。",
                    "why_it_matters": item.get("why_it_matters") or "建议VIP客服重点查看该时间点及其前后连续画面。",
                }
            )
        elif item not in (None, ""):
            result.append(
                {
                    "source_type": "video_frame",
                    "timestamp": item,
                    "fact": "该时间点被标记为问题位置。",
                    "why_it_matters": "建议VIP客服重点查看该时间点及其前后连续画面。",
                }
            )
    return result


def _evidence_items(
    items: Any,
    media_gallery: Optional[Dict[str, Any]] = None,
    default_status: str = "已采信",
) -> str:
    if not isinstance(items, list) or not items:
        return '<p class="muted">审核Agent没有给出可采信证据，建议客服查看原始素材。</p>'
    media_gallery = media_gallery or {}
    frame_map: Dict[str, Dict[str, Any]] = {}
    video_frame_map: Dict[str, Dict[str, Any]] = {}
    frame_candidates: Dict[str, List[Dict[str, Any]]] = {}
    timestamp_map: Dict[str, Dict[str, Any]] = {}
    timestamp_candidates: Dict[str, List[Dict[str, Any]]] = {}
    video_timestamp_map: Dict[str, Dict[str, Any]] = {}
    file_map: Dict[str, Dict[str, Any]] = {}
    for frame in media_gallery.get("frames") or []:
        for key in (frame.get("global_frame_index"), frame.get("frame_index")):
            if key is not None:
                frame_candidates.setdefault(str(key), []).append(frame)
                if frame.get("video_index") is not None:
                    video_frame_map[f"{frame.get('video_index')}:{key}"] = frame
    frame_map = {
        key: values[0]
        for key, values in frame_candidates.items()
        if len(values) == 1
    }
    for frame in media_gallery.get("frames") or []:
        timestamp_key = _timestamp_key(frame.get("timestamp"))
        if timestamp_key:
            timestamp_candidates.setdefault(timestamp_key, []).append(frame)
            if frame.get("video_index") is not None:
                video_timestamp_map[f"{frame.get('video_index')}:{timestamp_key}"] = frame
        file_key = _file_key(frame.get("file_name") or frame.get("file"))
        if file_key:
            file_map[file_key] = frame
    timestamp_map = {
        key: values[0]
        for key, values in timestamp_candidates.items()
        if len(values) == 1
    }
    image_map = {
        str(item.get("image_index")): item
        for item in media_gallery.get("images") or []
        if item.get("image_index") is not None
    }
    for image in media_gallery.get("images") or []:
        file_key = _file_key(image.get("file_name") or image.get("file"))
        if file_key:
            file_map[file_key] = image
    reference_map = {
        str(item.get("reference_index")): item
        for item in media_gallery.get("official_references") or []
        if item.get("reference_index") is not None
    }

    def media_preview(item: Dict[str, Any]) -> str:
        frame_key = item.get("global_frame_index")
        if frame_key is None:
            frame_key = item.get("frame_index")
        image_key = item.get("image_index")
        reference_key = item.get("reference_index")
        video_frame_key = (
            f"{item.get('video_index')}:{frame_key}"
            if item.get("video_index") is not None and frame_key is not None
            else ""
        )
        media = video_frame_map.get(video_frame_key) or (frame_map.get(str(frame_key)) if frame_key is not None else None)
        media_label = "查看视频时间点"
        if media is None and image_key is not None:
            media = image_map.get(str(image_key))
            media_label = "查看补充图片"
        if media is None and reference_key is not None:
            media = reference_map.get(str(reference_key))
            media_label = "查看官方参考图"
        timestamp_key = _timestamp_key(item.get("timestamp"))
        if media is None and timestamp_key:
            video_key = f"{item.get('video_index')}:{timestamp_key}" if item.get("video_index") is not None else ""
            media = video_timestamp_map.get(video_key) or timestamp_map.get(timestamp_key)
        if media is None:
            media = file_map.get(_file_key(item.get("file_name") or item.get("file")))
        if media in (media_gallery.get("images") or []):
            media_label = "查看补充图片"
        if media in (media_gallery.get("official_references") or []):
            media_label = "查看官方参考图"
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
    for index, raw_item in enumerate(items[:12], start=1):
        item = raw_item if isinstance(raw_item, dict) else {"description": raw_item}
        source = item.get("timestamp") or item.get("file_name") or item.get("file") or item.get("source_type") or f"证据 {index}"
        fact = item.get("fact") or item.get("description") or item.get("why_it_matters") or item
        why_it_matters = item.get("why_it_matters")
        confidence = item.get("confidence")
        evidence_impact = ""
        if why_it_matters and str(why_it_matters) != str(fact):
            evidence_impact = f'<p class="evidence-impact"><strong>证据作用</strong>{_h(why_it_matters)}</p>'
        cards.append(
            '<article class="evidence-card">'
            f'<small>{_h(_source_label(item.get("source_type")))} · {_h(source)}</small>'
            f"{media_preview(item)}"
            f"<p>{_h(fact)}</p>"
            f"{evidence_impact}"
            f'<b>{_h(confidence if confidence not in (None, "") else default_status)}</b>'
            "</article>"
        )
    return "".join(cards) or '<p class="muted">审核Agent没有给出可采信证据，建议客服查看原始素材。</p>'


def _gallery_items(items: List[Dict[str, Any]], kind: str) -> str:
    html_items: List[str] = []
    visible_items = items if kind == "补充图片" else items[:24]
    for item in visible_items:
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
        image_index = item.get("image_index")
        anchor = f' id="image-{_h(image_index)}"' if image_index not in (None, "") else ""
        html_items.append(
            f'<figure class="media-tile"{anchor}>'
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
    diagnostics = data.get("diagnostics") or {}
    diagnostic_panel = ""
    if diagnostics:
        diagnostic_panel = (
            '<section class="panel failure-panel">'
            '<h2>本轮失败诊断</h2>'
            f'<p><b>失败阶段：</b>{_h(diagnostics.get("failure_stage") or "-")}</p>'
            f'<p><b>失败原因：</b>{_h(diagnostics.get("failure_reason") or "-")}</p>'
            f'<p><b>客服动作：</b>{_h(diagnostics.get("operator_hint") or "-")}</p>'
            "</section>"
        )
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
      <p class="lead">本页仅展示客服可复核的业务摘要和处理建议。最终处理结论仍需VIP客服复核确认。</p>
    </section>
    <section class="metrics">
      <div class="metric"><small>审核样本</small><b>{_h(summary.get("cases") or "-")}</b></div>
      <div class="metric"><small>复核次数</small><b>{_h(summary.get("total_reviews") or 0)}</b></div>
      <div class="metric"><small>成功返回</small><b>{_h(summary.get("successful_reviews") or 0)}</b></div>
      <div class="metric"><small>生成时间</small><b>{_h(data.get("generated_at"))}</b></div>
	    </section>
	    <section class="panel conclusion-card"><h2>处理建议</h2><p>{_h(data.get("conclusion"))}</p></section>
	    {diagnostic_panel}
		  </main>
{_LIGHTBOX_HTML}
</body>
</html>"""


def _render_agent_report(data: Dict[str, Any]) -> str:
    report = data.get("agent_report") or {}
    parsed = report.get("parsed") or {}
    diagnostics = data.get("diagnostics") or report.get("diagnostics") or {}
    failed = bool(diagnostics) or ((data.get("summary") or {}).get("review_status") == "failed")
    overall = parsed.get("overall_audit") or {}
    visual = parsed.get("visual_qc_conclusion") or {}
    video = parsed.get("video_audit_conclusion") or parsed.get("continuity_assessment") or {}
    continuity_status = (
        video.get("evidence_continuity_status")
        or (parsed.get("object_continuity_assessment") or {}).get("continuity_verdict")
    )
    runtime = report.get("runtime") or {}
    inference = report.get("inference_estimate") or {}
    media_forensics = data.get("media_forensics") or {}
    playback_speed_evidence = _playback_speed_evidence(media_forensics)
    visual_playback_speed = {
        "normal": "未见明显加速",
        "accelerated": "疑似加速",
        "unknown": "无法判断",
    }.get(str(video.get("playback_speed") or "unknown"), "无法判断")
    speed_impact = video.get("speed_review_impact") or {}
    speed_status = str(speed_impact.get("status") or "unknown")
    sampling_fps = video.get("sampling_fps")
    try:
        sampling_fps_value = float(sampling_fps)
        sampling_fps_text = f"{sampling_fps_value:g} FPS"
    except (TypeError, ValueError):
        sampling_fps_value = 0.0
        sampling_fps_text = "当前抽帧密度"
    affected_labels = {
        "sealed_start": "封箱起始",
        "waybill": "面单可见性",
        "opening_action": "拆封动作",
        "claimed_item_continuity": "争议商品连续性",
        "issue_first_visible": "伤情首次出现",
    }
    affected_text = "、".join(
        affected_labels.get(str(item), str(item))
        for item in speed_impact.get("affected_review_items") or []
    ) or "关键审核节点"
    if video.get("playback_speed") != "accelerated":
        speed_impact_html = ""
    elif speed_status == "uncertain":
        speed_impact_html = (
            f"<p><b>橙色风险：</b>疑似加速，当前 {_h(sampling_fps_text)} 不足以判断"
            f"{_h(affected_text)}；建议受控提升到 2 FPS 强化复核，加速本身不作为判负依据。</p>"
        )
    elif speed_status == "material" and sampling_fps_value >= 2.0:
        speed_impact_html = (
            f"<p><b>实质影响：</b>2 FPS 强化复核后仍无法判断{_h(affected_text)}，"
            "当前开箱材料不足以形成可靠结论。</p>"
        )
    elif speed_status == "material":
        speed_impact_html = (
            f"<p><b>橙色风险：</b>当前仅完成 {_h(sampling_fps_text)} 审核，"
            f"{_h(affected_text)}仍需 2 FPS 强化复核，不能提前写成实质不合规。</p>"
        )
    elif speed_status == "none" and speed_impact.get("critical_evidence_observable") is True:
        speed_impact_html = (
            f"<p><b>橙色风险：</b>疑似加速，但当前 {_h(sampling_fps_text)} 下"
            "关键证据仍可判断，不因加速本身阻断结论。</p>"
        )
    else:
        speed_impact_html = "<p><b>橙色风险：</b>疑似加速，但尚未形成速度影响结论，不能据此判负。</p>"
    opening_compliance = video.get("opening_video_compliance") or {}
    opening_field_labels = (
        ("sealed_start", "封箱起始"),
        ("waybill_visible", "面单可核验"),
        ("single_take_continuity", "一镜到底连续拆封"),
        ("issue_visible_in_continuous_opening", "伤点在连续开箱中清晰展示"),
    )
    opening_status_labels = {True: "符合", False: "不符合", None: "未判断"}
    opening_rows = "".join(
        f"<li><b>{_h(label)}：</b>{_h(opening_status_labels.get(opening_compliance.get(field), '未判断'))}</li>"
        for field, label in opening_field_labels
    )
    opening_compliance_html = (
        f'<div class="opening-checks"><h3>主开箱视频硬要求</h3><ul class="boundary-list">{opening_rows}</ul></div>'
        if isinstance(opening_compliance, dict)
        and any(isinstance(opening_compliance.get(field), bool) for field, _ in opening_field_labels)
        else ""
    )
    advisory = report.get("advisory_assessment") or data.get("advisory_assessment") or {}
    advisory_assessment = advisory.get("assessment") or {}
    sop_recommendation = advisory.get("sop_recommendation") or {}
    human_review = advisory.get("human_review") or {}
    advisory_policy = advisory.get("policy") or {}
    evidence_attention = advisory.get("evidence_attention") or {}
    human_level = str(human_review.get("level") or "")
    human_level_label = {
        "required": "必须人工复审",
        "optional": "建议抽检",
        "not_required": "无需人工复审",
    }.get(human_level, "未分级")
    workflow_label = {
        "human_review": "进入人工复审",
        "request_more_material": "只补充缺少或看不清的材料",
        "continue_by_customer_policy": "按甲方规则继续",
        "system_retry": "系统重试，不让用户重复补材料",
    }.get(str(advisory.get("workflow_recommendation") or ""), "未给出")
    signal_cards = "".join(
        '<article class="boundary-card">'
        f'<h3>{_h(SIGNAL_LABELS.get(str(item.get("code") or ""), "风险信号"))}</h3>'
        f'<p>{_h(item.get("effect") or "-")}</p>'
        + (
            f'<p><b>持续时间：</b>{_h(item.get("duration_seconds"))} 秒</p>'
            if item.get("duration_seconds") not in (None, "") else ""
        )
        + '</article>'
        for item in advisory.get("signals") or []
        if isinstance(item, dict)
    )
    advisory_panel = ""
    channel_labels = {
        "main_review": "主审核",
        "object_continuity": "主体连续性",
        "damage_causality": "损伤因果",
        "minor_material_inventory": "未成年人材料识别",
        "minor_process_video": "未成年人过程视频",
        "minor_field_consistency": "未成年人字段一致性",
    }
    channel_cards = "".join(
        '<article class="boundary-card">'
        f'<h3>{_h(channel_labels.get(key, key))}</h3>'
        f'<p><b>调用：</b>{_h((value or {}).get("model_calls") or 0)} 次</p>'
        f'<p><b>Token：</b>{_h((value or {}).get("total_tokens") or 0)}</p>'
        f'<p><b>估算成本：</b>${_h((value or {}).get("estimated_usd") or 0)}</p>'
        '</article>'
        for key, value in (inference.get("channels") or {}).items()
    )
    quality = report.get("quality") or {}
    media_gallery = report.get("media_gallery") or {}
    restricted_media_notice = (
        '<p class="muted">为保护用户隐私，公开报告不展示原始视频、抽帧和补充图片；授权人员可在受控工单中回看原始证据。</p>'
        if media_gallery.get("restricted_original_evidence") else ""
    )
    evidence_package = report.get("evidence_package") or {}
    video_deduplication = evidence_package.get("video_deduplication") or {}
    official_reference_status = evidence_package.get("official_reference_status") or {}
    order_baseline = evidence_package.get("order_baseline") or {}
    order_rows = "".join(
        "<tr>"
        f"<td>{_h(item.get('item_ref') or '-')}</td>"
        f"<td>{_h(item.get('sku') or '-')}</td>"
        f"<td>{_h(item.get('product_name') or '-')}</td>"
        f"<td>{_h(item.get('specification') or '-')}</td>"
        f"<td>{_h(item.get('expected_quantity') or '-')}</td>"
        "</tr>"
        for item in order_baseline.get("expected_items") or []
        if isinstance(item, dict)
    )
    official_status_label = {
        "available": "可用",
        "partial": "部分可用",
        "unavailable": "不可用",
        "not_requested": "本单未提供",
    }.get(str(official_reference_status.get("status") or ""), "未提供")
    official_fallback = (
        "已回退到文字订单基线"
        if official_reference_status.get("fallback") == "text_order_baseline"
        else "无需降级"
    )
    scenario_label = report.get("scenario_label") or str(data.get("review_label") or "当前审核").split("/", 1)[0].strip()
    public_brief = report.get("public_brief") or {}
    conclusion = advisory_assessment.get("conclusion") or public_brief.get("conclusion") or safe_agent_conclusion(parsed, scenario_label)
    confidence = advisory_assessment.get("confidence")
    if confidence is None:
        confidence = overall.get("confidence") or parsed.get("confidence") or "-"
    core_reason = _safe_agent_reason(sop_recommendation.get("basis"))
    if not core_reason:
        core_reason = _safe_agent_reason(overall.get("core_reason") or parsed.get("confidence_reason"))
    if not core_reason:
        core_reason = parsed.get("visual_evidence_verdict") or visual.get("reason") or ""
    next_step = public_brief.get("next_step") or safe_agent_next_step(overall.get("business_follow_up_suggestion") or parsed.get("next_step"))
    workflow = str(advisory.get("workflow_recommendation") or "")
    is_minor_report = bool(parsed.get("minor_material_assessment"))
    if workflow == "request_more_material":
        next_step = (
            "只补交报告中明确标黄的缺失或看不清材料，补齐后可在同一工单继续审核。"
            if is_minor_report
            else "按报告中的材料缺口补充连续材料或其他缺失证据，材料齐备后重新送审。"
        )
    elif workflow == "human_review":
        next_step = human_review.get("recommendation") or next_step
    elif workflow == "system_retry":
        next_step = "当前请求已完成结构修复和逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型成本，且不要求用户补材料。"
    elif workflow == "continue_by_customer_policy" and human_level == "not_required":
        next_step = "按 SOP 审核倾向继续处理，本轮无需人工复审；具体业务动作由甲方系统执行。"
    elif workflow == "continue_by_customer_policy" and human_level == "optional":
        next_step = "按 SOP 审核倾向继续处理；仅按甲方抽检规则回看风险项，不要求逐单人工复审。"
    if failed:
        conclusion = data.get("conclusion") or conclusion
        core_reason = diagnostics.get("failure_reason") or "本轮审核没有完成，不能把该结果解释为业务证据不足。"
        next_step = diagnostics.get("operator_hint") or next_step
        confidence = "-"
    material_gaps = parsed.get("material_gaps") or []
    model_limitations = [
        "本报告只说明送审证据支持什么结论，不能替代甲方的退款、换货、补偿或拒绝决定。",
        "未接入的订单、仓库、物流或权威核验数据不会被假设为已核验。",
    ]
    if parsed.get("specialized_pass_warning"):
        model_limitations.append(str(parsed["specialized_pass_warning"]))
    confidence_reason = _safe_agent_reason(parsed.get("confidence_reason") or overall.get("core_reason") or core_reason)
    supporting_evidence = parsed.get("adopted_evidence") or parsed.get("supporting_evidence") or []
    challenging_evidence = parsed.get("challenging_evidence") or []
    risky_findings = _risky_frame_findings(parsed.get("frame_findings"))
    issue_timestamps = _issue_timestamp_items(parsed.get("issue_timestamps"))
    damage_causality_panel = render_damage_causality_panel(
        parsed.get("damage_causality_assessment"), media_gallery, _evidence_items, _h
    )
    object_continuity_panel = render_object_continuity_panel(
        parsed.get("object_continuity_assessment"), media_gallery, _evidence_items, _h
    )
    fulfillment_panel = render_fulfillment_reconciliation_panel(parsed.get("fulfillment_reconciliation"), _h)
    claim_fact_panel = render_claim_fact_panel(parsed.get("claim_fact_assessment"), _h)
    minor_material_panel = render_minor_material_panel(parsed.get("minor_material_assessment"), _h)
    confidence_components_panel = render_confidence_components_panel(parsed.get("confidence_components"), _h)
    decision_policy_panel = _decision_policy_panel(parsed.get("decision_policy_audit") or data.get("decision_policy_audit"))
    raw_gap_items = material_gaps if isinstance(material_gaps, list) else [material_gaps] if material_gaps else []
    gap_items = list(dict.fromkeys(
        text for item in raw_gap_items if len(text := str(item).strip()) >= 2
    ))
    gap_summary = "；".join(gap_items[:10]) or "本轮未发现需要用户补充的明确材料。"
    attention_tone = {
        "green": "green",
        "orange": "amber",
        "red": "red",
        "gray": "gray",
    }.get(str(evidence_attention.get("level") or ""), "amber")
    attention_panel = ""
    if evidence_attention:
        attention_panel = f"""
    <section class="summary-attention status-card status-{attention_tone}">
      <h3>客服证据优先级</h3>
      <p><b>{_h(evidence_attention.get("headline") or "请按证据优先级继续审核。")}</b></p>
      <div class="attention-grid">
        <article><h4>先看什么</h4>{_list_html(evidence_attention.get("customer_focus"), "本轮暂无额外关注项。")}</article>
        <article><h4>需要对齐的分歧</h4>{_list_html(evidence_attention.get("disagreements"), "本轮未发现需要对齐的证据分歧。")}</article>
        <article><h4>缺少的具体证据</h4>{_list_html(evidence_attention.get("missing_evidence"), "本轮未发现明确证据缺口。")}</article>
      </div>
    </section>"""
    advisory_panel = f"""
  <section class="panel advisory-panel decision-{_h(advisory_assessment.get('conclusion_code') or 'unknown')}">
    <div class="section-head"><h2>客服审核摘要</h2><p>按照 SOP 的审核倾向，先看建议，再决定是否展开技术细节。</p></div>
    <div class="causality-grid">
      <article><small>证据结论</small><b>{_h(advisory_assessment.get("conclusion") or conclusion)}</b></article>
      <article><small>SOP 处理建议</small><b>{_h(sop_recommendation.get("recommendation") or advisory_assessment.get("conclusion") or conclusion)}</b></article>
      <article><small>证据分数</small><b>{_h(advisory_assessment.get("confidence") if advisory_assessment.get("confidence") is not None else confidence)}</b></article>
      <article><small>人工复审</small><b>{_h(human_level_label)}</b></article>
      <article><small>流程</small><b>{_h(workflow_label)}</b></article>
    </div>
    <p class="muted">证据分数表示本轮证据充分程度，不是客观正确率。</p>
    {attention_panel}
    <div class="summary-reason"><h3>为什么这样建议</h3><p>{_h(core_reason or advisory_assessment.get("reason") or conclusion)}</p></div>
    <div class="summary-gaps"><h3>需要补什么</h3><p>{_h(gap_summary)}</p></div>
    <div class="human-action status-{_h({'required': 'red', 'optional': 'amber', 'not_required': 'green'}.get(human_level, 'amber'))}">
      <h3>客服下一步</h3><p>{_h(next_step)}</p>
      <p class="muted">建议进一步评估：{_h(human_review.get("recommendation") or "本轮没有额外人工复核重点。")}</p>
    </div>
    <h3>关键证据</h3>
    <div class="evidence-grid">{_evidence_items(list(supporting_evidence)[:6], media_gallery)}</div>
    <p><b>业务边界：</b>{_h(advisory_policy.get("boundary") or "本服务输出证据结论和 SOP 处理建议；具体业务动作由甲方系统执行，人工复审等级独立判断。")}</p>
    <details class="summary-signals"><summary>查看其他风险信号</summary><div class="boundary-grid">{signal_cards or '<p class="muted">本轮没有额外风险信号。</p>'}</div></details>
  </section>
"""
    conclusion_code = str(advisory_assessment.get("conclusion_code") or "")
    yes_no = "REVIEW" if failed else {
        "evidence_supports_claim": "YES",
        "evidence_does_not_support_claim": "NO",
        "evidence_inconclusive": "REVIEW",
    }.get(conclusion_code, _public_yes_no(parsed))
    tone = "gray" if failed else (
        attention_tone if evidence_attention else {
            "evidence_supports_claim": "green",
            "evidence_does_not_support_claim": "red",
            "evidence_inconclusive": "amber",
        }.get(conclusion_code, "amber")
    )
    report_class = "minor-report" if is_minor_report else "product-report"
    verdict_text = "未完成" if failed else {
        "evidence_supports_claim": "支持",
        "evidence_does_not_support_claim": "不支持",
        "evidence_inconclusive": "待确认",
    }.get(conclusion_code, yes_no)
    confidence_display = (
        f"{round(float(confidence) * 100)}%"
        if isinstance(confidence, (int, float))
        else confidence
    )
    if challenging_evidence or risky_findings:
        risk_panel = f"""
  <section class="panel risk-panel">
    <div class="section-head"><h2>反证与可疑帧</h2><p>红色内容会削弱当前结论，请优先回看原始图片或视频。</p></div>
    <div class="evidence-grid">{_evidence_items(challenging_evidence, media_gallery, "需复核") if challenging_evidence else ''}</div>
    <div class="evidence-grid">{_evidence_items(risky_findings, media_gallery, "风险画面") if risky_findings else ''}</div>
  </section>"""
    else:
        risk_panel = """
  <details class="panel risk-panel empty-panel">
    <summary>反证与可疑帧：未发现</summary>
    <p class="muted">本轮没有标记削弱当前结论的图片或视频画面。</p>
  </details>"""
    if issue_timestamps:
        issue_panel = f"""
  <section class="panel issue-panel">
    <div class="section-head"><h2>问题时间点</h2><p>点击证据卡可回看对应画面或原视频片段。</p></div>
    <div class="evidence-grid">{_evidence_items(issue_timestamps, media_gallery, "重点复核")}</div>
  </section>"""
    else:
        issue_panel = """
  <details class="panel issue-panel empty-panel video-only">
    <summary>问题时间点：未发现</summary>
    <p class="muted">本轮没有额外标记问题时间点。</p>
  </details>"""
    visual_verdict = ({
        "evidence_supports_claim": "五类材料与可见字段初审通过",
        "evidence_does_not_support_claim": "材料字段存在明确冲突",
        "evidence_inconclusive": "材料或可见字段仍待确认",
    } if is_minor_report else {
        "evidence_supports_claim": "证据支持本次事实诉求",
        "evidence_does_not_support_claim": "现有证据不支持本次事实诉求",
        "evidence_inconclusive": "证据不足，建议按流程补充或复核",
    }).get(conclusion_code, _public_verdict(parsed, scenario_label))
    if workflow == "request_more_material":
        visual_verdict = "需要补充缺失材料"
    latency = runtime.get("latency_seconds") or "-"
    video_count = len(evidence_package.get("videos") or [])
    def effective_sample_fps(item: Dict[str, Any]) -> Any:
        if item.get("effective_sample_fps") not in (None, ""):
            return item["effective_sample_fps"]
        duration = float(item.get("duration_seconds") or 0)
        return round(float(item.get("sampled_frames") or 0) / duration, 4) if duration > 0 else "-"

    sampling_rows = "".join(
        "<tr>"
        f"<td>视频 {_h(item.get('video_index') or '-')}</td>"
        f"<td>{_h(item.get('duration_seconds') or '-')}s</td>"
        f"<td>{_h(item.get('native_fps') or '-')}</td>"
        f"<td>{_h(item.get('fps_requested') or '-')}</td>"
        f"<td>{_h(item.get('sampled_frames') or '-')}</td>"
        f"<td>{_h(effective_sample_fps(item))}</td>"
        "</tr>"
        for item in evidence_package.get("videos") or []
    )
    video_metrics_html = ""
    video_density_html = ""
    video_proof_html = ""
    video_gallery_html = ""
    if video_count:
        video_metrics_html = f"""
      <div class="metric"><small>商品连续性分数</small><b>{_h(video.get("continuity_score") or "-")}</b></div>
      <div class="metric"><small>疑似调包风险</small><b>{_h(video.get("swap_risk_level") or "-")}</b></div>
      <div class="metric"><small>审核视频</small><b>{_h(video_count)}</b></div>
      <div class="metric"><small>查看画面</small><b>{_h(evidence_package.get("frames_sent") or "-")}</b></div>
      <div class="metric"><small>重复视频已跳过</small><b>{_h(video_deduplication.get("duplicate_count") or 0)}</b></div>"""
        video_density_html = f"""
    <section class="panel">
      <div class="section-head"><h2>视频查看密度</h2><p>这里说明系统每秒实际查看多少个画面。</p></div>
      <div class="table-wrap"><table><thead><tr><th>视频</th><th>时长</th><th>原视频每秒帧数</th><th>计划每秒查看</th><th>实际查看画面</th><th>实际每秒查看</th></tr></thead><tbody>{sampling_rows}</tbody></table></div>
    </section>"""
        continuity_label = {
            "continuous": "连续",
            "brief_occlusion": "短暂遮挡",
            "long_absence": "较长离镜",
            "indeterminate": "不确定",
        }.get(continuity_status, continuity_status or "未知")
        video_proof_html = f"""
  <section class="panel proof">
    <h2>视频审核论证</h2>
    <div class="causality-grid">
      <article><small>抽帧首尾覆盖</small><b>{_h({"covered": "已覆盖", "incomplete": "未完整覆盖", "unknown": "未知"}.get(video.get("sampling_boundary_status"), video.get("sampling_boundary_status") or "未知"))}</b></article>
      <article><small>媒体技术取证</small><b>{_h(_public_status((parsed.get("decision_policy_audit") or data.get("decision_policy_audit") or {}).get("evidence_gate", {}).get("media_forensics_status") or video.get("technical_timeline_status") or "未提供"))}</b></article>
      <article><small>开箱过程完整性</small><b>{_h({"complete": "完整", "incomplete": "不完整", "indeterminate": "不确定"}.get(video.get("opening_integrity"), video.get("opening_integrity") or "未知"))}</b></article>
      <article><small>商品证据连续性</small><b>{_h(continuity_label)}</b></article>
    </div>
    <p><b>口径说明：</b>视频时间轴完整不等于争议商品全程连续可见；抽帧覆盖、媒体技术取证、开箱过程和商品连续性是四个独立维度。</p>
    <p><b>画面节奏判断：{_h(visual_playback_speed)}</b>。这是模型对画面节奏的观察，不是精确倍速测量。</p>
    {speed_impact_html}
    {opening_compliance_html}
    <p><b>播放速度技术取证：</b></p><ul class="boundary-list">{playback_speed_evidence}</ul>
    <p><b>连续性：</b>{_h(video.get("continuity_reason") or video.get("reason") or "本轮没有输出明确连续性理由。")}</p>
    <p><b>剪辑/调包风险：</b>{_h(video.get("edit_or_cut_risk") or "-")} / {_h(video.get("swap_risk_level") or "-")}</p>
  </section>"""
    if media_gallery.get("frames"):
        video_gallery_html = f"""
    <h3>视频画面</h3>
    <div class="media-grid">{_gallery_items(media_gallery.get("frames") or [], "视频帧")}</div>"""
    diagnostic_panel = ""
    if failed:
        diagnostic_panel = (
            '<section class="panel failure-panel">'
            '<h2>本轮失败诊断</h2>'
            f'<p><b>失败阶段：</b>{_h(diagnostics.get("failure_stage") or "-")}</p>'
            f'<p><b>失败原因：</b>{_h(diagnostics.get("failure_reason") or core_reason)}</p>'
            f'<p><b>客服动作：</b>{_h(next_step)}</p>'
            "</section>"
        )
    internal_metrics_html = ""
    if inference:
        estimated_cost = f"${inference.get('estimated_usd')}" if inference.get("estimated_usd") not in (None, "") else "-"
        internal_metrics_html = f"""
      <div class="metric"><small>估算 Token</small><b>{_h(inference.get('total_tokens') or '-')}</b></div>
      <div class="metric"><small>估算成本</small><b>{_h(estimated_cost)}</b></div>
      <div class="metric"><small>识别次数</small><b>{_h(inference.get('segment_count') or 1)}</b></div>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_h(scenario_label)} Agent 报告</title>
  <style>{_REPORT_CSS}</style>
</head>
<body class="{report_class}">
<main class="shell">
  <section class="hero tone-{tone}">
    <div>
      <span class="badge">{_h(scenario_label)} Agent 报告</span>
      <h1>{_h(conclusion)}</h1>
      <p class="lead">{_h(core_reason or "审核Agent已完成视觉证据整理，请结合下方证据链复核。")}</p>
    </div>
    <aside class="verdict-card">
      <small>审核建议</small>
      <b>{_h(verdict_text)}</b>
      <span>证据分数 {_h(confidence_display)}</span>
    </aside>
  </section>

  {advisory_panel}

	<details class="panel technical-details">
	  <summary>展开完整技术分析</summary>
	  <div class="technical-details-body">
	  <section class="metrics">
		    <div class="metric hot"><small>视觉质检</small><b>{_h("审核未完成" if failed else visual_verdict)}</b></div>
	    {video_metrics_html}
	    <div class="metric"><small>本次审核用时</small><b>{_h(latency)} 秒</b></div>
	    <div class="metric"><small>补充图片</small><b>{_h(evidence_package.get("supplemental_images_sent") or "-")}</b></div>
	    <div class="metric product-only"><small>官方参考图</small><b>{_h(evidence_package.get("official_reference_images_sent") or "-")}</b></div>
	    {internal_metrics_html}
		    <div class="metric"><small>报告用途</small><b>客服审核建议</b></div>
		  </section>
		  <details class="panel inference-channels-panel" {'open' if inference else 'hidden'}>
			    <summary>系统处理明细</summary>
		    <p><b>本次总用时：</b>{_h(runtime.get("latency_seconds") or "-")} 秒；<b>各次识别累计用时：</b>{_h(runtime.get("model_latency_seconds_sum") or "-")} 秒（并行任务会重叠）。</p>
		    <div class="boundary-grid">{channel_cards or '<p class="muted">本轮没有分通道统计。</p>'}</div>
		  </details>
		  {video_density_html}
	  {diagnostic_panel}

	  <section class="panel">
	    <div class="section-head"><h2>审核Agent采信的证据</h2><p>每张图都可以在本页放大查看；带时间点的帧可以直接预览原视频片段。</p></div>
	    <div class="evidence-grid">{_evidence_items(supporting_evidence, media_gallery)}</div>
	  </section>

  {risk_panel}
  {issue_panel}

  {video_proof_html}
  {decision_policy_panel}

	  <section class="panel boundary-panel">
	    <div class="section-head"><h2>置信度与已知边界</h2><p>帮助VIP客服理解分数依据、缺失材料和本轮视觉判断无法覆盖的范围。</p></div>
	    <div class="boundary-grid">
	      <article class="boundary-card"><h3>置信度理由</h3><p>{_h(confidence_reason or "本轮没有输出明确的置信度理由，请结合证据卡片理解结论。")}</p></article>
	      <article class="boundary-card"><h3>材料缺口</h3>{_list_html(material_gaps, "本轮未声明额外材料缺口；" + ("最终退款决定仍由授权人员按 SOP 执行。" if is_minor_report else "最终处置仍需核对订单、库存和售后规则。"))}</article>
	      <article class="boundary-card"><h3>模型局限</h3>{_list_html(model_limitations, "本轮未单独声明模型局限；报告结论仍仅作为VIP客服复核参考。")}</article>
	    </div>
	  </section>

    {minor_material_panel}
    {confidence_components_panel}
    {damage_causality_panel}
  {object_continuity_panel}
  {fulfillment_panel}
  {claim_fact_panel}

  <section class="panel product-only">
    <div class="section-head"><h2>系统订单基线</h2><p>这里展示服务实际送审的受信任订单字段，不依赖模型复述。</p></div>
    <p><b>基线版本：</b>{_h(order_baseline.get("baseline_version") or "未提供")}；<b>承运商：</b>{_h(order_baseline.get("carrier") or "未提供")}；<b>物流引用：</b>{_h(order_baseline.get("tracking_ref") or "未提供")}</p>
    <p><b>抽赏规则：</b>{_h("完整" if order_baseline.get("selection_rules_complete") else "不完整或待确认")}；<b>赠品/特典规则：</b>{_h("完整" if order_baseline.get("benefit_rules_complete") else "不完整或待确认")}；<b>分包映射：</b>{_h(order_baseline.get("package_mapping_status") or "未提供")}</p>
    <div class="table-wrap"><table><thead><tr><th>行项目</th><th>SKU</th><th>商品</th><th>规格</th><th>应发数量</th></tr></thead><tbody>{order_rows or '<tr><td colspan="5">本轮未提供订单商品基线。</td></tr>'}</tbody></table></div>
  </section>

  <section class="panel boundary-panel product-only">
    <div class="section-head"><h2>官方商品参考图</h2><p>仅作为订单商品标准外观基准，不属于用户提交证据，也不能单独证明实际收货、漏发或损伤。</p></div>
    <p><b>读取状态：</b>{_h(official_status_label)}；请求 {_h(official_reference_status.get("requested_count") or 0)} 张，可用 {_h(official_reference_status.get("available_count") or 0)} 张，失败 {_h(official_reference_status.get("failed_count") or 0)} 张；{_h(official_fallback)}。</p>
    <div class="media-grid">{_gallery_items(media_gallery.get("official_references") or [], "官方商品参考图")}</div>
  </section>

  <section class="panel">
    <div class="section-head"><h2>送审证据画廊</h2><p>用于快速复核审核Agent看到的帧图和用户补充图片。</p></div>
    {restricted_media_notice}
    {video_gallery_html}
    <h3>补充图片</h3>
    <div class="media-grid">{_gallery_items(media_gallery.get("images") or [], "补充图片")}</div>
	  </section>
	  </div>
	</details>
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
.hero.tone-green::after { background:#2eaf5d; }
.hero.tone-amber::after { background:#f0a31a; }
.hero.tone-red::after { background:#df4b4b; }
.hero.tone-gray::after { background:#6b7280; }
.hero.tone-green .verdict-card { background:#e9f8ee; border-color:#78c895; }
.hero.tone-amber .verdict-card { background:#fff5d9; border-color:#e8bd59; }
.hero.tone-red .verdict-card { background:#fff0f0; border-color:#e29292; }
.hero.tone-gray .verdict-card { background:#f1f3f5; border-color:#aeb4bd; }
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
	.failure-panel { background:linear-gradient(135deg,#fff2e7,#fff 74%); border-color:rgba(255,138,31,.35); }
.technical-details > summary, .summary-signals > summary {
  cursor:pointer;
  font-weight:900;
  list-style-position:inside;
}
.technical-details-body { margin-top:16px; }
.technical-details-body > .panel { box-shadow:none; border-color:var(--line); }
.summary-attention, .summary-reason, .summary-gaps, .human-action { margin-top:12px; padding:14px; border-radius:8px; background:#f7faef; }
.summary-attention h3, .summary-reason h3, .summary-gaps h3, .human-action h3 { margin-top:0; }
.attention-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }
.attention-grid article { min-width:0; }
.attention-grid h4 { margin:0 0 8px; }
.summary-signals { margin-top:14px; }
.metrics {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:12px;
  margin-top:16px;
}
.causality-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:10px;
  margin:14px 0;
}
.causality-grid article {
  min-width:0;
  padding:14px;
  border:1px solid var(--line);
  border-radius:8px;
  background:#f8fff0;
}
.causality-grid small { display:block; color:var(--muted); margin-bottom:7px; }
.causality-grid b { display:block; overflow-wrap:anywhere; }
.causality-panel { border-left:5px solid var(--cyan); }
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
.evidence-card .evidence-impact {
  display:grid;
  gap:3px;
  padding:9px 10px;
  border-left:4px solid var(--cyan);
  border-radius:8px;
  background:#effcf9;
  color:var(--ink-2);
}
.evidence-impact strong { font-size:12px; }
.evidence-card b {
  display:inline-flex;
  padding:5px 9px;
  border-radius:999px;
  background:linear-gradient(90deg,var(--lime),var(--gold));
  font-size:12px;
}
.risk-panel { border-top:4px solid #d76543; background:#fffaf7; }
.issue-panel { border-top:4px solid var(--cyan); background:#f7fcfd; }
.boundary-panel { border-top:4px solid #75a43a; background:#fbfdf8; }
.boundary-grid {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
  gap:12px;
}
.boundary-card {
  min-width:0;
  padding:16px;
  border:1px solid var(--line);
  border-radius:8px;
  background:#fff;
}
.boundary-card h3 { margin-top:0; }
.boundary-card p { margin:0; overflow-wrap:anywhere; }
.status-card { border-left:6px solid #d3d8df; }
.status-green { border-left-color:#2eaf5d; background:#f2fbf5; }
.status-amber { border-left-color:#f0a31a; background:#fffaf0; }
.status-red { border-left-color:#df4b4b; background:#fff5f5; }
.status-gray { border-left-color:#6b7280; background:#f4f5f6; }
.evidence-link {
  display:inline-flex;
  margin:2px 4px 2px 0;
  padding:4px 8px;
  border:1px solid #9bc7bd;
  border-radius:6px;
  color:#11665b;
  font-weight:800;
  text-decoration:none;
}
.evidence-link:hover, .evidence-link:focus-visible { background:#e8f8f4; outline:2px solid #12a895; outline-offset:2px; }
.human-action { margin-top:16px; padding:18px; border:1px solid var(--line); border-left-width:8px; border-radius:8px; }
.human-action h3 { margin:0 0 6px; }
.human-action p { margin:0; font-size:17px; font-weight:750; }
.empty-panel summary, .inference-channels-panel summary { cursor:pointer; font-size:18px; font-weight:900; }
.inference-channels-panel summary { margin-bottom:12px; }
.minor-report .video-only, .minor-report .product-only { display:none !important; }
.boundary-list { margin:0; padding-left:20px; }
.boundary-list li { margin:7px 0; line-height:1.65; overflow-wrap:anywhere; }
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
  .shell { width:calc(100% - 20px); max-width:370px; margin-inline:auto; }
}
"""
