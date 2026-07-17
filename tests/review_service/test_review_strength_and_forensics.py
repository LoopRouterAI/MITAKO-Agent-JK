# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from review_service import media_forensics, service
from review_service.schemas import ReviewSamplingPolicy


class ReviewStrengthPolicyTest(unittest.TestCase):
    def test_strength_presets_and_custom_bounds(self) -> None:
        strong = ReviewSamplingPolicy(preset="strong")
        strict = ReviewSamplingPolicy(preset="strict")
        forensic = ReviewSamplingPolicy(preset="forensic")
        custom = ReviewSamplingPolicy(preset="custom", fps=0.1)

        self.assertEqual(service._sampling_fields({"sampling_policy": strong.model_dump()})["fps"], "2.0")
        self.assertEqual(service._sampling_fields({"sampling_policy": strict.model_dump()})["fps"], "1.0")
        self.assertEqual(service._sampling_fields({"sampling_policy": forensic.model_dump()})["fps"], "2.0")
        self.assertEqual(service._sampling_fields({"sampling_policy": custom.model_dump()})["fps"], "0.1")
        self.assertEqual(service._sampling_fields({"sampling_policy": strong.model_dump()})["sampling_mode"], "dense")

        with self.assertRaises(ValidationError):
            ReviewSamplingPolicy(preset="custom", fps=0.09)
        with self.assertRaises(ValidationError):
            ReviewSamplingPolicy(preset="custom", fps=2.01)

    def test_optional_escalation_and_forensic_fields_are_backward_compatible(self) -> None:
        legacy = ReviewSamplingPolicy.model_validate({})
        all_checks = ReviewSamplingPolicy(forensic_checks=True)
        selected_checks = ReviewSamplingPolicy(
            auto_escalate=True,
            confidence_threshold=0.82,
            forensic_checks=["timeline_consistency", "editor_metadata"],
        )

        self.assertEqual(legacy.preset, "adaptive")
        self.assertFalse(legacy.auto_escalate)
        self.assertEqual(all_checks.forensic_checks, True)
        self.assertEqual(selected_checks.confidence_threshold, 0.82)
        self.assertEqual(selected_checks.forensic_checks, ["timeline_consistency", "editor_metadata"])


