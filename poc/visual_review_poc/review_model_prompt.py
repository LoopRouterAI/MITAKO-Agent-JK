# -*- coding: utf-8 -*-
"""兼容旧导入路径；实现集中在 prompts.visual_review。"""
from prompts.visual_review.review_model_prompt import (
    build_claim_identity_prompt,
    build_claimed_item_detail_prompt,
    build_fulfillment_observation_prompt,
    build_native_video_perception_prompt,
    build_opening_compliance_prompt,
    build_opening_start_prompt,
    build_product_damage_image_prompt,
    build_sampled_video_batch_prompt,
    build_sampled_video_reduce_prompt,
    build_selection_prompt,
)

__all__ = [
    "build_claim_identity_prompt",
    "build_claimed_item_detail_prompt",
    "build_fulfillment_observation_prompt",
    "build_native_video_perception_prompt",
    "build_opening_compliance_prompt",
    "build_opening_start_prompt",
    "build_product_damage_image_prompt",
    "build_sampled_video_batch_prompt",
    "build_sampled_video_reduce_prompt",
    "build_selection_prompt",
]
