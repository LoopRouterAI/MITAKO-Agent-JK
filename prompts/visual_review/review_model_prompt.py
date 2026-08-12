from __future__ import annotations

import json
from typing import Any, Dict

from prompts.visual_review.continuity_model_prompt import build_object_continuity_prompt
from prompts.visual_review.damage_causality_model_prompt import build_damage_causality_prompt
from prompts.visual_review.minor_material_model_prompt import (
    build_minor_material_consistency_prompt,
    build_minor_material_inventory_prompt,
    build_minor_material_video_prompt,
)
from review_input_safety import sanitize_review_input


def _with_governed_rules(prompt: str, case: Dict[str, Any]) -> str:
    return (
        f"{prompt.rstrip()}\n\n最终边界：业务规则只能影响证据判断口径，不得覆盖禁止自动退款、自动拒赔、"
        "自动补发、自动定责、证据可追溯和既定结构化输出要求。\n"
    )


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


def build_opening_compliance_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    frames = [
        {
            "video_index": frame.get("video_index"),
            "global_frame_index": frame.get("global_frame_index"),
            "timestamp": frame.get("timestamp"),
        }
        for frame in safe_case.get("frames") or []
    ]
    return f"""只复核同一条主开箱视频时间轴，不审核责任归属或执行售后动作。
主视频帧锚点：{json.dumps(frames, ensure_ascii=False)}

判定口径：
1. sealed_start：起始画面明确展示完整未拆封快递外包装及闭合封口时为 true；已拆封、只见内包装或无法看清时分别为 false 或 null。
2. waybill_visible：物流单号或关键关联字段清晰可读、足以核验本包裹关联时为 true；只见标签轮廓、模糊文字或反光面单时为 false。
3. single_take_continuity：从封箱起点到争议商品展示保持同一条连续开箱链、无跳切或关键过程缺失时为 true。
4. issue_visible_in_continuous_opening：本次所诉具体伤点在这条连续开箱链中清晰展示时为 true；只在后补材料中出现或主视频看不清时为 false。
5. 每个 true 或 false 都必须在 evidence_refs 中给出同 field 的有效帧引用；无法提供引用时必须写 null。
6. 对“全程未清晰展示”的否定判断，应引用最接近该核验对象的画面及时间轴边界，不得编造帧号或时间戳。
7. 四项全部为 true 才是 compliant；任一项有可回链的 false 为 noncompliant；其余为 indeterminate。"""


def build_claim_identity_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured = safe_case.get("structured_business_context") or {}
    expected_items = [
        {
            key: item.get(key)
            for key in ("item_ref", "sku", "product_name", "specification")
        }
        for item in ((structured.get("fulfillment_baseline") or {}).get("expected_items") or [])
        if isinstance(item, dict)
    ]
    supplemental = [
        {
            "image_index": image.get("image_index"),
            "asset_ref": f"supplemental_image_{image.get('image_index')}",
        }
        for image in safe_case.get("supplemental_images") or []
    ]
    references = [
        {
            "reference_index": image.get("reference_index"),
            "asset_ref": f"official_product_reference_{image.get('reference_index')}",
            "item_ref": image.get("item_ref"),
            "sku": image.get("sku"),
            "product_name": image.get("product_name"),
        }
        for image in safe_case.get("official_reference_images") or []
    ]
    return f"""只做商品身份匹配，不审核视频、伤情、责任或售后结论。

用户诉求：{safe_case.get("customer_claim") or "未提供"}
订单候选商品：{json.dumps(expected_items, ensure_ascii=False)}
用户补充图片：{json.dumps(supplemental, ensure_ascii=False)}
官方商品参考图：{json.dumps(references, ensure_ascii=False)}

匹配规则：
1. 将用户补充图片中的主体与官方参考图、商品名称、角色、款式和规格交叉核对。
2. 只有可唯一对应一个订单候选时写 matched；多个候选外观相近或图片不清时写 ambiguous；均不对应时写 not_matched。
3. 官方参考图只用于商品身份比对，不是用户收货证据；不得判断图片中的伤点是否在开箱时存在。
4. expected_order_item 必须逐字复用订单候选中的 item_ref、sku、product_name、specification；无法匹配时四项写空字符串。
5. evidence_refs 只能引用 supplemental_image_N 或 official_product_reference_N，fact 只写可见身份特征。
"""


