from __future__ import annotations

import json
from typing import Any, Dict


def build_damage_causality_prompt(case: Dict[str, Any]) -> str:
    structured = case.get("structured_business_context") or {}
    frontdesk = structured.get("frontdesk_evidence_package") or {}
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
    return f"""你正在执行商品有伤场景的独立动作因果复核。本轮只判断损伤是否存在、何时出现以及可能由什么阶段造成，不作退款、拒赔或责任裁决。

用户诉求：{case.get("customer_claim") or "未提供"}
清洗后的用户消息：{json.dumps(frontdesk.get("conversation_history") or {}, ensure_ascii=False)}
视频窗口与原视频时间映射：{json.dumps(frontdesk.get("asset_manifest") or {}, ensure_ascii=False)}
按发送顺序排列的帧：{json.dumps(frames, ensure_ascii=False)}

审查纪律：
1. 先明确用户具体投诉的对象与部位，例如撕拉片、包装角、毛绒缝线或商品表面；不同部位不得混成一条因果链。
2. 主动查找剪刀切割、手指撕扯、拉拽、挤压、碰撞、刮擦等动作，但仅看见工具或动作不能直接判定用户造成损伤。
3. 只有同一对象同一部位在动作前完好、动作中受到作用、动作后首次出现对应损伤，才可写 damage_change_observed=true 和 direct。
4. 若损伤在动作前已可见，不能归因于该动作；若前态被遮挡或分辨率不足，只能 indirect/insufficient。
5. role=context_only 只提供前序上下文；frame_findings 只输出 role=target 的帧，逐帧且不得省略。
6. 样本标签、人工答案和最终处置没有提供给你，不得猜测或迎合。

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
    "first_visible_evidence": "可回链帧",
    "pre_opening_state_visible": false,
    "opening_action_visible": false,
    "damage_change_observed": false,
    "damage_timing": "pre_opening_visible/appears_during_opening/post_opening_only/unknown",
    "possible_origins": [{{"origin": "manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate", "confidence": 0.0, "supporting_evidence": "", "challenging_evidence": ""}}],
    "most_likely_origin": "manufacturing_or_original_packaging/logistics_transport/customer_opening_or_handling/mixed/indeterminate",
    "origin_confidence": 0.0,
    "causal_evidence_level": "direct/indirect/insufficient",
    "claim_support": "supported/not_supported/insufficient",
    "before_action_evidence": [{{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "动作前状态"}}],
    "action_evidence": [{{"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "作用动作"}}],
    "after_action_evidence": [{{"video_index": 1, "global_frame_index": 3, "timestamp": "00:02.00", "subject": "对象", "location": "具体部位", "chain_id": "chain-1", "fact": "动作后状态"}}],
    "alternative_explanations": [],
    "cannot_conclude_reason": "无法闭环时明确缺口"
  }}
}}
"""
