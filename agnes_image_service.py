# -*- coding: utf-8 -*-
"""Agnes Image 2.1 Flash — OpenAI 兼容生图兜底"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from dotenv import load_dotenv
from image_models import get_image_api_key, get_image_model_config
from llm_models import mask_api_key

load_dotenv()


def _has_valid_key(api_key: Optional[str]) -> bool:
    return bool(api_key) and "your_" not in (api_key or "")


async def generate_image_agnes(
    prompt: str,
    model_id: str = "agnes-image-2.1-flash",
    size: Optional[str] = None,
    n: int = 1,
) -> Dict[str, Any]:
    """POST /v1/images/generations — Agnes Hub"""
    cfg = get_image_model_config(model_id)
    api_key = get_image_api_key(model_id)
    if not _has_valid_key(api_key):
        key_env = cfg.get("api_key_env", "AGNES_API_KEY")
        raise ValueError(f"未配置有效的 Agnes API Key，请在 .env 中设置 {key_env}")

    payload = {
        "model": cfg["model"],
        "prompt": prompt.strip()[:4000],
        "size": size or cfg.get("default_size", "2752x1536"),
        "n": max(1, min(n, 1)),
    }
    api_base = cfg["api_base"].rstrip("/")
    endpoint = cfg.get("endpoint", "/images/generations")
    timeout = httpx.Timeout(180.0, connect=15.0, read=180.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{api_base}{endpoint}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Agnes 生图 API 错误 {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

    urls = [item.get("url") for item in data.get("data", []) if item.get("url")]
    if not urls:
        raise RuntimeError("Agnes 生图 API 未返回图片 URL")

    return {
        "model": cfg["label"],
        "model_id": cfg["id"],
        "urls": urls,
        "created": data.get("created"),
        "api_key_masked": mask_api_key(api_key),
        "request": payload,
    }
