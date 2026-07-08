# -*- coding: utf-8 -*-
"""客服知识库/RAG POC 样本，后续可替换为 WeKnora 文档库。"""
from __future__ import annotations

from typing import Any, Dict, List


KNOWLEDGE_DOCS: List[Dict[str, Any]] = [
    {
        "doc_id": "sop_damage_v1",
        "title": "商品有伤 SOP",
        "category": "SOP",
        "version": "2026-06-30",
        "approved": True,
        "source": "客服 SOP / 商品有伤",
        "content": "商品有伤需先核对订单、商品图和用户上传材料。视频或图片低置信度时必须转VIP客服复核。不得自动拒赔、自动补发或自动退款。",
    },
    {
        "doc_id": "sop_minor_refund_v1",
        "title": "未成年人退款材料要求",
        "category": "SOP",
        "version": "2026-06-30",
        "approved": True,
        "source": "客服 SOP / 未成年人退款",
        "content": "未成年人退款需要监护人说明、身份材料、订单归属、付款证明和敏感信息遮盖。即使材料齐全，也必须人工审批，不得自动退款。",
    },
    {
        "doc_id": "faq_logistics_v1",
        "title": "物流异常 FAQ",
        "category": "FAQ",
        "version": "2026-06-30",
        "approved": True,
        "source": "客服 FAQ / 物流",
        "content": "物流超过约定时间未更新时，应先查询物流状态并生成仓库核查任务。未收到仓库或物流反馈前，不承诺具体发货日期。",
    },
    {
        "doc_id": "policy_private_domain_draft",
        "title": "私域触达频控草案",
        "category": "运营政策",
        "version": "draft",
        "approved": False,
        "source": "私域运营草案",
        "content": "草案文档不得直接用于客服 Agent 正式回复，需主管审核后发布。",
    },
]


EVAL_QUESTIONS: List[Dict[str, str]] = [
    {
        "question": "用户说商品有划痕，图片不清楚，可以直接拒赔吗？",
        "expected_doc": "sop_damage_v1",
        "must_contain": "转VIP客服复核",
    },
    {
        "question": "未成年人退款材料齐全时能不能自动退款？",
        "expected_doc": "sop_minor_refund_v1",
        "must_contain": "必须人工审批",
    },
    {
        "question": "物流很久没更新，可以承诺明天发货吗？",
        "expected_doc": "faq_logistics_v1",
        "must_contain": "不承诺具体发货日期",
    },
]
