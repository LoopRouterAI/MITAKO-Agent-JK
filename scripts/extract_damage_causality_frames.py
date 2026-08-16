# -*- coding: utf-8 -*-
"""从指定视频时段提取因果审查帧；不读取目录标签或人工审核结论。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="提取损伤形成前后证据帧")
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float, default=0.0, help="0 表示视频结束")
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--columns", type=int, default=5)
    return parser.parse_args()


def _resize(image: np.ndarray, max_width: int) -> np.ndarray:
    if image.shape[1] <= max_width:
        return image
    scale = max_width / image.shape[1]
    return cv2.resize(image, (max_width, max(1, int(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)


def extract(video: Path, output: Path, start: float, end: float, sample_fps: float, max_width: int, columns: int) -> dict:
    if sample_fps <= 0:
        raise ValueError("fps 必须大于 0")
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{video}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / source_fps if source_fps > 0 else 0.0
    actual_end = min(end if end > 0 else duration, duration) if duration > 0 else end
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    thumbnails = []
    timestamp = max(0.0, start)
    interval = 1.0 / sample_fps
    while actual_end <= 0 or timestamp <= actual_end + 1e-6:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()
        if not ok:
            break
        frame = _resize(frame, max_width)
        label = f"{timestamp:.2f}s"
        cv2.rectangle(frame, (0, 0), (150, 34), (0, 0, 0), -1)
        cv2.putText(frame, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        name = f"frame_{len(rows) + 1:04d}_{timestamp:09.2f}s.jpg"
        encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not encoded_ok:
            raise RuntimeError(f"帧编码失败：{timestamp:.2f}s")
        encoded.tofile(str(output / name))
        rows.append({"frame_index": len(rows) + 1, "timestamp_seconds": round(timestamp, 3), "file": name})
        thumbnails.append(frame)
        timestamp += interval
    capture.release()

    if thumbnails:
        tile_width = max(item.shape[1] for item in thumbnails)
        tile_height = max(item.shape[0] for item in thumbnails)
        pages = []
        page_size = max(1, columns) * 6
        for page_index in range(0, len(thumbnails), page_size):
            chunk = thumbnails[page_index : page_index + page_size]
            rows_on_page = (len(chunk) + columns - 1) // columns
            sheet = np.full((rows_on_page * tile_height, columns * tile_width, 3), 242, dtype=np.uint8)
            for index, image in enumerate(chunk):
                row, column = divmod(index, columns)
                sheet[row * tile_height : row * tile_height + image.shape[0], column * tile_width : column * tile_width + image.shape[1]] = image
            page_name = f"contact_sheet_{len(pages) + 1:02d}.jpg"
            cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(str(output / page_name))
            pages.append(page_name)
    else:
        pages = []

    manifest = {
        "source_file": video.name,
        "source_fps": source_fps,
        "duration_seconds": round(duration, 3),
        "window": {"start": start, "end": actual_end, "sample_fps": sample_fps},
        "frames": rows,
        "contact_sheets": pages,
        "label_isolation": "只读取指定视频像素与基础媒体参数，不读取父目录、manifest、reply 或 annotation。",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    args = parse_args()
    result = extract(args.video, args.output, args.start, args.end, args.fps, args.max_width, args.columns)
    print(json.dumps({"frames": len(result["frames"]), "duration_seconds": result["duration_seconds"], "contact_sheets": result["contact_sheets"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
