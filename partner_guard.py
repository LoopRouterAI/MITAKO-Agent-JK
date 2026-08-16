# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from urllib.parse import urlparse

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def real_partner_api_allowed() -> bool:
    return os.getenv("MITAKO_ALLOW_REAL_PARTNER_API", "0").strip().lower() in ("1", "true", "yes")


def assert_local_or_allowed(url: str, name: str = "partner api") -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_HOSTS or real_partner_api_allowed():
        return url
    raise RuntimeError(
        f"{name} is blocked by default: {url}. "
        "Set MITAKO_ALLOW_REAL_PARTNER_API=1 only for an approved real integration."
    )
