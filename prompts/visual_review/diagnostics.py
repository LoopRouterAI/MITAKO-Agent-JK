# -*- coding: utf-8 -*-
"""视觉审核诊断脚本共用的提示词构建器。"""
from __future__ import annotations

from typing import Any, Dict


DIAGNOSTIC_BOUNDARY = "只做证据初筛，不自动定责、拒赔、退款或补发。"


def build_fixture_contract_prompt(case: Dict[str, Any]) -> str:
    return f"""你是客服视觉审核助手。请只输出 JSON，不要输出解释。
任务：判断 {case['title']}。
要求字段：case_id, scenario, decision, confidence, issues, evidence, next_step, human_required, mock_only, boundary。
边界：这是 Mock 契约，{DIAGNOSTIC_BOUNDARY} human_required 只表示证据必须人工复核；材料齐全且无关键冲突时不得仅因未成年人场景强制转人工。"""


def build_real_api_fixture_prompt(sample: Dict[str, Any]) -> str:
    return f"""你是客服视觉审核助手。请根据图片判断场景：{sample['scenario']}。
样例标题：{sample['title']}。
只输出 JSON，字段必须匹配 schema。
业务边界：
- {DIAGNOSTIC_BOUNDARY}
- 未成年人材料齐全、清晰且无关键冲突时，可以输出明确初审结论，不得仅因场景类型强制 human_required=true。
- 当前素材来自公开网络样例，不代表甲方真实样本。
请把 mock_only 设为 false，boundary 写明“真实 Gemini API 调用结果，仍需甲方样本盲测和人工复核”。"""


def build_public_video_prompt(case: Dict[str, Any]) -> str:
    focus = "、".join(case["review_focus"])
    return f"""你是电商客服视觉审核质检助手。请分析前面提供的公开视频，按售后审核视角只输出严格 JSON，不要输出 Markdown。
场景：{case['scenario']}
标题：{case['title']}
审核重点：{focus}
必须输出字段：case_id, scenario, decision, confidence, issues, evidence, timestamps, next_step, human_required, boundary。
decision 只能是 pass/suspect/fail/manual_review/request_more_material。
要求：
- evidence 必须说明视频中能看到或看不到什么。
- timestamps 尽量给出关键时间点；如果无法定位，返回空数组并说明原因。
- {DIAGNOSTIC_BOUNDARY}
- 公开视频不是甲方真实样本，boundary 必须写明仍需甲方脱敏样本盲测。"""
