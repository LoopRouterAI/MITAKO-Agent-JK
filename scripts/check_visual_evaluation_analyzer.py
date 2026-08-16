# -*- coding: utf-8 -*-
"""锁定离线评测统计口径，并确保不会引入运行时标签门槛。"""
from __future__ import annotations

from analyze_visual_review_results import analyze_rows, render_html


def main() -> int:
    rows = [
        {"人工结论": "正向", "系统结论": "正向", "置信度": 0.9},
        {"人工结论": "正向", "系统结论": "需复核", "置信度": 0.6},
        {"人工结论": "负向", "系统结论": "正向", "置信度": 0.8},
        {"人工结论": "负向", "系统结论": "负向", "置信度": 0.7},
        {"人工结论": "负向", "系统结论": "需复核", "置信度": 0.5},
        {"人工结论": "需复核", "系统结论": "需复核"},
    ]
    report = analyze_rows(rows)
    checks = {
        "三分类一致率": report["metrics"]["exact_agreement"] == 0.5,
        "负向误接纳风险": report["metrics"]["negative_to_positive_risk"] == round(1 / 3, 6),
        "负向安全路由": report["metrics"]["negative_safe_route"] == round(2 / 3, 6),
        "review 单独统计": report["metrics"]["review_route_rate"] == 0.5,
        "无商务治理硬门槛": "不要求双人标注或仲裁字段" in report["boundary"],
        "HTML 可读": "混淆矩阵" in render_html(report, "评测分析器回归"),
    }
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
