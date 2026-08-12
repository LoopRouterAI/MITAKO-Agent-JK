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
    "claimed_item": "争议商品",
    "complete": "完整",
    "completed": "已完成",
    "not_applicable": "不适用",
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
    source_summary = assessment.get("evidence_source_summary") or {}
    primary_video = source_summary.get("primary_video") or {}
    supplemental = source_summary.get("supplemental_images") or {}
    main_video_presence = primary_video.get("damage_presence") or assessment.get("damage_presence")
    supplemental_presence = assessment.get("supplemental_damage_presence")
    supplemental_status = {
        "verified": "已建立关联，必须与主视频共同复核",
        "not_linked": "已明确未建立同物或过程关联",
        "unresolved": "同物、同部位和过程关联尚未解决，不能忽略该证据",
    }.get(supplemental.get("linkage_status"), "未提供或未完成关联分析")
    supplemental_findings = supplemental.get("evidence_findings") or []
    supplemental_findings_html = (
        '<h3>补充图片所见与关联判断</h3><div class="evidence-grid">'
        + evidence_renderer(supplemental_findings, media_gallery, "补充证据")
        + "</div>"
        if supplemental_findings
        else '<h3>补充图片所见与关联判断</h3><p class="muted">本轮没有形成可回链的补充图片事实，不能据此忽略补充证据。</p>'
    )
    key_evidence = assessment.get("key_evidence") or []
    key_evidence_html = (
        '<h3>关键帧审查链</h3><div class="evidence-grid">'
        + evidence_renderer(key_evidence, media_gallery, "关键审查帧")
        + "</div>"
        if key_evidence
        else '<h3>关键帧审查链</h3><p class="muted">本轮没有形成可回链的关键帧；因此不能声称已逐步证明结论。</p>'
    )
    source_breakdown_html = ""
    if source_summary:
        source_breakdown_html = f"""
    <h3>主视频与补充证据分层</h3>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>主视频</h3><p>范围：{escape(primary_video.get("scope") or "未说明")}</p><p>损伤存在性：{escape(_label(primary_video.get("damage_presence")))}</p><p>诉求支持度：{escape(_label(primary_video.get("claim_support")))}</p></article>
      <article class="boundary-card"><h3>用户补充证据</h3><p>补充图片 {escape(supplemental.get("provided_count") or 0)} 张；报告引用 {escape(supplemental.get("referenced_count") or 0)} 张。</p><p>补充图损伤所见：{escape(_label(supplemental_presence))}</p><p>{escape(supplemental_status)}</p></article>
    </div>
    <p><b>证据权重边界：</b>{escape(source_summary.get("decision_boundary") or "补充图片与主视频必须分别说明证据作用。")}</p>
    {supplemental_findings_html}
    {key_evidence_html}
"""

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
      <article><small>主视频损伤存在性</small><b>{escape(_label(main_video_presence))}</b></article>
      <article><small>首次出现阶段</small><b>{escape(_label(assessment.get("damage_timing")))}</b></article>
      <article><small>最可能原因</small><b>{escape(_label(assessment.get("most_likely_origin")))}</b></article>
      <article><small>因果证据等级</small><b>{escape(_label(assessment.get("causal_evidence_level")))}</b></article>
      <article><small>成因置信度</small><b>{escape(assessment.get("origin_confidence") if assessment.get("origin_confidence") is not None else "-")}</b></article>
      <article><small>诉求支持度</small><b>{escape(_label(assessment.get("claim_support")))}</b></article>
    </div>
    <p><b>损伤位置与类型：</b>{escape(assessment.get("damage_type_and_location") or "本轮未明确描述。")}</p>
    <p><b>过程锚点：</b>操作前状态 {escape("可见" if assessment.get("pre_opening_state_visible") else "不可见")}；拆封/操作动作 {escape("可见" if assessment.get("opening_action_visible") else "不可见")}；损伤变化 {escape("已观察到" if assessment.get("damage_change_observed") else "未形成直接观察")}</p>
    {source_breakdown_html}
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

    def event_duration_text(event: Dict[str, Any]) -> str:
        estimate = event.get("duration_seconds") or 0
        if event.get("duration_basis") != "sampled_source_timestamps":
            return f"{escape(estimate)} 秒"
        lower = event.get("duration_lower_bound_seconds")
        upper = event.get("duration_upper_bound_seconds")
        resolution = event.get("sampling_resolution_seconds")
        if lower is None:
            bounds = "边界未知"
        elif upper is None:
            bounds = f"至少 {escape(lower)} 秒，上界未知"
        else:
            bounds = f"{escape(lower)} 至 {escape(upper)} 秒"
        resolution_text = f"；采样分辨率 {escape(resolution)} 秒" if resolution is not None else ""
        return f"{escape(estimate)} 秒（采样边界估计；范围 {bounds}{resolution_text}）"

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
                f'{event_duration_text(event)}，{escape(event.get("visibility") or "unknown")}，{identity}。'
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
            f'<h3>{escape(subject.get("description") or _label(subject.get("subject_id")) or "未命名主体")}</h3>'
            f'<p><b>跟踪区间：</b>{escape(subject.get("tracking_start") or "-")} 至 {escape(subject.get("tracking_end") or "-")}</p>'
            f'<p><b>首次曝光：</b>{escape(subject.get("first_exposed_timestamp") or "-")}</p>'
            f'<p><b>可见覆盖率：</b>{escape(subject.get("visibility_coverage") if subject.get("visibility_coverage") is not None else "-")}</p>'
            f'<p><b>最长离镜估计：</b>{escape(subject.get("longest_out_of_frame_seconds") or 0)} 秒</p>'
            f'<ul class="boundary-list">{"".join(events) or "<li>未记录离镜事件。</li>"}</ul></article>'
            f'{evidence_html}'
        )
    policy = assessment.get("policy") or {}
    return f"""
  <section class="panel continuity-panel">
    <div class="section-head"><h2>主体连续性与离镜时间轴</h2><p>快递包装、商品包装和争议商品分别跟踪；尚未拆出不算离镜。</p></div>
    <div class="causality-grid">
      <article><small>连续性结论</small><b>{escape(_label(assessment.get("continuity_verdict")))}</b></article>
      <article><small>最长连续离镜估计</small><b>{escape(assessment.get("longest_out_of_frame_seconds") or 0)} 秒</b></article>
      <article><small>累计不可观察估计</small><b>{escape(assessment.get("total_unobserved_seconds") or 0)} 秒</b></article>
      <article><small>复核阈值</small><b>{escape(policy.get("out_of_frame_warning_seconds") or "-")} 秒</b></article>
    </div>
    <p>离镜秒数来自送审帧源时间戳，是采样边界估计，不是逐毫秒精确时长。</p>
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

    warehouse = value.get("warehouse_verification") or {}
    warehouse_status = {
        "confirmed_missing": "确认漏发",
        "confirmed_not_missing": "确认未漏发",
    }.get(warehouse.get("status"), "未提供终核")
    warehouse_cards = ""
    if value.get("resolution_basis") == "warehouse_verification" and warehouse:
        warehouse_cards = f"""
      <article><small>判断依据</small><b>仓库终核</b></article>
      <article><small>仓库结论</small><b>{escape(warehouse_status)}</b></article>
      <article><small>核实编号</small><b>{escape(warehouse.get("verification_ref") or "未提供")}</b></article>"""

    return f"""
  <section class="panel fulfillment-panel">
    <div class="section-head"><h2>应发与视频展示清单对账</h2><p>订单基准、实际识别和未确认项分开表达；证据不完整不直接认定发错或漏发。</p></div>
    <div class="causality-grid">
      <article><small>基准版本</small><b>{escape(value.get("baseline_version") or "未提供")}</b></article>
      <article><small>包裹是否全部提交</small><b>{escape("是" if value.get("all_packages_uploaded") else "否/未确认")}</b></article>
      <article><small>物品是否全部展示</small><b>{escape("是" if value.get("all_items_displayed") else "否/未确认")}</b></article>
      <article><small>物品观察自评分</small><b>{escape(value.get("observation_confidence") if value.get("observation_confidence") is not None else "-")}</b></article>
      <article><small>对账置信度</small><b>{escape(value.get("confidence") if value.get("confidence") is not None else "-")}</b></article>
      {warehouse_cards}
    </div>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>应发清单</h3><ul class="boundary-list">{items("expected_items", "未提供应发清单。")}</ul></article>
      <article class="boundary-card"><h3>视频已识别</h3><ul class="boundary-list">{items("observed_items", "视频中未形成可确认清单。")}</ul></article>
      <article class="boundary-card"><h3>疑似缺失</h3><ul class="boundary-list">{items("suspected_missing_items", "未形成疑似缺失项。")}</ul></article>
      <article class="boundary-card"><h3>未确认项</h3><ul class="boundary-list">{items("unconfirmed_items", "无额外未确认项。")}</ul></article>
    </div>
    <p><b>包裹覆盖：</b>{escape(value.get("package_coverage") or "未提供")}</p>
    <p><b>判断边界：</b>{escape(value.get("decision_boundary") or "最终业务动作仍由甲方规则执行。")}</p>
  </section>"""


def render_claim_fact_panel(value: Any, escape: Callable[[Any], str]) -> str:
    if not isinstance(value, dict):
        return ""
    status_labels = {
        "supported": "支持",
        "not_supported": "不支持",
        "insufficient": "证据不足",
        "verified": "已核验一致",
        "failed": "核验冲突",
        "matched": "场景匹配",
        "mismatched": "场景不匹配",
        "indeterminate": "尚不能确定",
        "resolved_assembly_issue": "可复位装配问题",
        "permanent_damage": "永久损伤",
        "successful": "复装成功",
        "not_tested": "未复装测试",
    }
    atomic_cards = []
    for item in (value.get("atomic_claim_results") or [])[:20]:
        if not isinstance(item, dict):
            continue
        atomic_cards.append(
            '<article class="boundary-card">'
            f'<h3>{escape(item.get("claim_id") or "未编号诉求")}</h3>'
            f'<p><b>争议对象：</b>{escape(item.get("subject_ref") or "未绑定")}</p>'
            f'<p><b>事实结论：</b>{escape(status_labels.get(item.get("support_status"), item.get("support_status") or "未给出"))}</p>'
            f'<p>{escape(item.get("reason") or "本轮未给出单项理由。")}</p></article>'
        )
    summary_cards = []
    for title, key, status_key in (
        ("订单/包裹归属", "order_linkage", "status"),
        ("诉求场景匹配", "scene_match", "status"),
        ("装配与永久损伤", "assembly", "state"),
    ):
        item = value.get(key) or {}
        if not isinstance(item, dict) or not item:
            continue
        status = item.get(status_key)
        details = item.get("reason") or item.get("permanent_damage") or "本轮未给出补充说明。"
        summary_cards.append(
            '<article class="boundary-card">'
            f'<h3>{escape(title)}</h3>'
            f'<p><b>状态：</b>{escape(status_labels.get(status, status or "未给出"))}</p>'
            f'<p>{escape(details)}</p></article>'
        )
    if not atomic_cards and not summary_cards:
        return ""
    return f"""
  <section class="panel claim-fact-panel product-only">
    <div class="section-head"><h2>原子诉求逐项核验</h2><p>每个诉求分别绑定商品对象和证据结论，整单标签不能覆盖单项差异。</p></div>
    <div class="boundary-grid">{"".join(atomic_cards) or '<p class="muted">本轮没有形成可展示的原子诉求结果。</p>'}</div>
    <h3>归属、场景与装配核验</h3>
    <div class="boundary-grid">{"".join(summary_cards) or '<p class="muted">本轮没有额外核验结果。</p>'}</div>
  </section>"""


def render_confidence_components_panel(value: Any, escape: Callable[[Any], str]) -> str:
    if not isinstance(value, dict):
        return ""
    if "material_image_coverage" in value:
        labels = (
            ("material_image_coverage", "图片处理完成度"),
            ("required_category_completeness", "五类材料完整度"),
            ("final_decision", "本轮证据分数"),
        )
    else:
        labels = (
            ("main_segment_mean", "主要证据分数"),
            ("damage_origin", "损伤来源判断"),
            ("fulfillment_reconciliation", "应发与实收对账"),
            ("continuity_visibility_coverage", "商品持续可见程度"),
            ("final_decision", "本轮证据分数"),
        )

    def display(raw: Any) -> str:
        if isinstance(raw, (int, float)) and 0 <= raw <= 1:
            return f"{round(raw * 100, 1)}%"
        return str(raw if raw is not None else "-")

    cards = "".join(
        f'<article><small>{escape(label)}</small><b>{escape(display(value.get(key)))}</b></article>'
        for key, label in labels
    )
    calibrated = not str(value.get("calibration_status") or "").startswith("uncalibrated")
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
    def evidence_links(indices: Any) -> str:
        links = []
        for raw in indices or []:
            try:
                index = int(raw)
            except (TypeError, ValueError):
                continue
            links.append(f'<a class="evidence-link" href="#image-{index}">图片 {index}</a>')
        return " ".join(links) or '<span class="muted">无</span>'

    def item_tone(item: dict) -> str:
        if item.get("validation_status") == "visual_relationship_link_unresolved":
            return "status-amber"
        if item.get("status") == "not_observed_after_full_scan" or item.get("validation_status") == "visual_consistency_mismatched":
            return "status-red"
        if item.get("status") == "present" and item.get("validation_status") == "visual_consistency_matched":
            return "status-green"
        return "status-amber"
    status_labels = {
        "present": "已识别到候选材料",
        "needs_manual_confirmation": "已观察到候选材料，按核对结果处理",
        "not_observed_after_full_scan": "全量扫描后尚未确认",
        "not_assessed": "尚未完成识别",
        "needs_manual_consistency_check": "可见主体与字段仍待核对",
        "needs_business_system_check": "需业务系统核对金额与订单",
        "confirmed_by_visual_category": "视觉类别已确认",
        "visual_consistency_matched": "视觉字段未发现明显矛盾",
        "visual_consistency_mismatched": "视觉字段存在冲突",
        "visual_consistency_uncertain": "视觉字段仍不确定",
        "visual_relationship_link_unresolved": "未建立直接监护关系，需补关系证明",
        "matched": "一致",
        "mismatched": "存在冲突",
        "uncertain": "不确定",
        "not_assessed": "未完成",
        "not_validated": "尚未验证",
        "usable": "清晰度满足视觉初审",
        "needs_manual_quality_check": "已提交，清晰度或完整页待确认",
        "not_observed": "未观察到",
    }
    checklist_cards = []
    for item in (value.get("checklist") or [])[:10]:
        if not isinstance(item, dict):
            continue
        checklist_cards.append(
            f'<article class="boundary-card status-card {item_tone(item)}">'
            f'<h3>{escape(item.get("label") or item.get("requirement_id") or "未命名材料")}</h3>'
            f'<p><b>材料状态：</b>{escape(status_labels.get(item.get("status"), item.get("status") or "未知"))}</p>'
            f'<p><b>材料质量：</b>{escape(status_labels.get(item.get("quality_status"), item.get("quality_status") or "未知"))}</p>'
            f'<p><b>核对结果：</b>{escape(status_labels.get(item.get("validation_status"), item.get("validation_status") or "未知"))}</p>'
            f'<p><b>点击回看：</b>{evidence_links(item.get("evidence_image_indices"))}</p>'
            f'<p>{escape(item.get("rule_note") or "")}</p></article>'
        )
    passport_cards = []
    passport_role_labels = {
        "guardian": "监护人",
        "minor": "未成年人",
        "unknown": "角色未知",
        "not_applicable": "不适用",
    }
    passport_readability_labels = {
        "clear": "清晰",
        "partial": "部分可读",
        "unknown": "未知",
    }
    for item in (value.get("material_inventory") or [])[:50]:
        if not isinstance(item, dict) or item.get("document_type") != "passport":
            continue
        country_or_region = str(item.get("issuing_country_or_region") or "unknown")
        readability = str(item.get("readability") or "unknown")
        passport_cards.append(
            '<article class="boundary-card status-card status-amber">'
            '<h3>护照</h3>'
            f'<p><b>材料角色：</b>{escape(passport_role_labels.get(str(item.get("subject_role") or "unknown"), "角色未知"))}</p>'
            f'<p><b>签发国家/地区：</b>{escape("未知" if country_or_region == "unknown" else country_or_region)}</p>'
            f'<p><b>可读性：</b>{escape(passport_readability_labels.get(readability, "未知"))}</p>'
            f'<p><b>点击回看：</b>{evidence_links([item.get("image_index")])}</p>'
            '<p>仅作视觉/OCR 初审并参与身份、年龄和监护关系一致性比较；不替代身份证必交项，不代表权威验真。</p>'
            '</article>'
        )
    process_items = []
    process_type_labels = {
        "invoice_generation": "发票或凭证生成过程",
        "document_capture": "资料拍摄过程",
        "payment_record": "支付记录展示",
        "other": "其他过程",
        "uncertain": "过程待确认",
    }
    quality_labels = {"clear": "清晰", "partial": "部分可见", "unreadable": "无法辨认"}
    for item in (value.get("process_evidence") or [])[:20]:
        if not isinstance(item, dict):
            continue
        process_items.append(
            f'<li>视频 {escape(item.get("video_index") or "-")} / 帧 {escape(item.get("global_frame_index") or "-")} / '
            f'{escape(item.get("timestamp") or "-")}：{escape(process_type_labels.get(item.get("process_type"), "过程待确认"))}，'
            f'画面{escape(quality_labels.get(item.get("evidence_quality"), "待确认"))}</li>'
        )
    unclassified = "、".join(str(index) for index in value.get("unclassified_image_indices") or []) or "无"
    check_labels = {
        "identity_age": "身份与年龄是否对得上",
        "guardian_relationship": "监护关系是否对得上",
        "commitment_signatures": "承诺书签署主体是否正确",
        "order_payment": "订单与支付材料是否对得上",
        "mobile_realname": "手机号实名归属材料是否对得上",
    }
    risk_labels = {
        "no_obvious_risk": "未发现明显编辑风险",
        "suspected_editing": "疑似编辑",
        "unreadable_fields": "字段不可读",
        "incomplete_document": "材料页面不完整",
        "conflicting_fields": "字段冲突",
        "evidence_gap": "证据不足",
    }
    consistency = value.get("field_consistency") or {}
    consistency_cards = []
    for item in consistency.get("checks") or []:
        if not isinstance(item, dict):
            continue
        risks = "、".join(
            risk_labels.get(str(code), str(code)) for code in item.get("risk_reason_codes") or []
        ) or "无"
        tone = "status-green" if item.get("status") == "matched" else "status-red" if item.get("status") == "mismatched" else "status-amber"
        consistency_cards.append(
            f'<article class="boundary-card status-card {tone}">'
            f'<h3>{escape(check_labels.get(item.get("check_id"), item.get("check_id") or "未命名检查"))}</h3>'
            f'<p><b>结果：</b>{escape(status_labels.get(item.get("status"), item.get("status") or "未知"))}</p>'
            f'<p><b>点击回看：</b>{evidence_links(item.get("evidence_image_indices"))}</p>'
            f'<p><b>需要注意：</b>{escape(risks)}</p>'
            f'<p>{escape(item.get("message") or "")}</p></article>'
        )
    authoritative = value.get("authoritative_verification") or {}
    authoritative_status = str(authoritative.get("status") or "")
    if authoritative_status == "customer_integration_required":
        authoritative_text = "本单已启用严格在线验真，尚待甲方核验能力"
        authoritative_tone = "status-red"
    elif authoritative_status == "not_configured_advisory":
        authoritative_text = "在线验真未配置，仅作非阻断提醒"
        authoritative_tone = "status-amber"
    else:
        authoritative_text = "在线验真默认关闭，不影响本轮视觉初审"
        authoritative_tone = "status-green"
    precheck_text = {
        "passed": "视觉初审通过",
        "failed": "视觉初审不通过",
        "needs_review": "有存疑项，请看标黄或标红图片",
        "incomplete": "资料未处理完整",
        "processing_incomplete": "系统处理未完成，请重试",
    }.get(value.get("visual_precheck_status"), "未完成")
    authenticity = value.get("authenticity_assessment") or {}
    authenticity_tone = {
        "critical": "status-red",
        "warning": "status-amber",
        "clear": "status-green",
    }.get(str(authenticity.get("severity") or ""), "status-amber")
    payment_capability = value.get("payment_capability_risk") or {}
    under_nine_review = payment_capability.get("requires_review") is True
    show_payment_card = any((
        payment_capability.get("low_age") is True,
        payment_capability.get("under_nine") is True,
        under_nine_review,
        payment_capability.get("requires_more_material") is True,
    ))
    payment_tone = "status-red" if under_nine_review else "status-amber" if payment_capability.get("requires_more_material") else "status-green" if payment_capability.get("process_evidence_status") == "matched" else "status-amber"
    payment_label = "未满 9 周岁，需人工关注支付能力" if under_nine_review else "需补支付过程说明" if payment_capability.get("requires_more_material") else "支付过程说明已核对" if payment_capability.get("process_evidence_status") == "matched" else "支付过程信息待确认"
    payment_card = (
        f'<article class="boundary-card status-card {payment_tone}"><h3>低龄支付过程核验</h3>'
        f'<p><b>{escape(payment_label)}</b></p><p>{escape(payment_capability.get("effect") or "该信号只用于核对支付密码来源和监护人发现消费过程，不自动决定退款结果。")}</p>'
        f'<p><b>点击回看：</b>{evidence_links(payment_capability.get("evidence_image_indices"))}</p></article>'
        if show_payment_card else ""
    )
    action_text = {
        "passed": "五类材料和可见字段均未发现明显问题，可按甲方现行一审流程继续。",
        "failed": "先打开标红图片确认冲突，再按 SOP 要求用户更正或补交对应材料。",
        "needs_review": "只检查标黄或标红项目；能确认一致时继续，不能确认时只补对应材料。",
        "processing_incomplete": "先重试系统处理，不要据此要求用户重复提交材料。",
    }.get(value.get("visual_precheck_status"), "按上方材料卡逐项处理，不要跳过未完成项目。")
    action_tone = {
        "passed": "status-green",
        "failed": "status-red",
        "needs_review": "status-amber",
        "processing_incomplete": "status-amber",
    }.get(value.get("visual_precheck_status"), "status-amber")
    if under_nine_review:
        action_text = "年龄判断为高置信未满 9 周岁；保持材料事实结论，但须由授权人员重点核对独立支付能力、支付密码来源和监护发现过程。"
        action_tone = "status-red"
    return f"""
  <section class="panel minor-material-panel">
    <div class="section-head"><h2>未成年人退款五类材料核对</h2><p>绿色可继续，黄色只看存疑项，红色优先复核；报告不展示姓名、号码或 OCR 原文。</p></div>
    <div class="causality-grid">
      <article><small>申报图片</small><b>{escape(value.get("declared_image_count") or 0)}</b></article>
      <article><small>接收图片</small><b>{escape(value.get("accepted_image_count") or 0)}</b></article>
      <article><small>已处理图片</small><b>{escape(value.get("processed_image_count") or 0)}</b></article>
      <article><small>图片处理完成度</small><b>{escape(round(float(value.get("coverage_ratio") or 0) * 100, 1))}%</b></article>
      <article><small>覆盖是否完整</small><b>{escape("是" if value.get("coverage_complete") else "否")}</b></article>
      <article><small>视觉初审结论</small><b>{escape(precheck_text)}</b></article>
    </div>
    <p><b>未分类图片编号：</b>{escape(unclassified)}</p>
    <div class="boundary-grid">{"".join(checklist_cards) or '<p class="muted">本轮未形成材料清单。</p>'}</div>
    <div class="section-head"><h2>护照视觉识别</h2><p>仅展示证件类型、签发国家/地区、可读性和图片编号。</p></div>
    <div class="boundary-grid">{"".join(passport_cards) or '<p class="muted">本轮未识别到护照材料。</p>'}</div>
    <div class="section-head"><h2>视觉字段一致性初审</h2><p>五项内容是否互相对得上；只比较图片中能看清的内容，不冒充政府、运营商或支付系统验真。</p></div>
    <p><b>总体状态：</b>{escape(status_labels.get(consistency.get("verdict"), consistency.get("verdict") or "未完成"))}</p>
    <div class="boundary-grid">{"".join(consistency_cards) or '<p class="muted">本轮未完成字段一致性初审。</p>'}</div>
    <div class="boundary-grid">
      <article class="boundary-card status-card {authenticity_tone}"><h3>图片真实性风险</h3><p><b>{escape(f'疑似修改风险 {authenticity["risk_percent"]}%' if authenticity.get("risk_percent") is not None else "本轮未形成可用风险分数")}</b></p><p>{escape(authenticity.get("conclusion") or "本轮没有可用的图片风险结果。")}</p><p><b>需优先回看：</b>{evidence_links(authenticity.get("evidence_image_indices"))}</p><p><b>编辑软件信息：</b>{evidence_links((authenticity.get("editor_metadata_image_indices") or [])[:20])}</p><p><b>缺少拍摄信息：</b>{evidence_links((authenticity.get("missing_exif_image_indices") or [])[:20])}</p><p>{escape(authenticity.get("boundary") or "缺少拍摄信息不等于图片造假。")}</p></article>
      {payment_card}
      <article class="boundary-card status-card {authoritative_tone}"><h3>外部在线验真</h3><p><b>{escape(authoritative_text)}</b></p><p>{escape(authoritative.get("boundary") or "视觉一致性不等于法定真实性，但未配置的接口不会阻断本轮初审。")}</p></article>
    </div>
    <h3>过程视频证据</h3><ul class="boundary-list">{"".join(process_items) or '<li>本轮没有形成可回链的过程视频证据。</li>'}</ul>
    <div class="boundary-grid">
      <article class="boundary-card"><h3>隐私边界</h3><p>{escape(value.get("privacy_boundary") or "公开报告不展示个人敏感信息。")}</p></article>
      <article class="boundary-card"><h3>业务边界</h3><p>{escape(value.get("business_boundary") or "最终业务动作由授权人员执行。")}</p></article>
    </div>
    <section class="human-action {action_tone}"><h3>客服接下来怎么做</h3><p>{escape(action_text)}</p></section>
  </section>"""
