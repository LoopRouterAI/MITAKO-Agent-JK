# -*- coding: utf-8 -*-
"""未成年人退款资料的分批视觉识别提示词。"""
from __future__ import annotations

import json
from typing import Any, Dict


DOCUMENT_TYPES = (
    "identity_card",
    "passport",
    "household_register",
    "birth_certificate",
    "signed_commitment",
    "order_payment_proof",
    "mobile_realname_proof",
    "carrier_invoice",
    "other",
    "unknown",
)

CONSISTENCY_FIELDS = {
    "identity_age": [
        "guardian_identity", "minor_identity", "age_eligibility",
        "payment_password_access", "guardian_discovery_process",
    ],
    "guardian_relationship": [
        "guardian_identity", "minor_identity", "relationship_document_linkage",
        "explicit_relationship_entry", "relationship_link", "applicant_guardian_role",
    ],
    "commitment_signatures": [
        "guardian_signer", "minor_signer", "signature_presence", "signature_method", "field_alignment",
        "commitment_content", "refund_scope", "recipient_information", "signed_date",
        "account_bound_phone", "account_nickname", "consumption_time_range",
        "refund_amount", "refund_method", "payment_recipient",
    ],
    "order_payment": [
        "order_reference", "order_item_scope", "item_quantity", "order_status",
        "payer_identity", "payment_status", "transaction_time", "amount",
        "merchant_identity", "transaction_id", "merchant_order_id",
        "transaction_scope", "commitment_amount",
    ],
    "mobile_realname": [
        "subscriber_identity", "account_mobile", "invoice_identity", "invoice_phone",
        "number_status", "ownership_proof", "guardian_phone_holder",
    ],
}

CONSISTENCY_LABELS = {
    "identity_age": "身份与年龄",
    "guardian_relationship": "监护关系",
    "commitment_signatures": "承诺书签署主体",
    "order_payment": "订单与支付",
    "mobile_realname": "手机号实名归属",
}


