# -*- coding: utf-8 -*-
"""使用 OpenCV 生成视频关键时间窗，供密集视觉复核使用。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def extract_window(source: Path, output: Path, start_seconds: float, end_seconds: float, max_width: int) -> dict:
    if not source.is_file():
        raise ValueError(f"视频不存在：{source}")
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise ValueError("时间窗必须满足 0 <= start < end")
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError("无法读取视频")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        capture.release()
        raise ValueError("无法读取视频尺寸")
    scale = min(1.0, max_width / width) if max_width > 0 else 1.0
    target_size = (max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, target_size)
    if not writer.isOpened():
        capture.release()
        raise ValueError("无法创建输出视频")
    capture.set(cv2.CAP_PROP_POS_MSEC, start_seconds * 1000)
    frames_written = 0
    while capture.get(cv2.CAP_PROP_POS_MSEC) <= end_seconds * 1000:
        ok, frame = capture.read()
        if not ok:
            break
        if frame.shape[1] != target_size[0] or frame.shape[0] != target_size[1]:
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
        writer.write(frame)
        frames_written += 1
    capture.release()
    writer.release()
    if frames_written == 0 or not output.exists():
        raise ValueError("时间窗没有生成有效帧")
    result = {
        "source": str(source),
        "output": str(output),
        "source_start_seconds": start_seconds,
        "source_end_seconds": end_seconds,
        "fps": round(fps, 3),
        "frames_written": frames_written,
        "duration_seconds": round(frames_written / fps, 3),
        "width": target_size[0],
        "height": target_size[1],
        "bytes": output.stat().st_size,
    }
    sidecar = output.with_suffix(output.suffix + ".window.json")
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["sidecar"] = str(sidecar)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="提取视频关键时间窗")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--max-width", type=int, default=1280)
    args = parser.parse_args()
    result = extract_window(args.source, args.output, args.start, args.end, args.max_width)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