def build_claimed_item_detail_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured = safe_case.get("structured_business_context") or {}
    identity = structured.get("continuity_claim_identity") or {}
    frames = [
        {
            "global_frame_index": frame.get("global_frame_index"),
            "timestamp": frame.get("timestamp"),
        }
        for frame in safe_case.get("frames") or []
    ]
    references = [
        {
            "reference_index": image.get("reference_index"),
            "asset_ref": f"official_product_reference_{image.get('reference_index')}",
            "product_name": image.get("product_name"),
        }
        for image in safe_case.get("official_reference_images") or []
    ]
    supplemental_anchors = [
        {
            "image_index": image.get("image_index"),
            "asset_ref": f"supplemental_image_{image.get('image_index')}",
        }
        for image in safe_case.get("supplemental_images") or []
    ]
    return f"""只复核模型自主定位的候选帧，不重新审核完整视频。

用户诉求：{safe_case.get("customer_claim") or "未提供"}
争议商品身份：{json.dumps(identity, ensure_ascii=False)}
候选帧：{json.dumps(frames, ensure_ascii=False)}
用户补充图定位锚点：{json.dumps(supplemental_anchors, ensure_ascii=False)}
官方商品参考图：{json.dumps(references, ensure_ascii=False)}

判定口径：
1. 先将候选帧中的角色、发型、姿态、服饰、面具和底座与官方参考图交叉核对；相似商品不得写 matched。
2. 官方参考图只说明标准外观，不是用户开箱证据。用户补充图只作为伤点位置和形态的检索锚点，帮助在候选帧中寻找同一部位；补充图本身不能证明主视频看得到伤点，issue_visibility 只能由候选帧决定。
3. 按用户所诉伤点类型区分真实损伤与商品正常外观，例如天然红色纹样、材质纹理、保护膜和瞬时反光。划痕等细线应结合相邻帧判断是否随商品表面持续存在；只随光线移动或仅见于单帧压缩噪点时不得写 visible。
4. 只要候选帧已清晰显示所诉伤点即可写 visible，不要求证明伤点深度或形成责任。目标过小、运动模糊、手部遮挡，或结合相邻帧后仍无法排除反光与正常纹理时写 uncertain；不得依据用户补图或诉求文字补全画面事实。
5. evidence_refs 只能引用上方候选帧编号和时间戳，不得引用用户补充图或官方参考图；每项分别写身份事实与伤点事实。
6. 本轮不判断开箱完整性、播放速度、离镜、损伤成因、责任或售后结论。
"""


