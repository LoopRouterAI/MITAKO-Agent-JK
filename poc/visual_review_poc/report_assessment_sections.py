# -*- coding: utf-8 -*-
"""视觉报告中的商品因果与主体连续性专项区块。"""
from __future__ import annotations

from typing import Any, Callable, Dict


LABELS = {
    "confirmed": "已确认可见损伤",
    "not_visible": "未见所述损伤",
    "uncertain": "损伤存在性不确定",
    "pre_opening_visible": "拆封/操作前已可见",
    "appears_during_opening": "拆封/操作过程中出现",
    "post_opening_only": "仅在拆封/操作后可见",
    "unknown": "出现时点未知",
    "manufacturing_or_original_packaging": "生产或原包装阶段",
    "logistics_transport": "物流运输阶段",
    "customer_opening_or_handling": "用户拆封或后续操作",
    "mixed": "多因素共同作用",
    "indeterminate": "无法确定",
    "direct": "直接前后证据",
    "indirect": "间接关联证据",
    "insufficient": "证据不足",
    "supported": "支持用户所述到手有伤",
    "not_supported": "不支持用户所述到手有伤",
    "continuous": "连续可观察",
    "brief_occlusion": "存在短暂遮挡",
    "long_absence": "存在较长离镜",
}


def _label(value: Any) -> Any:
    return LABELS.get(str(value), value or "-")


def _text_items(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value] if value not in (None, "") else []
    result = []
    for item in values:
        if isinstance(item, dict):
            text = item.get("fact") or item.get("description") or item.get("reason")
            if text:
                result.append(str(text))
        elif item not in (None, ""):
            result.append(str(item))
    return result


def render_damage_causality_panel(
    assessment: Any,
    media_gallery: Dict[str, Any],
    evidence_renderer: Callable[..., str],
    escape: Callable[[Any], str],
) -> str:
    if not isinstance(assessment, dict):
        return ""
    first_visible = assessment.get("first_visible_evidence")
    first_visible_html = ""
    if isinstance(first_visible, dict):
        evidence = {
            **first_visible,
            "source_type": first_visible.get("source_type") or ("video_frame" if first_visible.get("timestamp") is not None else "supplementary_image"),
            "fact": first_visible.get("fact") or first_visible.get("description") or "损伤在该证据中首次清晰可见。",
            "why_it_matters": first_visible.get("why_it_matters") or "用于判断损伤首次出现时点和可能形成阶段。",
        }
        first_visible_html = '<h3>首次清晰可见证据</h3><div class="evidence-grid">' + evidence_renderer([evidence], media_gallery, "首次可见") + "</div>"
    origin_cards = []
    for item in (assessment.get("possible_origins") or [])[:5]:
        if not isinstance(item, dict):
            continue
        support = "；".join(_text_items(item.get("supporting_evidence"))[:3]) or "未提供"
        challenge = "；".join(_text_items(item.get("challenging_evidence"))[:3]) or "未提供"
        origin_cards.append(
            '<article class="boundary-card">'
            f'<h3>{escape(_label(item.get("origin")))}</h3>'
            f'<p><b>可能性置信度：</b>{escape(item.get("confidence") if item.get("confidence") is not None else "-")}</p>'
            f'<p><b>支持：</b>{escape(support)}</p><p><b>反证/缺口：</b>{escape(challenge)}</p></article>'
        )
    alternatives = _text_items(assessment.get("alternative_explanations"))
    alternatives_html = "".join(f"<li>{escape(item)}</li>" for item in alternatives[:8]) or "<li>本轮没有列出其他解释。</li>"

    def chain_cards(key: str, title: str, empty: str) -> str:
        items = []
        for raw in assessment.get(key) or []:
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    **raw,
                    "source_type": "video_frame",
                    "fact": raw.get("fact") or raw.get("description") or title,
                    "why_it_matters": f"{title}：{raw.get('subject') or '争议对象'} / {raw.get('location') or '未明确部位'} / {raw.get('chain_id') or '未提供链编号'}",
                }
            )
        body = evidence_renderer(items, media_gallery, title) if items else f'<p class="muted">{escape(empty)}</p>'
        return f'<h3>{escape(title)}</h3><div class="evidence-grid">{body}</div>'
    return f"""
  <section class="panel causality-panel">
    <div class="section-head"><h2>损伤来源与发生阶段</h2><p>损伤事实、形成时点和责任归属分开表达；本区不代表业务定责。</p></div>
    <div class="causality-grid">
      <article><small>损伤存在性</small><b>{escape(_label(assessment.get("damage_presence")))}</b></article>
      <article><small>首次出现阶段</small><b>{escape(_label(assessment.get("damage_timing")))}</b></article>
      <article><small>最可能原因</small><b>{escape(_label(assessment.get("most_likely_origin")))}</b></article>
      <article><small>因果证据等级</small><b>{escape(_label(assessment.get("causal_evidence_level")))}</b></article>
      <article><small>成因置信度</small><b>{escape(assessment.get("origin_confidence") if assessment.get("origin_confidence") is not None else "-")}</b></article>
      <article><small>诉求支持度</small><b>{escape(_label(assessment.get("claim_support")))}</b></article>
    </div>
    <p><b>损伤位置与类型：</b>{escape(assessment.get("damage_type_and_location") or "本轮未明确描述。")}</p>
    <p><b>过程锚点：</b>操作前状态 {escape("可见" if assessment.get("pre_opening_state_visible") else "不可见")}；拆封/操作动作 {escape("可见" if assessment.get("opening_action_visible") else "不可见")}；损伤变化 {escape("已观察到" if assessment.get("damage_change_observed") else "未形成直接观察")}</p>
    {chain_cards("before_action_evidence", "动作前证据", "未形成同一对象同一部位的动作前证据。")}
    {chain_cards("action_evidence", "动作证据", "未形成可能致损动作的可回链证据。")}
    {chain_cards("after_action_evidence", "动作后证据", "未形成同一对象同一部位的动作后变化证据。")}
    {first_visible_html}
    <h3>可能原因对比</h3><div class="boundary-grid">{"".join(origin_cards) or '<p class="muted">本轮没有输出可能原因对比。</p>'}</div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>其他合理解释</h3><ul class="boundary-list">{alternatives_html}</ul></article>
      <article class="boundary-card"><h3>为什么不能进一步确定</h3><p>{escape(assessment.get("cannot_conclude_reason") or "本轮未声明额外无法归因原因。")}</p></article>
    </div>
  </section>"""


