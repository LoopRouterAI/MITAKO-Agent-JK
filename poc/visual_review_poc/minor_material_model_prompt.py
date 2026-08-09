# -*- coding: utf-8 -*-
"""兼容旧导入路径；实现集中在 prompts.visual_review。"""
from prompts.visual_review.minor_material_model_prompt import (
    CONSISTENCY_FIELDS,
    CONSISTENCY_LABELS,
    DOCUMENT_TYPES,
    build_minor_material_consistency_prompt,
    build_minor_material_inventory_prompt,
    build_minor_material_video_prompt,
)

__all__ = [
    "CONSISTENCY_FIELDS",
    "CONSISTENCY_LABELS",
    "DOCUMENT_TYPES",
    "build_minor_material_consistency_prompt",
    "build_minor_material_inventory_prompt",
    "build_minor_material_video_prompt",
]