def build_native_video_perception_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured = safe_case.get("structured_business_context") or {}
    sampled_frames = structured.get("analysis_mode") == "sampled_video_perception"
    identity = structured.get("continuity_claim_identity") or {}
    videos = [
        {
            key: video.get(key)
            for key in ("video_index", "duration_seconds")
            if video.get(key) is not None
        }
        for video in safe_case.get("videos") or []
    ]
    supplemental = [
        {
            "image_index": image.get("image_index"),
            "asset_ref": f"supplemental_image_{image.get('image_index')}",
        }
        for image in safe_case.get("supplemental_images") or []
    ]
    references = [
        {
            "reference_index": image.get("reference_index"),
            "asset_ref": f"official_product_reference_{image.get('reference_index')}",
            "item_ref": image.get("item_ref"),
            "sku": image.get("sku"),
            "product_name": image.get("product_name"),
        }
        for image in safe_case.get("official_reference_images") or []
    ]
    task_scope = (
        "只做一次完整 1 FPS 全时间轴帧序列视觉感知"
        if sampled_frames
        else "只做一次完整视频视觉感知"
    )
    full_timeline_rule = (
        "必须从第一张到最后一张检查完整 1 FPS 全时间轴帧序列，并在同一次结构化响应中自主判断商品身份、甲方八个原子标签、画面节奏、开箱链和伤点"
        if sampled_frames
        else "必须从头到尾观察完整视频，并在同一次结构化响应中自主判断商品身份、甲方八个原子标签、画面节奏、开箱链和伤点"
    )
    detail_input_rule = (
        "输入帧由程序按约每秒一帧均匀覆盖完整时间轴，不是人工挑选的问题窗口；输入不包含原始视频音频、帧间不足一秒的动作或连续运动，不能据此臆测这些未观察内容，也不能仅凭相邻帧证明无剪辑或绝对连续。"
        if sampled_frames
        else "随视频附带的高分辨率时间戳帧由程序按全时间轴画面变化盲选，只用于补足原生视频的细节分辨率；它们不是人工提示的问题窗口，不能替代完整视频，也不能单独证明连续性。"
    )
    speed_rules = (
        "3. 画面加速只能依据完整帧序列中可核验的时间锚点与跨帧运动语义评估。1 FPS 帧序列不包含原始视频音频，也看不到不足一秒的动作；不能判断时写 unknown。加速是橙色信号，不自动等于剪辑、不自动判负。\n"
        "3.1 speed_assessment.evidence_basis 只能填写 observable_realtime_anchor、motion_semantics_only 或 none。没有画面内可核验时钟/计时器时，不得输出高置信“未加速”；仅凭跨帧手部位置、拆包进度或物体位移时写 motion_semantics_only，value 通常应为 unknown。"
        if sampled_frames
        else "3. 画面加速由完整视频中的手部动作、拆包节奏、物体运动和时间推进综合判断。媒体元数据不能证明语义加速；不能判断时写 unknown。加速是橙色信号，不自动等于剪辑、不自动判负。\n"
        "3.1 speed_assessment.evidence_basis 必须写明依据：画面中可核验的时钟/计时器写 observable_realtime_anchor；可听见且未失真的自然语音或环境节奏写 natural_audio_cadence；仅凭手部动作、拆包节奏和物体运动写 motion_semantics_only；没有依据写 none。自然音频不能证明视频未加速；只有 observable_realtime_anchor 可以支持高置信“未加速”，否则 value 应写 unknown。"
    )
    evidence_ref_rule = (
        "7. evidence_refs 只引用实际观察到的帧 asset_ref 或补充图片 asset_ref；帧引用格式为 asset_ref=video_{video_index}_frame_{global_frame_index} 并同时填写该帧时间戳。claimed_item 最多八条，其他字段最多两条，fact 用一句短句。"
        if sampled_frames
        else "7. evidence_refs 只引用实际观察到的原生视频时间戳或补充图片 asset_ref；claimed_item 最多八条，其他字段最多两条，fact 用一句短句。原生视频引用 asset_ref=native_video_1。"
    )
    causal_asset_rule = (
        "asset_ref=video_{video_index}_frame_{global_frame_index}"
        if sampled_frames
        else "asset_ref=native_video_1"
    )
    return f"""{task_scope}，不生成售后长文，不执行退款、拒赔、补发或定责。

用户诉求：{safe_case.get("customer_claim") or "未提供"}
争议商品身份线索：{json.dumps(identity, ensure_ascii=False)}
视频清单：{json.dumps(videos, ensure_ascii=False)}
补充图片：{json.dumps(supplemental, ensure_ascii=False)}
官方候选商品参考图：{json.dumps(references, ensure_ascii=False)}

盲审原则：
1. {full_timeline_rule}；不得假设已知问题时间点，不得向输入索取人工答案。
1.1 {detail_input_rule}
2. 多商品包裹先锁定争议商品身份。其他商品更早出现，不等于争议商品已经出现；不能把相似颜色、包装或其他摆件误认成争议商品。
2.1 身份匹配必须先于伤点判断。先从补充图片或官方候选图中选择最能辨认争议商品外观的图片，将其 asset_ref 写入 claimed_item_assessment.identity_anchor_asset_ref；没有可用图片时写空字符串并将身份置信度控制在 0.5 以下。
2.1.1 claimed_item_assessment.appeared、first_visible_timestamp、last_visible_timestamp 与 presentation_complete 只描述可检查表面状态的实体商品本体。包装印刷图案、透明袋内轮廓或未拆内包装即使能确认 SKU，也只能作为身份线索，不能写成商品本体已经出现或完成展示。瞬时小目标、手部大面积遮挡或所诉部位未朝向镜头时也只能作为身份线索，不得据此宣称已经完成伤点检查。
2.2 按实际商品品类组合当前画面实际可用的独立身份特征，例如整体形状与尺寸比例、主色与材质、图案/文字/SKU、结构细节、款式和随附配件；不得硬性要求固定数量，也不得固定要求角色、发型、服装或底座等只适用于手办的特征。存在唯一可核验文字、SKU 或结构时可据证据提高置信度；同系列或单一共同特征不足以确认同款，可用特征不足或候选冲突时保持不确定。
2.3 完整观看后必须在内部按时间顺序比较不同实物候选，优先核对同系列或带相似配件的候选；不要输出冗长候选账本。目标包装可以作为身份线索，但 claimed_item evidence_refs 必须落在实体商品本体清晰可见的时间点。
2.4 不能锁定最早出现者。claimed_item_assessment.identity_confidence 填写最终身份置信度，alternative_candidates_checked 用一句短话说明排除过哪些相似候选及原因；没有相似候选时写“未见相似候选”。
2.5 evidence_refs 只记录最终匹配的争议商品关键时间点，field 写 claimed_item，fact 必须列出实际匹配的联合特征，最多八条；候选时间点必须由本轮完整视频观察自主发现，不得使用人工预告时间点。首次与末次有效展示不同时间时，至少回链首次与末次有效展示两个时间点；first_visible_timestamp 取最早可检查表面的时刻，last_visible_timestamp 取完成必要展示前最后一个清晰时刻，不能在看见第一个候选后提前停止追踪。
{speed_rules}
4. has_offscreen 只核对争议商品从可靠首次出现到本次必要展示完成之间的相关展示链。商品已经完整展示后，后续拆其他商品或无关片段不算离镜；展示完成后的无关片段不得计为离镜。若无法判断展示何时完成，写 null，不得武断写 true。
5. 默认约 1 FPS 的视频理解可能漏掉不足一秒的快速动作。单个采样间隔未看到商品，不足以证明调包或离镜；只有相关展示链内有明确持续离框证据时 has_offscreen 才写 true。
6. issue_visible 与 damage_assessment.visible_in_continuous_opening 只表示所诉具体伤点在同一条主连续开箱视频中清晰可见。补充图片可用于身份对照，并通过 supplemental_damage_visible 单独记录当前伤点是否可见；补充图片不能把 issue_visible 置为 true，也不能证明伤在收货时已经存在。
6.0.1 supplemental_damage_visible=true 时，evidence_refs 至少提供一条 field=supplemental_damage_visible、asset_ref=supplemental_image_N 的真实补图引用，timestamp 写 null，fact 说明该图实际可见的伤点与同物特征；没有有效补图引用时必须写 null，不能只凭布尔值宣称补图已确认伤点或同物。
6.1 issue_visible 必须来自你独立看见的物理痕迹本体；用户指框、口述位置或单帧反光不能单独置为 true。细微折痕、压痕或划痕若在两个以上时间点或角度持续存在，可判为可见，但 reason 必须如实写“细微”或“明显”，不得夸大成深划痕或结构破损。
6.1.1 damage_assessment.main_video_detail_sufficient 只表示主连续开箱视频是否把所诉部位展示到足以作出有伤/无伤判断。商品占画面过小、运动模糊、过曝、遮挡或所诉部位未朝向镜头时写 false，并把 issue_visible 与 visible_in_continuous_opening 写 null；只有部位在至少两个清晰画面或角度中足以排除所诉物理痕迹时，才可写 false 表示确认未见损伤。补充图片清晰不能把该字段置为 true。
6.1.2 锁定争议商品的首次与末次有效展示后，必须在同一次完整视频理解中重新检查该展示窗内的所诉部位，不得只凭全片总体观感结束审核。补充图片只能用于定位要检查的部位和同物特征，随后仍要在主视频中独立寻找同一位置、形态和走向的痕迹；至少两个时间点或角度持续可见才可确认，找不到时如实写 null，不能把补图结论迁移到视频。
6.2 damage_assessment.severity_level 按品类和实际使用/展示影响判断：minor 为不影响主体的轻微表面痕迹，moderate 为清楚但非结构性的局部损伤，severe 为明显影响主体完整性或正常展示，extreme 表示严重到离谱的结构性断裂、主体分离、大面积破损或基本不可用。不能仅凭用户措辞提高等级；structural_failure 只在画面直接可见时写 true。
6.3 damage_assessment.causal_chain_status 必须基于同一部位的操作前、操作中、操作后。只有连续画面直接显示操作前无伤、相关动作发生、操作后同位置新出现损伤时，才能写 direct_customer_action + direct；操作前已经看见同一伤点写 pre_existing_visible；只看到最终伤点或任一阶段看不清时写 indeterminate，不得给制造、运输或用户定责。causal_reason 用一句话概括三个阶段。causal_evidence_refs 最多三条，分别用 before_action、action、after_action 回链真实时间点；每条必须填写 {causal_asset_rule}、同一 subject、同一 location、同一 chain_id、damage_visible 与短事实，且时间严格前后递增。操作前 damage_visible=false、操作后 damage_visible=true；没有看清的阶段不得编造，direct_customer_action 必须三阶段齐全。
{evidence_ref_rule}
7.1 continuous 与 has_edit 的全局结论各自至少回链开箱链首尾两个时间点；发现跳切或拼接时改为回链异常前后两个时间点。不能用单一时间点宣称全片连续或无剪辑。all_items_shown 至少回链争议商品完成必要展示的时间点。
8. 每段 reason 只写必要事实，不重复规则；整份输出保持紧凑。

甲方开箱视频字段：
- sealed_start：是否从完整未拆封快递外箱及闭合封口开始。
- waybill_visible：面单关键字段是否清晰可核验。
- continuous：关键开箱链是否一镜到底、无关键跳切或缺段。
- has_edit：是否有可见剪辑、拼接或跳切。
- has_offscreen：争议商品是否在相关展示链内发生有意义的离镜。
- has_speed_change：是否观察到明显加速或异常变速；不确定写 null。
- all_items_shown：本次需核对的相关商品是否完成展示。
- issue_visible：所诉伤点是否在主连续开箱链中清晰可见。
- field_confidences：严格按 [sealed_start, waybill_visible, continuous, has_edit, has_offscreen, has_speed_change, all_items_shown, issue_visible] 的固定顺序填写 8 个 0 到 1 数值。它表示本轮证据对该字段值的支持强度，不是客观正确率；字段为 null 时仍填写“无法判断”这一判断本身的置信度。
- overall_video_result 由程序根据原子字段确定性生成，本轮不要输出该字段；加速仅为橙色信号，除非 speed_assessment.affects_visual_judgement=true，否则不单独造成门槛失败。
"""


