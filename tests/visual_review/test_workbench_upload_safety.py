# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import UploadFile
from starlette.datastructures import Headers

from poc.visual_review_poc import workbench_server
from poc.visual_review_poc.local_video_triage_demo import load_case_from_folder
from poc.visual_review_poc.model_selection_e2e import load_case_bundle


def upload(name: str, body: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(body), filename=name, headers=Headers({"content-type": "video/mp4"}))


class WorkbenchUploadSafetyTest(unittest.TestCase):
    def test_new_upload_cleans_expired_case_cache_only(self) -> None:
        valid_body = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64
        original_upload_dir = workbench_server.UPLOAD_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            expired = upload_dir / "folder_expired"
            recent = upload_dir / "folder_recent"
            shared_downloads = upload_dir / "url_downloads"
            for directory in (expired, recent, shared_downloads):
                directory.mkdir()
                (directory / "evidence.mp4").write_bytes(valid_body)
            expired_at = time.time() - 73 * 60 * 60
            os.utime(expired, (expired_at, expired_at))
            workbench_server.UPLOAD_DIR = upload_dir
            try:
                with patch.object(workbench_server, "UPLOAD_RETENTION_SECONDS", 72 * 60 * 60):
                    workbench_server._save_folder_uploads([upload("new.mp4", valid_body)])
            finally:
                workbench_server.UPLOAD_DIR = original_upload_dir

            self.assertFalse(expired.exists())
            self.assertTrue(recent.is_dir())
            self.assertTrue(shared_downloads.is_dir())

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

    def test_folder_upload_excludes_evaluation_label_context(self) -> None:
        valid_body = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64
        uploads = [
            upload("case/evidence.mp4", valid_body),
            upload("case/annotation.json", b'{"expected_label":"negative"}'),
            upload("case/reply.json", b'{"manual_result":"approved"}'),
        ]
        original_upload_dir = workbench_server.UPLOAD_DIR
        with tempfile.TemporaryDirectory() as temp_dir:
            workbench_server.UPLOAD_DIR = Path(temp_dir)
            try:
                folder, summary = workbench_server._save_folder_uploads(uploads)
                self.assertEqual(summary["accepted_count"], 1)
                self.assertEqual(summary["skipped_count"], 2)
                self.assertTrue(all(
                    item["reason_code"] == "evaluation_label_not_allowed"
                    for item in summary["skipped_files"]
                ))
                self.assertEqual([path.name for path in folder.iterdir()], ["evidence.mp4"])
            finally:
                workbench_server.UPLOAD_DIR = original_upload_dir

    def test_folder_loader_ignores_manifest_tag_but_keeps_customer_predecision_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "content.txt").write_text("请复核本次售后", encoding="utf-8")
            (folder / "manifest.json").write_text(
                '{"tag":"负样本 未成年人资料","resources":[]}', encoding="utf-8"
            )
            (folder / "conversation_predecision.json").write_text(
                '[{"from":"user","text":"之前审核不通过，我要补充证据申请复核"}]', encoding="utf-8"
            )

            case = load_case_from_folder(folder, 0)

        self.assertEqual(case["scenario"], "video_unboxing")
        self.assertNotIn("tag", case["order_context"])
        self.assertEqual(
            case["structured_business_context"]["conversation_history"][0]["text"],
            "之前审核不通过，我要补充证据申请复核",
        )

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

    def test_identical_videos_are_sampled_once_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            run_dir = Path(temp_dir) / "run"
            case_dir.mkdir()
            first_video = case_dir / "001_first.mp4"
            writer = cv2.VideoWriter(str(first_video), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48))
            self.assertTrue(writer.isOpened())
            for level in (32, 96, 160, 224):
                writer.write(np.full((48, 64, 3), level, dtype=np.uint8))
            writer.release()
            (case_dir / "002_duplicate.mp4").write_bytes(first_video.read_bytes())

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
        self.assertEqual(case["video_deduplication"]["submitted_count"], 2)
        self.assertEqual(case["video_deduplication"]["unique_count"], 1)
        self.assertEqual(case["video_deduplication"]["duplicate_count"], 1)
        self.assertEqual(case["video_deduplication"]["duplicates"][0]["kept"], "001_first.mp4")

    def test_native_bundle_uses_two_start_anchors_without_full_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            run_dir = Path(temp_dir) / "run"
            case_dir.mkdir()
            video = case_dir / "evidence.mp4"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (64, 48))
            self.assertTrue(writer.isOpened())
            for level in range(11):
                writer.write(np.full((48, 64, 3), 20 + level * 20, dtype=np.uint8))
            writer.release()

            with patch(
                "poc.visual_review_poc.model_selection_e2e.sample_video_frames"
            ) as sampler:
                case = load_case_bundle(
                    case_dir,
                    SimpleNamespace(
                        fps=1.0,
                        sampling_mode="adaptive",
                        max_frames_per_video=24,
                        api_frame_limit=24,
                        probe_seconds=12.0,
                        frame_width=960,
                        supplemental_image_limit=0,
                    ),
                    run_dir,
                    native_video={
                        "video_index": 1,
                        "api_path": str(video),
                        "api_mime_type": "video/mp4",
                    },
                )

            sampler.assert_not_called()
            self.assertEqual([frame["timestamp"] for frame in case["frames"]], ["00:00.00", "00:01.00"])
            self.assertTrue(all(Path(frame["api_path"]).is_file() for frame in case["frames"]))
            self.assertEqual(case["native_video"]["api_path"], str(video))
            self.assertEqual(case["videos"][0]["sampled_frames"], 2)


if __name__ == "__main__":
    unittest.main()