class MediaForensicsTest(unittest.TestCase):
    def _asset(self) -> dict:
        return {
            "asset_id": "RA-TEST",
            "original_name": "evidence.mp4",
            "stored_name": "stored.mp4",
            "mime_type": "video/mp4",
        }

    def test_ffprobe_unavailable_is_an_explicit_non_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stored.mp4"
            path.write_bytes(b"test")
            with patch.object(media_forensics.shutil, "which", return_value=None):
                result = media_forensics.inspect_job_media(Path(temp_dir), [self._asset()])

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["unavailable_reason"], "ffprobe_not_available")
        self.assertEqual(result["assets"][0]["status"], "unavailable")
        self.assertIn("不能单独证明", result["interpretation"])
        self.assertEqual(result["summary"]["risk_signal_count"], 0)

    def test_ffprobe_metadata_derives_risks_without_claiming_proven_editing(self) -> None:
        probe_payload = {
            "format": {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "duration": "10.0",
                "start_time": "0.0",
                "bit_rate": "3200000",
                "tags": {"encoder": "Adobe Premiere Pro", "comment": "private text must not be returned"},
            },
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "duration": "8.0",
                    "start_time": "0.5",
                    "avg_frame_rate": "24/1",
                    "r_frame_rate": "30/1",
                    "time_base": "1/90000",
                    "nb_frames": "192",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "duration": "10.5",
                    "start_time": "0.0",
                    "time_base": "1/48000",
                },
            ],
        }
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(probe_payload).encode("utf-8"), stderr=b"")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stored.mp4"
            path.write_bytes(b"test")
            with patch.object(media_forensics.shutil, "which", return_value="ffprobe"), patch.object(
                media_forensics.subprocess, "run", return_value=completed
            ) as run:
                result = media_forensics.inspect_job_media(Path(temp_dir), [self._asset()])

        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["summary"]["risk_level"], "medium")
        codes = {item["code"] for item in result["assets"][0]["risk_signals"]}
        self.assertTrue(
            {
                "container_video_duration_mismatch",
                "audio_video_duration_mismatch",
                "frame_rate_variation",
                "editor_metadata_present",
            }.issubset(codes)
        )
        self.assertTrue(all(item["is_proof_of_editing"] is False for item in result["assets"][0]["risk_signals"]))
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("private text", serialized)
        self.assertNotIn(str(path), serialized)

    def test_forensic_checks_can_be_disabled_without_running_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stored.mp4"
            path.write_bytes(b"test")
            with patch.object(media_forensics.shutil, "which") as which:
                result = media_forensics.inspect_job_media(Path(temp_dir), [self._asset()], checks=[])

        self.assertEqual(result["status"], "disabled")
        which.assert_not_called()

    def test_packet_timeline_detects_bounded_timestamp_discontinuities(self) -> None:
        facts = media_forensics._packet_timeline_facts(
            [
                {"dts_time": "0.00", "flags": "K_"},
                {"dts_time": "0.04", "flags": "__"},
                {"dts_time": "2.50", "flags": "K_"},
                {"dts_time": "2.20", "flags": "__"},
            ]
        )
        risks = media_forensics._derive_risks({}, [], {"packet_timeline"}, facts)
        codes = {item["code"] for item in risks}

        self.assertEqual(facts["packets_analyzed"], 4)
        self.assertEqual(facts["large_gap_count"], 1)
        self.assertEqual(facts["non_monotonic_count"], 1)
        self.assertEqual(codes, {"packet_timeline_gap", "packet_timestamp_regression"})
        self.assertTrue(all(item["is_proof_of_editing"] is False for item in risks))


