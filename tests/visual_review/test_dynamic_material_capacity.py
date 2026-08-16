# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile

from poc.visual_review_poc.minor_material_pipeline import run_minor_material_pipeline
from poc.visual_review_poc.model_selection_e2e import load_case_bundle
from poc.visual_review_poc import workbench_server


def _image(index: int) -> dict:
    return {
        "image_index": index,
        "file": f"material_{index:03d}.png",
        "api_path": __file__,
        "api_mime_type": "image/png",
        "width": 1,
        "height": 1,
    }


def _minor_case(image_count: int) -> dict:
    return {
        "case_id": "capacity-62",
        "scenario": "minor_material",
        "structured_business_context": {
            "business_scenario": "minor_refund",
            "frontdesk_evidence_package": {
                "asset_manifest": {
                    "assets": [
                        {"file": f"material_{index:03d}.png", "mime_type": "image/png"}
                        for index in range(1, image_count + 1)
                    ]
                }
            },
        },
        "evidence_assets": [
            {"file": f"material_{index:03d}.png", "status": "downloaded"}
            for index in range(1, image_count + 1)
        ],
        "supplemental_images": [_image(index) for index in range(1, image_count + 1)],
        "frames": [],
        "videos": [],
        "model_frames_per_call": 24,
    }


def _inventory_result(indices: list[int]) -> dict:
    return {
        "status": "success",
        "parsed": {
            "coverage_ack": {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            },
            "material_observations": [
                {
                    "image_index": index,
                    "asset_ref": f"supplemental_image_{index}",
                    "document_types": ["other"],
                    "subject_role": "not_applicable",
                    "document_side": "page",
                    "readability": "clear",
                    "quality_issues": [],
                }
                for index in indices
            ],
        },
        "usage": {},
        "cost": {},
        "cost_status": "estimated",
    }


