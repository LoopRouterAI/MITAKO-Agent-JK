# -*- coding: utf-8 -*-
"""LLM 模型注册表 — 支持多供应商 OpenAI 兼容接口"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from llm_rate_limit import DEFAULT_MAX_REQUESTS, DEFAULT_WINDOW_SECONDS, get_rate_limiter

try:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
except Exception:
    pass


def _env_name(*parts: str) -> str:
    return "_".join(parts)

# 默认模型（可通过环境变量覆盖）
DEFAULT_MODEL_ID = os.getenv("DEFAULT_MODEL_ID", "deepseek-v4-flash")
DEFAULT_PUBLIC_MODEL_ID = "standard-service"

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
        "api_base": os.getenv(_env_name("SENSENOVA", "API", "BASE"), "https://token.sensenova.cn/v1"),
        "api_key_env": _env_name("SENSENOVA", "API", "KEY"),
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
        "api_base": os.getenv(_env_name("OPENAI", "API", "BASE"), "https://apihub.agnes-ai.com/v1"),
        "api_key_env": _env_name("OPENAI", "API", "KEY"),
        "model": os.getenv("MODEL_NAME", "agnes-2.0-flash"),
        "provider": "agnes",
        "supports_reasoning_stream": True,
        "extra_payload": {
            "chat_template_kwargs": {"enable_thinking": False},
        },
    },
}


PUBLIC_MODEL_ALIASES = {
    "standard-service": DEFAULT_MODEL_ID,
    "backup-service": "agnes-2.0-flash",
}


def get_model_config(model_id: Optional[str] = None) -> Dict[str, Any]:
    """获取模型配置，未知 ID 时回退默认模型"""
    mid = PUBLIC_MODEL_ALIASES.get(model_id or "", model_id or DEFAULT_MODEL_ID)
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
    """返回客户可见回复方式；真实模型、供应商与密钥状态只留在服务端。"""
    return [
        {
            "id": "standard-service" if cfg["id"] == DEFAULT_MODEL_ID else "backup-service",
            "label": "标准回复" if cfg["id"] == DEFAULT_MODEL_ID else "备用回复",
            "description": "用于客服回复、意图识别与服务记录整理",
            "is_default": cfg["id"] == DEFAULT_MODEL_ID,
            "configured": True,
        }
        for cfg in MODEL_REGISTRY.values()
    ]


def mask_api_key(key: Optional[str]) -> str:
    if not key or len(key) <= 10:
        return "None"
    return f"{key[:6]}...{key[-4:]}"
