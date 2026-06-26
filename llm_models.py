# -*- coding: utf-8 -*-
"""LLM 模型注册表 — 支持多供应商 OpenAI 兼容接口"""
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from llm_rate_limit import DEFAULT_MAX_REQUESTS, DEFAULT_WINDOW_SECONDS, get_rate_limiter

load_dotenv()

# 默认模型（可通过环境变量覆盖）
DEFAULT_MODEL_ID = os.getenv("DEFAULT_MODEL_ID", "deepseek-v4-flash")

# DeepSeek V4 Flash：客服场景关闭思考模式（reasoning_effort=none），响应更快
_DEEPSEEK_REASONING = os.getenv("DEEPSEEK_REASONING_EFFORT", "none").strip().lower()
if _DEEPSEEK_REASONING not in ("none", "low", "medium", "high"):
    _DEEPSEEK_REASONING = "none"

# 模型配置：api_key 从环境变量读取，不写死在代码中
MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "deepseek-v4-flash": {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "description": "SenseNova 高性能对话模型，1M 上下文；客服默认关闭思考模式",
        "api_base": os.getenv("SENSENOVA_API_BASE", "https://token.sensenova.cn/v1"),
        "api_key_env": "SENSENOVA_API_KEY",
        "model": "deepseek-v4-flash",
        "provider": "sensenova",
        # none = 关闭思考模式；high 适合复杂推理任务
        "reasoning_effort": _DEEPSEEK_REASONING,
        "supports_reasoning_stream": _DEEPSEEK_REASONING != "none",
        "stream_options": {"include_usage": True},
        "rate_limit": {
            "max_requests": int(os.getenv("DEEPSEEK_RATE_LIMIT_MAX", str(DEFAULT_MAX_REQUESTS))),
            "window_seconds": int(os.getenv("DEEPSEEK_RATE_LIMIT_WINDOW_SECONDS", str(DEFAULT_WINDOW_SECONDS))),
        },
    },
    "agnes-2.0-flash": {
        "id": "agnes-2.0-flash",
        "label": "Agnes 2.0 Flash",
        "description": "Agnes AI Hub 主力对话模型",
        "api_base": os.getenv("OPENAI_API_BASE", "https://apihub.agnes-ai.com/v1"),
        "api_key_env": "OPENAI_API_KEY",
        "model": os.getenv("MODEL_NAME", "agnes-2.0-flash"),
        "provider": "agnes",
        "supports_reasoning_stream": True,
        "extra_payload": {
            "chat_template_kwargs": {"enable_thinking": False},
        },
    },
}


def get_model_config(model_id: Optional[str] = None) -> Dict[str, Any]:
    """获取模型配置，未知 ID 时回退默认模型"""
    mid = model_id or DEFAULT_MODEL_ID
    if mid not in MODEL_REGISTRY:
        mid = DEFAULT_MODEL_ID
    return MODEL_REGISTRY[mid]


def get_model_api_key(model_id: Optional[str] = None) -> Optional[str]:
    cfg = get_model_config(model_id)
    return os.getenv(cfg["api_key_env"])


def _build_rate_limit_public(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rl = cfg.get("rate_limit")
    if not rl:
        return None
    quota = get_rate_limiter().get_quota(
        cfg["id"],
        rl["max_requests"],
        rl["window_seconds"],
    )
    return {
        "max_requests": quota["max_requests"],
        "window_hours": quota["window_hours"],
        "used": quota["used"],
        "remaining": quota["remaining"],
        "reset_at": quota["reset_at"],
    }


def list_models_public() -> List[Dict[str, Any]]:
    """返回前端可用的模型列表（不含密钥）"""
    result = []
    for cfg in MODEL_REGISTRY.values():
        item = {
            "id": cfg["id"],
            "label": cfg["label"],
            "description": cfg.get("description", ""),
            "provider": cfg.get("provider", ""),
            "is_default": cfg["id"] == DEFAULT_MODEL_ID,
            "configured": bool(os.getenv(cfg["api_key_env"])),
            "reasoning_effort": cfg.get("reasoning_effort"),
        }
        rl_public = _build_rate_limit_public(cfg)
        if rl_public:
            item["rate_limit"] = rl_public
        result.append(item)
    return result


def mask_api_key(key: Optional[str]) -> str:
    if not key or len(key) <= 10:
        return "None"
    return f"{key[:6]}...{key[-4:]}"
