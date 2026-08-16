# -*- coding: utf-8 -*-
"""Gemini 原生及兼容网关共用的端点和认证规则。"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote, urlsplit

from configs.model_catalog import MODEL_CONFIGS


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"


def _first_env(names: Iterable[str]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def resolve_gemini_model(model: str = "") -> str:
    supported = {
        str(config.get("model") or "").strip()
        for config in MODEL_CONFIGS.values()
        if str(config.get("model") or "").strip()
    }
    candidates = (
        str(model or "").strip(),
        os.getenv("VISUAL_REVIEW_PRIMARY_MODEL", "").strip(),
        os.getenv("GEMINI_MODEL", "").strip(),
        DEFAULT_GEMINI_MODEL,
    )
    return next((candidate for candidate in candidates if candidate in supported), DEFAULT_GEMINI_MODEL)


def endpoint_vendor_hint(endpoint: str) -> str:
    host = (urlsplit(endpoint).hostname or "").lower()
    if "bananarouter" in host or "brouter" in host:
        return "bananarouter"
    if host.endswith("baidubce.com"):
        return "baidu"
    if "apiyi" in host:
        return "apiyi"
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
    bearer = mode == "bearer" or (
        mode == "auto" and endpoint_vendor_hint(endpoint) in {"bananarouter", "baidu", "apiyi"}
    )
    key_name = "Authorization" if bearer else "x-goog-api-key"
    key_value = f"Bearer {api_key}" if bearer else api_key
    return {key_name: key_value, "Content-Type": "application/json"}


def gemini_channel_options(model: str = "") -> List[Dict[str, Any]]:
    """按固定优先级生成已完整配置且去重的 Gemini 请求通道。"""
    resolved_model = resolve_gemini_model(model)
    shared_base = _first_env(("VISION_REVIEW_GEMINI_BASE_URL",))
    shared_hint = endpoint_vendor_hint(shared_base) if shared_base else ""
    specs: List[Tuple[str, Tuple[str, ...], Tuple[str, ...], str]] = [
        (
            "bananarouter",
            ("BANANAROUTER_API_KEY", "BROUTER_API_KEY", "BRouter_API_KEY"),
            ("BANANAROUTER_GEMINI_BASE_URL", "BANANAROUTER_BASE_URL", "BROUTER_GEMINI_BASE_URL", "BROUTER_BASE_URL"),
            "bearer",
        ),
        ("baidu", ("BAIDU_API_KEY",), ("BAIDU_GEMINI_BASE_URL", "BAIDU_BASE_URL"), "bearer"),
        ("apiyi", ("APIYI_API_KEY",), ("APIYI_GEMINI_BASE_URL", "APIYI_BASE_URL"), "bearer"),
    ]
    candidates: List[Tuple[str, str, str, str]] = []
    for channel, key_names, url_names, auth_mode in specs:
        key = _first_env(key_names)
        base = _first_env(url_names) or (shared_base if shared_hint == channel else "")
        if key and base:
            candidates.append((channel, key, base, auth_mode))

    official_key = _first_env(("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    if official_key:
        configured_base = _first_env(("GEMINI_API_BASE_URL",)) or DEFAULT_GEMINI_BASE_URL
        configured_hint = endpoint_vendor_hint(configured_base)
        candidates.append(
            (
                "official" if configured_hint == "google" else configured_hint,
                official_key,
                configured_base,
                os.getenv("GEMINI_AUTH_MODE", "auto"),
            )
        )

    if shared_base:
        legacy_channel = "official" if shared_hint == "google" else shared_hint
        configured_channels = {candidate[0] for candidate in candidates}
        if legacy_channel == "compatible":
            if not candidates:
                legacy_key = _first_env(
                    ("VISION_REVIEW_API_KEY", "BROUTER_API_KEY", "BRouter_API_KEY", "APIYI_API_KEY")
                )
                if legacy_key:
                    candidates.append(
                        ("legacy", legacy_key, shared_base, os.getenv("VISION_REVIEW_GEMINI_AUTH_MODE", "auto"))
                    )
        elif legacy_channel not in configured_channels:
            legacy_keys = {
                "bananarouter": ("VISION_REVIEW_API_KEY", "BROUTER_API_KEY", "BRouter_API_KEY"),
                "baidu": ("VISION_REVIEW_API_KEY", "BAIDU_API_KEY"),
                "apiyi": ("VISION_REVIEW_API_KEY", "APIYI_API_KEY"),
                "official": ("VISION_REVIEW_API_KEY",),
            }
            legacy_key = _first_env(legacy_keys[legacy_channel])
            if legacy_key:
                candidates.append(
                    (
                        legacy_channel,
                        legacy_key,
                        shared_base,
                        os.getenv("VISION_REVIEW_GEMINI_AUTH_MODE", "auto"),
                    )
                )

    options: List[Dict[str, Any]] = []
    seen_endpoints = set()
    priorities = {"baidu": 0, "bananarouter": 1, "legacy": 1, "apiyi": 2, "official": 3}
    candidates.sort(key=lambda item: priorities.get(item[0], 4))
    for channel, key, base, auth_mode in candidates:
        endpoint = gemini_generate_endpoint(base, resolved_model)
        normalized_endpoint = endpoint.casefold()
        if normalized_endpoint in seen_endpoints:
            continue
        seen_endpoints.add(normalized_endpoint)
        options.append(
            {
                "channel": channel,
                "model": resolved_model,
                "endpoint": endpoint,
                "headers": gemini_auth_headers(endpoint, key, auth_mode),
                "supports_external_file_uri": channel == "baidu",
            }
        )
    return options
