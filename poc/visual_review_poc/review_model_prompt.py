from __future__ import annotations

import json
from typing import Any, Dict

from poc.visual_review_poc.continuity_model_prompt import build_object_continuity_prompt
from poc.visual_review_poc.damage_causality_model_prompt import build_damage_causality_prompt
from poc.visual_review_poc.minor_material_model_prompt import (
    build_minor_material_consistency_prompt,
    build_minor_material_inventory_prompt,
    build_minor_material_video_prompt,
)
from review_input_safety import sanitize_review_input


def build_opening_start_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    frames = [
        {
            "video_index": frame.get("video_index"),
            "global_frame_index": frame.get("global_frame_index"),
            "timestamp": frame.get("timestamp"),
        }
        for frame in safe_case.get("frames") or []
    ]
    return f"""只判断 sealed_start，不审核商品伤情、责任、订单或整段连续性。

首帧锚点：{json.dumps(frames, ensure_ascii=False)}

判定口径：
1. sealed：起始画面明确展示完整未拆封快递外包装，并能观察封口或封条仍保持闭合。
2. unsealed：起始画面已经是泡沫、气泡袋、商品内包装、裸露商品或已打开的快递包装；泡沫、气泡袋、商品内包装均不是完整未拆封快递外包装。
3. indeterminate：画面裁切、遮挡或清晰度不足，无法判断完整外包装及封口状态。
4. 面单可见不能替代封箱起始，也不能单独把结果判为 sealed。
5. evidence_refs 只能引用上方首帧锚点；sealed_start 必须与 result 一致：sealed=true、unsealed=false、indeterminate=null。
"""


