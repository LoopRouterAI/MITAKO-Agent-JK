# -*- coding: utf-8 -*-
"""审核服务部署依赖验收：真实 ffprobe、存储水位与可选媒体探测。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from review_service.media_forensics import inspect_job_media, resolve_ffprobe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path)
    parser.add_argument("--minimum-free-mb", type=int, default=2250)
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ffprobe = resolve_ffprobe()
    checks = []
    if ffprobe:
        completed = subprocess.run(
            [ffprobe, "-version"], capture_output=True, text=True, timeout=10, check=False
        )
        checks.append(
            {
                "name": "ffprobe_executable",
                "ok": completed.returncode == 0,
                "configured_by": "REVIEW_FFPROBE_PATH" if os.getenv("REVIEW_FFPROBE_PATH") else "PATH",
                "version_line": (completed.stdout.splitlines() or [""])[0],
            }
        )
    else:
        checks.append({"name": "ffprobe_executable", "ok": False, "reason": "ffprobe_not_available"})

    usage = shutil.disk_usage(Path.cwd())
    minimum_free = args.minimum_free_mb * 1024 * 1024
    checks.append(
        {
            "name": "storage_headroom",
            "ok": usage.free >= minimum_free,
            "free_bytes": usage.free,
            "minimum_free_bytes": minimum_free,
        }
    )

    if args.media:
        media = args.media.expanduser().resolve()
        if not media.is_file():
            checks.append({"name": "real_media_probe", "ok": False, "reason": "media_not_found"})
        elif ffprobe:
            started = time.time()
            result = inspect_job_media(
                media.parent,
                [
                    {
                        "asset_id": "runtime-probe",
                        "original_name": media.name,
                        "stored_name": media.name,
                        "mime_type": "video/mp4",
                    }
                ],
                timeout_seconds=args.timeout,
            )
            checks.append(
                {
                    "name": "real_media_probe",
                    "ok": result.get("status") == "completed",
                    "media_bytes": media.stat().st_size,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "status": result.get("status"),
                    "summary": result.get("summary"),
                }
            )

    output = {"ok": all(item["ok"] for item in checks), "checks": checks}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
