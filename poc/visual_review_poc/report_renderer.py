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
    return f"证据不足，需要VIP客服复核，置信度 {confidence}。"


def safe_agent_next_step(text: Any) -> str:
    if _has_business_action(text):
        return "将视觉证据摘要提交VIP客服复核；由客服系统结合订单、售后政策和库存记录决定后续业务动作。"
    return str(text or "请VIP客服结合订单、售后规则和原始素材处理。")


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
    return "需要VIP客服复核"


def _public_yes_no(parsed: Dict[str, Any]) -> str:
    value = str(parsed.get("system_yes_no") or parsed.get("predicted_label") or "").lower()
    if value in {"yes", "y", "positive", "support"}:
        return "YES"
    if value in {"no", "n", "negative", "reject"}:
        return "NO"
    return "REVIEW"


def _decision_policy_panel(value: Any) -> str:
    if not isinstance(value, dict) or not value:
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
    <div class="section-head"><h2>版本化规则判定说明</h2><p>规则只生成分类建议，不自动拒绝、退款、补发、换货或定责。</p></div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>策略与结果</h3><p><b>{_h(value.get("policy_ref") or "未提供策略版本")}</b></p><p>{_h("已命中规则" if value.get("applied") else "未命中规则，保持复核")}</p><p>{_h(value.get("reason") or "")}</p></article>
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
    runtime = report.get("runtime") or {}
    inference = report.get("inference_estimate") or {}
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
    evidence_package = report.get("evidence_package") or {}
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
    conclusion = public_brief.get("conclusion") or safe_agent_conclusion(parsed, scenario_label)
    confidence = overall.get("confidence") or parsed.get("confidence") or "-"
    core_reason = _safe_agent_reason(overall.get("core_reason") or parsed.get("confidence_reason") or "")
    if not core_reason:
        core_reason = parsed.get("visual_evidence_verdict") or visual.get("reason") or ""
    next_step = public_brief.get("next_step") or safe_agent_next_step(overall.get("business_follow_up_suggestion") or parsed.get("next_step"))
    if failed:
        conclusion = data.get("conclusion") or conclusion
        core_reason = diagnostics.get("failure_reason") or "本轮审核没有完成，不能把该结果解释为业务证据不足。"
        next_step = diagnostics.get("operator_hint") or next_step
        confidence = "-"
    material_gaps = parsed.get("material_gaps") or []
    model_limitations = parsed.get("model_limitations") or []
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
    minor_material_panel = render_minor_material_panel(parsed.get("minor_material_assessment"), _h)
    confidence_components_panel = render_confidence_components_panel(parsed.get("confidence_components"), _h)
    decision_policy_panel = _decision_policy_panel(parsed.get("decision_policy_audit") or data.get("decision_policy_audit"))
    yes_no = "REVIEW" if failed else _public_yes_no(parsed)
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
      <p class="lead">{_h(core_reason or "审核Agent已完成视觉证据整理，请结合下方证据链复核。")}</p>
    </div>
    <aside class="verdict-card">
      <small>系统参考</small>
      <b>{_h(yes_no)}</b>
      <span>置信度 {_h(confidence)}</span>
    </aside>
  </section>

  <section class="panel next-step">
    <h2>给VIP客服的下一步</h2>
    <p>{_h(next_step)}</p>
  </section>

	  <section class="metrics">
		    <div class="metric hot"><small>视觉质检</small><b>{_h("审核未完成" if failed else _public_verdict(parsed, scenario_label))}</b></div>
	    <div class="metric"><small>连续性分数</small><b>{_h(video.get("continuity_score") or "-")}</b></div>
	    <div class="metric"><small>调包风险</small><b>{_h(video.get("swap_risk_level") or "-")}</b></div>
	    <div class="metric"><small>耗时</small><b>{_h(latency)}s</b></div>
	    <div class="metric"><small>送审视频</small><b>{_h(video_count or "-")}</b></div>
	    <div class="metric"><small>送审帧数</small><b>{_h(evidence_package.get("frames_sent") or "-")}</b></div>
	    <div class="metric"><small>补充图片</small><b>{_h(evidence_package.get("supplemental_images_sent") or "-")}</b></div>
	    <div class="metric"><small>官方参考图</small><b>{_h(evidence_package.get("official_reference_images_sent") or "-")}</b></div>
	    <div class="metric"><small>估算 Token</small><b>{_h(inference.get("total_tokens") or "-")}</b></div>
	    <div class="metric"><small>估算成本</small><b>{_h((f"${inference.get('estimated_usd')}" if inference.get("estimated_usd") not in (None, "") else "-"))}</b></div>
		    <div class="metric"><small>模型调用</small><b>{_h(inference.get("segment_count") or 1)}</b></div>
		    <div class="metric"><small>报告属性</small><b>VIP客服复核参考</b></div>
		  </section>
		  <section class="panel inference-channels-panel">
			    <div class="section-head"><h2>分通道调用统计</h2><p>墙钟耗时与累计模型耗时分开统计；成本与 Token 包含所有模型调用。</p></div>
		    <p><b>墙钟耗时：</b>{_h(runtime.get("latency_seconds") or "-")} 秒；<b>累计模型耗时：</b>{_h(runtime.get("model_latency_seconds_sum") or "-")} 秒。</p>
		    <div class="boundary-grid">{channel_cards or '<p class="muted">本轮没有分通道统计。</p>'}</div>
		  </section>
		  <section class="panel">
		    <div class="section-head"><h2>视频抽帧强度</h2><p>请求 FPS 是审核策略；有效抽样 FPS 按实际帧数/源视频时长计算。</p></div>
		    <div class="table-wrap"><table><thead><tr><th>视频</th><th>时长</th><th>原生 FPS</th><th>请求 FPS</th><th>实际帧数</th><th>有效抽样 FPS</th></tr></thead><tbody>{sampling_rows or '<tr><td colspan="6">本轮没有视频。</td></tr>'}</tbody></table></div>
		  </section>
	  {diagnostic_panel}

			  <section class="panel">
	    <div class="section-head"><h2>审核Agent采信的证据</h2><p>每张图都可以在本页放大查看；带时间点的帧可以直接预览原视频片段。</p></div>
	    <div class="evidence-grid">{_evidence_items(supporting_evidence, media_gallery)}</div>
	  </section>

	  <section class="panel risk-panel">
	    <div class="section-head"><h2>反证与可疑帧</h2><p>这里集中展示削弱当前结论的证据，以及逐帧审查中被标记为风险的画面。</p></div>
	    <h3>反证与风险证据</h3>
	    <div class="evidence-grid">{_evidence_items(challenging_evidence, media_gallery, "需复核") if challenging_evidence else '<p class="muted">本轮没有输出明确反证。</p>'}</div>
	    <h3>可疑帧</h3>
	    <div class="evidence-grid">{_evidence_items(risky_findings, media_gallery, "风险帧") if risky_findings else '<p class="muted">逐帧结果未标记额外可疑帧。</p>'}</div>
	  </section>

	  <section class="panel issue-panel">
	    <div class="section-head"><h2>问题时间点</h2><p>来自 issue_timestamps 的重点复核位置，可按时间戳回链抽帧和原视频。</p></div>
	    <div class="evidence-grid">{_evidence_items(issue_timestamps, media_gallery, "重点复核") if issue_timestamps else '<p class="muted">本轮没有标记问题时间点。</p>'}</div>
	  </section>

  <section class="panel proof">
    <h2>视频审核论证</h2>
    <div class="causality-grid">
      <article><small>抽帧首尾覆盖</small><b>{_h({"covered": "已覆盖", "incomplete": "未完整覆盖", "unknown": "未知"}.get(video.get("sampling_boundary_status"), video.get("sampling_boundary_status") or "未知"))}</b></article>
      <article><small>媒体技术取证</small><b>{_h((parsed.get("decision_policy_audit") or data.get("decision_policy_audit") or {}).get("evidence_gate", {}).get("media_forensics_status") or video.get("technical_timeline_status") or "未提供")}</b></article>
      <article><small>开箱过程完整性</small><b>{_h({"complete": "完整", "incomplete": "不完整", "indeterminate": "不确定"}.get(video.get("opening_integrity"), video.get("opening_integrity") or "未知"))}</b></article>
      <article><small>商品证据连续性</small><b>{_h({"continuous": "连续", "brief_occlusion": "短暂遮挡", "long_absence": "较长离镜", "indeterminate": "不确定"}.get(video.get("evidence_continuity_status"), video.get("evidence_continuity_status") or "未知"))}</b></article>
    </div>
    <p><b>连续性：</b>{_h(video.get("continuity_reason") or video.get("reason") or "本轮没有输出明确连续性理由。")}</p>
    <p><b>剪辑/调包风险：</b>{_h(video.get("edit_or_cut_risk") or "-")} / {_h(video.get("swap_risk_level") or "-")}</p>
  </section>
  {decision_policy_panel}

	  <section class="panel boundary-panel">
	    <div class="section-head"><h2>置信度与已知边界</h2><p>帮助VIP客服理解分数依据、缺失材料和本轮视觉判断无法覆盖的范围。</p></div>
	    <div class="boundary-grid">
	      <article class="boundary-card"><h3>置信度理由</h3><p>{_h(confidence_reason or "本轮没有输出明确的置信度理由，需结合证据卡片人工复核。")}</p></article>
	      <article class="boundary-card"><h3>材料缺口</h3>{_list_html(material_gaps, "本轮未声明额外材料缺口；最终处置仍需核对订单、库存和售后规则。")}</article>
	      <article class="boundary-card"><h3>模型局限</h3>{_list_html(model_limitations, "本轮未单独声明模型局限；报告结论仍仅作为VIP客服复核参考。")}</article>
	    </div>
	  </section>

    {minor_material_panel}
    {confidence_components_panel}
    {damage_causality_panel}
  {object_continuity_panel}
  {fulfillment_panel}

  <section class="panel">
    <div class="section-head"><h2>系统订单基线</h2><p>这里展示服务实际送审的受信任订单字段，不依赖模型复述。</p></div>
    <p><b>基线版本：</b>{_h(order_baseline.get("baseline_version") or "未提供")}；<b>承运商：</b>{_h(order_baseline.get("carrier") or "未提供")}；<b>物流引用：</b>{_h(order_baseline.get("tracking_ref") or "未提供")}</p>
    <p><b>抽赏规则：</b>{_h("完整" if order_baseline.get("selection_rules_complete") else "不完整或待确认")}；<b>赠品/特典规则：</b>{_h("完整" if order_baseline.get("benefit_rules_complete") else "不完整或待确认")}；<b>分包映射：</b>{_h(order_baseline.get("package_mapping_status") or "未提供")}</p>
    <div class="table-wrap"><table><thead><tr><th>行项目</th><th>SKU</th><th>商品</th><th>规格</th><th>应发数量</th></tr></thead><tbody>{order_rows or '<tr><td colspan="5">本轮未提供订单商品基线。</td></tr>'}</tbody></table></div>
  </section>

  <section class="panel boundary-panel">
    <div class="section-head"><h2>官方商品参考图</h2><p>仅作为订单商品标准外观基准，不属于用户提交证据，也不能单独证明实际收货、漏发或损伤。</p></div>
    <p><b>读取状态：</b>{_h(official_status_label)}；请求 {_h(official_reference_status.get("requested_count") or 0)} 张，可用 {_h(official_reference_status.get("available_count") or 0)} 张，失败 {_h(official_reference_status.get("failed_count") or 0)} 张；{_h(official_fallback)}。</p>
    <div class="media-grid">{_gallery_items(media_gallery.get("official_references") or [], "官方商品参考图")}</div>
  </section>

			  <section class="panel">
    <div class="section-head"><h2>送审证据画廊</h2><p>用于快速复核审核Agent看到的帧图和用户补充图片。</p></div>
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
	.failure-panel { background:linear-gradient(135deg,#fff2e7,#fff 74%); border-color:rgba(255,138,31,.35); }
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
  .shell { width:min(370px, calc(100vw - 20px)); max-width:none; margin-left:10px; margin-right:10px; }
}
"""
