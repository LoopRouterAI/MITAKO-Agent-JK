# -*- coding: utf-8 -*-
"""未成年人退款资料的分批视觉识别提示词。"""
from __future__ import annotations

import json
from typing import Any, Dict


DOCUMENT_TYPES = (
    "identity_card",
    "household_register",
    "birth_certificate",
    "signed_commitment",
    "order_payment_proof",
    "mobile_realname_proof",
    "carrier_invoice",
    "other",
)


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
5. 账号绑定手机号实名归属证明。运营商话费账单或电子发票属于已提交的候选证明：能确认实名主体及购物手机号/备注信息时同时归为 mobile_realname_proof；只能确认运营商发票时归为 carrier_invoice，并留给人工核对主体一致性。

严格要求：
- 必须逐张返回，不能漏掉本批任何 image_index。
- 只判断本批图片实际可见的文档类型、角色、页/正反面和清晰度，不得根据文件顺序猜测。
- 看不清写 uncertain 或 unreadable，不得写“用户未提交”“缺少其他批次材料”。
- 不得输出姓名、手机号、证件号、住址、订单号、付款账号、二维码内容或任何 OCR 原文。
- 不执行退款、拒绝、通过等业务动作。

只输出 JSON：
{{
  "coverage_ack": {{"expected_image_indices": [], "observed_image_indices": []}},
  "material_observations": [
    {{
      "image_index": 1,
      "asset_ref": "supplemental_image_1",
      "document_types": ["identity_card"],
      "subject_role": "guardian|minor|unknown|not_applicable",
      "document_side": "front|back|page|multiple|unknown",
      "readability": "clear|partial|unreadable",
      "quality_issues": ["blur|glare|occlusion|excessive_redaction|incomplete_page|suspected_editing|other"]
    }}
  ],
  "batch_limitations": []
}}

document_types 只能从以下枚举选择：{json.dumps(DOCUMENT_TYPES, ensure_ascii=False)}。
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
