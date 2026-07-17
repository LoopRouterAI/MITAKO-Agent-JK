from __future__ import annotations

import json
from typing import Any, Dict

from poc.visual_review_poc.continuity_model_prompt import build_object_continuity_prompt
from poc.visual_review_poc.damage_causality_model_prompt import build_damage_causality_prompt
from review_input_safety import sanitize_review_input


def build_selection_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    if (safe_case.get("structured_business_context") or {}).get("analysis_mode") == "object_continuity_only":
        return build_object_continuity_prompt(safe_case)
    if (safe_case.get("structured_business_context") or {}).get("analysis_mode") == "damage_causality_only":
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
    videos = [
        {
            key: video.get(key)
            for key in ("video_index", "duration_seconds", "native_fps", "sampled_frames")
            if video.get(key) is not None
        }
        for video in safe_case.get("videos") or []
    ]
    return f"""请基于同一证据包进行售后视觉审核。

审核场景：{safe_case.get("scenario_label")}
用户诉求：{safe_case.get("customer_claim") or "未提供"}
订单/工单上下文：{json.dumps(safe_case.get("order_context") or {}, ensure_ascii=False)}
结构化业务上下文：{json.dumps(safe_case.get("structured_business_context") or {}, ensure_ascii=False)}
证据资源字段说明：{json.dumps(safe_case.get("evidence_assets") or [], ensure_ascii=False)}
视频清单：{json.dumps(videos, ensure_ascii=False)}
送入模型的视频帧清单：{json.dumps(frames, ensure_ascii=False)}
送入模型的补充图片清单：{json.dumps(images, ensure_ascii=False)}

审核方法要求：
1. 先锁定本次诉求范围：只审核 claim_scope.active_claim_ids 指向的原子诉求；后续追加、已排除或没有绑定证据的诉求不得混入当前结论。未提供 claim_scope 时，只使用本次 customer_claim。
2. 再核对业务上下文：订单商品名、SKU、规格、角色、款式、数量、随机/盲抽规则，以及仓库/商品主数据。
3. 对所有视频按 video_index + global_frame_index + timestamp 做跨帧审查：箱子/商品是否持续在镜头内，是否离镜、跳切、遮挡、换手、剪辑或可能调包。
4. 对补充图片做交叉验证：是否能对应视频里的同一实物，是否有 EXIF、低分辨率、AI 水印、生成痕迹、局部裁剪或过度锐化风险。
5. 必须同时写支持证据和反证/不确定性。证据足够时要敢于输出 positive 或 negative；证据不足才输出 review。
6. 只能引用已提供的帧编号和时间戳，不得编造不存在的时间点。
7. 样本目录名、人工结论、expected_predicted_label 没有提供给你；你只能根据本证据包独立判断。
8. 如果 structured_business_context.review_chunk 存在，本次只看到全视频的一个分段；分段最后一帧绝不等于视频结束，不得据此声称“视频结束于当前时间点”。

请严格输出 JSON 对象，字段：
- decision: pass / manual_review / request_more_material / fail。只表示 POC 流转，不代表业务裁决。
- predicted_label: positive / negative / review。
- system_yes_no: YES / NO / REVIEW。
- confidence: 0 到 1。
- overall_audit: 整体审核结论，必须包含 conclusion、confidence、core_reason、business_follow_up_suggestion。
- visual_evidence_verdict: 一句话视觉质检结论。
- visual_qc_conclusion: 视觉质检结论，必须包含 verdict、confidence、core_reason。
- confidence_reason: 置信度理由。
- video_audit_conclusion: 视频审核结论，必须包含 continuity_score、continuity_reason、swap_risk_level(high/medium/low)、edit_or_cut_risk、opening_integrity。
- object_continuity_assessment: 有视频时必填。必须分别定义并跟踪 shipping_package、product_package、claimed_item 等主体；包含 tracked_subjects 数组，每项含 subject_id、description、tracking_start、tracking_end、first_exposed_timestamp、visibility_coverage、out_of_frame_events。每个离镜事件必须含 start_timestamp、end_timestamp、duration_seconds、visibility(out_of_frame/occluded/unknown)、before_evidence、after_evidence、identity_reestablished、reason。顶层还要给 continuity_verdict(continuous/brief_occlusion/long_absence/indeterminate)、longest_out_of_frame_seconds、total_unobserved_seconds、critical_events。未从不透明包装中拆出的阶段写 not_yet_exposed，不算离镜；不能因为前后都再次出现就声称全程未离镜。
- customer_claim_parse: expected_item、claimed_received_item、claimed_mismatch_type。
- expected_order_item: 订单要求的商品/角色/SKU/规格/数量。
- actual_received_item: 实际收到的商品/角色/SKU/规格/数量或破损事实。
- audit_methods: 实际使用的审核方法数组。
- frame_findings: 每帧一句客观观察，必须含 video_index、global_frame_index、timestamp、visible_facts、risk、subject_visibility。subject_visibility 必须逐帧列出 shipping_package、product_package、claimed_item 三个 canonical subject_id 及其 state(visible/partial/occluded/out_of_frame/not_yet_exposed/unknown)；不知道时写 unknown，不得省略。
- adopted_evidence: 模型采信的关键证据数组，每项必须含 source_type、video_index、global_frame_index 或 image_index、timestamp、asset_ref、fact、why_it_matters、confidence；必须能回链到上方帧清单或补充图片清单。
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
- human_required: true。
- business_follow_up_reason: 人工跟进原因。
- next_step: 后续VIP客服建议，不直接退款、拒赔、补发或定责。
- model_limitations: 局限。
- damage_causality_assessment: 仅商品有伤场景必填，其他场景写 null。必须包含 damage_presence(confirmed/not_visible/uncertain)、damage_type_and_location、first_visible_evidence(对象，含 video_index/global_frame_index/timestamp/asset_ref 或 image_index)、pre_opening_state_visible、opening_action_visible、damage_change_observed、damage_timing(pre_opening_visible/appears_during_opening/post_opening_only/unknown)、possible_origins(数组，每项含 origin、confidence、supporting_evidence、challenging_evidence)、most_likely_origin(manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate)、origin_confidence、causal_evidence_level(direct/indirect/insufficient)、claim_support(supported/not_supported/insufficient)、before_action_evidence/action_evidence/after_action_evidence(均为证据对象数组，每项含 video_index/global_frame_index/timestamp/subject/location/chain_id/fact，三段必须同对象同部位同 chain_id 且帧序递增)、alternative_explanations、cannot_conclude_reason。不得仅凭“看见有伤”或布尔自报推断损伤成因。
- damage_observability: 仅商品有伤场景必填。包含 status(fully_observable/partial/not_observable/unknown)、same_item_linkage、claimed_region_closeup、required_view_coverage(0-1)、conflicting_evidence、missing_views。只有争议部位特写清晰、与开箱商品确认同物、必检视角全部覆盖且视频/图片不冲突时，才可写 fully_observable。
- fulfillment_reconciliation: 仅发错货/漏发货必填，其他场景写 null。必须包含 baseline_version、expected_items、observed_items、suspected_missing_items、unexpected_items、unconfirmed_items、package_observations、package_coverage、all_packages_uploaded、all_items_displayed、evidence_timestamps、confidence、decision_boundary。每个清单项写 item_ref/SKU/名称/规格/应发数量/已识别数量/证据时间点；每个 package_observations 项写 package_ref、opening_complete、all_contents_laid_out、evidence_timestamps。缺少唯一应发基准、赠品或特典规则、分包关联，或视频未完整展示全部包裹和物品时，predicted_label 必须是 review，decision_boundary 必须明确“证据不足，人工复核”，不得直接认定发错或漏发。
"""