def build_sampled_video_batch_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured = safe_case.get("structured_business_context") or {}
    batch = structured.get("sampled_frame_batch") or {}
    identity = structured.get("continuity_claim_identity") or {}
    identity_anchor = str(batch.get("identity_anchor_asset_ref") or "")
    frames = [
        {
            "video_index": frame.get("video_index"),
            "global_frame_index": frame.get("global_frame_index"),
            "timestamp": frame.get("timestamp"),
            "asset_ref": (
                f"video_{frame.get('video_index')}_frame_{frame.get('global_frame_index')}"
            ),
        }
        for frame in safe_case.get("frames") or []
    ]
    return f"""只观察完整 1 FPS 时间轴中的当前一批独立图片，不执行售后动作，也不得输出整案综合结论。

当前批次：第 {batch.get('index')}/{batch.get('total')} 批；时间 {batch.get('start_timestamp')} 至 {batch.get('end_timestamp')}；相邻批保留 {batch.get('overlap_frames')} 张重叠帧。
用户诉求：{safe_case.get('customer_claim') or '未提供'}
争议商品身份线索：{json.dumps(identity, ensure_ascii=False)}
身份视觉锚点：{identity_anchor or '未提供'}。该图只用于商品身份比对，不能证明伤点来自开箱过程，也不能替代当前批次中的视频帧证据。
本批帧：{json.dumps(frames, ensure_ascii=False)}

统一观察规则：
1. 按 global_frame_index 顺序逐张观察；本批未见不等于全片未见，本批起止也不等于原视频起止。重叠帧用于让相邻批衔接，不得虚构两帧之间不足一秒的动作。
2. 只有实体商品本体表面可检查时，才能认定争议商品 appeared；包装图案或透明袋轮廓只能作为身份线索。身份至少同时匹配三个独立特征组，相似商品不得冒充目标商品。
3. sealed_start 只有第 1 批且首帧明确展示完整未拆封外箱与闭合封口时才能填 true/false，其他批写 null。waybill_visible 只记录本批是否看见足以核验的面单。
4. continuous、has_edit 只记录本批相邻帧间是否出现明确阶段倒退、主体突变、跳切或拼接信号；没有直接信号时分别写 null/null，不得把 1 FPS 采样空隙当成剪辑证据。
5. has_offscreen 只在本批已经可靠锁定实体争议商品、必要展示尚未完成且随后出现有意义的持续离框时写 true；本批未出现目标、展示完成后的其他商品片段或单个采样间隔都写 null，而不是 true。
6. has_speed_change 只有画面内可核验时钟或跨多帧明确异常运动语义时才写 true；1 FPS 图片没有音频和帧间动作，不能判断时写 null，speed_assessment.value 写 unknown。
7. issue_visible 只有同一物理痕迹在至少两个时间点或角度持续存在时才写 true；用户指框、口述、单帧反光、包装印刷或压缩噪点不能单独置真。清晰结构性断裂可凭单帧置真。伤点可见与成因是两件事。主视频商品过小、模糊、过曝或遮挡时，main_video_detail_sufficient=false，issue_visible 与 visible_in_continuous_opening 必须写 null，不能写 false 冒充确认无伤。
8. damage_assessment.causal_chain_status 只有本批连续帧直接覆盖同一部位的操作前、操作中、操作后，才能写 direct_customer_action；缺任一阶段写 indeterminate，不得猜测运输、制造或用户责任。
9. all_items_shown 与 claimed_item_assessment.presentation_complete 只描述本批是否已经看到争议商品必要表面展示完成；不确定写 null。evidence_refs 只能引用本批 asset_ref 和原时间戳。
10. field_confidences 严格按 [sealed_start, waybill_visible, continuous, has_edit, has_offscreen, has_speed_change, all_items_shown, issue_visible] 顺序填写 8 个局部判断置信度；输出保持紧凑。局部字段只能表达本批观察事实；最终九字段由后续全时间轴汇总生成。
"""