def build_minor_material_inventory_prompt(case: Dict[str, Any]) -> str:
    context = case.get("structured_business_context") or {}
    batch = context.get("minor_material_batch") or {}
    images = [
        {
            "image_index": item.get("image_index"),
            "asset_ref": f"supplemental_image_{item.get('image_index')}",
            "width": item.get("width"),
            "height": item.get("height"),
        }
        for item in case.get("supplemental_images") or []
    ]
    return f"""你正在执行未成年人退款资料的一个图像分批识别任务。本批结果会由服务端与其他批次确定性聚合。

本批信息：{json.dumps(batch, ensure_ascii=False)}
本批图片：{json.dumps(images, ensure_ascii=False)}
SOP 版本：minor_refund_2_0

五类材料规则：
1. 未成年人及监护人身份证明。身份证必须同时看到正面和反面；未成年人没有身份证时，可由未成年人户口本信息页或出生证明替代。
2. 监护关系证明：通常户口本相关页或出生证明二选一；如两者不能闭合关系链，可使用盖章的合法监护证明。不得重复要求已经由其他有效路径证明的材料。
3. 监护人与未成年人亲笔签字的退款申请承诺书。
4. 购买订单材料与支付材料两者都必须存在，并逐笔或以可解释汇总覆盖申请范围；只有订单页或只有支付页都不齐全。
5. 账号绑定手机号实名归属证明。只有填写了本案用户信息、能看到实名主体和购物手机号或备注信息的运营商话费账单/电子发票，才属于有效证明。空白模板、示例图无效；只显示账号名和手机号的运营商 App 页面只能作为辅助线索，不能替代该证明。
学校盖章报名表只能作为身份或就读信息的辅助线索，不能单独替代身份证明或监护关系证明。

异常经验规则：
- 身份证仅允许遮挡住址门牌号和身份证号后三位；密集水印或错误打码导致关键字段不可读时，应要求重新提交清晰材料，但不得仅凭水印认定造假。
- 申请人与未成年人分处两本户口本时，必须由出生证明、同户直系关系页或盖章的合法监护证明闭合关系链；哥哥或姐姐不是法定监护人，不能直接代替父母或合法监护人申请。
- 承诺书双方姓名必须亲笔签名，电脑录入姓名不能视为亲笔签名；金额与订单可退款范围一致且不得涂改，字段错位时应要求重新提交未涂改且字段对应正确的版本。
- 运营商材料必须显示可与平台绑定号码比对的业务手机号；支付截图不能替代手机号实名归属证明。号码已注销时，应补充销户或原号码归属证明。

例外证明的受控编码：
- 当前 Schema 没有独立子类型。盖章的合法监护证明使用 document_type=other、subject_role=not_applicable、document_side=multiple；只有官方盖章、同时连接申请人与未成年人且关键记载可读时才能标 sop_eligibility=valid。
- 主副卡关系证明、销户证明或原号码归属证明使用 document_type=other、subject_role=guardian、document_side=multiple；只有运营商出具、号码归属链可读且能连接本案申请监护人时才能标 sop_eligibility=valid。
- 低于 10 周岁的支付密码来源及监护发现过程说明使用 document_type=other、subject_role=not_applicable、document_side=page；只有两项过程均有实际填写内容且可读时才能标 sop_eligibility=valid，空白或仅有标题时标 invalid。
- 普通其他文件不得套用上述组合标 valid；不能确定证明类型、主体关系或出具方时，sop_eligibility 必须为 supporting_only、invalid 或 unknown。

护照识别边界：
- 护照作为可识别证件，document_type 必须输出 passport，并输出签发国家/地区 issuing_country_or_region 与可读性 readability。
- 护照只做视觉/OCR 初审，可参与身份、年龄和监护关系的可见字段一致性比较，不宣称权威验真。
- 护照不自动替代现有 SOP 的身份证必交项；身份证清单是否满足仍按上述五类材料规则判断。

严格要求：
- 必须逐张返回，不能漏掉本批任何 image_index。
- 只判断本批图片实际可见的文档类型、角色、页/正反面和清晰度，不得根据文件顺序猜测。
- 任一结构化字段缺失或不可读时统一输出 unknown，不得猜测，也不得写“用户未提交”“缺少其他批次材料”。
- document_state 必须区分 filled、blank_template、example、unknown；模板和示例不得判为 filled。
- 带有红色填写说明、占位文字、示例金额、教学箭头或样本水印的运营商发票属于 example，document_state 必须写 example、sop_eligibility 必须写 invalid；版式完整或字段清晰不能把样本变成用户实名材料。
- sop_eligibility 必须区分 valid、supporting_only、invalid、unknown。材料类别识别正确不等于满足 SOP；运营商 App 账号页只能标 supporting_only。
- 清晰可读且已填写的订单页、支付流水或支付账单可标 order_payment_proof；同时必须按实际可见内容输出 order_payment_evidence_type：只含订单/商品范围写 order，只含支付事实写 payment，同一材料同时包含两类完整事实才写 combined，看不清写 unknown。不得根据文件名、图片顺序或用户描述猜分类。
- application_scope_coverage 只描述该材料是否逐笔或以可解释汇总覆盖申请范围：完整覆盖写 complete，只覆盖局部写 partial，看不清或申请范围不可比写 unknown。单独一张局部订单页或支付截图不得写 complete。
- document_box_2d 标出本张图片中主要材料的完整外边界，格式固定为 [ymin,xmin,ymax,xmax]，坐标归一化到 0 至 1000。必须覆盖整张证件或整页材料，不得只框文字、头像、签名或疑似问题区域；无法可靠定位时输出空数组 []。
- 即使订单或支付材料的权威归属仍需业务系统复核，也不得仅因此把已经可见的对应材料分类为缺失。支付截图只是不可以替代手机号实名归属证明。
- suspected_editing 只允许在发现明确局部异常时使用，并同时填写 editing_evidence_codes。压缩、扫描、截图、水印、缺少 EXIF、轻微模糊或普通拍屏不能单独视为编辑证据。
- 不得输出姓名、手机号、证件号、住址、订单号、付款账号、二维码内容或任何 OCR 原文。
- 不执行退款、拒绝、通过等业务动作。

只输出 JSON：
{{
  "schema_version": "minor_inventory_v2",
  "coverage_ack": {{"expected_image_indices": [], "observed_image_indices": []}},
  "material_observations": [
    {{
      "image_index": 1,
      "asset_ref": "supplemental_image_1",
      "document_type": "passport",
      "subject_role": "guardian|minor|unknown|not_applicable",
      "document_side": "front|back|page|multiple|unknown",
      "issuing_country_or_region": "国家或地区名称|unknown",
      "readability": "clear|partial|unknown",
      "document_state": "filled|blank_template|example|unknown",
      "sop_eligibility": "valid|supporting_only|invalid|unknown",
      "order_payment_evidence_type": "order|payment|combined|unknown",
      "application_scope_coverage": "complete|partial|unknown",
      "document_box_2d": [100, 80, 900, 920],
      "quality_issues": ["blur|glare|occlusion|excessive_redaction|incomplete_page|suspected_editing|other"],
      "editing_evidence_codes": ["inconsistent_text_edge|duplicated_region|local_resampling_artifact|impossible_geometry|other_specific_anomaly"]
    }}
  ],
  "batch_limitations": []
}}

document_type 只能从以下枚举选择：{json.dumps(DOCUMENT_TYPES, ensure_ascii=False)}。
"""


