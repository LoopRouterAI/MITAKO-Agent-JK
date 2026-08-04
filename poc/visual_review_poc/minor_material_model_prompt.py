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
    "identity_age": ["guardian_identity", "minor_identity", "age_eligibility"],
    "guardian_relationship": ["guardian_identity", "minor_identity", "relationship_link"],
    "commitment_signatures": ["guardian_signer", "minor_signer", "signature_presence"],
    "order_payment": ["order_reference", "payer_identity", "amount", "transaction_scope"],
    "mobile_realname": ["subscriber_identity", "account_mobile", "invoice_identity"],
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
1. 未成年人及监护人身份证明。未成年人没有身份证时，可由未成年人户口本信息页或出生证明替代。
2. 监护关系证明：户口本相关页或出生证明二选一，不得同时要求二者。
3. 监护人与未成年人亲笔签字的退款申请承诺书。
4. 购买订单证明、支付流水或支付账单。
5. 账号绑定手机号实名归属证明。只有填写了本案用户信息、能看到实名主体和购物手机号或备注信息的运营商话费账单/电子发票，才属于有效证明。空白模板、示例图无效；只显示账号名和手机号的运营商 App 页面只能作为辅助线索，不能替代该证明。

护照识别边界：
- 护照作为可识别证件，document_type 必须输出 passport，并输出签发国家/地区 issuing_country_or_region 与可读性 readability。
- 护照只做视觉/OCR 初审，可参与身份、年龄和监护关系的可见字段一致性比较，不宣称权威验真。
- 护照不自动替代现有 SOP 的身份证必交项；身份证清单是否满足仍按上述五类材料规则判断。

严格要求：
- 必须逐张返回，不能漏掉本批任何 image_index。
- 只判断本批图片实际可见的文档类型、角色、页/正反面和清晰度，不得根据文件顺序猜测。
- 任一结构化字段缺失或不可读时统一输出 unknown，不得猜测，也不得写“用户未提交”“缺少其他批次材料”。
- document_state 必须区分 filled、blank_template、example、unknown；模板和示例不得判为 filled。
- sop_eligibility 必须区分 valid、supporting_only、invalid、unknown。材料类别识别正确不等于满足 SOP；运营商 App 账号页只能标 supporting_only。
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
    return f"""你正在执行未成年人退款资料的跨材料视觉字段一致性初审。

检查项：{label}（{check_id}）
必须检查的字段类型：{json.dumps(fields, ensure_ascii=False)}
本次图片：{json.dumps(images, ensure_ascii=False)}
预期图片编号：{json.dumps(check.get("expected_image_indices") or [], ensure_ascii=False)}
本次审核策略：{json.dumps(policy, ensure_ascii=False)}

审核方法：
1. 比较图片中可见字段是否彼此一致，逐项返回 matched、mismatched、uncertain 或 not_assessed。
   必须原样返回全部字段类型，不能改名、缩写或遗漏：{json.dumps(fields, ensure_ascii=False)}。
   matched 表示所给图片中的该字段彼此一致；mismatched 表示存在明确冲突；uncertain 表示看不清或证据不足；not_assessed 只用于图片不包含该字段。
   matched 可用于至少两张图片中足够的可见字段片段一致，即使 SOP 允许的证件号中段已打码；但完全遮盖、手写难辨或缺字段必须输出 uncertain。
   mismatched 仅允许用于至少两张图片中的同一字段均完整清晰可见且明确不同；部分遮盖、打码、裁切或主副卡关系不明时不得输出 mismatched。
2. 身份与年龄：比较监护人、未成年人主体及年龄是否满足未成年人申请条件；护照可作为视觉/OCR 一致性证据参与比较。
3. 监护关系：比较身份证、护照与户口本或出生证明中的双方主体及关系链；护照签发国家/地区仅作可见字段初审。
4. 承诺书：比较监护人与未成年人签署主体标注及双方签字是否存在；不得声称签名具有法律真实性。
5. 订单与支付：比较订单引用、付款主体、金额和交易范围在所给凭证中是否一致；不得声称平台订单或支付记录真实。
6. 手机号实名：比较运营商材料中的实名主体、账号绑定手机号和发票抬头/备注是否与其他材料一致；不得声称运营商实名状态真实有效。
   主副卡并存、号码部分遮盖、发票备注不完整或无法建立主副卡关系时必须输出 uncertain，不得输出 mismatched。
7. 同时检查明显裁切、拼接、涂改、遮挡或字段冲突风险。疑似编辑只能标风险，不能直接认定造假。tamper_risk=high 必须有明确局部异常，并只在 tamper_evidence_image_indices 中引用直接支持该异常的图片；压缩、扫描、截图、水印、缺少 EXIF 或一般清晰度问题不得单独判 high。

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
    "field_results": {json.dumps(field_rows, ensure_ascii=False)},
    "tamper_risk": "low|medium|high|uncertain",
    "risk_reason_codes": ["no_obvious_risk|suspected_editing|unreadable_fields|incomplete_document|conflicting_fields|evidence_gap"],
    "tamper_evidence_image_indices": []
  }},
  "authoritative_verification": "disabled|advisory|required"
}}
"""
