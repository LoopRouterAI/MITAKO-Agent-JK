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
        "必须把“当前能看见损伤”和“损伤在何时、由什么原因形成”拆成两个问题",
        "看见损伤不等于证明",
        "连续前后画面",
        "没有品类标准时不得套用固定处数、毫米或展示秒数阈值",
        "只有连续画面清楚展示动作前无伤、动作过程和动作后出现同位置损伤",
    ),
    "wrong_item": ("绿色自封袋", "光栅", "隐藏款", "角色", "SKU"),
    "missing_item": ("拆单", "纸类", "全家福", "绿色自封袋", "仓库终核", "待核实备注本身不能下结论"),
    "minor_refund": (
        "五类材料",
        "主副卡",
        "低于 10 周岁",
        "不输出支持或不支持退款诉求",
        "五类和低龄条件均闭环时只写材料审核通过",
        "材料齐全且无动作时不输出空泛流程话术",
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