class DynamicMaterialCapacityTest(unittest.TestCase):
    def test_multiple_native_videos_skip_full_frame_sampling(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_dir = root / "case"
            sample_dir.mkdir()
            videos = [sample_dir / "001.mp4", sample_dir / "002.mp4"]
            for video in videos:
                video.write_bytes(b"video")
            args = SimpleNamespace(
                fps=1.0,
                sampling_mode="dense",
                max_frames_per_video=1200,
                api_frame_limit=24,
                probe_seconds=1.0,
                frame_width=1920,
                supplemental_image_limit=40,
            )
            current = {
                "case_id": "multi-native",
                "scenario": "product_damage",
                "structured_business_context": {},
                "supplemental_images": [],
                "frames": [],
                "videos": [],
            }
            sources = [
                {
                    "video_index": index,
                    "file_uri": f"https://media.example/video-{index}",
                    "api_mime_type": "video/webm",
                }
                for index in (1, 2)
            ]
            with (
                patch(
                    "poc.visual_review_poc.model_selection_e2e.discover_case_videos",
                    return_value=(videos, {}),
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.load_case",
                    return_value=current,
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.extract_video_start_anchors",
                    return_value=[],
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.sample_video_frames"
                ) as sample_frames,
                patch(
                    "poc.visual_review_poc.model_selection_e2e.prepare_media",
                    side_effect=lambda items, *_args, **_kwargs: list(items),
                ),
                patch("poc.visual_review_poc.model_selection_e2e.prepare_official_reference_images"),
            ):
                case = load_case_bundle(
                    sample_dir,
                    args,
                    root / "run",
                    scenario_override="product_damage",
                    native_videos=sources,
                    selected_videos=videos,
                )

        sample_frames.assert_not_called()
        self.assertEqual(case["sampling_mode"], "native_video")
        self.assertEqual(
            [row["video_index"] for row in case["native_videos"]],
            [1, 2],
        )
        self.assertEqual(case["frames"], [])

    def test_product_damage_frames_keep_1080p_budget_but_uploaded_images_use_shared_2k_policy(self) -> None:
        calls: list[dict] = []

        def record_prepare(items, *_args, **kwargs):
            calls.append(dict(kwargs))
            return list(items)

        with TemporaryDirectory() as temp_dir:
            sample_dir = Path(temp_dir) / "case"
            run_dir = Path(temp_dir) / "run"
            sample_dir.mkdir()
            args = SimpleNamespace(
                fps=1.0,
                sampling_mode="dense",
                max_frames_per_video=1200,
                api_frame_limit=24,
                probe_seconds=1.0,
                frame_width=1920,
                supplemental_image_limit=40,
            )
            product_case = {
                "case_id": "damage-resolution",
                "scenario": "product_damage",
                "structured_business_context": {},
                "supplemental_images": [_image(1)],
                "frames": [],
                "videos": [],
            }
            with (
                patch(
                    "poc.visual_review_poc.model_selection_e2e.load_case_from_folder",
                    return_value=product_case,
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.prepare_media",
                    side_effect=record_prepare,
                ),
                patch("poc.visual_review_poc.model_selection_e2e.prepare_official_reference_images"),
            ):
                load_case_bundle(
                    sample_dir,
                    args,
                    run_dir,
                    scenario_override="product_damage",
                )

        self.assertEqual(calls, [
            {"max_edge": 1920, "quality": 88, "lossless_webp": True},
            {"diagnostics": []},
        ])

    def test_fulfillment_images_use_shared_2k_webp_policy(self) -> None:
        calls: list[dict] = []

        def record_prepare(items, *_args, **kwargs):
            calls.append(dict(kwargs))
            return list(items)

        with TemporaryDirectory() as temp_dir:
            sample_dir = Path(temp_dir) / "case"
            sample_dir.mkdir()
            args = SimpleNamespace(
                fps=1.0,
                sampling_mode="dense",
                max_frames_per_video=1200,
                api_frame_limit=24,
                probe_seconds=1.0,
                frame_width=1920,
                supplemental_image_limit=40,
            )
            current = {
                "case_id": "wrong-item-resolution",
                "scenario": "wrong_item",
                "structured_business_context": {},
                "supplemental_images": [_image(1)],
                "frames": [],
                "videos": [],
            }
            with (
                patch(
                    "poc.visual_review_poc.model_selection_e2e.load_case_from_folder",
                    return_value=current,
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.prepare_media",
                    side_effect=record_prepare,
                ),
                patch("poc.visual_review_poc.model_selection_e2e.prepare_official_reference_images"),
            ):
                load_case_bundle(
                    sample_dir,
                    args,
                    Path(temp_dir) / "run",
                    scenario_override="wrong_item",
                )

        self.assertEqual(calls[-1], {"diagnostics": []})

    def test_hidden_files_do_not_consume_folder_capacity(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        uploads = [
            UploadFile(filename="first.png", file=BytesIO(png)),
            UploadFile(filename="._resource.png", file=BytesIO(png)),
            UploadFile(filename="second.png", file=BytesIO(png)),
        ]
        with TemporaryDirectory() as temp_dir, patch.object(
            workbench_server, "UPLOAD_DIR", Path(temp_dir)
        ), patch.object(workbench_server, "MAX_FOLDER_FILES", 2):
            folder, summary = workbench_server._save_folder_uploads(uploads)

        self.assertEqual(summary["received_count"], 3)
        self.assertEqual(summary["accepted_count"], 2)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertFalse(folder.exists())

    def test_sixty_two_images_are_counted_before_capacity_and_all_reach_minor_pipeline(self) -> None:
        reviewed_indices: list[int] = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            self.assertEqual(mode, "minor_material_inventory")
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            reviewed_indices.extend(indices)
            return _inventory_result(indices)

        with TemporaryDirectory() as temp_dir:
            sample_dir = Path(temp_dir) / "case"
            run_dir = Path(temp_dir) / "run"
            sample_dir.mkdir()
            args = SimpleNamespace(
                fps=0.2,
                sampling_mode="adaptive",
                max_frames_per_video=4,
                api_frame_limit=4,
                probe_seconds=1.0,
                frame_width=320,
                supplemental_image_limit=40,
            )
            with (
                patch(
                    "poc.visual_review_poc.model_selection_e2e.load_case_from_folder",
                    return_value=_minor_case(62),
                ),
                patch(
                    "poc.visual_review_poc.model_selection_e2e.prepare_media",
                    side_effect=lambda items, *_args, **_kwargs: list(items),
                ),
                patch("poc.visual_review_poc.model_selection_e2e.prepare_official_reference_images"),
            ):
                case = load_case_bundle(sample_dir, args, run_dir, scenario_override="minor_material")

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        assessment = result["parsed"]["minor_material_assessment"]

        checks = {
            "清点后保留全部图片": (len(case["supplemental_images"]), 62),
            "全部图片进入模型批次": (sorted(reviewed_indices), list(range(1, 63))),
            "申报数量保持完整": (assessment["declared_image_count"], 62),
            "接收数量保持完整": (assessment["accepted_image_count"], 62),
            "处理数量保持完整": (assessment["processed_image_count"], 62),
            "处理覆盖完整": (assessment["coverage_complete"], True),
        }
        for name, (actual, expected) in checks.items():
            with self.subTest(contract=name):
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
