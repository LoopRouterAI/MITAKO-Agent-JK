"""审核运行时资源预算：标准库实现，避免低内存部署被并发任务拖垮。"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, Optional


MB = 1024**2
GB = 1024**3


@dataclass(frozen=True)
class ResourceSnapshot:
    total_bytes: int
    available_bytes: int
    process_bytes: Optional[int]
    source: str


def _env_mb(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _linux_memory_snapshot() -> ResourceSnapshot:
    values: Dict[str, int] = {}
    try:
        for line in open("/proc/meminfo", "r", encoding="ascii"):
            key, _, raw = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached"}:
                values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        values = {}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable") or sum(values.get(key, 0) for key in ("MemFree", "Buffers", "Cached"))
    source = "proc"
    try:
        limit_raw = open("/sys/fs/cgroup/memory.max", "r", encoding="ascii").read().strip()
        usage_raw = open("/sys/fs/cgroup/memory.current", "r", encoding="ascii").read().strip()
        if limit_raw.isdigit():
            limit = int(limit_raw)
            usage = int(usage_raw) if usage_raw.isdigit() else 0
            if limit > 0:
                total = min(total or limit, limit)
                available = min(available, max(0, limit - usage))
                source = "proc+cgroup"
    except (OSError, ValueError):
        pass
    return ResourceSnapshot(total, max(0, available), None, source)


def _windows_memory_snapshot() -> ResourceSnapshot:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return ResourceSnapshot(int(status.ullTotalPhys), int(status.ullAvailPhys), None, "windows")
    except (AttributeError, OSError):
        return ResourceSnapshot(0, 0, None, "unknown")


def memory_snapshot() -> ResourceSnapshot:
    """获取宿主或 cgroup 视角的物理内存水位。"""
    if sys.platform.startswith("linux"):
        return _linux_memory_snapshot()
    if os.name == "nt":
        return _windows_memory_snapshot()
    return ResourceSnapshot(0, 0, None, "unknown")


def recommended_concurrency(configured: int, *, low_memory_mb: Optional[int] = None) -> int:
    configured = max(1, min(int(configured or 1), 8))
    snapshot = memory_snapshot()
    low_memory = (low_memory_mb if low_memory_mb is not None else _env_mb("REVIEW_RESOURCE_LOW_MEMORY_MB", 4096)) * MB
    min_available = _env_mb("REVIEW_RESOURCE_MIN_AVAILABLE_MB", 512) * MB
    if snapshot.total_bytes and snapshot.total_bytes <= low_memory:
        return 1
    if snapshot.available_bytes and snapshot.available_bytes < min_available * 2:
        return 1
    return configured


class ResourceGate:
    """有界进程内资源槽位，并在启动任务前检查可用内存。"""

    def __init__(self, capacity: int, *, min_available_bytes: Optional[int] = None) -> None:
        self.capacity = max(1, int(capacity))
        self.min_available_bytes = min_available_bytes or _env_mb("REVIEW_RESOURCE_MIN_AVAILABLE_MB", 512) * MB
        self._slots = threading.BoundedSemaphore(self.capacity)
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = 0

    def try_acquire(self, timeout: float = 0.0) -> bool:
        with self._lock:
            self._waiting += 1
        try:
            deadline = time.monotonic() + max(0.0, float(timeout))
            while True:
                snapshot = memory_snapshot()
                if snapshot.available_bytes and snapshot.available_bytes < self.min_available_bytes:
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))
                    continue
                remaining = max(0.0, deadline - time.monotonic())
                if not self._slots.acquire(timeout=remaining):
                    return False
                snapshot = memory_snapshot()
                if snapshot.available_bytes and snapshot.available_bytes < self.min_available_bytes:
                    self._slots.release()
                    if time.monotonic() >= deadline:
                        return False
                    continue
                with self._lock:
                    self._active += 1
                return True
        finally:
            with self._lock:
                self._waiting = max(0, self._waiting - 1)

    def acquire(self, timeout: float = 0.0) -> bool:
        """兼容 threading.Semaphore 的调用形态。"""
        return self.try_acquire(timeout)

    def release(self) -> None:
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("resource_gate_release_without_acquire")
            self._active -= 1
        self._slots.release()

    @contextmanager
    def slot(self, timeout: float = 0.0) -> Iterator[bool]:
        if not self.try_acquire(timeout):
            yield False
            return
        try:
            yield True
        finally:
            self.release()

    def diagnostics(self) -> Dict[str, object]:
        snapshot = memory_snapshot()
        with self._lock:
            active = self._active
            waiting = self._waiting
        return {
            "capacity": self.capacity,
            "active": active,
            "waiting": waiting,
            "available_slots": max(0, self.capacity - active),
            "min_available_bytes": self.min_available_bytes,
            "memory": {
                "total_bytes": snapshot.total_bytes,
                "available_bytes": snapshot.available_bytes,
                "process_bytes": snapshot.process_bytes,
                "source": snapshot.source,
                "pressure": bool(snapshot.available_bytes and snapshot.available_bytes < self.min_available_bytes),
            },
        }


def _configured_capacity(name: str, default: int) -> int:
    try:
        configured = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        configured = default
    return recommended_concurrency(configured)


CASE_GATE = ResourceGate(_configured_capacity("REVIEW_WORKBENCH_WORKERS", 2))
TRANSCODE_GATE = ResourceGate(_configured_capacity("REVIEW_VIDEO_TRANSCODE_CONCURRENCY", 2))


def runtime_diagnostics() -> Dict[str, object]:
    return {
        "memory": {
            "total_bytes": memory_snapshot().total_bytes,
            "available_bytes": memory_snapshot().available_bytes,
            "source": memory_snapshot().source,
        },
        "case_gate": CASE_GATE.diagnostics(),
        "transcode_gate": TRANSCODE_GATE.diagnostics(),
    }