def build_minor_material_video_prompt(case: Dict[str, Any]) -> str:
    context = case.get("structured_business_context") or {}
    batch = context.get("minor_video_batch") or {}
    frames = [
        {
            "video_index": item.get("video_index"),
            "global_frame_index": item.get("global_frame_index"),
            "timestamp": item.get("timestamp"),
            "asset_ref": f"video_{item.get('video_index')}_frame_{item.get('global_frame_index')}",
        }
        for item in case.get("frames") or []
    ]
    return f"""你正在审核未成年人退款材料包中的过程视频分段。视频仅用于识别开票、材料展示或操作过程，不能据此判断其他图片材料缺失。

分段信息：{json.dumps(batch, ensure_ascii=False)}
本段帧：{json.dumps(frames, ensure_ascii=False)}

严格要求：
- 只能引用已提供的帧和时间戳。
- 本段末帧不等于视频结束。
- 不得输出姓名、手机号、证件号、住址、订单号、付款账号、二维码内容或 OCR 原文。
- 不得判断未提供给本分段的图片是否缺失。
- 不执行退款、拒绝、通过等业务动作。

只输出 JSON：
{{
  "process_observations": [
    {{
      "video_index": 1,
      "global_frame_index": 1,
      "timestamp": "00:00.00",
      "asset_ref": "video_1_frame_1",
      "process_type": "invoice_generation|document_capture|payment_record|other|uncertain",
      "evidence_quality": "clear|partial|unreadable"
    }}
  ],
  "process_summary": "不包含个人信息的过程摘要",
  "limitations": []
}}
"""


