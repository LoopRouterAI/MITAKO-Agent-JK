# -*- coding: utf-8 -*-
"""Companion 审核模型配置 — 统一走 DeepSeek V4 Flash（SenseNova）"""
from __future__ import annotations

import os
from typing import Optional

# 默认 deepseek-v4-flash + SENSENOVA_API_KEY，与主对话一致
DEFAULT_REVIEW_MODEL_ID = os.getenv("COMPANION_REVIEW_MODEL", "deepseek-v4-flash")


def resolve_review_model_id(explicit: Optional[str] = None) -> str:
    """解析审核用 model_id — 未指定时固定 DeepSeek 审核链"""
    mid = (explicit or "").strip()
    if mid:
        return mid
    return DEFAULT_REVIEW_MODEL_ID
