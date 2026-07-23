# -*- coding: utf-8 -*-
"""Gemini 原生及兼容网关共用的端点和认证规则。"""
from __future__ import annotations

from typing import Dict
from urllib.parse import quote, urlsplit


def endpoint_vendor_hint(endpoint: str) -> str:
    host = (urlsplit(endpoint).hostname or "").lower()
    if host.endswith("baidubce.com"):
        return "baidu"
    if host.endswith("googleapis.com"):
        return "google"
    return "compatible"


def gemini_generate_endpoint(base_or_endpoint: str, model: str) -> str:
    base = str(base_or_endpoint or "").strip().rstrip("/")
    encoded_model = quote(str(model or "").strip(), safe="-._")
    if "{model}" in base:
        return base.replace("{model}", encoded_model)
    if base.endswith(":generateContent"):
        return base
    if "/models/" in base:
        return f"{base}:generateContent"
    return f"{base}/v1beta/models/{encoded_model}:generateContent"


def gemini_auth_headers(endpoint: str, api_key: str, auth_mode: str = "auto") -> Dict[str, str]:
    mode = str(auth_mode or "auto").strip().lower()
    if mode not in {"auto", "bearer", "google_key"}:
        raise ValueError("invalid_gemini_auth_mode")
    bearer = mode == "bearer" or (mode == "auto" and endpoint_vendor_hint(endpoint) == "baidu")
    key_name = "Authorization" if bearer else "x-goog-api-key"
    key_value = f"Bearer {api_key}" if bearer else api_key
    return {key_name: key_value, "Content-Type": "application/json"}
