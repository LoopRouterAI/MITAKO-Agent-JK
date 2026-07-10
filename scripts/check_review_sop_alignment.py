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
    "product_damage": ("一镜到底", "未拆封", "5mm", "用户暴力拆件", "快递暴力运输"),
    "wrong_item": ("绿色自封袋", "光栅", "隐藏款", "角色", "SKU"),
    "missing_item": ("拆单", "纸类", "全家福", "绿色自封袋", "_1"),
    "minor_refund": ("五类材料", "主副卡", "10周岁以下", "人工一审", "二审", "终审"),
}


def main() -> int:
    checks = {
        scenario: all(term in build_system_prompt(scenario) for term in terms)
        for scenario, terms in REQUIRED.items()
    }
    boundaries = all(
        "business_action_allowed 必须为 false" in build_system_prompt(scenario)
        and "human_required 必须为 true" in build_system_prompt(scenario)
        for scenario in REQUIRED
    )
    report = {"ok": all(checks.values()) and boundaries, "scenarios": checks, "business_boundary": boundaries}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
