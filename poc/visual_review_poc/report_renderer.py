# -*- coding: utf-8 -*-
"""视觉审核工作台的客服可读报告渲染。"""
from __future__ import annotations

import re
from typing import Any, Dict

from poc.visual_review_poc.report_assessment_sections import (
    render_confidence_components_panel,
    render_damage_causality_panel,
    render_fulfillment_reconciliation_panel,
    render_claim_fact_panel,
    render_minor_material_panel,
    render_object_continuity_panel,
)
from poc.visual_review_poc.report_assets import (
    LIGHTBOX_HTML as _LIGHTBOX_HTML,
    REPORT_CSS as _REPORT_CSS,
)
from poc.visual_review_poc.report_evidence import (
    _evidence_items,
    _gallery_items,
    _h,
    _issue_timestamp_items,
    _list_html,
    _merge_evidence_items,
    _readable_fact,
    _risky_frame_findings,
    _summary_evidence_items,
    _timestamp_key,
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
    "customer_risk_context": "抽检优先级提示",
}
RETIRED_SIGNAL_CODES = {
    "minor_payment_process_evidence_gap",
    "minor_low_age_process_verified",
}


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
    score = f"，证据分数 {confidence}" if confidence not in (None, "", "-") else ""
    if label == "positive":
        return f"视觉证据支持{clean_label}诉求{score}。"
    if label == "negative":
        return f"视觉证据暂不支持用户诉求{score}。"
    return f"本轮未形成明确事实倾向{score}。"


def safe_agent_next_step(text: Any) -> str:
    if _has_business_action(text):
        return "将视觉证据摘要提交VIP客服复核；由客服系统结合订单、售后政策和库存记录决定后续业务动作。"
    return str(text or "请结合本页证据、订单资料和适用 SOP 继续处理。")


def _safe_agent_reason(text: Any) -> str:
    raw_text = (_readable_fact(text) if isinstance(text, (dict, list, tuple)) else str(text or "")).strip()
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
        "partial": "部分完成",
        "failed": "处理失败",
        "pending": "等待处理",
        "processing": "处理中",
        "not_assessed": "未评估",
        "unavailable": "本轮不可用",
        "not_provided": "未提供",
        "未提供": "未提供",
        "requires_media_forensics": "需要结合媒体技术取证",
        "ffprobe_not_available": "媒体取证工具不可用",
    }.get(str(value or "").strip().lower(), "待确认")


def _public_risk(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "none": "未发现",
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "待确认",
        "indeterminate": "待确认",
        "not_assessed": "未评估",
    }.get(normalized, str(value or "未评估"))


