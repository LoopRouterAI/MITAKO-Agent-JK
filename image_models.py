# -*- coding: utf-8 -*-
"""生图模型注册表。"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from llm_rate_limit import get_rate_limiter

try:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
except Exception:
    pass


def _env_name(*parts: str) -> str:
    return "_".join(parts)

# U1 Fast：每 5 小时 1500 次
U1_WINDOW_SECONDS = 5 * 3600
U1_MAX_REQUESTS = 1500

IMAGE_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "sensenova-u1-fast": {
        "id": "sensenova-u1-fast",
        "label": "SenseNova U1 Fast",
        "description": "信息图 Infographics 加速生成，2K 多比例",
        "api_base": os.getenv(_env_name("SENSENOVA", "API", "BASE"), "https://token.sensenova.cn/v1"),
        "api_key_env": _env_name("SENSENOVA", "API", "KEY"),
        "model": "sensenova-u1-fast",
        "endpoint": "/images/generations",
        "default_size": os.getenv("SENSENOVA_U1_DEFAULT_SIZE", "2752x1536"),
        "provider": "sensenova",
        "rate_limit": {
            "max_requests": int(os.getenv("SENSENOVA_U1_RATE_LIMIT_MAX", str(U1_MAX_REQUESTS))),
            "window_seconds": int(os.getenv("SENSENOVA_U1_RATE_LIMIT_WINDOW_SECONDS", str(U1_WINDOW_SECONDS))),
        },
        "allowed_sizes": [
            "1664x2496", "2496x1664", "1760x2368", "2368x1760",
            "1824x2272", "2272x1824", "2048x2048", "2752x1536",
            "1536x2752", "3072x1376", "1344x3136",
        ],
    },
    "agnes-image-2.1-flash": {
        "id": "agnes-image-2.1-flash",
        "label": "Agnes Image 2.1 Flash",
        "description": "Agnes Hub 生图兜底（OpenAI 兼容 images API）",
        "api_base": os.getenv(_env_name("AGNES", "API", "BASE"), os.getenv(_env_name("OPENAI", "API", "BASE"), "https://apihub.agnes-ai.com/v1")),
        "api_key_env": _env_name("AGNES", "API", "KEY"),
        "model": os.getenv("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash"),
        "endpoint": "/images/generations",
        "default_size": "2752x1536",
        "provider": "agnes",
        "rate_limit": {
            "max_requests": int(os.getenv("AGNES_IMAGE_RATE_LIMIT_MAX", "500")),
            "window_seconds": int(os.getenv("AGNES_IMAGE_RATE_LIMIT_WINDOW_SECONDS", str(5 * 3600))),
        },
        "allowed_sizes": [
            "2752x1536", "1760x2368", "1536x2752", "2048x2048",
        ],
    },
}

PUBLIC_IMAGE_MODEL_ALIASES = {
    "standard-image": "sensenova-u1-fast",
    "backup-image": "agnes-image-2.1-flash",
}


def get_image_model_config(model_id: Optional[str] = None) -> Dict[str, Any]:
    mid = PUBLIC_IMAGE_MODEL_ALIASES.get(model_id or "", model_id or "sensenova-u1-fast")
    if mid not in IMAGE_MODEL_REGISTRY:
        mid = "sensenova-u1-fast"
    return IMAGE_MODEL_REGISTRY[mid]


def get_image_api_key(model_id: Optional[str] = None) -> Optional[str]:
    cfg = get_image_model_config(model_id)
    key = os.getenv(cfg["api_key_env"])
    if not key and cfg.get("provider") == "agnes":
        key = os.getenv(_env_name("OPENAI", "API", "KEY"))
    return key


def _build_image_rate_limit_public(cfg: Dict[str, Any]) -> Dict[str, Any]:
    rl = cfg["rate_limit"]
    quota = get_rate_limiter().get_quota(cfg["id"], rl["max_requests"], rl["window_seconds"])
    return {
        "max_requests": quota["max_requests"],
        "window_hours": quota["window_hours"],
        "used": quota["used"],
        "remaining": quota["remaining"],
        "reset_at": quota["reset_at"],
    }


def list_image_models_public() -> List[Dict[str, Any]]:
    """返回客户可见生图档位；真实模型、供应商与配额只留在服务端。"""
    return [
        {
            "id": "standard-image" if idx == 0 else "backup-image",
            "label": "标准配图档位" if idx == 0 else "备用配图档位",
            "description": "用于对话配图与视觉素材生成",
            "configured": True,
            "default_size": cfg.get("default_size"),
            "allowed_sizes": cfg.get("allowed_sizes", []),
        }
        for idx, cfg in enumerate(IMAGE_MODEL_REGISTRY.values())
    ]
