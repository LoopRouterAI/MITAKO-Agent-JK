# -*- coding: utf-8 -*-
"""LLM 调用配额追踪 — 滑动窗口限流（持久化到本地 JSON）"""
import json
import os
import time
from threading import Lock
from typing import Any, Dict, List, Tuple

from runtime_paths import viking_memory_dir

# DeepSeek V4 Flash @ SenseNova 平台配额：每 5 小时 500 次
DEFAULT_WINDOW_SECONDS = 5 * 3600
DEFAULT_MAX_REQUESTS = 500


class LLMRateLimiter:
    """按 model_id 记录调用时间戳，滑动窗口内限制最大请求次数"""

    def __init__(self, state_path: str = None):
        memory_dir = str(viking_memory_dir())
        os.makedirs(memory_dir, exist_ok=True)
        self.state_path = state_path or os.path.join(memory_dir, "llm_rate_limit.json")
        self._lock = Lock()

    def _load(self) -> Dict[str, List[float]]:
        if not os.path.exists(self.state_path):
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k: list(v) for k, v in data.items() if isinstance(v, list)}
        except Exception:
            return {}

    def _save(self, data: Dict[str, List[float]]) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _prune(self, timestamps: List[float], window_seconds: int) -> List[float]:
        cutoff = time.time() - window_seconds
        return sorted(t for t in timestamps if t >= cutoff)

    def get_quota(
        self,
        model_id: str,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> Dict[str, Any]:
        """返回当前窗口内的用量与剩余配额"""
        with self._lock:
            data = self._load()
            active = self._prune(data.get(model_id, []), window_seconds)
            used = len(active)
            remaining = max(0, max_requests - used)
            reset_at = int(active[0] + window_seconds) if active else None
            return {
                "max_requests": max_requests,
                "window_seconds": window_seconds,
                "window_hours": window_seconds // 3600,
                "used": used,
                "remaining": remaining,
                "reset_at": reset_at,
            }

    def check(
        self,
        model_id: str,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> Tuple[bool, Dict[str, Any]]:
        quota = self.get_quota(model_id, max_requests, window_seconds)
        return quota["remaining"] > 0, quota

    def try_acquire(
        self,
        model_id: str,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> Tuple[bool, Dict[str, Any]]:
        """原子检查并占用一次配额，成功返回 (True, quota)"""
        with self._lock:
            data = self._load()
            active = self._prune(data.get(model_id, []), window_seconds)
            if len(active) >= max_requests:
                used = len(active)
                reset_at = int(active[0] + window_seconds) if active else None
                return False, {
                    "max_requests": max_requests,
                    "window_seconds": window_seconds,
                    "window_hours": window_seconds // 3600,
                    "used": used,
                    "remaining": 0,
                    "reset_at": reset_at,
                }
            active.append(time.time())
            data[model_id] = active
            self._save(data)
            used = len(active)
            remaining = max(0, max_requests - used)
            reset_at = int(active[0] + window_seconds) if active else None
            return True, {
                "max_requests": max_requests,
                "window_seconds": window_seconds,
                "window_hours": window_seconds // 3600,
                "used": used,
                "remaining": remaining,
                "reset_at": reset_at,
            }

    def release_last(self, model_id: str) -> None:
        """失败回滚：移除该模型最近一次占用的时间戳"""
        with self._lock:
            data = self._load()
            active = data.get(model_id, [])
            if active:
                active.pop()
                if active:
                    data[model_id] = active
                else:
                    data.pop(model_id, None)
                self._save(data)

    def record(
        self,
        model_id: str,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
    ) -> Dict[str, Any]:
        """记录一次成功调用并返回更新后的配额"""
        with self._lock:
            data = self._load()
            active = self._prune(data.get(model_id, []), window_seconds)
            active.append(time.time())
            data[model_id] = active
            self._save(data)
        return self.get_quota(model_id, max_requests, window_seconds)


_limiter: LLMRateLimiter = None


def get_rate_limiter() -> LLMRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = LLMRateLimiter()
    return _limiter
