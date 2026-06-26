# -*- coding: utf-8 -*-
"""SenseNova 生图 API 封装"""
from typing import Any, Dict, Optional

import httpx

from image_models import get_image_api_key, get_image_model_config
from llm_models import mask_api_key
from llm_rate_limit import get_rate_limiter


def _has_valid_key(api_key: Optional[str]) -> bool:
    return bool(api_key) and "your_" not in (api_key or "")


async def generate_image(
    prompt: str,
    model_id: str = "sensenova-u1-fast",
    size: Optional[str] = None,
    n: int = 1,
) -> Dict[str, Any]:
    """调用 POST /v1/images/generations，返回 URL 与配额信息"""
    cfg = get_image_model_config(model_id)
    api_key = get_image_api_key(model_id)
    if not _has_valid_key(api_key):
        key_env = cfg.get("api_key_env", "SENSENOVA_API_KEY")
        raise ValueError(f"未配置有效的 API Key，请在 .env 中设置 {key_env}")

    rl = cfg["rate_limit"]
    limiter = get_rate_limiter()
    allowed, quota = limiter.try_acquire(cfg["id"], rl["max_requests"], rl["window_seconds"])
    if not allowed:
        raise RuntimeError(
            f"SenseNova U1 配额已用尽：每 {quota['window_hours']} 小时最多 "
            f"{quota['max_requests']} 次，已用 {quota['used']} 次"
        )

    rl = cfg["rate_limit"]
    limiter = get_rate_limiter()
    allowed, quota = limiter.try_acquire(cfg["id"], rl["max_requests"], rl["window_seconds"])
    if not allowed:
        raise RuntimeError(
            f"SenseNova U1 配额已用尽：每 {quota['window_hours']} 小时最多 "
            f"{quota['max_requests']} 次，已用 {quota['used']} 次"
        )

    try:
        payload = {
            "model": cfg["model"],
            "prompt": prompt.strip(),
            "size": size or cfg["default_size"],
            "n": max(1, min(n, 1)),
        }

        api_base = cfg["api_base"].rstrip("/")
        timeout = httpx.Timeout(180.0, connect=15.0, read=180.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{api_base}{cfg['endpoint']}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"生图 API 错误 {resp.status_code}: {resp.text[:500]}")
            data = resp.json()

        urls = [item.get("url") for item in data.get("data", []) if item.get("url")]
        if not urls:
            raise RuntimeError("生图 API 未返回图片 URL")

        updated_quota = limiter.get_quota(cfg["id"], rl["max_requests"], rl["window_seconds"])

        return {
            "model": cfg["label"],
            "model_id": cfg["id"],
            "urls": urls,
            "created": data.get("created"),
            "api_key_masked": mask_api_key(api_key),
            "request": payload,
            "rate_limit": updated_quota,
        }
    except Exception:
        limiter.release_last(cfg["id"])
        raise