def render_object_continuity_panel(
    assessment: Any,
    media_gallery: Dict[str, Any],
    evidence_renderer: Callable[..., str],
    escape: Callable[[Any], str],
) -> str:
    if not isinstance(assessment, dict):
        return ""
    subjects = []
    for subject in (assessment.get("tracked_subjects") or [])[:10]:
        if not isinstance(subject, dict):
            continue
        events = []
        event_evidence = []
        for event in (subject.get("out_of_frame_events") or [])[:8]:
            if not isinstance(event, dict):
                continue
            identity = "已核对同一性" if event.get("identity_reestablished") else "未确认重新入镜同一性"
            events.append(
                f'<li>{escape(event.get("start_timestamp") or "-")} 至 {escape(event.get("end_timestamp") or "-")}，'
                f'{escape(event.get("duration_seconds") or 0)} 秒，{escape(event.get("visibility") or "unknown")}，{identity}。'
                f'{escape(event.get("reason") or "")}</li>'
            )
            for key, title, fallback_timestamp in (
                ("before_evidence", "离镜前", event.get("start_timestamp")),
                ("out_of_frame_evidence", "离镜起点", event.get("start_timestamp")),
                ("after_evidence", "重新入镜", event.get("end_timestamp")),
            ):
                raw = event.get(key)
                if not isinstance(raw, dict):
                    continue
                timestamp = raw.get("timestamp_label") or raw.get("source_timestamp") or raw.get("timestamp") or fallback_timestamp
                event_evidence.append(
                    {
                        **raw,
                        "timestamp": timestamp,
                        "frame_index": raw.get("global_frame_index") or raw.get("frame_index"),
                        "source_type": "video_frame",
                        "fact": f"{title}：{subject.get('description') or subject.get('subject_id') or '跟踪主体'}",
                        "why_it_matters": "用于复核主体是否真正离开画面，以及重新入镜后是否仍为同一对象。",
                    }
                )
        evidence_html = (
            '<h3>离镜前 / 离镜起点 / 重新入镜证据</h3><div class="evidence-grid">'
            + evidence_renderer(event_evidence, media_gallery, "连续性证据")
            + "</div>"
            if event_evidence
            else ""
        )
        subjects.append(
            '<article class="boundary-card">'
            f'<h3>{escape(subject.get("description") or subject.get("subject_id") or "未命名主体")}</h3>'
            f'<p><b>跟踪区间：</b>{escape(subject.get("tracking_start") or "-")} 至 {escape(subject.get("tracking_end") or "-")}</p>'
            f'<p><b>首次曝光：</b>{escape(subject.get("first_exposed_timestamp") or "-")}</p>'
            f'<p><b>可见覆盖率：</b>{escape(subject.get("visibility_coverage") if subject.get("visibility_coverage") is not None else "-")}</p>'
            f'<p><b>最长离镜：</b>{escape(subject.get("longest_out_of_frame_seconds") or 0)} 秒</p>'
            f'<ul class="boundary-list">{"".join(events) or "<li>未记录离镜事件。</li>"}</ul></article>'
            f'{evidence_html}'
        )
    policy = assessment.get("policy") or {}
    return f"""
  <section class="panel continuity-panel">
    <div class="section-head"><h2>主体连续性与离镜时间轴</h2><p>快递包装、商品包装和争议商品分别跟踪；尚未拆出不算离镜。</p></div>
    <div class="causality-grid">
      <article><small>连续性结论</small><b>{escape(_label(assessment.get("continuity_verdict")))}</b></article>
      <article><small>最长连续离镜</small><b>{escape(assessment.get("longest_out_of_frame_seconds") or 0)} 秒</b></article>
      <article><small>累计不可观察</small><b>{escape(assessment.get("total_unobserved_seconds") or 0)} 秒</b></article>
      <article><small>复核阈值</small><b>{escape(policy.get("out_of_frame_warning_seconds") or "-")} 秒</b></article>
    </div>
    <div class="boundary-grid">{"".join(subjects) or '<p class="muted">本轮没有定义可跟踪主体，不能声称全程未离镜。</p>'}</div>
  </section>"""


