# -*- coding: utf-8 -*-
"""本地启动前的环境变量可用性检查，不输出任何密钥值。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env_file() -> bool:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return False
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")
    return True


def configured(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def main() -> int:
    loaded = load_env_file()
    print("[MITAKO] 环境变量检查：已读取 .env" if loaded else "[MITAKO] 环境变量检查：未发现 .env，将使用当前系统环境")

    checks = [
        (
            "核心对话模型",
            configured("SENSENOVA_API_KEY") or configured("OPENAI_API_KEY"),
            "缺少 SENSENOVA_API_KEY 或 OPENAI_API_KEY，客服自动回复会降级为转人工。",
        ),
        (
            "视觉审核 / Gemini",
            configured("VISION_REVIEW_API_KEY") or configured("GEMINI_API_KEY") or configured("GOOGLE_API_KEY"),
            "缺少 VISION_REVIEW_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY，视频审核只能跑契约或本地样例。",
        ),
        (
            "JWT 鉴权密钥",
            configured("MITAKO_JWT_SECRET"),
            "缺少 MITAKO_JWT_SECRET，启动脚本会使用本地默认值；生产必须替换。",
        ),
    ]

    missing = 0
    for name, ok, warning in checks:
        if ok:
            print(f"[MITAKO] 通过：{name}")
        else:
            missing += 1
            print(f"[MITAKO] 提醒：{warning}")

    if missing:
        print("[MITAKO] 环境检查完成：存在未配置项，但不会阻止本地 POC 启动。")
    else:
        print("[MITAKO] 环境检查完成：关键运行项已配置。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
