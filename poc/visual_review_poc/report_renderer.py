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
    "minor_payment_process_evidence_gap": "低龄支付过程待补",
    "minor_low_age_process_verified": "低龄支付过程已核对",
    "customer_risk_context": "抽检优先级提示",
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
        '目前没有稳定方法确认原视频是否加速；系统按 1 FPS 通看全片并把不确定项标黄，'
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
    severity = (parsed.get("damage_causality_assessment") or {}).get("severity_assessment") or {}
    severity_level = str(severity.get("level") or "unknown")
    severity_confidence = severity.get("confidence")
    if severity_confidence in (None, ""):
        field_confidences = parsed.get("field_confidences") or {}
        severity_confidence = (
            field_confidences.get("issue_visible")
            if isinstance(field_confidences, dict)
            else field_confidences[7]
            if isinstance(field_confidences, list) and len(field_confidences) >= 8
            else None
        )
    try:
        show_severe_flag = (
            severity_level in {"severe", "extreme"}
            and parsed.get("issue_visible") is True
            and float(severity_confidence) >= 0.8
        )
    except (TypeError, ValueError, OverflowError):
        show_severe_flag = False
    severity_flag_html = (
        '<div class="severity-flag severity-yes">'
        '<small>严重商品质量问题</small><b>是</b>'
        f'<span>{_h(severity.get("reason") or "按可见损坏程度与商品正常展示影响判断。")}</span></div>'
        if show_severe_flag and ("商品有伤" in scenario_label or data.get("scenario") == "product_damage")
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
    summary_evidence = _summary_evidence_items(parsed)
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
    summary_cards = [
        f'<article><small>证据结论</small><b>{_h(evidence_summary)}</b></article>'
    ]
    if sop_summary and str(sop_summary).strip() != str(evidence_summary).strip():
        summary_cards.append(f'<article><small>SOP 处理建议</small><b>{_h(sop_summary)}</b></article>')
    confidence_display = _confidence_display(confidence)
    if confidence_display not in (None, "", "-"):
        summary_cards.append(f'<article><small>证据分数</small><b>{_h(confidence_display)}</b></article>')
    if human_level in {"required", "optional", "not_required"}:
        summary_cards.append(f'<article><small>人工复审</small><b>{_h(human_level_label)}</b></article>')
    if workflow_label != "未给出":
        summary_cards.append(f'<article><small>流程</small><b>{_h(workflow_label)}</b></article>')
    score_note = (
        '<p class="muted">证据分数表示本轮证据充分程度，不是客观正确率。</p>'
        if confidence_display not in (None, "", "-") else ""
    )
    human_review_recommendation = str(human_review.get("recommendation") or "").strip()
    human_review_hint_html = (
        f'<p class="muted">复核重点：{_h(human_review_recommendation)}</p>'
        if human_review_recommendation and human_review_recommendation != str(next_step).strip()
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
    advisory_panel = f"""
  <section class="panel advisory-panel decision-{_h(advisory_assessment.get('conclusion_code') or 'unknown')}">
    <div class="section-head"><h2>客服审核摘要</h2><p>先看结论和关键证据，需要时再展开技术分析。</p></div>
    <div class="causality-grid">{"".join(summary_cards)}</div>
    {opening_evidence_html}
    {score_note}
    {attention_panel}
    {reason_panel_html}
    {gap_panel_html}
    <div class="human-action status-{_h({'required': 'red', 'optional': 'amber', 'not_required': 'green'}.get(human_level, 'amber'))}">
      <h3>建议下一步</h3><p>{_h(next_step)}</p>
      {human_review_hint_html}
    </div>
    <h3>关键证据</h3>
    <div class="evidence-grid">{_evidence_items(summary_evidence[:6], media_gallery)}</div>
    {restricted_media_notice}
    <p class="fine-print summary-boundary"><b>业务边界：</b>{_h(advisory_policy.get("boundary") or "本服务输出证据结论和 SOP 处理建议；具体业务动作由甲方系统执行，人工复审等级独立判断。")}</p>
    {summary_signals_html}
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
    hero_title = "审核未完成" if failed else {
        "evidence_supports_claim": "现有证据支持用户诉求",
        "evidence_does_not_support_claim": "现有证据暂不支持用户诉求",
        "evidence_inconclusive": "现有证据尚不足以判断",
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
    <p class="fine-print"><b>说明：</b>视频从头拍到尾，不代表争议商品一直在镜头里。系统会分别检查开箱过程、商品展示和文件异常，不能用其中一项替代另一项。</p>
    <p><b>画面节奏判断：{_h(visual_playback_speed)}</b>。这是模型对画面节奏的观察，不是精确倍速测量。</p>
    {speed_impact_html}
    {speed_limit_html}
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
