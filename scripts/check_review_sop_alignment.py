# -*- coding: utf-8 -*-
"""验证四类优先审核场景与甲方 SOP 的关键约束保持对齐。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import build_system_prompt


REQUIRED = {
    "product_damage": (
        "一镜到底",
        "未拆封",
        "5mm",
        "物流运输",
        "用户拆封或后续操作",
        "连续前后画面",
        "不得直接认定",
    ),
    "wrong_item": ("绿色自封袋", "光栅", "隐藏款", "角色", "SKU"),
    "missing_item": ("拆单", "纸类", "全家福", "绿色自封袋", "仓库终核", "待核实备注本身不能下结论"),
    "minor_refund": (
        "五类材料",
        "主副卡",
        "10周岁以下",
        "不得笼统写“必须调用权威接口”",
        "可以输出明确正向初审建议",
    ),
}


def main() -> int:
    checks = {
        scenario: all(term in build_system_prompt(scenario) for term in terms)
        for scenario, terms in REQUIRED.items()
    }
    boundaries = all(
        "business_action_allowed 必须为 false" in build_system_prompt(scenario)
        and "human_required 只表示证据是否必须人工复核" in build_system_prompt(scenario)
        and "不能因为业务动作由甲方执行就强制转人工" in build_system_prompt(scenario)
        and "证据足够时要敢于输出 positive 或 negative" in build_system_prompt(scenario)
        and "不自动退款、不自动拒赔、不自动补发、不自动定责" in build_system_prompt(scenario)
        for scenario in REQUIRED
    )
    report = {"ok": all(checks.values()) and boundaries, "scenarios": checks, "business_boundary": boundaries}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
