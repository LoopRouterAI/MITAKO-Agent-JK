from __future__ import annotations

import json
from typing import Any, Dict, List


def build_object_continuity_prompt(case: Dict[str, Any]) -> str:
    frames: List[Dict[str, Any]] = []
    target_indices = {
        int(value)
        for value in ((case.get("structured_business_context") or {}).get("continuity_target_frame_indices") or [])
    }
    for frame in case.get("frames") or []:
        index = int(frame.get("global_frame_index") or 0)
        frames.append(
            {
                "role": "target" if not target_indices or index in target_indices else "context_only",
                "global_frame_index": index,
                "video_index": frame.get("video_index"),
                "timestamp": frame.get("timestamp"),
                "asset_ref": f"video_{frame.get('video_index')}_frame_{index}",
            }
        )

    return f"""你正在执行售后视频的独立主体连续性复核。本轮不判断商品是否有伤，不判断责任，不输出退款或拒赔结论。

场景：{case.get("scenario_label")}
用户诉求：{case.get("customer_claim") or "未提供"}
连续性策略：{json.dumps((case.get("structured_business_context") or {}).get("continuity_policy") or {}, ensure_ascii=False)}
按发送顺序排列的帧：{json.dumps(frames, ensure_ascii=False)}

主体定义必须保持稳定：
1. shipping_package：外层快递箱、快递袋或运输包装。
2. product_package：直接承载争议商品的最内层商品包装、扭蛋壳、密封袋或原包装；不能用外层快递箱替代。
3. claimed_item：用户投诉所指向的商品本体；未从不透明包装中出现前是 not_yet_exposed。

逐帧状态规则：
- visible：主体关键外观清楚可见。
- partial：主体仍在画面内但仅部分可见。
- occluded：主体位置仍在画面范围内，但被手、包装或其他物体短暂遮挡。
- out_of_frame：主体已经出现过，当前完整离开画面边界；不能因为之后重新出现就改写为持续可见。
- not_yet_exposed：主体尚未首次从不透明包装中出现，不属于离镜。
- unknown：无法区分以上状态。宁可写 unknown，不得把外层纸箱存在误写成商品包装存在。

每个目标帧还必须标注 opening_stage：
- sealed_package：外层包裹仍保持封闭、尚未开始拆封。
- opening_in_progress：正在拆快递包装或商品原包装。
- item_exposed：争议商品已首次从不透明包装中出现。
- contents_displayed：商品及本次争议相关内容已完成展示。
- post_opening：完成展示后的后续过程。
- unknown：本帧无法确认开箱阶段。不得用分段末帧冒充完整开箱结束。

只为 role=target 的每一帧输出一条 frame_findings，数量必须与 target 帧数完全一致，按 global_frame_index 升序。role=context_only 的帧只用于确认上一时段主体身份，不输出记录。每条必须逐一列出三个 canonical subject_id，不得省略。

严格输出 JSON 对象：
{{
  "frame_findings": [
    {{
      "video_index": 1,
      "global_frame_index": 1,
      "timestamp": "00:00.00",
      "opening_stage": "sealed_package/opening_in_progress/item_exposed/contents_displayed/post_opening/unknown",
      "visible_facts": "只写客观可见事实",
      "subject_visibility": [
        {{"subject_id": "shipping_package", "state": "visible", "reason": "可见依据"}},
        {{"subject_id": "product_package", "state": "not_yet_exposed", "reason": "可见依据"}},
        {{"subject_id": "claimed_item", "state": "not_yet_exposed", "reason": "可见依据"}}
      ]
    }}
  ],
  "object_continuity_assessment": {{
    "continuity_verdict": "continuous/brief_occlusion/long_absence/indeterminate",
    "critical_events": [],
    "limitations": "仅说明本帧组无法确认的内容"
  }}
}}
"""
