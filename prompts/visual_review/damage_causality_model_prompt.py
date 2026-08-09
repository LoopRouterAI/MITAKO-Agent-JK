from __future__ import annotations

import json
from typing import Any, Dict


def build_damage_causality_prompt(case: Dict[str, Any]) -> str:
    structured = case.get("structured_business_context") or {}
    frontdesk = structured.get("frontdesk_evidence_package") or {}
    product_standard = {
        "product_master_data": structured.get("product_master_data") or frontdesk.get("product_master_data") or {},
        "sop_context": structured.get("sop_context") or frontdesk.get("sop_context") or {},
    }
    targets = {int(value) for value in structured.get("causality_target_frame_indices") or []}
    frames = [
        {
            "role": "target" if not targets or int(frame.get("global_frame_index") or 0) in targets else "context_only",
            "global_frame_index": frame.get("global_frame_index"),
            "video_index": frame.get("video_index"),
            "timestamp": frame.get("timestamp"),
            "asset_ref": f"video_{frame.get('video_index')}_frame_{frame.get('global_frame_index')}",
        }
        for frame in case.get("frames") or []
    ]
    return f"""你正在执行商品有伤场景的独立动作因果复核。本轮只判断主视频中的损伤是否存在、何时出现以及可能由什么阶段造成，不作退款、拒赔或责任裁决。补充图片由主审核通道独立记录，本专项结果不得声称补充图片不存在。

用户诉求：{case.get("customer_claim") or "未提供"}
争议商品身份锚点：{json.dumps(structured.get("continuity_claim_identity") or {}, ensure_ascii=False)}
清洗后的用户消息：{json.dumps(frontdesk.get("conversation_history") or {}, ensure_ascii=False)}
视频窗口与原视频时间映射：{json.dumps(frontdesk.get("asset_manifest") or {}, ensure_ascii=False)}
商品主数据与版本化缺陷标准：{json.dumps(product_standard, ensure_ascii=False)}
按发送顺序排列的帧：{json.dumps(frames, ensure_ascii=False)}

审查纪律：
1. 先按争议商品身份锚点明确用户具体投诉的准确对象与部位，例如撕拉片、包装角、毛绒缝线或商品表面；若请求附带官方商品参考图，必须先核对主体图案、形状和规格。同品类但非同一件商品的损伤不得计入本次诉求；无法确认同物时只能写 uncertain。
2. 主动查找剪刀切割、手指撕扯、拉拽、挤压、碰撞、刮擦等动作，但仅看见工具或动作不能直接判定用户造成损伤。
3. 只有同一对象同一部位在动作前完好、动作中受到作用、动作后首次出现对应损伤，才可写 damage_change_observed=true 和 direct。
4. 若损伤在动作前已可见，不能归因于该动作；若前态被遮挡或分辨率不足，只能 indirect/insufficient。
5. role=context_only 只提供前序上下文；frame_findings 只输出 role=target 的帧，逐帧且不得省略。
6. 样本标签、人工答案和最终处置没有提供给你，不得猜测或迎合。
7. 必须区分“视频文件/时间轴完整”“开箱过程完整”和“争议商品持续可观察”；三者不能互相替代。
8. 异形、软体、手工或材质特性商品的外观差异不自动等于业务缺陷；必须分开记录可见外观差异和甲方商品标准是否足以认定缺陷，没有可执行标准时保持 indeterminate。

严格输出 JSON 对象：
{{
  "frame_findings": [
    {{
      "video_index": 1,
      "global_frame_index": 1,
      "timestamp": "00:00.00",
      "visible_facts": "客观事实",
      "action": "none/cut/tear/pull/squeeze/impact/scratch/other",
      "affected_object": "对象",
      "affected_location": "具体部位",
      "damage_state": "not_visible/visible/uncertain",
      "why_it_matters": "该帧对前态、动作或后态的作用"
    }}
  ],
  "damage_causality_assessment": {{
    "damage_presence": "confirmed/not_visible/uncertain",
    "damage_type_and_location": "对象与具体部位",
    "first_visible_evidence": {{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject": "准确商品", "location": "具体部位", "fact": "该帧直接可见的损伤事实", "damage_visible": true}},
    "pre_opening_state_visible": false,
    "opening_action_visible": false,
    "damage_change_observed": false,
    "damage_timing": "pre_opening_visible/appears_during_opening/post_opening_only/unknown",
    "possible_origins": [{{"origin": "manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate", "confidence": 0.0, "supporting_evidence": "", "challenging_evidence": ""}}],
    "most_likely_origin": "manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate",
    "origin_confidence": 0.0,
    "causal_evidence_level": "direct/indirect/insufficient",
    "claim_support": "supported/not_supported/insufficient",
    "appearance_difference": "visible/not_visible/uncertain",
    "business_defect_qualification": "confirmed/not_qualified/indeterminate",
    "special_product_rule": "not_required/satisfied/required_but_not_quantified",
    "before_action_evidence": [{{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "动作前状态"}}],
    "action_evidence": [{{"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "作用动作"}}],
    "after_action_evidence": [{{"video_index": 1, "global_frame_index": 3, "timestamp": "00:02.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "动作后直接可见的损伤", "damage_visible": true}}],
    "alternative_explanations": [],
    "cannot_conclude_reason": "无法闭环时明确缺口"
  }},
  "damage_observability": {{
    "status": "fully_observable/partial/not_observable/unknown",
    "same_item_linkage": false,
    "claimed_region_closeup": false,
    "required_view_coverage": 0.0,
    "conflicting_evidence": false,
    "missing_views": []
  }}
}}

判定纪律：
- first_visible_evidence.damage_visible 必须明确填写 true 或 false，不得省略；描述文字只用于人工阅读，不能替代该布尔字段。
- claim_support 表示证据是否支持用户诉求；确认损伤由用户操作造成时可写 not_supported，它与“损伤是否存在”是两个独立字段。
- same_item_linkage 只有在争议商品与开箱过程中的同一商品已由画面证据关联时才可写 true。
- damage_visible 或 same_item_linkage 任一条件不成立时，damage_presence 必须写 uncertain 或 not_visible，不得输出已确认伤情。
"""