class ReviewJobIntegrationTest(unittest.TestCase):
    def test_workbench_transient_503_is_retried_with_fresh_upload_stream(self) -> None:
        class Response:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.is_error = status_code >= 400

            def json(self):
                return self._payload

        responses = [Response(503), Response(200, {"ok": True, "review": {}})]
        observed_sizes = []

        class Client:
            def __init__(self, *args, **kwargs):
                self.trust_env = kwargs.get("trust_env")
                self.assert_internal = kwargs.get("trust_env") is False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, headers, data, files):
                self_outer.assertFalse(self.trust_env)
                self_outer.assertEqual(headers.get("X-MITAKO-Internal-Metrics"), "1")
                observed_sizes.append(sum(len(item[1][1].read()) for item in files))
                return responses.pop(0)

        self_outer = self
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "RJ-RETRY"
            job_dir.mkdir()
            (job_dir / "asset.mp4").write_bytes(b"video-bytes")
            job = {
                "job_id": "RJ-RETRY",
                "client_case_id": "CASE-RETRY",
                "scenario": "product_damage",
                "metadata": {"sampling_policy": {"preset": "adaptive"}},
                "assets": [
                    {
                        "asset_id": "RA-1",
                        "stored_name": "asset.mp4",
                        "original_name": "asset.mp4",
                        "mime_type": "video/mp4",
                    }
                ],
            }
            with patch.object(service, "upload_root", return_value=root), patch.object(
                service.httpx, "Client", Client
            ), patch.object(service.time, "sleep"):
                payload = service._call_workbench(job)

        self.assertEqual(observed_sizes, [11, 11])
        self.assertEqual(payload["_workbench_transport"]["retry_count"], 1)
        self.assertEqual([item["status_code"] for item in payload["_workbench_transport"]["attempts"]], [503, 200])

    def test_run_job_forensics_precedes_single_model_call_and_recommends_bounded_escalation(self) -> None:
        calls = []
        job = {
            "job_id": "RJ-TEST",
            "client_case_id": "CASE-TEST",
            "scenario": "product_damage",
            "metadata": {
                "sampling_policy": {
                    "preset": "adaptive",
                    "auto_escalate": True,
                    "confidence_threshold": 0.8,
                    "forensic_checks": ["timeline_consistency"],
                }
            },
            "assets": [],
        }
        forensic_result = {
            "status": "completed",
            "assets": [],
            "summary": {
                "video_assets": 1,
                "analyzed_assets": 1,
                "unavailable_assets": 0,
                "risk_signal_count": 1,
                "risk_level": "medium",
            },
            "interpretation": "风险信号不是已证实剪辑。",
        }
        model_payload = {
            "ok": True,
            "source_status": "completed",
            "review": {
                "summary": {"predicted_label": "review", "confidence": 0.55},
                "agent_report": {
                    "parsed": {
                        "decision": "request_more_material",
                        "material_gaps": ["缺少连续开箱片段"],
                    }
                },
            },
        }

        def inspect(current_job: dict) -> dict:
            calls.append("forensics")
            self.assertIs(current_job, job)
            return forensic_result

        def invoke(current_job: dict) -> dict:
            calls.append("model")
            self.assertIs(current_job, job)
            return model_payload

        def finish(job_id: str, *, status: str, result: dict, diagnostics: dict) -> dict:
            calls.append("finish")
            return {"job_id": job_id, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service, "_media_forensics", side_effect=inspect), patch.object(
            service, "_call_workbench", side_effect=invoke
        ) as model, patch.object(service.store, "finish_job", side_effect=finish):
            completed = service.run_job("RJ-TEST")

        self.assertEqual(calls, ["forensics", "model", "finish"])
        self.assertEqual(model.call_count, 1)
        result = completed["result"]
        self.assertEqual(result["media_forensics"], forensic_result)
        plan = result["recommended_escalation"]
        self.assertTrue(plan["recommended"])
        self.assertEqual(plan["execution_mode"], "recommendation_only")
        self.assertEqual(plan["automatic_model_retries"], 0)
        self.assertEqual(plan["actions"][0]["target_preset"], "strong")
        self.assertEqual(
            {item["code"] for item in plan["reasons"]},
            {"low_confidence", "review_conclusion", "material_gaps", "forensic_risk"},
        )
        public_result = json.dumps(result, ensure_ascii=False).lower()
        self.assertNotIn("api_key", public_result)
        self.assertNotIn("system prompt", public_result)

    def test_model_failure_preserves_forensics_and_does_not_retry_model(self) -> None:
        job = {
            "job_id": "RJ-FAILED",
            "client_case_id": "CASE-FAILED",
            "scenario": "wrong_item",
            "metadata": {"sampling_policy": {"preset": "strong", "auto_escalate": True}},
            "assets": [],
        }
        forensic_result = {
            "status": "unavailable",
            "assets": [],
            "summary": {
                "video_assets": 1,
                "analyzed_assets": 0,
                "unavailable_assets": 1,
                "risk_signal_count": 0,
                "risk_level": "none",
            },
            "unavailable_reason": "ffprobe_not_available",
            "interpretation": "本轮不可用，不能据此判断剪辑。",
        }

        def finish(job_id: str, *, status: str, result: dict, diagnostics: dict) -> dict:
            return {"job_id": job_id, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service, "_media_forensics", return_value=forensic_result), patch.object(
            service, "_call_workbench", side_effect=RuntimeError("upstream unavailable")
        ) as model, patch.object(service.store, "finish_job", side_effect=finish):
            completed = service.run_job("RJ-FAILED")

        self.assertEqual(model.call_count, 1)
        self.assertEqual(completed["status"], "FAILED")
        self.assertEqual(completed["result"]["media_forensics"], forensic_result)
        self.assertTrue(completed["result"]["recommended_escalation"]["recommended"])
        self.assertEqual(completed["result"]["recommended_escalation"]["automatic_model_retries"], 0)


if __name__ == "__main__":
    unittest.main()
