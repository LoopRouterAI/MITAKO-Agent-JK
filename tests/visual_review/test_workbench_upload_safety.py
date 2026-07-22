# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi import UploadFile
from starlette.datastructures import Headers

from poc.visual_review_poc import workbench_server
from poc.visual_review_poc.model_selection_e2e import load_case_bundle


def upload(name: str, body: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(body), filename=name, headers=Headers({"content-type": "video/mp4"}))


class WorkbenchUploadSafetyTest(unittest.TestCase):
    def test_batch_parent_folder_is_split_by_first_child_directory(self) -> None:
        files = [
            upload("batch/case-a/evidence.mp4", b"video-a"),
            upload("batch/case-a/material.jpg", b"image-a"),
            upload("batch/case-b/evidence.mp4", b"video-b"),
            upload("batch/case-b/material.jpg", b"image-b"),
            upload("batch/__MACOSX/._evidence.mp4", b"hidden"),
        ]
        groups = workbench_server._group_batch_folder_uploads(files)
        self.assertEqual(sorted(groups), ["case-a", "case-b"])
        self.assertEqual([len(groups[key]) for key in sorted(groups)], [2, 2])

    def test_concurrent_folder_uploads_use_isolated_directories(self) -> None:
        valid_body = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64
        original_upload_dir = workbench_server.UPLOAD_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            workbench_server.UPLOAD_DIR = Path(temp_dir)
            try:
                def save(index: int) -> Path:
                    folder, summary = workbench_server._save_folder_uploads([upload(f"clip_{index}.mp4", valid_body)])
                    self.assertEqual(summary["accepted_count"], 1)
                    return folder

                with ThreadPoolExecutor(max_workers=20) as executor:
                    folders = list(executor.map(save, range(20)))
            finally:
                workbench_server.UPLOAD_DIR = original_upload_dir
        self.assertEqual(len({folder.name for folder in folders}), 20)

    def test_undecodable_video_is_isolated_when_valid_video_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            run_dir = Path(temp_dir) / "run"
            case_dir.mkdir()
            (case_dir / "000_bad.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"broken" * 8)
            valid_video = case_dir / "001_valid.mp4"
            writer = cv2.VideoWriter(str(valid_video), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48))
            self.assertTrue(writer.isOpened())
            for level in (32, 96, 160, 224):
                writer.write(np.full((48, 64, 3), level, dtype=np.uint8))
            writer.release()
            self.assertTrue(valid_video.is_file())
            case = load_case_bundle(
                case_dir,
                SimpleNamespace(
                    fps=0.2,
                    sampling_mode="adaptive",
                    max_frames_per_video=4,
                    api_frame_limit=4,
                    probe_seconds=1.0,
                    frame_width=320,
                    supplemental_image_limit=0,
                ),
                run_dir,
            )
        self.assertEqual(len(case["videos"]), 1)
        self.assertEqual(case["videos"][0]["file"], "001_valid.mp4")
        self.assertEqual(case["video_file"], "001_valid.mp4")
        self.assertEqual(case["rejected_videos"], [{"file": "000_bad.mp4", "reason": "视频无法解码，已从本次审核中隔离"}])
        self.assertGreater(len(case["frames"]), 0)


if __name__ == "__main__":
    unittest.main()
