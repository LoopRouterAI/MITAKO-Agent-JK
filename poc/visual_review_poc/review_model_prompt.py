# -*- coding: utf-8 -*-
"""兼容旧导入路径；实现集中在 prompts.visual_review。"""
from prompts.visual_review.review_model_prompt import (
    build_opening_compliance_prompt,
    build_opening_start_prompt,
    build_selection_prompt,
)

__all__ = [
    "build_opening_compliance_prompt",
    "build_opening_start_prompt",
    "build_selection_prompt",
]