def render_fulfillment_reconciliation_panel(value: Any, escape: Callable[[Any], str]) -> str:
    if not isinstance(value, dict):
        return ""

    def items(key: str, empty: str) -> str:
        rows = []
        for item in (value.get(key) or [])[:20]:
            if not isinstance(item, dict):
                rows.append(f"<li>{escape(item)}</li>")
                continue
            name = item.get("product_name") or item.get("name") or item.get("sku") or item.get("item_ref") or "未命名项"
            expected = item.get("expected_quantity")
            observed = item.get("observed_quantity")
            quantity = ""
            if expected is not None or observed is not None:
                quantity = f"，应发 {escape(expected if expected is not None else '-')} / 已识别 {escape(observed if observed is not None else '-')}"
            evidence = item.get("evidence_timestamp") or item.get("timestamp") or ""
            evidence_text = f"，证据 {escape(evidence)}" if evidence else ""
            rows.append(f"<li>{escape(name)}{quantity}{evidence_text}</li>")
        return "".join(rows) or f"<li>{escape(empty)}</li>"

    return f"""
  <section class="panel fulfillment-panel">
    <div class="section-head"><h2>应发与视频展示清单对账</h2><p>订单基准、实际识别和未确认项分开表达；证据不完整不直接认定发错或漏发。</p></div>
    <div class="causality-grid">
      <article><small>基准版本</small><b>{escape(value.get("baseline_version") or "未提供")}</b></article>
      <article><small>包裹是否全部提交</small><b>{escape("是" if value.get("all_packages_uploaded") else "否/未确认")}</b></article>
      <article><small>物品是否全部展示</small><b>{escape("是" if value.get("all_items_displayed") else "否/未确认")}</b></article>
      <article><small>物品观察自评分</small><b>{escape(value.get("observation_confidence") if value.get("observation_confidence") is not None else "-")}</b></article>
      <article><small>对账置信度</small><b>{escape(value.get("confidence") if value.get("confidence") is not None else "-")}</b></article>
    </div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>应发清单</h3><ul class="boundary-list">{items("expected_items", "未提供应发清单。")}</ul></article>
      <article class="boundary-card"><h3>视频已识别</h3><ul class="boundary-list">{items("observed_items", "视频中未形成可确认清单。")}</ul></article>
      <article class="boundary-card"><h3>疑似缺失</h3><ul class="boundary-list">{items("suspected_missing_items", "未形成疑似缺失项。")}</ul></article>
      <article class="boundary-card"><h3>未确认项</h3><ul class="boundary-list">{items("unconfirmed_items", "无额外未确认项。")}</ul></article>
    </div>
    <p><b>包裹覆盖：</b>{escape(value.get("package_coverage") or "未提供")}</p>
    <p><b>判断边界：</b>{escape(value.get("decision_boundary") or "最终业务处置仍需人工复核。")}</p>
  </section>"""


