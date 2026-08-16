# -*- coding: utf-8 -*-
"""兼容旧入口：生成 Gemini 3.5 Flash 单样本审核报告。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    cmd = [
        sys.executable,
        str(ROOT / "poc" / "visual_review_poc" / "local_video_triage_demo.py"),
        "--video",
        str(ROOT / "docs" / "三大审核场景的小量样本" / "sample_001" / "005_cWKxEnRn.mp4"),
        "--fps",
        "1",
        "--max-frames",
        "12",
        "--api-frame-limit",
        "12",
        "--probe-seconds",
        "0",
        "--supplemental-image-limit",
        "4",
        "--request-timeout",
        "240",
        "--soft-retries",
        "2",
    ]
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
