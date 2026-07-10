# -*- coding: utf-8 -*-
"""验证长视频抽帧覆盖完整时轴，并只生成压缩帧供模型输入。"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import sample_video_frames


SAMPLE = ROOT / "docs" / "三大审核场景的小量样本" / "sample_002"
REPORT = ROOT / "tests" / "reports" / "review_media_preprocessing_latest.json"


def main() -> int:
    video = next(path for path in sorted(SAMPLE.iterdir()) if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"})
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-media-check-", dir=ROOT / "tmp") as workdir:
        sampled = sample_video_frames(video, fps=1.0, max_frames=4, probe_seconds=1.0, frame_width=768, run_dir=Path(workdir))
        frames = sampled.get("frames") or []
        duration = float(sampled.get("duration_seconds") or 0)
        checks = {
            "full_timeline_strategy": sampled.get("sampling_strategy") == "full_timeline_uniform",
            "full_timeline_coverage": float(sampled.get("timeline_coverage_ratio") or 0) >= 0.9,
            "tail_frame_included": bool(frames) and float(frames[-1].get("timestamp_seconds") or 0) >= duration * 0.9,
            "compressed_frame_input": (sampled.get("model_input") or {}).get("type") == "compressed_jpeg_frames",
            "source_size_recorded": sampled.get("source_bytes") == video.stat().st_size,
        }
    report = {"ok": all(checks.values()), "video": video.name, "duration_seconds": duration, "checks": checks}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