def render_confidence_components_panel(value: Any, escape: Callable[[Any], str]) -> str:
    if not isinstance(value, dict):
        return ""
    labels = (
        ("main_segment_mean", "主审核分段均值"),
        ("damage_origin", "损伤成因假设"),
        ("fulfillment_reconciliation", "履约对账识别"),
        ("continuity_visibility_coverage", "主体可见覆盖率"),
        ("final_decision", "规则降级后决策分"),
    )
    cards = "".join(
        f'<article><small>{escape(label)}</small><b>{escape(value.get(key) if value.get(key) is not None else "-")}</b></article>'
        for key, label in labels
    )
    calibrated = value.get("calibration_status") != "uncalibrated_model_score"
    return f"""
  <section class="panel confidence-components-panel">
    <div class="section-head"><h2>置信度分解与口径</h2><p>不同分数不可相互替代，也不可直接解释为样本正确率。</p></div>
    <div class="causality-grid">{cards}</div>
    <p><b>校准状态：</b>{escape("已校准" if calibrated else "尚未使用独立留出集校准")}</p>
    <p><b>解释：</b>{escape(value.get("interpretation") or "请结合证据卡和人工复核边界解读。")}</p>
  </section>"""


def render_minor_material_panel(value: Any, escape: Callable[[Any], str]) -> str:
    if not isinstance(value, dict):
        return ""
    status_labels = {
        "present": "已识别到候选材料",
        "needs_manual_confirmation": "已观察到，待人工确认",
        "not_observed_after_full_scan": "全量扫描后尚未确认",
        "not_assessed": "尚未完成识别",
        "needs_manual_consistency_check": "需人工核对主体与一致性",
        "needs_business_system_check": "需业务系统核对金额与订单",
        "confirmed_by_visual_category": "视觉类别已确认",
        "not_validated": "尚未验证",
    }
    checklist_cards = []
    for item in (value.get("checklist") or [])[:10]:
        if not isinstance(item, dict):
            continue
        image_indices = "、".join(str(index) for index in item.get("evidence_image_indices") or []) or "无"
        checklist_cards.append(
            '<article class="boundary-card">'
            f'<h3>{escape(item.get("label") or item.get("requirement_id") or "未命名材料")}</h3>'
            f'<p><b>材料状态：</b>{escape(status_labels.get(item.get("status"), item.get("status") or "未知"))}</p>'
            f'<p><b>验证状态：</b>{escape(status_labels.get(item.get("validation_status"), item.get("validation_status") or "未知"))}</p>'
            f'<p><b>证据图片：</b>{escape(image_indices)}</p>'
            f'<p>{escape(item.get("rule_note") or "")}</p></article>'
        )
    process_items = []
    for item in (value.get("process_evidence") or [])[:20]:
        if not isinstance(item, dict):
            continue
        process_items.append(
            f'<li>视频 {escape(item.get("video_index") or "-")} / 帧 {escape(item.get("global_frame_index") or "-")} / '
            f'{escape(item.get("timestamp") or "-")}：{escape(item.get("process_type") or "uncertain")}，'
            f'质量 {escape(item.get("evidence_quality") or "-")}</li>'
        )
    unclassified = "、".join(str(index) for index in value.get("unclassified_image_indices") or []) or "无"
    return f"""
  <section class="panel minor-material-panel">
    <div class="section-head"><h2>未成年人退款五类材料核对</h2><p>材料存在性、字段一致性和最终退款裁决分开表达；报告不展示任何个人号码或OCR原文。</p></div>
    <div class="causality-grid">
      <article><small>申报图片</small><b>{escape(value.get("declared_image_count") or 0)}</b></article>
      <article><small>接收图片</small><b>{escape(value.get("accepted_image_count") or 0)}</b></article>
      <article><small>已处理图片</small><b>{escape(value.get("processed_image_count") or 0)}</b></article>
      <article><small>覆盖率</small><b>{escape(value.get("coverage_ratio") or 0)}</b></article>
      <article><small>覆盖是否完整</small><b>{escape("是" if value.get("coverage_complete") else "否")}</b></article>
      <article><small>流程准备度</small><b>{escape(value.get("readiness") or "-")}</b></article>
    </div>
    <p><b>未分类图片编号：</b>{escape(unclassified)}</p>
    <div class="boundary-grid">{"".join(checklist_cards) or '<p class="muted">本轮未形成材料清单。</p>'}</div>
    <h3>过程视频证据</h3><ul class="boundary-list">{"".join(process_items) or '<li>本轮没有形成可回链的过程视频证据。</li>'}</ul>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>隐私边界</h3><p>{escape(value.get("privacy_boundary") or "公开报告不展示个人敏感信息。")}</p></article>
      <article class="boundary-card"><h3>业务边界</h3><p>{escape(value.get("business_boundary") or "最终业务动作由授权人员执行。")}</p></article>
    </div>
  </section>"""