def build_selection_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured_context = safe_case.get("structured_business_context") or {}
    analysis_mode = structured_context.get("analysis_mode")
    if analysis_mode == "minor_material_inventory":
        return build_minor_material_inventory_prompt(safe_case)
    if analysis_mode == "minor_material_process_video":
        return build_minor_material_video_prompt(safe_case)
    if analysis_mode == "minor_material_consistency":
        return build_minor_material_consistency_prompt(safe_case)
    if analysis_mode == "object_continuity_only":
        return build_object_continuity_prompt(safe_case)
    if analysis_mode == "damage_causality_only":
        return build_damage_causality_prompt(safe_case)
    frames = [
        {
            "global_frame_index": frame["global_frame_index"],
            "video_index": frame["video_index"],
            "timestamp": frame["timestamp"],
            "asset_ref": f"video_{frame['video_index']}_frame_{frame['global_frame_index']}",
        }
        for frame in safe_case["frames"]
    ]
    images = [
        {
            "image_index": image["image_index"],
            "asset_ref": f"supplemental_image_{image['image_index']}",
            "width": image.get("width"),
            "height": image.get("height"),
            "has_exif": image.get("has_exif"),
        }
        for image in safe_case["supplemental_images"]
    ]
    official_references = [
        {
            "reference_index": image.get("reference_index"),
            "reference_id": image.get("reference_id"),
            "item_ref": image.get("item_ref"),
            "sku": image.get("sku"),
            "product_name": image.get("product_name"),
            "asset_ref": f"official_product_reference_{image.get('reference_index')}",
            "evidence_role": "official_product_reference",
        }
        for image in safe_case.get("official_reference_images") or []
    ]
    videos = [
        {
            key: video.get(key)
            for key in ("video_index", "duration_seconds", "native_fps", "sampled_frames")
            if video.get(key) is not None
        }
        for video in safe_case.get("videos") or []
    ]
    native_video_instruction = ""
    if (structured_context.get("native_video_review") or {}).get("enabled") is True:
        native_video_instruction = """
原生视频实验规则：本请求直接提供原视频而不是预先抽帧。证据引用必须使用原生视频时间戳；global_frame_index 写 null，不得伪造抽帧编号。frame_findings 按关键时间点填写，不要求覆盖每秒；时间戳必须来自实际观察到的原视频内容。该规则仅覆盖下方关于“必须使用已提供帧编号”的格式要求，不放宽证据、业务边界或标签隔离规则。
"""
    return f"""请基于同一证据包进行售后视觉审核。

审核场景：{safe_case.get("scenario_label")}
用户诉求：{safe_case.get("customer_claim") or "未提供"}
订单/工单上下文：{json.dumps(safe_case.get("order_context") or {}, ensure_ascii=False)}
结构化业务上下文：{json.dumps(safe_case.get("structured_business_context") or {}, ensure_ascii=False)}
视频清单：{json.dumps(videos, ensure_ascii=False)}
送入模型的视频帧清单：{json.dumps(frames, ensure_ascii=False)}
送入模型的补充图片清单：{json.dumps(images, ensure_ascii=False)}
送入模型的官方商品参考图清单：{json.dumps(official_references, ensure_ascii=False)}
{native_video_instruction}

审核方法要求：
1. 先锁定本次诉求范围：只审核 claim_scope.active_claim_ids 指向的原子诉求；后续追加、已排除或没有绑定证据的诉求不得混入当前结论。未提供 claim_scope 时，只使用本次 customer_claim。
2. 再核对业务上下文：订单商品名、SKU、规格、角色、款式、数量、随机/盲抽规则，以及仓库/商品主数据。
3. 对所有视频按 video_index + global_frame_index + timestamp 做跨帧审查：箱子/商品是否持续在镜头内，是否离镜、跳切、遮挡、换手、剪辑或可能调包。
4. 对补充图片做交叉验证：是否能对应视频里的同一实物，是否有 EXIF、低分辨率、AI 水印、生成痕迹、局部裁剪或过度锐化风险。
4.1 官方商品参考图只用于核对订单 SKU、款式、正常外观和包装标识，不能作为用户开箱证据，不能单独证明用户实际收到、漏收或损伤的事实。
5. 必须同时写支持证据和反证/不确定性。证据足够时要敢于输出 positive 或 negative；证据不足才输出 review。
6. 只能引用已提供的帧编号和时间戳，不得编造不存在的时间点。
7. 样本目录名、人工结论、expected_predicted_label 没有提供给你；你只能根据本证据包独立判断。
8. 如果 structured_business_context.review_chunk 存在，本次只看到全视频的一个分段；分段最后一帧绝不等于视频结束，不得据此声称“视频结束于当前时间点”。
9. 不得把抽帧首尾覆盖写成“视频文件/时间轴完整”；抽帧只能说明送审首尾边界，容器、码流、时间戳和剪辑风险必须引用独立媒体取证结果。
10. 播放加速本身不等于拼接剪辑或视频不合规；加速本身只作为橙色风险信号。一镜到底且关键开箱过程完整时，不能仅凭加速判负；跳切、拼接、时间轴异常或关键过程缺失才是独立风险。默认 1 FPS 下若封箱起始、面单、连续拆封、争议商品连续性和伤情首次出现仍可判断，speed_review_impact.status 写 none；若关键证据受画面节奏影响而无法判断，写 uncertain 并列出 affected_review_items，交由服务端升级到 2 FPS 复核；只有在 2 FPS 强化复核后关键证据仍不可判断，才可写 material。不得仅凭加速推断用户责任或造假。
11. sealed_start 只有在视频起始明确展示完整未拆封快递外箱及封条时才写 true；泡沫、气泡袋或商品内包装不算封箱起点，面单可见不能补足 sealed_start。分段未覆盖某个开箱节点时，对应 opening_video_compliance 字段必须写 null，不能把“本段没看到”写成 false；false 只表示本段画面直接证明该硬要求不满足。
12. fulfillment_baseline.warehouse_verification 是服务端校验的甲方仓库事实，模型不得自行生成、修改或覆盖。pending 只表示过程待办；只有服务端认可的 confirmed_missing/confirmed_not_missing 可覆盖历史待核实备注，最终仍由服务端确定履约事实。
13. 多诉求案件必须对每个 active_claim_id 分别绑定 SKU/对象、证据时间点和事实结论，不能用一个总标签覆盖；整单结论只能在原子结果完整后聚合。

请严格输出 JSON 对象，字段：
- decision: pass / manual_review / request_more_material / fail。只表示 POC 流转，不代表业务裁决。
- predicted_label: positive / negative / review。
- system_yes_no: YES / NO / REVIEW。
- confidence: 0 到 1。
- overall_audit: 整体审核结论，必须包含 conclusion、confidence、core_reason、business_follow_up_suggestion。
- visual_evidence_verdict: 一句话视觉质检结论。
- visual_qc_conclusion: 视觉质检结论，必须包含 verdict、confidence、core_reason。
- confidence_reason: 置信度理由。
- video_audit_conclusion: 视频审核结论，必须包含 continuity_score、continuity_reason、swap_risk_level(high/medium/low)、edit_or_cut_risk、opening_integrity、playback_speed(normal/accelerated/unknown)、sampling_fps、speed_review_impact、opening_video_compliance。playback_speed 只表示从画面节奏观察到的正常、疑似加速或无法判断，不得猜测精确倍速。speed_review_impact 必须包含 status(none/uncertain/material)、critical_evidence_observable(true/false/null)、affected_review_items(只能从 sealed_start/waybill/opening_action/claimed_item_continuity/issue_first_visible 选择)、evidence_refs 和 reason；opening_video_compliance 必须包含 sealed_start、waybill_visible、single_take_continuity、issue_visible_in_continuous_opening（均为 true/false/null）、evidence_refs 和 result(compliant/noncompliant/indeterminate)。evidence_refs 使用扁平数组，每项必须含 field(sealed_start/waybill_visible/single_take_continuity/issue_visible_in_continuous_opening)、video_index、global_frame_index、timestamp；没有可回链证据时不得输出 material 或 false。
- object_continuity_assessment: 有视频时必填。必须分别定义并跟踪 shipping_package、product_package、claimed_item 等主体；包含 tracked_subjects 数组，每项含 subject_id、description、tracking_start、tracking_end、first_exposed_timestamp、visibility_coverage、out_of_frame_events。每个离镜事件必须含 start_timestamp、end_timestamp、duration_seconds、visibility(out_of_frame/occluded/unknown)、before_evidence、after_evidence、identity_reestablished、reason。顶层还要给 continuity_verdict(continuous/brief_occlusion/long_absence/indeterminate)、longest_out_of_frame_seconds、total_unobserved_seconds、critical_events。未从不透明包装中拆出的阶段写 not_yet_exposed，不算离镜；不能因为前后都再次出现就声称全程未离镜。
- customer_claim_parse: expected_item、claimed_received_item、claimed_mismatch_type。
- expected_order_item: 订单要求的商品/角色/SKU/规格/数量。
- actual_received_item: 实际收到的商品/角色/SKU/规格/数量或破损事实。
- audit_methods: 实际使用的审核方法数组。
- frame_findings: 只记录对结论有贡献的关键状态帧，不逐帧复述；至少覆盖主体首次可见、状态变化、争议首次可见、离镜/复入镜和末个可判断状态。每条必须含 video_index、global_frame_index、timestamp、visible_facts、risk、subject_visibility。subject_visibility 必须列出 shipping_package、product_package、claimed_item 三个 canonical subject_id 及其 state(visible/partial/occluded/out_of_frame/not_yet_exposed/unknown)；不知道时写 unknown，不得省略。
- adopted_evidence: 模型采信的关键证据数组，每项必须含 source_type、asset_ref、fact、why_it_matters、confidence，并按来源填写 video_index/global_frame_index、image_index 或 reference_index/reference_id；必须能回链到上方清单。仅补充图片证据填写 same_item_linkage、temporal_linkage 和 damage_visible（必须是 true/false，文字描述不能替代）；官方参考图的 source_type 必须是 official_product_reference，且不得表述为用户证据。
- supporting_evidence: 支持用户诉求的证据数组。
- challenging_evidence: 反证或风险数组。
- continuity_assessment: 多视频整体连续性、调包/剪辑风险。
- authenticity_assessment: 图片真实性、AI生成/水印/EXIF/低分辨率/裁剪风险，尤其商品有伤场景必须填写。
- size_sku_assessment: 发错货/发错尺寸场景填写；其他场景可写 null。
- issue_timestamps: 问题帧数组，只能使用上面帧清单中的时间戳。
- skeptical_questions: 你主动质疑自己结论的问题数组。
- material_gaps: 还缺什么材料。
- conclusion_argument: support、challenge、why_not_final_business_decision。
- business_action_allowed: false。
- human_required: true / false。只表示证据是否必须人工复核；不能因为退款、拒赔、补发等业务动作由甲方执行就强制写 true。
- business_follow_up_reason: 证据复核或业务流转原因；两者必须分开说明。
- next_step: 给甲方的 SOP 处理建议，可以明确建议支持、不支持、补件或安慰性补偿，但不得声称已经执行退款、拒赔、补发或定责。
- model_limitations: 局限。
- claim_fact_assessment: 商品有伤场景必填，其他场景可写 null。包含 atomic_claim_results、order_linkage、scene_match、assembly。atomic_claim_results 必须逐一覆盖每个 active_claim_id，每项包含 claim_id、subject_ref、support_status(supported/not_supported/insufficient)、evidence_refs、reason；order_linkage 包含 status(verified/failed/indeterminate)、expected_package_fact、observed_package_fact、evidence_refs、reason，只有明确包裹/承运标识冲突才写 failed，未提供订单归属材料不得猜成 failed；scene_match 包含 status(matched/mismatched/indeterminate)、claimed_scene、observed_scene、reason，包装来源/二次销售疑问不得混成商品实体有伤；assembly 包含 state(permanent_damage/resolved_assembly_issue/unresolved/not_applicable)、reassembly_result(successful/failed/not_tested/unknown)、permanent_damage(supported/not_supported/insufficient)、evidence_refs、reason，部件脱开不自动等于断裂，只有复装成功且未见断裂、缺料或不可逆形变才可写 resolved_assembly_issue。
- damage_causality_assessment: 仅商品有伤场景必填，其他场景写 null。必须包含 damage_presence(confirmed/not_visible/uncertain)、damage_type_and_location、first_visible_evidence(对象，含 video_index/global_frame_index/timestamp/asset_ref 或 image_index，以及明确的 damage_visible 布尔值)、pre_opening_state_visible、opening_action_visible、damage_change_observed、damage_timing(pre_opening_visible/appears_during_opening/post_opening_only/unknown)、possible_origins(数组，每项含 origin、confidence、supporting_evidence、challenging_evidence)、most_likely_origin(manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate)、origin_confidence、causal_evidence_level(direct/indirect/insufficient)、claim_support(supported/not_supported/insufficient)、appearance_difference(visible/not_visible/uncertain)、business_defect_qualification(confirmed/not_qualified/indeterminate)、special_product_rule(not_required/satisfied/required_but_not_quantified)、before_action_evidence/action_evidence/after_action_evidence(均为证据对象数组，每项含 video_index/global_frame_index/timestamp/subject/location/chain_id/fact，损伤帧还必须含 damage_visible，三段必须同对象同部位同 chain_id 且帧序递增)、alternative_explanations、cannot_conclude_reason。异形、软体、手工或材质特性商品的外观差异不自动等于业务缺陷；没有可执行的商品标准时必须保持 indeterminate。不得根据描述文字猜测损伤是否存在，也不得仅凭“看见有伤”或布尔自报推断损伤成因。
- damage_observability: 仅商品有伤场景必填。包含 status(fully_observable/partial/not_observable/unknown)、same_item_linkage、claimed_region_closeup、required_view_coverage(0-1)、conflicting_evidence、missing_views。只有争议部位特写清晰、与开箱商品确认同物、必检视角全部覆盖且视频/图片不冲突时，才可写 fully_observable。
- fulfillment_reconciliation: 仅发错货/漏发货必填，其他场景写 null。必须包含 baseline_version、expected_items、observed_items、suspected_missing_items、unexpected_items、unconfirmed_items、package_observations、package_coverage、all_packages_uploaded、all_items_displayed、evidence_timestamps、confidence、decision_boundary。每个清单项写 item_ref/SKU/名称/规格/应发数量/已识别数量/证据时间点；每个 package_observations 项写 package_ref、opening_complete、all_contents_laid_out、evidence_timestamps。没有服务端受信 warehouse_verification 时，缺少唯一应发基准、赠品或特典规则、分包关联，或视频未完整展示全部包裹和物品，predicted_label 必须是 review，decision_boundary 必须明确“证据不足，先补齐可获得的材料再复核”，不得直接认定发错或漏发，也不得仅因材料缺口强制占用人工席位。
"""
