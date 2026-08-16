# -*- coding: utf-8 -*-
"""验证受控 1 FPS 回退与独立 WebP 图片送审策略。"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import adaptive_frame_budget, sample_video_frames
from poc.visual_review_poc.media_preflight import prepare_image_media, resolve_runtime_temp_dir


SAMPLE = ROOT / "docs" / "三大审核场景的小量样本" / "sample_002"
REPORT = ROOT / "tests" / "reports" / "review_media_preprocessing_latest.json"


def main() -> int:
    video = next(path for path in sorted(SAMPLE.iterdir()) if path.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".mkv"})
    runtime_root = resolve_runtime_temp_dir(ROOT)
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-media-check-", dir=runtime_root) as workdir:
        sampled = sample_video_frames(video, fps=1.0, max_frames=4, probe_seconds=1.0, frame_width=768, run_dir=Path(workdir))
        frames = sampled.get("frames") or []
        duration = float(sampled.get("duration_seconds") or 0)
        model_input = sampled.get("model_input") or {}
        checks = {
            "full_timeline_strategy": sampled.get("sampling_strategy") == "full_timeline_adaptive",
            "full_timeline_coverage": float(sampled.get("timeline_coverage_ratio") or 0) >= 0.9,
            "tail_frame_included": bool(frames) and float(frames[-1].get("timestamp_seconds") or 0) >= duration * 0.9,
            "compressed_frame_input": (
                model_input.get("type") == "individual_lossless_webp_frames"
                and model_input.get("lossless") is True
                and bool(frames)
                and all(Path(frame["path"]).suffix.lower() == ".webp" for frame in frames)
            ),
            "source_size_recorded": sampled.get("source_bytes") == video.stat().st_size,
            "large_video_adaptive_budget": adaptive_frame_budget(452.5, 543_351_335, 24) == 18,
        }
        dense = sample_video_frames(
            video,
            fps=1.0,
            max_frames=1800,
            probe_seconds=1.0,
            frame_width=768,
            run_dir=Path(workdir) / "dense",
            sampling_mode="dense",
        )
        checks["dense_1fps"] = dense.get("sampling_strategy") == "full_timeline_dense" and dense.get("sampled_frames", 0) >= math.floor(duration * 0.9)
        checks["dense_matches_sampling_plan"] = abs(
            dense.get("sampled_frames", 0) - (math.ceil(duration) + 1)
        ) <= 1
        checks["dense_requires_chunks"] = math.ceil(dense.get("sampled_frames", 0) / 24) >= 2

        image = Path(workdir) / "large-source.png"
        encoded_ok, encoded = cv2.imencode(".png", np.zeros((3000, 4000, 3), dtype=np.uint8))
        if not encoded_ok:
            raise RuntimeError("无法生成图片预处理验收素材")
        encoded.tofile(str(image))
        image_diagnostics = []
        prepared = prepare_image_media(
            [{"path": str(image), "image_index": 1}],
            Path(workdir) / "prepared-images",
            diagnostics=image_diagnostics,
        )
        submitted = Path(prepared[0]["api_path"]) if prepared else Path()
        decoded = cv2.imdecode(np.fromfile(str(submitted), dtype=np.uint8), cv2.IMREAD_COLOR) if submitted.is_file() else None
        diagnostic = image_diagnostics[0] if image_diagnostics else {}
        checks["large_image_individual_webp"] = (
            decoded is not None
            and max(decoded.shape[:2]) == 2560
            and submitted.suffix.lower() == ".webp"
            and diagnostic.get("source_width") == 4000
            and diagnostic.get("submitted_width") == 2560
            and diagnostic.get("status") == "prepared"
        )
    report = {"ok": all(checks.values()), "video": video.name, "duration_seconds": duration, "checks": checks}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
