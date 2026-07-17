# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

from review_media_safety import ignored_upload_reason, valid_media_magic
from review_service.schemas import ReviewCaseMetadata
from review_service import service


def upload(name: str, body: bytes, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(file=io.BytesIO(body), filename=name, headers=Headers({"content-type": content_type}))


class MediaUploadSafetyTest(unittest.IsolatedAsyncioTestCase):
    def test_system_and_hidden_paths_are_detected_before_name_cleanup(self) -> None:
        cases = {
            "__MACOSX/._002_clip.mp4": "system_directory",
            "case/._002_clip.mp4": "appledouble_file",
            "case/.hidden/video.mp4": "hidden_file",
            "case/.DS_Store": "system_file",
            "case/Thumbs.db": "system_file",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(ignored_upload_reason(name), expected)
        self.assertIsNone(ignored_upload_reason("case/002_clip.mp4"))

    def test_media_magic_rejects_appledouble_disguised_as_mp4(self) -> None:
        appledouble = b"\x00\x05\x16\x07" + b"resource-fork"
        self.assertFalse(valid_media_magic(".mp4", appledouble))
        self.assertTrue(valid_media_magic(".mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 20))

    async def test_formal_api_skips_hidden_file_and_keeps_valid_media(self) -> None:
        metadata = ReviewCaseMetadata(client_case_id="CASE-HIDDEN-1", scenario="product_damage")
        valid_body = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64
        hidden_body = b"\x00\x05\x16\x07" + b"resource-fork"
        original_upload_root = service.upload_root
        with tempfile.TemporaryDirectory() as temp_dir:
            service.upload_root = lambda: Path(temp_dir)
            try:
                assets = await service._save_uploads(
                    "RJ-HIDDEN-1",
                    metadata,
                    [
                        upload("__MACOSX/._002_clip.mp4", hidden_body, "video/mp4"),
                        upload("002_clip.mp4", valid_body, "video/mp4"),
                    ],
                )
            finally:
                service.upload_root = original_upload_root
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["original_name"], "002_clip.mp4")
        self.assertEqual(assets[0]["sha256"], hashlib.sha256(valid_body).hexdigest())

        summary = service._upload_ingestion_summary(
            [
                upload("__MACOSX/._002_clip.mp4", hidden_body, "video/mp4"),
                upload("002_clip.mp4", valid_body, "video/mp4"),
            ]
        )
        self.assertEqual(summary["received_count"], 2)
        self.assertEqual(summary["accepted_count"], 1)
        self.assertEqual(summary["ignored_count"], 1)
        self.assertEqual(summary["ignored_files"][0]["reason_code"], "system_directory")

    async def test_formal_api_rejects_nonhidden_fake_media(self) -> None:
        metadata = ReviewCaseMetadata(client_case_id="CASE-FAKE-1", scenario="product_damage")
        original_upload_root = service.upload_root
        with tempfile.TemporaryDirectory() as temp_dir:
            service.upload_root = lambda: Path(temp_dir)
            try:
                with self.assertRaisesRegex(ValueError, "invalid_review_asset_content"):
                    await service._save_uploads(
                        "RJ-FAKE-1",
                        metadata,
                        [upload("fake.mp4", b"not-a-video", "video/mp4")],
                    )
                self.assertFalse((Path(temp_dir) / "RJ-FAKE-1").exists())
            finally:
                service.upload_root = original_upload_root


if __name__ == "__main__":
    unittest.main()