def build_sampled_video_reduce_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    structured = safe_case.get("structured_business_context") or {}
    identity = structured.get("continuity_claim_identity") or {}
    batch_results = structured.get("sampled_batch_results") or []
    candidate_frames = [
        {
            "asset_ref": (
                f"video_{frame.get('video_index')}_frame_"
                f"{frame.get('global_frame_index')}"
            ),
            "timestamp": frame.get("timestamp"),
        }
        for frame in safe_case.get("frames") or []
    ]
    supplemental_refs = [
        f"supplemental_image_{image.get('image_index')}"
        for image in safe_case.get("supplemental_images") or []
    ]
    return f"""根据完整 1 FPS 时间轴的全部批次观察结果，生成一次紧凑的全局九字段结果；不执行退款、拒赔、补发或定责。

用户诉求：{safe_case.get('customer_claim') or '未提供'}
争议商品身份线索：{json.dumps(identity, ensure_ascii=False)}
按时间排序的批次结果：{json.dumps(batch_results, ensure_ascii=False)}
模型自主发现的候选帧：{json.dumps(candidate_frames, ensure_ascii=False)}
用户补充图片锚点：{json.dumps(supplemental_refs, ensure_ascii=False)}

汇总规则：
1. 按 batch_index 与全局时间戳还原完整顺序；相邻批相同 asset_ref 或相同 global_frame_index 的重叠帧只能计一次。批次局部 null 表示该批无法判断，不表示全片失败。
2. sealed_start 只采信第 1 批起始事实。waybill_visible、all_items_shown 与 issue_visible 可由任一批的直接可回链证据支持，但 false 必须基于全时间轴已覆盖相应核验窗口，不能用“某批未见”代替。
3. continuous 与 has_edit 综合所有批次的阶段顺序和直接跳切信号。1 FPS 只能说明采样时间轴未观察到异常，不能证明不足一秒内绝对无剪辑；没有直接异常且开箱阶段按序覆盖时可写 continuous=true、has_edit=false，并在 reason 中说明是采样时间轴结论。
4. has_offscreen 只检查争议商品从可靠首次出现到必要展示完成的窗口。展示完成后的无关片段、出现前片段、其他商品片段和单个 1 FPS 间隔均不得算离镜。
5. has_speed_change 不能由媒体元数据或帧间位移单独确定。没有画面内实时锚点时，speed_assessment.value 通常写 unknown，has_speed_change 写 null；它是黄/橙色复核信号，不自动判负。
6. issue_visible 必须来自实体商品物理痕迹本体。细微划痕、折痕或压痕至少有两个不同时间点或角度的持续证据；用户指框、口述和单帧反光不够。清晰结构性断裂可凭直接画面确认，并如实填写 severity_level 与 structural_failure。只要目标部位在所有批次中仍过小、模糊、过曝或遮挡，main_video_detail_sufficient=false，issue_visible 写 null 而不是 false。
7. 损伤可见不等于成因明确。只有同一部位的操作前无伤、相关动作和操作后新伤三段连续事实齐全，才能输出 direct_customer_action；否则 causal_chain_status=indeterminate。
8. 必须直接查看候选帧与补充图片，批次文字只是待复核假设。包装盒、包装图案、透明袋轮廓和其他相似商品都不能代替实体争议商品；按当前实际可见的独立特征组合比对，不得硬性要求固定数量，候选冲突时保持不确定。补充图片只能锚定用户所指商品或伤点，不能证明它来自连续开箱。
9. claimed_item_assessment 的首次、末次时间与 evidence_refs 必须来自批次原始时间戳。候选冲突时不能按最早出现或批次自报置信度选择；无法可靠排除相似候选时 appeared、presentation_complete 和 issue_visible 写 null，并降低 identity_confidence。
10. 汇总八个原子字段时，field_confidences 严格按 [sealed_start, waybill_visible, continuous, has_edit, has_offscreen, has_speed_change, all_items_shown, issue_visible] 顺序输出 8 个 0 到 1 数值；分数不是客观正确率。overall_video_result 不要输出，由程序确定性生成。每段 reason 只写本案事实和必要的 1 FPS 能力边界。
"""