def _decision_policy_panel(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    if str(value.get("reason") or "").startswith("未启用商品有伤规则"):
        return ""
    labels = {
        "opening_complete": "开箱过程未被确认完整",
        "sampling_boundary_covered": "抽帧未覆盖源视频首尾边界",
        "continuity_gate": "关键开箱链连续性尚未确认",
        "damage_not_visible": "主视频尚不能明确支持“未见主诉损伤”",
        "claim_not_supported": "主视频尚不能明确判定诉求不受支持",
        "visibility_coverage": "争议商品在有效展示窗口内未被充分观察",
        "model_confidence": "当前证据确定性不足",
        "claimed_item_absence_within_limit": "有效展示窗口内存在未解决的离镜",
        "effective_display_window_continuity": "有效展示窗口内存在未解决的离镜",
        "damage_observability": "主诉部位尚未被清楚观察",
        "media_forensics": "媒体技术取证未完成，或发现需要复核的异常",
        "supplemental_evidence_resolved": "补充证据关联尚未解决，不能忽略或自动判负",
    }
    failed = [
        labels.get(str(code), str(code))
        for code in value.get("failed_conditions") or []
    ]
    failed_html = "".join(f"<li>{_h(item)}</li>" for item in failed) or "<li>本轮规则已命中或未声明失败条件。</li>"
    gate = value.get("evidence_gate") or {}
    evidence_text = (
        f"争议商品最长离镜 {_h(gate.get('claimed_item_longest_out_of_frame_seconds') if gate.get('claimed_item_longest_out_of_frame_seconds') is not None else '-')} 秒；"
        f"有效展示窗口连续性 {'待复核' if gate.get('unresolved_effective_display_gap') is True else '未发现未解决缺口'}；"
        f"媒体取证 {_h(gate.get('media_forensics_status') or '未提供')}。"
    )
    return f"""
  <section class="panel boundary-panel">
    <div class="section-head"><h2>SOP 规则判定说明</h2><p>规则只生成审核倾向，不自动拒绝、退款、补发、换货或定责。</p></div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>规则结果</h3><p><b>{_h("已按 SOP 形成审核倾向" if value.get("applied") else "当前条件不足，保持复核")}</b></p><p>{_h(value.get("reason") or "")}</p></article>
      <article class="boundary-card"><h3>未通过的门槛</h3><ul class="boundary-list">{failed_html}</ul></article>
    </div>
    <p><b>关键依据：</b>{evidence_text}</p>
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


def _confidence_display(value: Any) -> Any:
    if value in (None, "", "-"):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return value
    if 0 <= number <= 1:
        return f"{round(number * 100)}%"
    return f"{number:g}"


def _same_readable_text(first: Any, second: Any) -> bool:
    def normalized(value: Any) -> str:
        return re.sub(r"[\s，。；：、,.!！?？:;]+", "", str(value or ""))

    left = normalized(first)
    return bool(left) and left == normalized(second)


def _material_readiness_html(value: Any, scenario: str) -> tuple[str, str]:
    if not isinstance(value, dict) or not value:
        return "", ""
    scene_labels = {
        "product_damage": "商品有伤",
        "wrong_item": "发错货",
        "missing_item": "漏发货",
        "minor_refund": "未成年人退款",
        "minor_material": "未成年人退款",
    }
    scene_label = scene_labels.get(str(value.get("scenario") or scenario), "当前审核")
    title = f"当前{scene_label}场景下的用户材料是否齐全"
    status = str(value.get("status") or "indeterminate")
    status_label = {
        "complete": "齐全",
        "incomplete": "不齐全",
        "indeterminate": "待确认",
        "not_required": "无需用户补充",
    }.get(status, "待确认")
    status_class = {
        "complete": "green",
        "incomplete": "red",
        "indeterminate": "amber",
        "not_required": "green",
    }.get(status, "amber")
    confidence = _confidence_display(value.get("confidence"))
    confidence_text = (
        f"材料状态确定性 {_h(confidence)}" if confidence not in (None, "", "-") else ""
    )
    summary = (
        f'<article class="material-readiness-summary status-{status_class}">'
        f'<small>{_h(title)}</small><b>{_h(status_label)}</b>'
        f'<span>{confidence_text}</span></article>'
    )
    status_labels = {
        "present": "已具备",
        "missing": "缺少",
        "invalid": "已有但不可用",
        "unknown": "待确认",
    }
    rows = "".join(
        "<tr>"
        f'<td>{_h(item.get("label") or "未命名材料")}</td>'
        f'<td>{_h("必需" if item.get("required") is True else "辅助")}</td>'
        f'<td>{_h(status_labels.get(str(item.get("status") or ""), "待确认"))}</td>'
        f'<td>{_h(item.get("reason") or "-")}</td>'
        "</tr>"
        for item in value.get("checklist") or []
        if isinstance(item, dict)
    )
    inventory = value.get("review_inventory") or {}
    counts = inventory.get("media_counts") or {}
    inventory_text = (
        f"系统收到 {int(inventory.get('received_asset_count') or 0)} 份文件："
        f"视频 {int(counts.get('video') or 0)}、图片 {int(counts.get('image') or 0)}、"
        f"文档 {int(counts.get('document') or 0)}。"
        if inventory else ""
    )
    warning = "；".join(
        str(item).strip() for item in value.get("warnings") or [] if str(item).strip()
    )
    detail = f"""
    <details class="material-readiness-details status-card status-{status_class}">
      <summary>{_h(title)}：{_h(status_label)}</summary>
      <p>{_h(value.get("reason") or "本轮尚未形成材料齐全性判断。")}</p>
      {f'<p class="fine-print">{_h(inventory_text)}</p>' if inventory_text else ''}
      <div class="table-wrap"><table><thead><tr><th>材料要求</th><th>级别</th><th>状态</th><th>说明</th></tr></thead><tbody>{rows or '<tr><td colspan="4">本轮没有可展示的材料检查项。</td></tr>'}</tbody></table></div>
      {f'<p class="fine-print">{_h(warning)}</p>' if warning else ''}
    </details>"""
    return summary, detail


def _media_preflight_execution_html(value: Any) -> str:
    """把媒体送审执行事实翻译成客服可读小字，不渲染原始枚举或 JSON。"""
    if not isinstance(value, dict) or not value:
        return ""
    videos = [item for item in value.get("videos") or [] if isinstance(item, dict)]
    legacy_video = value.get("video") if isinstance(value.get("video"), dict) else {}
    if not videos and legacy_video:
        videos = [legacy_video]
    images = value.get("images") if isinstance(value.get("images"), dict) else {}
    fallback = value.get("frame_fallback") if isinstance(value.get("frame_fallback"), dict) else {}
    facts = []
    for position, video in enumerate(videos, start=1):
        source_label = "保真代理" if video.get("submitted_source") == "quality_proxy" else "原始视频"
        delivery_label = {
            "file_uri": "HTTPS 地址",
            "https_url": "HTTPS 地址",
            "inline_data": "内联上传",
        }.get(str(video.get("delivery") or ""), "系统上传链路")
        prefix = f"视频 {position}" if len(videos) > 1 else "视频"
        video_fact = f"{prefix}：使用{source_label}，通过{delivery_label}送审"
        if video.get("native_sampling_fps") not in (None, ""):
            video_fact += f"，模型按 {float(video['native_sampling_fps']):g} 帧/秒理解完整时长"
        dimensions = (
            video.get("source_width"), video.get("source_height"),
            video.get("submitted_width"), video.get("submitted_height"),
        )
        if all(item not in (None, "") for item in dimensions):
            video_fact += (
                f"，画面由 {_h(dimensions[0])}×{_h(dimensions[1])} 保真处理为 "
                f"{_h(dimensions[2])}×{_h(dimensions[3])}"
            )
        facts.append(video_fact + "。")
    prepared_count = int(images.get("prepared_count") or 0)
    failed_count = int(images.get("failed_count") or 0)
    if prepared_count:
        facts.append(
            f"图片：{prepared_count} 张图片逐张 WebP 送审，最长边不超过 "
            f"{_h(images.get('max_long_edge') or 1920)} 像素，未拼接大图。"
        )
    if failed_count:
        facts.append(f"图片：另有 {failed_count} 张未能安全解码，未送入模型。")
    if fallback.get("used"):
        facts.append(
            f"补充复核：原片未完整建立目标身份或有效展示窗口，已按 "
            f"{_h(fallback.get('sampling_fps') or 1)} 帧/秒逐张 WebP 回看 "
            f"{_h(fallback.get('frame_count') or 0)} 帧。"
        )
    elif videos:
        facts.append("补充复核：本轮没有触发解帧回退。")
    if not facts:
        return ""
    return (
        '<section class="panel media-preflight-panel">'
        '<div class="section-head"><h2>送审前媒体处理</h2>'
        '<p>这里只展示本轮实际执行结果，不展示内部地址或调试参数。</p></div>'
        f'<ul class="boundary-list">{"".join(f"<li>{fact}</li>" for fact in facts)}</ul>'
        '</section>'
    )


def _review_media_comparison_html(media_gallery: Any) -> str:
    """仅在存在转码衍生片时提供原片与模型实际送审版的人工对照。"""
    if not isinstance(media_gallery, dict):
        return ""

    def file_size(value: Any) -> str:
        try:
            size = max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return "-"
        if size >= 1024 ** 3:
            return f"{size / (1024 ** 3):.2f} GB"
        if size >= 1024 ** 2:
            return f"{size / (1024 ** 2):.1f} MB"
        return f"{size / 1024:.1f} KB"

    rows = []
    for video in media_gallery.get("videos") or []:
        if not isinstance(video, dict) or video.get("comparison_available") is not True:
            continue
        original_url = str(video.get("original_url") or "")
        review_url = str(video.get("review_url") or "")
        if not original_url or not review_url:
            continue
        derivative = video.get("review_derivative") if isinstance(video.get("review_derivative"), dict) else {}
        transform = derivative.get("transformation") if isinstance(derivative.get("transformation"), dict) else {}
        source_dimensions = (
            f"{transform.get('source_width')}×{transform.get('source_height')}"
            if transform.get("source_width") and transform.get("source_height") else "-"
        )
        review_width = transform.get("submitted_width") or transform.get("proxy_width")
        review_height = transform.get("submitted_height") or transform.get("proxy_height")
        review_dimensions = f"{review_width}×{review_height}" if review_width and review_height else "-"
        codec = str(transform.get("proxy_codec") or transform.get("proxy_profile") or "WebM")
        index = int(video.get("video_index") or len(rows) + 1)
        rows.append(
            '<article class="boundary-card">'
            f'<h3>视频 {index} · 模型实际送审版</h3>'
            f'<p>原片 {file_size(derivative.get("source_bytes"))}、{_h(source_dimensions)}；'
            f'送审版 {file_size(derivative.get("review_bytes"))}、{_h(review_dimensions)}、{_h(codec.upper())}。</p>'
            '<p class="fine-print">Agent 结论基于送审版；如怀疑转码影响细节，请在相同时间点对照原片。</p>'
            f'<button class="jump preview-trigger" type="button" data-preview-kind="video" '
            f'aria-label="查看视频 {index} 原片" data-preview-src="{_h(original_url)}" '
            f'data-preview-title="视频 {index} 原片">查看原片</button> '
            f'<button class="jump preview-trigger" type="button" data-preview-kind="video" '
            f'aria-label="查看视频 {index} 模型送审版" data-preview-src="{_h(review_url)}" '
            f'data-preview-title="视频 {index} 模型实际送审版">查看模型送审版</button>'
            '</article>'
        )
    if not rows:
        return ""
    return (
        '<section class="panel boundary-panel review-media-comparison">'
        '<div class="section-head"><h2>原片与模型送审版对照</h2>'
        '<p>只在系统实际生成转码衍生片时显示，不把衍生片冒充原片。</p></div>'
        f'<div class="boundary-grid">{"".join(rows)}</div></section>'
    )


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
    material_readiness = dict(
        data.get("material_readiness") or parsed.get("material_readiness") or {}
    )
    review_inventory = (
        (data.get("input_readiness") or {}).get("review_inventory") or {}
    )
    if review_inventory:
        material_readiness["review_inventory"] = review_inventory
    scenario = str(
        material_readiness.get("scenario")
        or report.get("scenario")
        or data.get("scenario")
        or ""
    )
    fulfillment = parsed.get("fulfillment_reconciliation") or {}
    if scenario == "missing_item" and fulfillment.get("scenario_transition") == "wrong_item":
        scenario = "wrong_item"
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
    media_preflight_execution_html = _media_preflight_execution_html(
        data.get("media_preflight_execution")
    )
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
        sampling_method_text = f"按 {sampling_fps_text} 通看全片"
    except (TypeError, ValueError):
        sampling_fps_value = 0.0
        sampling_fps_text = "实际送审密度"
        sampling_method_text = "按实际送审方式通看全片"
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
    if video.get("playback_speed") == "unknown" and speed_status in {"uncertain", "material"}:
        speed_impact_html = (
            "<p><b>黄色提示：</b>系统无法可靠判断视频是否加速，不会仅凭这一点判负；"
            "若速度会影响离镜或伤点判断，请客服回看原视频中的商品展示片段。</p>"
        )
    elif video.get("playback_speed") != "accelerated":
        speed_impact_html = ""
    elif speed_status == "uncertain":
        speed_impact_html = (
            f"<p><b>橙色风险：</b>疑似加速，当前无法判断{_h(affected_text)}；"
            "请客服只回看对应原视频片段，加速本身不作为判负依据。</p>"
        )
    elif speed_status == "material":
        speed_impact_html = (
            f"<p><b>黄色提示：</b>{_h(affected_text)}在现有视频中仍无法判断；"
            "请客服回看原片，不把播放速度本身写成材料不合规。</p>"
        )
    elif speed_status == "none" and speed_impact.get("critical_evidence_observable") is True:
        speed_impact_html = (
            f"<p><b>橙色风险：</b>疑似加速，但当前 {_h(sampling_fps_text)} 下"
            "关键证据仍可判断，不因加速本身阻断结论。</p>"
        )
    else:
        speed_impact_html = "<p><b>橙色风险：</b>疑似加速，但尚未形成速度影响结论，不能据此判负。</p>"
    speed_limit_html = (
        '<p class="fine-print speed-limit"><b>速度判断边界：</b>'
        f'目前没有稳定方法确认原视频是否加速；系统{_h(sampling_method_text)}并把不确定项标黄，'
        '不会只凭普通 PTS、帧率或容器时长断言用户变速。</p>'
        if video.get("playback_speed") == "unknown"
        else ""
    )
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
    field_confidences = parsed.get("field_confidences") or {}
    if isinstance(field_confidences, list):
        field_confidences = dict(zip(
            (
                "sealed_start",
                "waybill_visible",
                "continuous",
                "has_edit",
                "has_offscreen",
                "has_speed_change",
                "all_items_shown",
                "issue_visible",
            ),
            field_confidences,
        ))
    elif not isinstance(field_confidences, dict):
        field_confidences = {}
    compact_evidence_refs = [
        item for item in parsed.get("evidence_refs") or []
        if isinstance(item, dict)
    ]

    def field_confidence_text(field: str, overall: bool) -> str:
        value = parsed.get("confidence") if overall else field_confidences.get(field)
        try:
            return f"{round(float(value) * 100)}%"
        except (TypeError, ValueError, OverflowError):
            return "未提供"

    def field_evidence_text(field: str, overall: bool) -> str:
        if overall:
            return "见各项证据"
        aliases = {
            "continuous": {"continuous", "single_take_continuity"},
            "issue_visible": {"issue_visible", "issue_visible_in_continuous_opening"},
        }.get(field, {field})
        timestamps = list(dict.fromkeys(
            str(item.get("timestamp") or "").strip()
            for item in compact_evidence_refs
            if item.get("field") in aliases and str(item.get("timestamp") or "").strip()
        ))
        return "、".join(timestamps[:4]) or "未提供"

    nine_field_specs = (
        ("all_items_shown", "相关商品是否全部展示", False),
        ("continuous", "关键过程是否连续", False),
        ("has_edit", "是否存在剪辑", False),
        ("has_offscreen", "商品是否离开画面", False),
        ("has_speed_change", "是否存在变速", False),
        ("issue_visible", "投诉问题是否清晰可见", False),
        ("overall_video_result", "视频综合结论", True),
        ("sealed_start", "是否封箱起拍", False),
        ("waybill_visible", "面单是否可见", False),
    )
    if any(field in parsed for field, _, _ in nine_field_specs):
        overall_labels = {
            "compliant": "合格",
            "noncompliant": "不合格",
            "indeterminate": "待确认",
        }
        nine_rows = "".join(
            "<tr>"
            f"<td>{_h(label)}</td>"
            f"<td>{_h(overall_labels.get(str(parsed.get(field) or ''), '待确认') if overall else {True: '是', False: '否', None: '待确认'}.get(parsed.get(field), '待确认'))}</td>"
            f"<td>{_h(field_confidence_text(field, overall))}</td>"
            f"<td>{_h(field_evidence_text(field, overall))}</td>"
            "</tr>"
            for field, label, overall in nine_field_specs
        )
        opening_compliance_html = (
            '<div class="opening-checks"><h3>开箱视频九项核对</h3>'
            '<div class="table-wrap"><table><thead><tr><th>审核字段</th><th>结果</th><th>判断置信度</th><th>证据时间点</th></tr></thead>'
            f'<tbody>{nine_rows}</tbody></table></div></div>'
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
        if isinstance(item, dict) and str(item.get("code") or "") not in RETIRED_SIGNAL_CODES
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
    review_media_comparison_html = _review_media_comparison_html(media_gallery)
    restricted_media_notice = (
        '<p class="fine-print"><b>素材权限：</b>脱敏分享页不包含原始素材；请在登录后的正式工单报告中点击证据时间点预览原视频。</p>'
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
    report_title = f"{scenario_label}报告" if str(scenario_label).endswith("审核") else f"{scenario_label}审核报告"
    is_minor_report = scenario in {"minor_refund", "minor_material"} or bool(parsed.get("minor_material_assessment"))
    is_product_damage = scenario == "product_damage" or "商品有伤" in scenario_label
    is_fulfillment_report = scenario in {"wrong_item", "missing_item"}
    severity = (parsed.get("damage_causality_assessment") or {}).get("severity_assessment") or {}
    severity_level = str(severity.get("level") or "unknown")
    severity_confidence = severity.get("confidence")
    decision_audit = parsed.get("decision_policy_audit") or {}
    show_severe_flag = decision_audit.get("severe_alert_eligible") is True
    severity_flag_html = (
        '<div class="severity-flag severity-yes">'
        '<small>严重商品质量问题</small><b>是</b>'
        f'<span>{_h(severity.get("reason") or "按可见损坏程度与商品正常展示影响判断。")}</span></div>'
        if show_severe_flag and is_product_damage
        else ""
    )
    opening_evidence = parsed.get("opening_video_evidence") or {}
    opening_status = str(opening_evidence.get("status") or "")
    opening_label = {"pass": "通过", "yellow": "黄标"}.get(opening_status, "待确认")
    try:
        opening_confidence = f"{round(float(opening_evidence.get('confidence')) * 100)}%"
    except (TypeError, ValueError, OverflowError):
        opening_confidence = "未提供"
    opening_evidence_html = (
        f'<section class="opening-evidence-banner opening-{_h(opening_status or "unknown")}">'
        f'<div><small>初次开箱视频证据</small><b>{_h(opening_label)}</b></div>'
        f'<p>{_h(opening_evidence.get("reason") or "本轮未形成明确判断。")} '
        f'<span>判断置信度 {_h(opening_confidence)}</span></p></section>'
        if isinstance(opening_evidence, dict) and opening_evidence
        else ""
    )
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
    material_status = str(material_readiness.get("status") or "")
    compact_material_html, material_detail_html = _material_readiness_html(
        material_readiness,
        scenario,
    )
    omit_no_action = (
        human_level == "not_required"
        and workflow == "continue_by_customer_policy"
    )
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
        next_step = ""
    elif workflow == "continue_by_customer_policy" and human_level == "optional":
        next_step = human_review.get("recommendation") or next_step
    if failed:
        conclusion = data.get("conclusion") or conclusion
        core_reason = diagnostics.get("failure_reason") or "本轮审核没有完成，不能把该结果解释为业务证据不足。"
        next_step = diagnostics.get("operator_hint") or next_step
        confidence = "-"
    material_gaps = (
        material_readiness.get("missing_items") or []
        if material_readiness
        else parsed.get("material_gaps") or []
    )
    model_limitations = [
        "本报告只说明送审证据支持什么结论，不能替代甲方的退款、换货、补偿或拒绝决定。",
        "未接入的订单、仓库、物流或权威核验数据不会被假设为已核验。",
    ]
    if parsed.get("specialized_pass_warning"):
        model_limitations.append(str(parsed["specialized_pass_warning"]))
    confidence_reason = _safe_agent_reason(parsed.get("confidence_reason") or overall.get("core_reason") or core_reason)
    supporting_evidence = _summary_evidence_items(parsed)
    summary_evidence = supporting_evidence
    evidence_priority = {
        "issue_visible": 0,
        "issue_visible_in_continuous_opening": 0,
        "claimed_item": 1,
        "warehouse_verification": 1,
        "sealed_start": 2,
        "waybill_visible": 3,
        "continuous": 4,
        "single_take_continuity": 4,
        "all_items_shown": 5,
        "has_offscreen": 6,
        "has_speed_change": 7,
        "has_edit": 8,
    }
    if isinstance(supporting_evidence, list):
        supporting_evidence = _merge_evidence_items(supporting_evidence)
        supporting_evidence = [
            item
            for _, item in sorted(
                enumerate(supporting_evidence),
                key=lambda pair: (
                    evidence_priority.get(
                        str(pair[1].get("field") or "") if isinstance(pair[1], dict) else "",
                        50,
                    ),
                    pair[0],
                ),
            )
        ]
    challenging_evidence = parsed.get("challenging_evidence") or []
    risky_findings = _risky_frame_findings(parsed.get("frame_findings"))
    issue_timestamps = _issue_timestamp_items(parsed.get("issue_timestamps"))
    damage_causality_panel = (
        render_damage_causality_panel(
            parsed.get("damage_causality_assessment"), media_gallery, _evidence_items, _h
        ) if is_product_damage else ""
    )
    object_continuity_panel = (
        render_object_continuity_panel(
            parsed.get("object_continuity_assessment"), media_gallery, _evidence_items, _h
        ) if is_product_damage or is_fulfillment_report else ""
    )
    fulfillment_panel = (
        render_fulfillment_reconciliation_panel(
            parsed.get("fulfillment_reconciliation"),
            _h,
            scenario,
            media_gallery,
            _evidence_items,
        )
        if is_fulfillment_report else ""
    )
    claim_fact_panel = (
        render_claim_fact_panel(parsed.get("claim_fact_assessment"), _h)
        if is_product_damage else ""
    )
    minor_material_panel = (
        render_minor_material_panel(parsed.get("minor_material_assessment"), _h)
        if is_minor_report else ""
    )
    confidence_components_panel = render_confidence_components_panel(parsed.get("confidence_components"), _h)
    decision_policy_panel = _decision_policy_panel(parsed.get("decision_policy_audit") or data.get("decision_policy_audit"))
    raw_gap_items = material_gaps if isinstance(material_gaps, list) else [material_gaps] if material_gaps else []
    gap_items = list(dict.fromkeys(
        text for item in raw_gap_items if len(text := _readable_fact(item).strip()) >= 2
    ))
    gap_summary = "；".join(gap_items[:10])
    gap_panel_html = (
        f'<div class="summary-gaps"><h3>需要补什么</h3><p>{_h(gap_summary)}</p></div>'
        if gap_summary else ""
    )
    attention_tone = {
        "green": "green",
        "orange": "amber",
        "red": "red",
        "gray": "gray",
    }.get(str(evidence_attention.get("level") or ""), "amber")
    attention_panel = ""
    if evidence_attention:
        attention_columns = []
        for heading, key in (
            ("优先核对", "customer_focus"),
            ("证据分歧", "disagreements"),
            ("材料缺口", "missing_evidence"),
        ):
            values = evidence_attention.get(key)
            if values:
                attention_columns.append(
                    f'<article><h4>{heading}</h4>{_list_html(values, "")}</article>'
                )
        attention_grid = (
            f'<div class="attention-grid">{"".join(attention_columns)}</div>'
            if attention_columns else ""
        )
        attention_panel = f"""
    <section class="summary-attention status-card status-{attention_tone}">
      <h3>复核顺序</h3>
      <p><b>{_h(evidence_attention.get("headline") or "请按证据优先级继续审核。")}</b></p>
      {attention_grid}
    </section>"""
    evidence_summary = advisory_assessment.get("conclusion") or conclusion
    sop_summary = sop_recommendation.get("recommendation")
    summary_cards = []
    if compact_material_html:
        summary_cards.append(compact_material_html)
    confidence_display = _confidence_display(confidence)
    distinct_sop_html = (
        f'<p class="fine-print"><b>处理口径：</b>{_h(sop_summary)}</p>'
        if sop_summary and not _same_readable_text(sop_summary, evidence_summary)
        else ""
    )
    evidence_summary_html = (
        '<div class="summary-reason"><h3>证据结论</h3>'
        f'<p>{_h(evidence_summary)}</p>{distinct_sop_html}</div>'
        if evidence_summary
        else ""
    )
    score_note = (
        '<p class="fine-print">证据分数表示本轮证据充分程度，不是客观正确率。</p>'
        if confidence_display not in (None, "", "-")
        else ""
    )
    human_review_recommendation = str(human_review.get("recommendation") or "").strip()
    human_review_hint_html = (
        '<div class="summary-reason"><h3>人工复核说明</h3>'
        f'<p>{_h(human_review_recommendation)}</p></div>'
        if human_review_recommendation
        and human_review_recommendation != str(next_step).strip()
        else ""
    )
    summary_signals_html = (
        f'<details class="summary-signals"><summary>查看其他风险信号</summary>'
        f'<div class="boundary-grid">{signal_cards}</div></details>'
        if signal_cards else ""
    )
    reason_panel_html = (
        f'<div class="summary-reason"><h3>判断依据</h3><p>{_h(core_reason)}</p></div>'
        if core_reason
        and not any(
            _same_readable_text(core_reason, item)
            for item in (evidence_summary, sop_summary, conclusion)
        )
        else ""
    )
    next_step_html = "" if omit_no_action or not str(next_step or "").strip() else f"""
    <div class="human-action status-{_h({'required': 'red', 'optional': 'amber', 'not_required': 'green'}.get(human_level, 'amber'))}">
      <h3>建议下一步</h3><p>{_h(next_step)}</p>
    </div>"""
    summary_detail_content = "".join((
        opening_evidence_html,
        evidence_summary_html,
        score_note,
        attention_panel,
        reason_panel_html,
        gap_panel_html,
        human_review_hint_html,
        '<h3>关键证据</h3>',
        f'<div class="evidence-grid">{_evidence_items(summary_evidence[:6], media_gallery)}</div>',
        restricted_media_notice,
        f'<p class="fine-print summary-boundary"><b>业务边界：</b>{_h(advisory_policy.get("boundary") or "本服务输出证据结论和 SOP 处理建议；具体业务动作由甲方系统执行，人工复审等级独立判断。")}</p>',
        summary_signals_html,
        material_detail_html,
    ))
    summary_details_html = (
        '<details class="summary-review-details"><summary>查看判断依据与关键证据</summary>'
        f'<div class="summary-review-details-body">{summary_detail_content}</div></details>'
        if summary_detail_content else ""
    )
    advisory_panel = f"""
    <section class="panel advisory-panel decision-{_h(advisory_assessment.get('conclusion_code') or 'unknown')}">
    <div class="section-head"><h2>客服审核摘要</h2><p>先看结论、材料状态和下一步，需要时再展开证据。</p></div>
    <div class="causality-grid">{"".join(summary_cards)}</div>
    {next_step_html}
    {summary_details_html}
  </section>
"""
    conclusion_code = str(advisory_assessment.get("conclusion_code") or "")
    yes_no = "REVIEW" if failed else {
        "evidence_supports_claim": "YES",
        "evidence_does_not_support_claim": "NO",
        "evidence_inconclusive": "REVIEW",
        "severe_structural_damage_follow_up": "REVIEW",
    }.get(conclusion_code, _public_yes_no(parsed))
    tone = "gray" if failed else (
        attention_tone if evidence_attention else {
            "evidence_supports_claim": "green",
            "evidence_does_not_support_claim": "red",
            "evidence_inconclusive": "amber",
            "severe_structural_damage_follow_up": "amber",
        }.get(conclusion_code, "amber")
    )
    report_class = (
        "minor-report scene-minor-refund" if is_minor_report
        else "product-report scene-product-damage" if is_product_damage
        else f"fulfillment-report scene-{scenario.replace('_', '-')}" if is_fulfillment_report
        else f"scene-{scenario.replace('_', '-')}"
    )
    if is_minor_report:
        material_status = str(material_readiness.get("status") or "")
        verdict_text = "未完成" if failed else {
            "complete": "资料齐全",
            "incomplete": "需补资料",
            "indeterminate": "待确认",
        }.get(material_status, "待确认")
        hero_title = "审核未完成" if failed else {
            "complete": "五类材料初审齐全",
            "incomplete": "材料需要补充或更正",
            "indeterminate": "材料仍待确认",
        }.get(material_status, "材料仍待确认")
    else:
        verdict_text = "未完成" if failed else {
            "evidence_supports_claim": "支持",
            "evidence_does_not_support_claim": "不支持",
            "evidence_inconclusive": "待确认",
            "severe_structural_damage_follow_up": "重点跟进",
        }.get(conclusion_code, yes_no)
        hero_title = "审核未完成" if failed else {
            "evidence_supports_claim": "现有证据支持用户诉求",
            "evidence_does_not_support_claim": "现有证据暂不支持用户诉求",
            "evidence_inconclusive": "现有证据尚不足以判断",
            "severe_structural_damage_follow_up": "严重结构问题已确认，交易归属、成因和责任待确认",
        }.get(conclusion_code)
    if not hero_title:
        compact_conclusion = str(conclusion or "").strip()
        hero_title = (
            compact_conclusion
            if compact_conclusion and len(compact_conclusion) <= 28
            else _public_verdict(parsed, scenario_label)
        )
    confidence_badge_html = (
        f'<span>证据分数 {_h(confidence_display)}</span>'
        if confidence_display not in (None, "", "-") else ""
    )
    hero_lead_html = (
        f'<p class="lead">{_h(core_reason)}</p>'
        if failed and core_reason else ""
    )
    if challenging_evidence or risky_findings:
        risk_panel = f"""
  <section class="panel risk-panel">
    <div class="section-head"><h2>反证与可疑帧</h2><p>红色内容会削弱当前结论，请优先回看原始图片或视频。</p></div>
    <div class="evidence-grid">{_evidence_items(challenging_evidence, media_gallery, "需复核") if challenging_evidence else ''}</div>
    <div class="evidence-grid">{_evidence_items(risky_findings, media_gallery, "风险画面") if risky_findings else ''}</div>
  </section>"""
    else:
        risk_panel = ""
    if issue_timestamps:
        issue_panel = f"""
  <section class="panel issue-panel">
    <div class="section-head"><h2>问题时间点</h2><p>点击证据卡可回看对应画面或原视频片段。</p></div>
    <div class="evidence-grid">{_evidence_items(issue_timestamps, media_gallery, "重点复核")}</div>
  </section>"""
    else:
        issue_panel = ""
    visual_verdict = ({
        "evidence_supports_claim": "五类材料与可见字段初审通过",
        "evidence_does_not_support_claim": "材料字段存在明确冲突",
        "evidence_inconclusive": "材料或可见字段仍待确认",
    } if is_minor_report else {
        "evidence_supports_claim": "证据支持本次事实诉求",
        "evidence_does_not_support_claim": "现有证据不支持本次事实诉求",
        "evidence_inconclusive": "证据不足，建议按流程补充或复核",
        "severe_structural_damage_follow_up": "严重结构问题已确认，交易归属、成因和责任待确认",
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
    if video_count and not is_minor_report:
        product_video_metrics = f"""
      <div class="metric"><small>商品连续性分数</small><b>{_h(video.get("continuity_score") or "-")}</b></div>
      <div class="metric"><small>展示连续性风险</small><b>{_h(_public_risk(video.get("swap_risk_level")))}</b></div>""" if is_product_damage else ""
        video_metrics_html = f"""
      {product_video_metrics}
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
        if is_product_damage:
            process_label = "开箱过程完整性"
            proof_subject_label = "商品证据连续性"
            proof_note = (
                "视频从头拍到尾，不代表争议商品一直在镜头里。系统会分别检查开箱过程、"
                "商品展示和文件异常，不能用其中一项替代另一项。"
            )
            scene_opening_checks = opening_compliance_html
        else:
            process_label = "包裹开启过程完整性"
            proof_subject_label = "包裹与实收展示连续性"
            proof_note = (
                "视频从头拍到尾，不代表应发与实收已经核对完成。系统会分别检查包裹开启过程、"
                "实收展示、订单基线和文件异常，不能用其中一项替代另一项。"
            )
            scene_opening_checks = ""
        video_proof_html = f"""
  <section class="panel proof">
    <h2>视频审核论证</h2>
    <div class="causality-grid">
      <article><small>抽帧首尾覆盖</small><b>{_h({"covered": "已覆盖", "incomplete": "未完整覆盖", "unknown": "未知"}.get(video.get("sampling_boundary_status"), video.get("sampling_boundary_status") or "未知"))}</b></article>
      <article><small>媒体技术取证</small><b>{_h(_public_status((parsed.get("decision_policy_audit") or data.get("decision_policy_audit") or {}).get("evidence_gate", {}).get("media_forensics_status") or video.get("technical_timeline_status") or "未提供"))}</b></article>
      <article><small>{process_label}</small><b>{_h({"complete": "完整", "incomplete": "不完整", "indeterminate": "不确定"}.get(video.get("opening_integrity"), video.get("opening_integrity") or "未知"))}</b></article>
      <article><small>{proof_subject_label}</small><b>{_h(continuity_label)}</b></article>
    </div>
    <p class="fine-print"><b>说明：</b>{proof_note}</p>
    <p><b>画面节奏判断：{_h(visual_playback_speed)}</b>。这是模型对画面节奏的观察，不是精确倍速测量。</p>
    {speed_impact_html}
    {speed_limit_html}
    {scene_opening_checks}
    <p><b>播放速度技术取证：</b></p><ul class="boundary-list">{playback_speed_evidence}</ul>
    <p><b>连续性：</b>{_h(video.get("continuity_reason") or video.get("reason") or "本轮没有输出明确连续性理由。")}</p>
    <p><b>剪辑与展示连续性：</b>{_h(_public_risk(video.get("edit_or_cut_risk")))} / {_h(_public_risk(video.get("swap_risk_level")))}</p>
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
    order_baseline_panel = "" if is_minor_report else f"""
  <section class="panel product-only">
    <div class="section-head"><h2>系统订单基线</h2><p>这里展示服务实际送审的受信任订单字段，不依赖模型复述。</p></div>
    <p><b>基线版本：</b>{_h(order_baseline.get("baseline_version") or "未提供")}；<b>承运商：</b>{_h(order_baseline.get("carrier") or "未提供")}；<b>物流引用：</b>{_h(order_baseline.get("tracking_ref") or "未提供")}</p>
    <p><b>抽赏规则：</b>{_h("完整" if order_baseline.get("selection_rules_complete") else "不完整或待确认")}；<b>赠品/特典规则：</b>{_h("完整" if order_baseline.get("benefit_rules_complete") else "不完整或待确认")}；<b>分包映射：</b>{_h(order_baseline.get("package_mapping_status") or "未提供")}</p>
    <div class="table-wrap"><table><thead><tr><th>行项目</th><th>SKU</th><th>商品</th><th>规格</th><th>应发数量</th></tr></thead><tbody>{order_rows or '<tr><td colspan="5">本轮未提供订单商品基线。</td></tr>'}</tbody></table></div>
  </section>"""
    official_reference_panel = "" if is_minor_report else f"""
  <section class="panel boundary-panel product-only">
    <div class="section-head"><h2>官方商品参考图</h2><p>仅作为订单商品标准外观基准，不属于用户提交证据，也不能单独证明实际收货、漏发或损伤。</p></div>
    <p><b>读取状态：</b>{_h(official_status_label)}；请求 {_h(official_reference_status.get("requested_count") or 0)} 张，可用 {_h(official_reference_status.get("available_count") or 0)} 张，失败 {_h(official_reference_status.get("failed_count") or 0)} 张；{_h(official_fallback)}。</p>
    <div class="media-grid">{_gallery_items(media_gallery.get("official_references") or [], "官方商品参考图")}</div>
  </section>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_h(report_title)}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body class="{report_class}">
<main class="shell">
  <section class="hero tone-{tone}">
    <div>
      <span class="badge">{_h(report_title)}</span>
      {severity_flag_html}
      <h1>{_h(hero_title)}</h1>
      {hero_lead_html}
    </div>
    <aside class="verdict-card">
      <small>审核建议</small>
      <b>{_h(verdict_text)}</b>
      {confidence_badge_html}
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
		  {media_preflight_execution_html}
		  {review_media_comparison_html}
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
    {confidence_components_panel if is_product_damage else ''}
    {damage_causality_panel}
  {object_continuity_panel}
  {fulfillment_panel}
  {claim_fact_panel}

  {order_baseline_panel}
  {official_reference_panel}

  <section class="panel">
    <div class="section-head"><h2>送审证据画廊</h2><p>用于快速复核审核Agent看到的帧图和用户补充图片。</p></div>
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


__all__ = ("render_public_report", "safe_agent_conclusion", "safe_agent_next_step")
