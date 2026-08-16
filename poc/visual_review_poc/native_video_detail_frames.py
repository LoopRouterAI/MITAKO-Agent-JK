# -*- coding: utf-8 -*-
"""为单轮原生视频审核盲选少量高分辨率细节帧。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np


def _decode_gray(path: Path) -> np.ndarray | None:
    try:
        encoded = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return cv2.resize(image, (144, 256), interpolation=cv2.INTER_AREA)


def select_transition_settle_frames(
    frames: List[Dict[str, Any]],
    *,
    limit: int = 18,
    settle_seconds: float = 3.0,
) -> List[Dict[str, Any]]:
    """每个时间分区先找画面变化，再取变化后最清晰的稳定帧。"""
    cap = max(0, int(limit))
    if cap == 0 or not frames:
        return []
    ordered = sorted(
        (dict(item) for item in frames),
        key=lambda item: float(item.get("timestamp_seconds") or 0.0),
    )
    metrics = []
    previous = None
    for index, item in enumerate(ordered):
        gray = _decode_gray(Path(str(item.get("path") or item.get("api_path") or "")))
        if gray is None:
            continue
        change = 0.0 if previous is None else float(cv2.absdiff(gray, previous).mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics.append({
            "index": index,
            "timestamp": float(item.get("timestamp_seconds") or 0.0),
            "change": change,
            "sharpness": sharpness,
        })
        previous = gray
    if not metrics:
        return []

    bin_count = min(max(1, (cap + 1) // 2), len(metrics))
    chosen_indices = []
    for bin_index in range(bin_count):
        start = round(bin_index * len(metrics) / bin_count)
        end = max(start + 1, round((bin_index + 1) * len(metrics) / bin_count))
        window = metrics[start:end]
        transition = max(window, key=lambda row: (row["change"], -row["index"]))
        if transition["index"] not in chosen_indices:
            chosen_indices.append(transition["index"])
        if len(chosen_indices) >= cap:
            break
        settle_end = transition["timestamp"] + max(0.0, float(settle_seconds))
        settled = [
            row for row in metrics
            if transition["timestamp"] < row["timestamp"] <= settle_end
        ]
        selected = max(
            settled or [transition],
            key=lambda row: (row["sharpness"], -row["timestamp"]),
        )
        if selected["index"] not in chosen_indices:
            chosen_indices.append(selected["index"])

    if len(chosen_indices) < cap:
        for row in sorted(metrics, key=lambda item: (item["change"], item["sharpness"]), reverse=True):
            if row["index"] not in chosen_indices:
                chosen_indices.append(row["index"])
            if len(chosen_indices) >= cap:
                break
    return [ordered[index] for index in sorted(chosen_indices[:cap])]