def build_selection_prompt(case: Dict[str, Any]) -> str:
    safe_case = sanitize_review_input(case)
    safe_case["_rule_tenant_id"] = str(case.get("tenant_id") or "mitako")
    structured_context = safe_case.get("structured_business_context") or {}
    analysis_mode = structured_context.get("analysis_mode")
    if analysis_mode == "claim_identity_only":
        return build_claim_identity_prompt(safe_case)
    if analysis_mode == "claimed_item_detail_only":
        return build_claimed_item_detail_prompt(safe_case)
    if analysis_mode in {"native_video_perception", "sampled_video_perception"}:
        return _with_governed_rules(build_native_video_perception_prompt(safe_case), safe_case)
    if analysis_mode == "sampled_video_batch_observation":
        return _with_governed_rules(build_sampled_video_batch_prompt(safe_case), safe_case)
    if analysis_mode == "sampled_video_perception_reduce":
        return _with_governed_rules(build_sampled_video_reduce_prompt(safe_case), safe_case)
    if analysis_mode == "minor_material_inventory":
        return _with_governed_rules(build_minor_material_inventory_prompt(safe_case), safe_case)
    if analysis_mode == "minor_material_process_video":
        return _with_governed_rules(build_minor_material_video_prompt(safe_case), safe_case)
    if analysis_mode == "minor_material_consistency":
        return _with_governed_rules(build_minor_material_consistency_prompt(safe_case), safe_case)
    if analysis_mode == "object_continuity_only":
        return _with_governed_rules(build_object_continuity_prompt(safe_case), safe_case)
    if analysis_mode == "damage_causality_only":
        return _with_governed_rules(build_damage_causality_prompt(safe_case), safe_case)
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
    unified_multitask_instruction = ""
    if structured_context.get("unified_multitask") is True and frames:
        unified_multitask_instruction = f"""
统一多任务规则：本次主审核必须在同一次结构化响应中完成业务判断、连续性和成因观察。frame_findings 必须逐一覆盖本批全部 {len(frames)} 个目标帧，每个 global_frame_index 恰好一条，不得只返回关键帧；每条都必须列出 shipping_package、product_package、claimed_item 三个主体的可见状态，不确定时写 unknown。object_continuity_assessment 和 damage_causality_assessment 必须复用这些逐帧事实，不得省略后交给重复视觉调用。
"""
    prompt = f"""请基于同一证据包进行售后视觉审核。

审核场景：{safe_case.get("scenario_label")}
用户诉求：{safe_case.get("customer_claim") or "未提供"}
订单/工单上下文：{json.dumps(safe_case.get("order_context") or {}, ensure_ascii=False)}
结构化业务上下文：{json.dumps(safe_case.get("structured_business_context") or {}, ensure_ascii=False)}
视频清单：{json.dumps(videos, ensure_ascii=False)}
送入模型的视频帧清单：{json.dumps(frames, ensure_ascii=False)}
送入模型的补充图片清单：{json.dumps(images, ensure_ascii=False)}
送入模型的官方商品参考图清单：{json.dumps(official_references, ensure_ascii=False)}
{native_video_instruction}
{unified_multitask_instruction}

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
10. 播放加速本身不等于拼接剪辑或视频不合规；加速本身只作为橙色风险信号。一镜到底且关键开箱过程完整时，不能仅凭加速判负；跳切、拼接、时间轴异常或关键过程缺失才是独立风险。默认 1 FPS 下若封箱起始、面单、连续拆封、争议商品连续性和伤情首次出现仍可判断，speed_review_impact.status 写 none；若关键证据受画面节奏影响而无法判断，写 uncertain 并列出 affected_review_items，保持黄色不确定并让客服只复核对应原视频片段。不得仅凭加速推断用户责任或造假，也不得要求通过提高抽帧密度证明原始倍速。
11. sealed_start 只有在视频起始明确展示完整未拆封快递外箱及封条时才写 true；泡沫、气泡袋或商品内包装不算封箱起点，面单可见不能补足 sealed_start。waybill_visible 只有在主连续开箱视频中物流单号或关键关联字段清晰可读、足以核验本包裹关联时才写 true；只看到标签轮廓、模糊文字或反光面单必须写 false。issue_visible_in_continuous_opening 只有在同一条主连续开箱链中清楚展示本次所诉具体伤点时才写 true，后补短视频或照片中的伤点不能计入；false 表示连续开箱未清楚展示伤点，不表示商品确定无损或用户造假。先用 sealed_start 的可回链证据确定主连续开箱视频，再判断其余三个字段，其他短片只作为后补现状。分段未覆盖某个开箱节点时，对应 opening_video_compliance 字段必须写 null，不能把“本段没看到”写成 false；false 只表示本段画面直接证明该硬要求不满足。
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
- video_audit_conclusion: 视频审核结论，必须包含 continuity_score、continuity_reason、swap_risk_level(high/medium/low)、edit_or_cut_risk、opening_integrity、playback_speed(normal/accelerated/unknown)、sampling_fps、speed_review_impact、opening_video_compliance。playback_speed 只表示从画面节奏观察到的正常、疑似加速或无法判断，不得猜测精确倍速。speed_review_impact 必须包含 status(none/uncertain/material)、critical_evidence_observable(true/false/null)、affected_review_items(只能从 sealed_start/waybill/opening_action/claimed_item_continuity/issue_first_visible 选择)、evidence_refs 和 reason；opening_video_compliance 必须包含 sealed_start、waybill_visible、single_take_continuity、issue_visible_in_continuous_opening（均为 true/false/null）、evidence_refs 和 result(compliant/noncompliant/indeterminate)。waybill_visible 表示关键面单字段可读且可核验，不是标签轮廓出现；issue_visible_in_continuous_opening 只允许引用主连续开箱视频，后补短片和照片不得置 true。evidence_refs 使用扁平数组，每项必须含 field(sealed_start/waybill_visible/single_take_continuity/issue_visible_in_continuous_opening)、video_index、global_frame_index、timestamp；没有可回链证据时不得输出 material 或 false。
- object_continuity_assessment: 有视频时必填。必须分别定义并跟踪 shipping_package、product_package、claimed_item 等主体；包含 tracked_subjects 数组，每项含 subject_id、description、tracking_start、tracking_end、first_exposed_timestamp、visibility_coverage、out_of_frame_events。每个离镜事件必须含 start_timestamp、end_timestamp、duration_seconds、visibility(out_of_frame/occluded/unknown)、before_evidence、after_evidence、identity_reestablished、reason。顶层还要给 continuity_verdict(continuous/brief_occlusion/long_absence/indeterminate)、longest_out_of_frame_seconds、total_unobserved_seconds、critical_events。未从不透明包装中拆出的阶段写 not_yet_exposed，不算离镜；不能因为前后都再次出现就声称全程未离镜。
- customer_claim_parse: expected_item、claimed_received_item、claimed_mismatch_type。
- expected_order_item: 订单要求的商品/角色/SKU/规格/数量。
- actual_received_item: 实际收到的商品/角色/SKU/规格/数量或破损事实。
- audit_methods: 实际使用的审核方法数组。
- frame_findings: 抽帧统一多任务时，全部目标帧各一条精简状态，不写冗长重复描述；原生视频时只记录对结论有贡献的关键时间点。两种模式都必须覆盖主体首次可见、状态变化、争议首次可见、离镜/复入镜和末个可判断状态。每条必须含 video_index、global_frame_index、timestamp、visible_facts、risk、subject_visibility。subject_visibility 必须列出 shipping_package、product_package、claimed_item 三个 canonical subject_id 及其 state(visible/partial/occluded/out_of_frame/not_yet_exposed/unknown)；不知道时写 unknown，不得省略。
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
- fulfillment_reconciliation: 仅发错货/漏发货必填，其他场景写 null。必须包含 baseline_version、expected_items、observed_items、suspected_missing_items、unexpected_items、unconfirmed_items、package_observations、package_coverage、all_packages_uploaded、all_items_displayed、evidence_timestamps、confidence、decision_boundary。每个清单项写 item_ref/SKU/名称/规格/应发数量/已识别数量/证据时间点；每个 package_observations 项写 package_ref、opening_complete、all_contents_laid_out、evidence_timestamps。漏发货在没有服务端受信 warehouse_verification 时，若缺少唯一应发基准、赠品/特典规则、分包关联或全部包裹及物品的完整展示，predicted_label 必须是 review。发错货则允许“版本化订单基准 + 应收身份 + 实收错误身份 + 包裹/面单关联”的清晰照片链形成明确结论，不得机械强制开箱视频。证据不足时 decision_boundary 要写明可获得的具体补件，不得仅因材料缺口强制占用人工席位。
"""
    return _with_governed_rules(prompt, safe_case)
