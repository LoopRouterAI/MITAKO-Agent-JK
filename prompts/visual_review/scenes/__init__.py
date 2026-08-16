# -*- coding: utf-8 -*-
"""四场景 Prompt 与 Schema 的唯一运行时注册入口。"""
from __future__ import annotations

from typing import Any, Dict

from prompts.visual_review.schemas import (
    CLAIM_IDENTITY_RESPONSE_SCHEMA,
    CLAIMED_ITEM_DETAIL_RESPONSE_SCHEMA,
    FRAME_RESPONSE_SCHEMA,
    MISSING_ITEM_OBSERVATION_RESPONSE_SCHEMA,
    MINOR_MATERIAL_CONSISTENCY_RESPONSE_SCHEMA,
    MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA,
    MINOR_MATERIAL_VIDEO_RESPONSE_SCHEMA,
    NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA,
    NATIVE_VIDEO_RESPONSE_SCHEMA,
    OPENING_COMPLIANCE_RESPONSE_SCHEMA,
    OPENING_START_RESPONSE_SCHEMA,
    OPENING_VIDEO_ROLE_RESPONSE_SCHEMA,
    PRODUCT_DAMAGE_IMAGE_RESPONSE_SCHEMA,
    WRONG_ITEM_OBSERVATION_RESPONSE_SCHEMA,
)
from . import missing_item, minor_refund, product_damage, wrong_item


_SCENES = {
    module.SCENE: {
        "module": module.__name__,
        "name": module.SCENE_NAME,
        "objective": module.OBJECTIVE,
        "default_rules": module.DEFAULT_RULES,
    }
    for module in (product_damage, wrong_item, missing_item, minor_refund)
}
_SCENES["minor_material"] = _SCENES["minor_refund"]

_MODE_SCHEMAS = {
    "claim_identity_only": CLAIM_IDENTITY_RESPONSE_SCHEMA,
    "claimed_item_detail_only": CLAIMED_ITEM_DETAIL_RESPONSE_SCHEMA,
    "native_video_perception": NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA,
    "sampled_video_perception": NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA,
    "sampled_video_batch_observation": NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA,
    "sampled_video_perception_reduce": NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA,
    "opening_compliance_only": OPENING_COMPLIANCE_RESPONSE_SCHEMA,
    "opening_start_only": OPENING_START_RESPONSE_SCHEMA,
    "opening_video_role_preflight": OPENING_VIDEO_ROLE_RESPONSE_SCHEMA,
    "minor_material_inventory": MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA,
    "minor_material_process_video": MINOR_MATERIAL_VIDEO_RESPONSE_SCHEMA,
    "minor_material_consistency": MINOR_MATERIAL_CONSISTENCY_RESPONSE_SCHEMA,
    "product_damage_images": PRODUCT_DAMAGE_IMAGE_RESPONSE_SCHEMA,
}


def get_scene_definition(scenario: str) -> Dict[str, Any]:
    return dict(_SCENES.get(scenario) or {})


def resolve_response_schema(
    scenario: str,
    analysis_mode: str,
    has_native_video: bool,
) -> Dict[str, Any]:
    if analysis_mode in _MODE_SCHEMAS:
        return _MODE_SCHEMAS[analysis_mode]
    if scenario == "product_damage":
        return NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA
    if scenario == "wrong_item":
        return WRONG_ITEM_OBSERVATION_RESPONSE_SCHEMA
    if scenario == "missing_item":
        return MISSING_ITEM_OBSERVATION_RESPONSE_SCHEMA
    return NATIVE_VIDEO_RESPONSE_SCHEMA if has_native_video else FRAME_RESPONSE_SCHEMA


__all__ = ["get_scene_definition", "resolve_response_schema"]
