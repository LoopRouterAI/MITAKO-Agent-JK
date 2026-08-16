# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from poc.visual_review_poc.native_video_detail_frames import select_transition_settle_frames


class NativeVideoDetailFramesTest(unittest.TestCase):
    def test_selects_sharp_settled_frame_after_visual_transition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            frames = []
            for second in range(20):
                image = np.zeros((96, 96, 3), dtype=np.uint8)
                if second == 9:
                    image[:] = 255
                elif second == 11:
                    image[20:76, 20:76] = 140
                elif second == 12:
                    image = np.indices((96, 96)).sum(axis=0) % 2 * 255
                    image = np.repeat(image[:, :, None], 3, axis=2).astype(np.uint8)
                path = Path(temp_dir) / f"frame_{second:02d}.jpg"
                cv2.imwrite(str(path), image)
                frames.append({
                    "path": str(path),
                    "timestamp_seconds": float(second),
                    "timestamp": f"00:{second:02d}",
                })

            selected = select_transition_settle_frames(frames, limit=2)

        self.assertLessEqual(len(selected), 2)
        self.assertIn(12.0, [item["timestamp_seconds"] for item in selected])

    def test_selection_is_deterministic_and_never_exceeds_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            frames = []
            for second in range(12):
                image = np.full((32, 32, 3), second * 20, dtype=np.uint8)
                path = Path(temp_dir) / f"frame_{second:02d}.jpg"
                cv2.imwrite(str(path), image)
                frames.append({"path": str(path), "timestamp_seconds": float(second)})

            first = select_transition_settle_frames(frames, limit=4)
            second = select_transition_settle_frames(frames, limit=4)

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 4)


if __name__ == "__main__":
    unittest.main()