def build_minor_material_consistency_prompt(case: Dict[str, Any]) -> str:
    context = case.get("structured_business_context") or {}
    policy = context.get("minor_refund_policy") or {
        "review_mode": "standard",
        "authoritative_verification": "disabled",
    }
    check = context.get("minor_consistency_check") or {}
    check_id = str(check.get("check_id") or "")
    fields = CONSISTENCY_FIELDS.get(check_id) or []
    label = CONSISTENCY_LABELS.get(check_id) or check_id
    material_context = check.get("material_context") or []
    field_rows = [
        {
            "field_name": field_name,
            "status": "matched|mismatched|uncertain|not_assessed",
            "visibility": "complete|partial|masked|unreadable",
            "evidence_image_indices": [],
        }
        for field_name in fields
    ]
    images = [
        {
            "image_index": item.get("image_index"),
            "asset_ref": f"supplemental_image_{item.get('image_index')}",
        }
        for item in case.get("supplemental_images") or []
    ]
    order_context = case.get("order_context") or {}
    assessment_date = str(
        order_context.get("assessment_at")
        or order_context.get("created_at")
        or "工单创建日期未提供"
    )
    return f"""你正在执行未成年人退款资料的跨材料视觉字段一致性初审。

检查项：{label}（{check_id}）
必须检查的字段类型：{json.dumps(fields, ensure_ascii=False)}
本次图片：{json.dumps(images, ensure_ascii=False)}
前序材料分类（不含字段原值）：{json.dumps(material_context, ensure_ascii=False)}
预期图片编号：{json.dumps(check.get("expected_image_indices") or [], ensure_ascii=False)}
本次审核策略：{json.dumps(policy, ensure_ascii=False)}
年龄判断基准日期：{assessment_date}

审核方法：
0. detail_crop_applied=true 表示当前输入是程序从原始图片裁出的完整材料区域，并保留了边距；它只用于精看打码、水印、签字、日期和细字段可读性。整页是否完整、是否裁边、正反面和材料类别必须服从前序全图观察，不得仅凭局部图改写。
1. 比较图片中可见字段是否彼此一致，逐项返回 matched、mismatched、uncertain 或 not_assessed。
   必须原样返回全部字段类型，不能改名、缩写或遗漏：{json.dumps(fields, ensure_ascii=False)}。
   matched 表示所给图片中的该字段彼此一致；mismatched 表示存在明确冲突；uncertain 表示看不清或证据不足；not_assessed 只用于图片不包含该字段。
   matched 可用于至少两张图片中足够的可见字段片段一致，即使 SOP 允许的证件号中段已打码；但完全遮盖、手写难辨或缺字段必须输出 uncertain。
   mismatched 仅允许用于至少两张图片中的同一字段均完整清晰可见且明确不同；部分遮盖、打码、裁切或主副卡关系不明时不得输出 mismatched。
2. 身份与年龄：比较监护人、未成年人主体及年龄是否满足未成年人申请条件；护照可作为视觉/OCR 一致性证据参与比较。低于 10 周岁时，支付密码来源和监护人发现消费过程属于条件性必审材料：分别检查未成年人如何获得或得知支付密码，以及监护人如何、何时发现消费，写入 payment_password_access 与 guardian_discovery_process；任一项缺少或不可读必须为 uncertain 或 not_assessed，不能推断为 matched。未满 9 周岁且年龄证据为高置信时另加授权人员重点核验，但该人工关注不得覆盖或改写五类材料及上述过程字段事实。
3. 监护关系：比较身份证、护照与户口本或出生证明中的双方主体及关系链；护照签发国家/地区仅作可见字段初审。guardian_relationship 检查必须用 relationship_evidence_type 标记关系证据类型：同一本户口本直接关系页为 same_household_direct_link，出生证明为 birth_certificate，盖章合法监护证明为 legal_guardianship_proof，两本户口本且没有上述桥接材料为 separate_household_books_without_bridge，无法判断为 uncertain；其他检查固定为 not_applicable。guardian_relationship 还必须逐页填写 relationship_document_groups：每张关系材料按可见户号、户主、户口本唯一标识或同一证书页面连续性分到 group_1 至 group_4，并标 subject_role；同一本材料使用同组，无法看清用 uncertain，其他检查输出空数组。不得根据同姓、相同地址、年龄接近、图片顺序或“看起来相关”分到同组，也不得输出任何户号或字段原值。relationship_document_linkage 只有在同一份合规关系材料确实连接双方时才能 matched：户口本必须核对未成年人页与申请人页属于同一分组，出生证明或合法监护证明必须在同一文件中连接双方；字段被遮挡或未同时看到时为 uncertain，清晰显示不同组时为 mismatched。explicit_relationship_entry 只有材料明确写出父母子女或合法监护关系时才能 matched，不能根据同姓、姓名一致、年龄或地址推断。relationship_link 只有在 relationship_evidence_type 为前三种有效桥接材料之一，且 relationship_document_linkage、explicit_relationship_entry 均为 matched 时才能 matched；申请人与未成年人位于两本户口本时，仅姓名等身份字段彼此一致不能闭合关系链，此时 relationship_link 必须为 uncertain。申请人是哥哥或姐姐时，applicant_guardian_role 不得判 matched，除非另有父母关系或合法监护证明。
4. 承诺书：比较监护人与未成年人签署主体标注、双方签字是否存在、是否为亲笔签名、字段是否对齐，并逐项检查 commitment_content、refund_scope、recipient_information、signed_date、account_bound_phone、account_nickname、consumption_time_range、refund_amount、refund_method、payment_recipient 是否完整；电脑录入姓名不能视为亲笔签名，不得声称签名具有法律真实性。电脑录入姓名、只有一方签名、缺少日期、字段错位或其他可通过重交正确承诺书解决的问题只输出对应原子字段状态，不得扩张为造假、主体冲突或必须人工。
   signature_presence 只有在监护人和未成年人两个签字位置都能看到实际手写笔迹时才可 matched；空白签字栏、打印或电脑录入的姓名必须为 mismatched，画面不清才为 uncertain。signature_method 同样只有明确可见手写笔迹才可 matched。
5. 订单与支付：订单材料和支付材料必须分别出现，并逐项检查 order_reference、order_item_scope、item_quantity、order_status、payer_identity、payment_status、transaction_time、amount、merchant_identity、transaction_id、merchant_order_id、transaction_scope、commitment_amount，比较订单引用、商品范围、数量、状态、付款主体、支付状态、交易时间、金额、商户、交易标识和承诺书退款金额是否一致；只有订单材料或只有支付材料时，缺失一侧的字段必须为 uncertain 或 not_assessed，不得把任一页当作两类齐全。明确的跨来源金额或主体冲突才输出 mismatched；缺页、缺签、缺日期、电脑姓名或不可读字段不得伪装成跨来源冲突。不得声称平台订单或支付记录真实。
6. 手机号实名：比较运营商材料中的实名主体、账号绑定手机号、发票抬头/备注和发票业务手机号是否一致，并用 guardian_phone_holder 检查该号码是否属于本案申请监护人；号码属于未成年人不能满足本项当前 SOP。不得声称运营商实名状态真实有效。支付截图不能替代手机号实名归属证明；号码已注销时必须检查销户或原号码归属证明。
   主副卡并存时必须检查主副卡关系证明；号码已注销时必须检查运营商销户证明或原号码归属证明。号码部分遮盖、发票备注不完整、缺少例外证明或无法建立归属关系时必须输出 uncertain，不得输出 mismatched。
7. 同时检查明显裁切、拼接、涂改、遮挡或字段冲突风险。疑似编辑只能标风险，不能直接认定造假。tamper_risk=high 必须有明确局部异常，并只在 tamper_evidence_image_indices 中引用直接支持该异常的图片；压缩、扫描、截图、水印、缺少 EXIF 或一般清晰度问题不得单独判 high。
8. 仅在 identity_age 检查中读取未成年人出生日期：主体和日期均清晰、跨材料无冲突时，将该日期规范为 YYYY-MM-DD 写入私有字段 minor_birth_date_iso；看不清、主体不明或日期冲突时写 null。不得把监护人的出生日期写入。age_band、low_age、under_nine、age_confidence 和 payment_capability_risk 固定写 unknown/null，由程序使用受信申请日期计算；其他检查同样将 minor_birth_date_iso 写 null。不得在任何自由文本或其他字段重复出生日期。

隐私与业务边界：
- 模型可以在本次推理中读取字段用于比较，但不得输出任何字段原值、部分值、尾号、姓名、号码、金额、地址、OCR原文或哈希。
- 输出不得包含自由文本说明，只能使用下面的枚举和图片编号。
- 本检查只表示视觉字段一致性，不得声称已完成政府、运营商、平台订单或支付系统的在线验真。
- 护照不自动替代现有 SOP 的身份证必交项，也不得声称护照或签发国家/地区已被权威验真。
- 在线验真是否阻断由服务端策略决定：默认 disabled，不得仅因没有外部接口把视觉初审降级为人工复核。
- 不执行退款、通过、拒绝或定责。

只输出 JSON：
{{
  "schema_version": "minor_consistency_v1",
  "coverage_ack": {{"expected_image_indices": [], "observed_image_indices": []}},
  "consistency_check": {{
    "check_id": "{check_id}",
    "relationship_evidence_type": "same_household_direct_link|birth_certificate|legal_guardianship_proof|separate_household_books_without_bridge|uncertain|not_applicable",
    "minor_birth_date_iso": "YYYY-MM-DD"|null,
    "age_band": "under_10|10_to_17|18_or_over|unknown",
    "low_age": true|false|null,
    "under_nine": true|false|null,
    "age_confidence": "high|low|unknown",
    "payment_capability_risk": "none|high|unknown",
    "relationship_document_groups": [{{"image_index": 1, "document_type": "household_register|birth_certificate|legal_guardianship_proof|other", "subject_role": "guardian|minor|both|unknown", "document_group": "group_1|group_2|group_3|group_4|uncertain|not_applicable"}}],
    "field_results": {json.dumps(field_rows, ensure_ascii=False)},
    "tamper_risk": "low|medium|high|uncertain",
    "risk_reason_codes": ["no_obvious_risk|suspected_editing|unreadable_fields|incomplete_document|conflicting_fields|evidence_gap"],
    "tamper_evidence_image_indices": []
  }},
  "authoritative_verification": "disabled|advisory|required"
}}
"""
