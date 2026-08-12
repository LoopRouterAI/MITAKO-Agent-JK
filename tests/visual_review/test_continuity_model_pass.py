from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PIL import Image

from poc.visual_review_poc import model_selection_e2e
from poc.visual_review_poc.model_selection_e2e import _aggregate_chunk_results, call_model_chunked, gemini_payload, merge_opening_start_verification, openai_messages, post_with_retries
from poc.visual_review_poc.review_model_prompt import build_selection_prompt
from poc.visual_review_poc.specialized_model_pass import run_specialized_frame_pass
from poc.visual_review_poc.unified_model_pass import native_dimension_gaps


def _visibility(index: int, subject_id: str) -> str:
    if subject_id == "product_package" and 3 <= index <= 5:
        return "out_of_frame"
    if subject_id == "claimed_item" and index < 6:
        return "not_yet_exposed"
    return "visible"


class ContinuityModelPassTest(unittest.TestCase):
    def test_native_dimension_check_rejects_empty_structured_shells(self):
        parsed = {
            "overall_audit": {},
            "frame_findings": [],
            "object_continuity_assessment": {},
            "damage_causality_assessment": {},
            "claim_fact_assessment": {},
        }

        self.assertEqual(
            native_dimension_gaps(parsed, "product_damage"),
            [
                "claim_facts",
                "damage_causality",
                "frame_findings",
                "object_continuity",
                "opening_video_compliance",
                "overall_audit",
            ],
        )

    def test_native_dimension_check_accepts_timestamp_based_video_evidence(self):
        parsed = {
            "overall_audit": {"conclusion": "可见损伤"},
            "frame_findings": [{"timestamp": "00:08.20", "visible_facts": "边角压痕"}],
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{"subject_id": "claimed_item"}],
            },
            "video_audit_conclusion": {
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [
                        {"field": field, "video_index": 1, "timestamp": "00:00.00"}
                        for field in (
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    ],
                    "field_sources": {
                        field: "native_full_video_perception"
                        for field in (
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    },
                    "validated_fields": [
                        "sealed_start",
                        "waybill_visible",
                        "single_take_continuity",
                        "issue_visible_in_continuous_opening",
                    ],
                    "result": "compliant",
                },
            },
            "damage_causality_assessment": {
                "damage_presence": "confirmed",
                "claim_support": "supported",
            },
            "claim_fact_assessment": {
                "order_linkage": {"status": "verified"},
                "scene_match": {"status": "matched"},
                "assembly": {"state": "permanent_damage"},
                "atomic_claim_results": [],
            },
        }

        self.assertEqual(native_dimension_gaps(parsed, "product_damage"), [])

    def test_native_dimension_check_requires_opening_video_compliance(self):
        parsed = {
            "overall_audit": {"conclusion": "可见损伤"},
            "frame_findings": [{"timestamp": "00:08.20", "visible_facts": "边角压痕"}],
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{"subject_id": "claimed_item"}],
            },
        }

        self.assertIn("opening_video_compliance", native_dimension_gaps(parsed, "video_unboxing"))

    def test_native_dimension_check_requires_timestamped_opening_evidence(self):
        parsed = {
            "overall_audit": {"conclusion": "面单可见但未从封箱开始"},
            "frame_findings": [{"timestamp": "00:00.00", "visible_facts": "首帧已是泡沫内包"}],
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{"subject_id": "shipping_package"}],
            },
            "video_audit_conclusion": {
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": {},
                    "result": "noncompliant",
                },
            },
        }

        self.assertIn("opening_video_compliance", native_dimension_gaps(parsed, "video_unboxing"))

    def test_timestamped_full_video_opening_failure_does_not_force_frame_fallback(self):
        parsed = {
            "overall_audit": {"conclusion": "可见损伤"},
            "frame_findings": [{"timestamp": "00:08.20", "visible_facts": "边角压痕"}],
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{"subject_id": "claimed_item"}],
            },
            "video_audit_conclusion": {
                "opening_video_compliance": {
                    "sealed_start": False,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [
                        {"field": field, "video_index": 1, "timestamp": "00:00.00"}
                        for field in (
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    ],
                    "field_sources": {
                        field: "native_full_video_perception"
                        for field in (
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    },
                    "validated_fields": [
                        "sealed_start",
                        "waybill_visible",
                        "single_take_continuity",
                        "issue_visible_in_continuous_opening",
                    ],
                    "result": "noncompliant",
                },
            },
        }

        gaps = native_dimension_gaps(parsed, "video_unboxing")
        self.assertNotIn("opening_video_compliance", gaps)
        self.assertNotIn("opening_video_hard_failure_candidate", gaps)

    def test_merge_opening_start_verification_overrides_only_sealed_start(self):
        native = {
            "status": "success",
            "latency_seconds": 1.5,
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            "cost": {"amount": 0.01, "currency": "USD", "estimated_usd": 0.01},
            "cost_status": "estimated",
            "estimated_cost_calls": 1,
            "_channel_route_attempts": [{"channel": "baidu", "decision": "selected"}],
            "parsed": {
                "video_audit_conclusion": {"opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [],
                    "result": "compliant",
                }},
            },
            "parsed_before_boundary": {},
        }
        verification = {
            "status": "success",
            "latency_seconds": 0.5,
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
            "cost": {"amount": 0.002, "currency": "USD", "estimated_usd": 0.002},
            "cost_status": "estimated",
            "estimated_cost_calls": 1,
            "_channel_route_attempts": [{"channel": "baidu", "decision": "selected"}],
            "parsed": {
                "result": "unsealed",
                "sealed_start": False,
                "evidence_refs": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
                "reason": "首帧已是气泡内包装。",
            },
        }

        merged = merge_opening_start_verification(native, verification, scenario="product_damage")
        opening = merged["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertIs(opening["sealed_start"], False)
        self.assertIs(opening["waybill_visible"], True)
        self.assertEqual(opening["result"], "noncompliant")
        self.assertEqual(opening["field_sources"]["sealed_start"], "opening_start_verification")
        self.assertEqual(opening["validated_fields"], ["sealed_start"])
        self.assertEqual(merged["parsed"]["predicted_label"], "negative")
        self.assertNotEqual(merged["parsed_before_boundary"].get("predicted_label"), "negative")
        self.assertIn("不等于商品无损", merged["parsed"]["overall_audit"]["core_reason"])
        self.assertEqual(merged["usage"]["total_tokens"], 16)
        self.assertEqual(merged["cost"]["estimated_usd"], 0.012)
        self.assertEqual(merged["estimated_cost_calls"], 2)
        self.assertEqual(merged["model_latency_seconds_sum"], 2.0)
        self.assertEqual(len(merged["_channel_route_attempts"]), 2)

    def test_opening_start_reference_uses_trusted_anchor_timestamp(self):
        native = {
            "status": "success",
            "parsed": {"video_audit_conclusion": {"opening_video_compliance": {
                "sealed_start": None,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": True,
                "evidence_refs": [],
                "result": "indeterminate",
            }}},
        }
        verification = {
            "status": "success",
            "parsed": {
                "result": "sealed",
                "sealed_start": True,
                "evidence_refs": [{"video_index": 1, "global_frame_index": 1, "timestamp": "0s"}],
                "reason": "首帧显示完整未拆封快递外箱。",
            },
        }
        anchors = [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}]

        merged = merge_opening_start_verification(native, verification, anchors)

        opening = merged["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertIs(opening["sealed_start"], True)
        self.assertEqual(opening["evidence_refs"][0]["timestamp"], "00:00.00")

        verification["parsed"]["evidence_refs"][0]["global_frame_index"] = 99
        rejected = merge_opening_start_verification(native, verification, anchors)
        self.assertIs(
            rejected["parsed"]["video_audit_conclusion"]["opening_video_compliance"]["sealed_start"],
            None,
        )

    def test_product_damage_start_merge_keeps_issue_visibility_hard_failure(self):
        native = {
            "status": "success",
            "parsed": {"video_audit_conclusion": {"opening_video_compliance": {
                "sealed_start": True,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": False,
                "evidence_refs": [],
                "result": "noncompliant",
            }}},
        }
        verification = {
            "status": "success",
            "parsed": {
                "result": "sealed",
                "sealed_start": True,
                "evidence_refs": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
            },
        }

        merged = merge_opening_start_verification(native, verification, scenario="product_damage")

        self.assertEqual(
            merged["parsed"]["video_audit_conclusion"]["opening_video_compliance"]["result"],
            "noncompliant",
        )

    def test_opening_compliance_verification_uses_dominant_video_and_valid_refs(self):
        case = {
            "case_id": "opening-compliance-verification",
            "scenario": "product_damage",
            "videos": [
                {"video_index": 1, "duration_seconds": 2.0},
                {"video_index": 9, "duration_seconds": 96.0},
            ],
            "frames": [
                {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                {"video_index": 9, "global_frame_index": 2, "timestamp": "00:00.00"},
                {"video_index": 9, "global_frame_index": 3, "timestamp": "01:36.00"},
            ],
        }
        verification_case = model_selection_e2e.opening_compliance_verification_case(case)
        self.assertEqual(
            {frame["video_index"] for frame in verification_case["frames"]},
            {9},
        )
        base = {
            "status": "success",
            "parsed": {"video_audit_conclusion": {"opening_video_compliance": {
                "sealed_start": False,
                "waybill_visible": False,
                "single_take_continuity": False,
                "issue_visible_in_continuous_opening": False,
                "evidence_refs": [],
                "validated_fields": [],
                "result": "noncompliant",
            }}},
        }
        verification = {
            "status": "success",
            "parsed": {
                "sealed_start": True,
                "waybill_visible": False,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": False,
                "evidence_refs": [
                    {
                        "field": field,
                        "video_index": 9,
                        "global_frame_index": 2,
                        "timestamp": "00:00.00",
                    }
                    for field in (
                        "sealed_start", "waybill_visible", "single_take_continuity",
                        "issue_visible_in_continuous_opening",
                    )
                ],
                "result": "noncompliant",
            },
        }

        merged = model_selection_e2e.merge_opening_compliance_verification(
            base,
            verification,
            verification_case["frames"],
            scenario="product_damage",
        )
        opening = merged["parsed"]["video_audit_conclusion"]["opening_video_compliance"]

        self.assertIs(opening["sealed_start"], True)
        self.assertIs(opening["waybill_visible"], False)
        self.assertIs(opening["single_take_continuity"], True)
        self.assertIs(opening["issue_visible_in_continuous_opening"], False)
        self.assertEqual(opening["result"], "noncompliant")
        self.assertEqual(opening["validated_fields"], [
            "issue_visible_in_continuous_opening",
            "sealed_start",
            "single_take_continuity",
            "waybill_visible",
        ])

    def test_chunk_labels_are_not_promoted_without_structured_whole_case_evidence(self):
        case = {
            "case_id": "segment-label-isolation",
            "scenario": "generic_review",
            "frames": [],
            "videos": [],
            "structured_business_context": {"business_scenario": "generic_review"},
        }
        results = [
            {"parsed": {"predicted_label": "positive", "confidence": 0.94, "overall_audit": {}}},
            {"parsed": {"predicted_label": "positive", "confidence": 0.91, "overall_audit": {}}},
        ]

        aggregated = _aggregate_chunk_results(case, results)

        self.assertEqual(aggregated["parsed"]["predicted_label"], "review")

    def test_opening_compliance_uses_only_the_primary_continuous_opening_video(self):
        case = {
            "case_id": "opening-source-scope",
            "scenario": "product_damage",
            "frames": [
                {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                {"video_index": 9, "global_frame_index": 2, "timestamp": "00:00.00"},
                {"video_index": 9, "global_frame_index": 3, "timestamp": "01:36.00"},
            ],
            "videos": [
                {"video_index": 1, "duration_seconds": 2},
                {"video_index": 9, "duration_seconds": 96},
            ],
            "structured_business_context": {"business_scenario": "product_damage"},
        }
        short_closeup = {
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.5,
                "video_audit_conclusion": {"opening_video_compliance": {
                    "sealed_start": None,
                    "waybill_visible": None,
                    "single_take_continuity": None,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [{
                        "field": "issue_visible_in_continuous_opening",
                        "video_index": 1,
                        "global_frame_index": 1,
                        "timestamp": "00:00.00",
                    }],
                }},
            },
        }
        primary_opening = {
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.6,
                "video_audit_conclusion": {"opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [
                        {
                            "field": field,
                            "video_index": 9,
                            "global_frame_index": 2,
                            "timestamp": "00:00.00",
                        }
                        for field in (
                            "sealed_start", "waybill_visible", "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        )
                    ],
                }},
                "damage_causality_assessment": {
                    "damage_presence": "uncertain",
                    "claim_support": "insufficient",
                },
            },
        }
        conflicting_primary = {
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.55,
                "video_audit_conclusion": {"opening_video_compliance": {
                    "waybill_visible": True,
                    "issue_visible_in_continuous_opening": True,
                    "evidence_refs": [
                        {
                            "field": field,
                            "video_index": 9,
                            "global_frame_index": 2,
                            "timestamp": "00:00.00",
                        }
                        for field in ("waybill_visible", "issue_visible_in_continuous_opening")
                    ],
                }},
            },
        }

        aggregated = _aggregate_chunk_results(case, [short_closeup, primary_opening, conflicting_primary])
        opening = aggregated["parsed"]["video_audit_conclusion"]["opening_video_compliance"]

        self.assertIs(opening["sealed_start"], True)
        self.assertIs(opening["waybill_visible"], False)
        self.assertIs(opening["single_take_continuity"], True)
        self.assertIs(opening["issue_visible_in_continuous_opening"], False)
        self.assertEqual(opening["result"], "noncompliant")
        self.assertEqual(
            opening["validated_fields"],
            ["waybill_visible"],
        )
        self.assertEqual(opening["evidence_refs"]["issue_visible_in_continuous_opening"], [])

    def test_provider_connect_timeout_is_bounded_separately_from_inference_timeout(self):
        client = MagicMock()
        client.__enter__.return_value.post.side_effect = TimeoutError("connect timeout")
        with patch("poc.visual_review_poc.model_selection_e2e.httpx.Client", return_value=client) as factory:
            result = post_with_retries("https://example.invalid", {}, {}, timeout=180, retries=0)

        configured_timeout = factory.call_args.kwargs["timeout"]
        self.assertEqual(configured_timeout.connect, 10.0)
        self.assertEqual(configured_timeout.read, 180.0)
        self.assertFalse(result["ok"])

    def test_openai_compatible_continuity_uses_24_individual_frames_per_call(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 50)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") == "object_continuity_only":
                observed.append({
                    "targets": list(current_structured.get("continuity_target_frame_indices") or []),
                    "has_contact_sheet": bool(current_case.get("model_images_override")),
                })
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch.dict("os.environ", {"REVIEW_CONTINUITY_FRAMES_PER_CALL": "48"}, clear=False), patch(
            "poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call
        ):
            result = call_model_chunked({"provider": "openai_compatible"}, case, timeout=30, retries=0)

        self.assertEqual([len(item["targets"]) for item in observed], [24, 24, 1])
        self.assertTrue(all(not item["has_contact_sheet"] for item in observed))
        self.assertEqual(result["chunking"]["continuity_pass"]["segment_count"], 3)

    def test_gemini_native_continuity_also_uses_24_individual_frames_per_call(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 50)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") == "object_continuity_only":
                observed.append({
                    "targets": list(current_structured.get("continuity_target_frame_indices") or []),
                    "has_contact_sheet": bool(current_case.get("model_images_override")),
                })
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch.dict("os.environ", {"REVIEW_CONTINUITY_FRAMES_PER_CALL": "48"}, clear=False), patch(
            "poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call
        ):
            result = call_model_chunked({"provider": "gemini_native"}, case, timeout=30, retries=0)

        self.assertEqual([len(item["targets"]) for item in observed], [24, 24, 1])
        self.assertTrue(all(not item["has_contact_sheet"] for item in observed))
        self.assertEqual(result["chunking"]["continuity_pass"]["segment_count"], 3)

    def test_missing_damage_assessment_preserves_frame_evidence_as_unknown_summary(self):
        frames = self.frames[:4]

        def findings_without_assessment(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "causality_target_frame_indices"
            ) or []
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": index,
                            "timestamp": f"00:0{index - 1}.00",
                            "visible_facts": "逐帧可见事实",
                        }
                        for index in targets
                    ]
                },
                "usage": {},
                "cost": {},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="damage_causality_only",
            target_index_key="causality_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=findings_without_assessment,
            preserve_partial_coverage=True,
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["coverage_status"], "partial_unknown")
        self.assertEqual(results[0]["assessment_status"], "model_output_missing")
        assessment = results[0]["parsed"]["damage_causality_assessment"]
        self.assertEqual(assessment["damage_presence"], "uncertain")
        self.assertEqual(assessment["claim_support"], "insufficient")

    def setUp(self) -> None:
        self.frames = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:0{index - 1}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 9)
        ]
        self.case = {
            "case_id": "continuity-orchestration-test",
            "scenario": "product_damage",
            "scenario_label": "商品有伤",
            "customer_claim": "商品有伤",
            "frames": self.frames,
            "videos": [{"video_index": 1, "file": "sample.mp4"}],
            "supplemental_images": [],
            "model_frames_per_call": 24,
            "structured_business_context": {
                "business_scenario": "product_damage",
                "continuity_policy": {
                    "force_dense_scan": True,
                    "dedicated_chunk_frames": 12,
                    "out_of_frame_warning_seconds": 2.0,
                },
            },
        }

    def _fake_call(self, _cfg, case, _timeout, _retries):
        mode = (case.get("structured_business_context") or {}).get("analysis_mode")
        if mode == "object_continuity_only":
            findings = []
            for frame in case["frames"]:
                index = frame["global_frame_index"]
                findings.append(
                    {
                        "global_frame_index": index,
                        "video_index": 1,
                        "timestamp": frame["timestamp"],
                        "opening_stage": "contents_displayed",
                        "visible_facts": "主体状态",
                        "subject_visibility": [
                            {"subject_id": subject_id, "state": _visibility(index, subject_id)}
                            for subject_id in ("shipping_package", "product_package", "claimed_item")
                        ],
                    }
                )
            parsed = {"frame_findings": findings, "object_continuity_assessment": {"continuity_verdict": "long_absence"}}
        elif mode == "damage_causality_only":
            findings = [
                {
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": 1,
                    "timestamp": frame["timestamp"],
                    "visible_facts": "逐帧动作事实",
                }
                for frame in case["frames"]
            ]
            common = {"video_index": 1, "subject": "撕拉片", "location": "右上角", "chain_id": "chain-1"}
            parsed = {
                "frame_findings": findings,
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "damage_type_and_location": "撕拉片同一断裂位置",
                    "pre_opening_state_visible": False,
                    "opening_action_visible": True,
                    "damage_change_observed": True,
                    "damage_timing": "appears_during_opening",
                    "most_likely_origin": "customer_opening_or_handling",
                    "origin_confidence": 0.92,
                    "causal_evidence_level": "direct",
                    "claim_support": "not_supported",
                    "possible_origins": [],
                    "before_action_evidence": [{**common, "global_frame_index": 1, "timestamp": "00:00.00", "fact": "动作前完整"}],
                    "action_evidence": [{**common, "global_frame_index": 2, "timestamp": "00:01.00", "fact": "用户撕拉"}],
                    "after_action_evidence": [{**common, "global_frame_index": 3, "timestamp": "00:02.00", "fact": "动作后断裂", "damage_visible": True}],
                },
                "damage_observability": {
                    "status": "fully_observable",
                    "same_item_linkage": True,
                    "claimed_region_closeup": True,
                    "required_view_coverage": 1.0,
                    "conflicting_evidence": False,
                    "missing_views": [],
                },
            }
        else:
            parsed = {
                "predicted_label": "positive",
                "system_yes_no": "YES",
                "confidence": 0.9,
                "overall_audit": {"conclusion": "主通道结论"},
                "customer_claim_parse": {
                    "expected_item": "哪吒盛装舞步系列明信片",
                    "claimed_received_item": "右上角有划痕的明信片",
                },
                "expected_order_item": {
                    "item_ref": "ORDER-LINE-008",
                    "sku": "mddfrzszmxp013",
                    "product_name": "哪吒 非人哉 盛装舞步系列 明信片",
                    "specification": "105x148mm",
                },
                "frame_findings": [],
                "damage_causality_assessment": {},
                "damage_observability": {
                    "status": "fully_observable",
                    "same_item_linkage": True,
                    "claimed_region_closeup": True,
                    "required_view_coverage": 1.0,
                    "conflicting_evidence": False,
                    "missing_views": [],
                },
                "adopted_evidence": [
                    {
                        "source_type": "supplementary_image",
                        "image_index": image["image_index"],
                        "fact": "用户另行提交了损伤特写图。",
                    }
                    for image in case.get("supplemental_images") or []
                ],
                "object_continuity_assessment": {
                    "continuity_verdict": "continuous",
                    "tracked_subjects": [
                        {
                            "subject_id": "product_package",
                            "description": "商品包装",
                            "visibility_coverage": 1.0,
                            "out_of_frame_events": [],
                        }
                    ],
                },
            }
        return {
            "status": "success",
            "parsed": parsed,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "cost": {"estimated_usd": 0.001},
            "latency_seconds": 0.1,
        }

    def test_specialized_passes_reuse_main_review_claimed_item_identity(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        case["structured_business_context"] = structured
        observed = {"object_continuity_only": [], "damage_causality_only": []}

        def recording_call(cfg, current_case, timeout, retries):
            structured = current_case.get("structured_business_context") or {}
            mode = structured.get("analysis_mode")
            if mode in observed:
                observed[mode].append(structured.get("continuity_claim_identity"))
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            call_model_chunked({}, case, timeout=30, retries=0)

        self.assertTrue(observed["object_continuity_only"])
        self.assertTrue(observed["damage_causality_only"])
        for items in observed.values():
            self.assertTrue(all(item["sku"] == "mddfrzszmxp013" for item in items))
            self.assertTrue(all("盛装舞步系列" in item["product_name"] for item in items))

    def test_gemini_dense_product_damage_reuses_complete_unified_main_pass(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        case["structured_business_context"] = structured
        observed_modes = []

        def unified_call(cfg, current_case, timeout, retries):
            mode = (current_case.get("structured_business_context") or {}).get("analysis_mode")
            observed_modes.append(mode)
            findings = [
                {
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": frame["video_index"],
                    "timestamp": frame["timestamp"],
                    "visible_facts": "逐帧统一审核事实",
                    "subject_visibility": [
                        {"subject_id": subject, "state": "visible"}
                        for subject in ("shipping_package", "product_package", "claimed_item")
                    ],
                }
                for frame in current_case["frames"]
            ]
            return {
                "status": "success",
                "parsed": {
                    "predicted_label": "review",
                    "confidence": 0.82,
                    "overall_audit": {"conclusion": "统一审核完成"},
                    "frame_findings": findings,
                    "object_continuity_assessment": {"continuity_verdict": "continuous"},
                    "damage_causality_assessment": {
                        "damage_presence": "confirmed",
                        "claim_support": "supported",
                    },
                },
                "usage": {"total_tokens": 20},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=unified_call):
            result = call_model_chunked({"provider": "gemini_native"}, case, timeout=30, retries=0)

        self.assertEqual(observed_modes, [None])
        self.assertEqual(result["chunking"]["total_model_calls"], 1)
        self.assertEqual(result["chunking"]["unified_multitask"]["status"], "completed")
        self.assertEqual(result["chunking"]["channels"]["object_continuity"]["model_calls"], 0)
        self.assertEqual(result["chunking"]["channels"]["damage_causality"]["model_calls"], 0)

    def test_gemini_dense_missing_item_reuses_complete_main_continuity(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["business_scenario"] = "missing_item"
        case["scenario"] = "video_unboxing"
        case["structured_business_context"] = structured
        observed_modes = []

        def unified_call(cfg, current_case, timeout, retries):
            observed_modes.append(
                (current_case.get("structured_business_context") or {}).get("analysis_mode")
            )
            result = self._fake_call(cfg, current_case, timeout, retries)
            result["parsed"]["frame_findings"] = [
                {
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": frame["video_index"],
                    "timestamp": frame["timestamp"],
                    "visible_facts": "逐帧统一审核事实",
                    "subject_visibility": [
                        {"subject_id": subject, "state": "visible"}
                        for subject in ("shipping_package", "product_package", "claimed_item")
                    ],
                }
                for frame in current_case["frames"]
            ]
            result["parsed"]["object_continuity_assessment"] = {
                "continuity_verdict": "continuous"
            }
            return result

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=unified_call):
            result = call_model_chunked(
                {"provider": "gemini_native"}, case, timeout=30, retries=0
            )

        self.assertEqual(observed_modes, [None])
        self.assertEqual(result["chunking"]["total_model_calls"], 1)
        self.assertEqual(result["chunking"]["unified_multitask"]["status"], "completed")
        self.assertEqual(result["chunking"]["channels"]["object_continuity"]["model_calls"], 0)

    def test_gemini_dense_missing_item_falls_back_when_main_continuity_is_sparse(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["business_scenario"] = "missing_item"
        case["scenario"] = "video_unboxing"
        case["structured_business_context"] = structured
        observed_modes = []

        def unified_call(cfg, current_case, timeout, retries):
            observed_modes.append(
                (current_case.get("structured_business_context") or {}).get("analysis_mode")
            )
            result = self._fake_call(cfg, current_case, timeout, retries)
            if observed_modes[-1] is None:
                frame = current_case["frames"][0]
                result["parsed"]["frame_findings"] = [{
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": frame["video_index"],
                    "timestamp": frame["timestamp"],
                    "visible_facts": "关键状态变化",
                    "subject_visibility": [
                        {"subject_id": subject, "state": "visible"}
                        for subject in ("shipping_package", "product_package", "claimed_item")
                    ],
                }]
                result["parsed"]["object_continuity_assessment"] = None
            return result

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=unified_call):
            result = call_model_chunked(
                {"provider": "gemini_native"}, case, timeout=30, retries=0
            )

        self.assertEqual(observed_modes, [None, "object_continuity_only"])
        self.assertEqual(result["chunking"]["total_model_calls"], 2)
        self.assertEqual(result["chunking"]["unified_multitask"]["status"], "dimension_fallback")
        self.assertEqual(result["chunking"]["channels"]["object_continuity"]["model_calls"], 1)

    def test_gemini_dense_product_damage_can_disable_unified_mode_for_ab_control(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        case["structured_business_context"] = structured
        observed_modes = []

        def recording_call(cfg, current_case, timeout, retries):
            observed_modes.append(
                (current_case.get("structured_business_context") or {}).get("analysis_mode")
            )
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            result = call_model_chunked(
                {"provider": "gemini_native", "unified_multitask": False},
                case,
                timeout=30,
                retries=0,
            )

        self.assertIn("object_continuity_only", observed_modes)
        self.assertIn("damage_causality_only", observed_modes)
        self.assertFalse(result["chunking"]["unified_multitask"]["enabled"])

    def test_unified_main_falls_back_only_for_missing_damage_dimension(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        case["structured_business_context"] = structured
        observed_modes = []

        def partial_unified_call(cfg, current_case, timeout, retries):
            mode = (current_case.get("structured_business_context") or {}).get("analysis_mode")
            observed_modes.append(mode)
            if mode == "damage_causality_only":
                return self._fake_call(cfg, current_case, timeout, retries)
            result = self._fake_call(cfg, current_case, timeout, retries)
            result["parsed"]["frame_findings"] = [
                {
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": frame["video_index"],
                    "timestamp": frame["timestamp"],
                    "visible_facts": "逐帧连续性事实",
                    "subject_visibility": [
                        {"subject_id": subject, "state": "visible"}
                        for subject in ("shipping_package", "product_package", "claimed_item")
                    ],
                }
                for frame in current_case["frames"]
            ]
            result["parsed"]["object_continuity_assessment"] = {"continuity_verdict": "continuous"}
            result["parsed"]["damage_causality_assessment"] = {}
            return result

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=partial_unified_call):
            result = call_model_chunked({"provider": "gemini_native"}, case, timeout=30, retries=0)

        self.assertNotIn("object_continuity_only", observed_modes)
        self.assertIn("damage_causality_only", observed_modes)
        self.assertEqual(result["chunking"]["unified_multitask"]["dimension_gaps"], ["damage_causality"])

    def test_specialized_passes_do_not_guess_order_item_when_main_identity_is_missing(self):
        case = dict(self.case)
        case["customer_claim"] = "Nezha postcard has scratches"
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        structured["order_items"] = [
            {"item_ref": "ORDER-LINE-001", "sku": "badge-1", "product_name": "Nezha badge"},
            {"item_ref": "ORDER-LINE-002", "sku": "postcard-1", "product_name": "Nezha postcard"},
        ]
        case["structured_business_context"] = structured
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") in {"object_continuity_only", "damage_causality_only"}:
                observed.append(current_structured.get("continuity_claim_identity"))
            result = self._fake_call(cfg, current_case, timeout, retries)
            if not current_structured.get("analysis_mode"):
                result["parsed"].pop("customer_claim_parse", None)
                result["parsed"].pop("expected_order_item", None)
            return result

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            call_model_chunked({}, case, timeout=30, retries=0)

        self.assertTrue(observed)
        self.assertTrue(all("sku" not in item for item in observed))
        self.assertTrue(all("item_ref" not in item for item in observed))
        self.assertTrue(all(item["customer_claim"] == "Nezha postcard has scratches" for item in observed))

    def test_specialized_passes_receive_only_the_claimed_item_reference(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["damage_causality_policy"] = {"force_action_scan": True}
        structured["continuity_claim_identity"] = {
            "item_ref": "ORDER-LINE-008",
            "sku": "mddfrzszmxp013",
        }
        case["structured_business_context"] = structured
        case["official_reference_images"] = [
            {"item_ref": "ORDER-LINE-001", "sku": "badge-1", "api_path": "badge.jpg"},
            {"item_ref": "ORDER-LINE-008", "sku": "mddfrzszmxp013", "api_path": "postcard.jpg"},
        ]
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") in {"object_continuity_only", "damage_causality_only"}:
                observed.append(current_case.get("official_reference_images") or [])
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertTrue(observed)
        self.assertTrue(all(len(items) == 1 for items in observed))
        self.assertTrue(all(items[0]["sku"] == "mddfrzszmxp013" for items in observed))
        self.assertEqual(
            result["parsed"]["object_continuity_assessment"]["claimed_item_reference_status"],
            "available",
        )

    def test_continuity_prompt_forbids_using_same_category_as_claimed_item(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["analysis_mode"] = "object_continuity_only"
        structured["continuity_claim_identity"] = {
            "sku": "mddfrzszmxp013",
            "product_name": "哪吒 非人哉 盛装舞步系列 明信片",
            "claimed_received_item": "右上角有划痕的明信片",
        }
        case["structured_business_context"] = structured

        prompt = build_selection_prompt(case)

        self.assertIn("mddfrzszmxp013", prompt)
        self.assertIn("同品类但非同一件商品", prompt)
        self.assertIn("不得标记为 claimed_item 可见", prompt)
        self.assertIn("identity_match", prompt)
        self.assertIn("官方商品参考图", prompt)

        structured["analysis_mode"] = "damage_causality_only"
        case["structured_business_context"] = structured
        damage_prompt = build_selection_prompt(case)
        self.assertIn("mddfrzszmxp013", damage_prompt)
        self.assertIn("同品类但非同一件商品的损伤", damage_prompt)
        self.assertIn("damage_visible", damage_prompt)

    def test_unmatched_product_cannot_be_counted_as_the_claimed_item(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update({
            "analysis_mode": "object_continuity_only",
            "continuity_target_frame_indices": [1],
            "continuity_claim_identity": {"item_ref": "ORDER-LINE-008", "sku": "mddfrzszmxp013"},
        })
        case["structured_business_context"] = structured
        case["frames"] = self.frames[:1]
        case["official_reference_images"] = [
            {"item_ref": "ORDER-LINE-008", "sku": "mddfrzszmxp013", "api_path": "postcard.jpg"},
        ]

        def invoke(current_case):
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [{
                        "video_index": 1,
                        "global_frame_index": 1,
                        "timestamp": "00:00.00",
                        "opening_stage": "item_exposed",
                        "visible_facts": "画面中是另一款商品",
                        "subject_visibility": [
                            {"subject_id": "shipping_package", "state": "visible"},
                            {"subject_id": "product_package", "state": "visible"},
                            {"subject_id": "claimed_item", "state": "visible", "identity_match": "not_matched"},
                        ],
                    }],
                    "object_continuity_assessment": {"continuity_verdict": "continuous"},
                },
            }

        results, failures = run_specialized_frame_pass(
            case,
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=1,
            context_frame_count=0,
            workers=1,
            invoke=invoke,
        )

        self.assertFalse(failures)
        claimed = next(
            item for item in results[0]["parsed"]["frame_findings"][0]["subject_visibility"]
            if item["subject_id"] == "claimed_item"
        )
        self.assertEqual(claimed["state"], "unknown")
        self.assertEqual(results[0]["parsed"]["object_continuity_assessment"]["claimed_item_reference_status"], "available")

    def test_dedicated_pass_overrides_missing_main_timeline(self):
        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, self.case, timeout=30, retries=0)

        continuity = result["parsed"]["object_continuity_assessment"]
        product_package = next(
            item for item in continuity["tracked_subjects"] if item["subject_id"] == "product_package"
        )
        self.assertEqual(result["chunking"]["continuity_pass"]["status"], "completed")
        self.assertEqual(product_package["longest_out_of_frame_seconds"], 3.0)
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["usage"]["total_tokens"], 30)
        confidence = result["parsed"]["confidence_components"]
        self.assertEqual(confidence["main_segment_mean"], 0.9)
        self.assertEqual(confidence["final_decision"], result["parsed"]["confidence"])
        self.assertEqual(confidence["calibration_status"], "uncalibrated_model_score")

    def test_product_damage_main_review_uses_representative_frames_but_specialized_passes_keep_full_timeline(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 214)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured
        observed = {"main": [], "continuity": [], "causality": []}

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            mode = current_structured.get("analysis_mode")
            if mode == "object_continuity_only":
                observed["continuity"].extend(current_structured.get("continuity_target_frame_indices") or [])
            elif mode == "damage_causality_only":
                observed["causality"].extend(current_structured.get("causality_target_frame_indices") or [])
            else:
                observed["main"].extend(
                    frame["global_frame_index"] for frame in current_case.get("frames") or []
                )
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(len(observed["main"]), 48)
        self.assertEqual(len(set(observed["main"])), 48)
        self.assertEqual(min(observed["main"]), 1)
        self.assertEqual(max(observed["main"]), 213)
        self.assertEqual(sorted(observed["continuity"]), list(range(1, 214)))
        self.assertEqual(sorted(observed["causality"]), list(range(1, 214)))
        self.assertEqual(result["chunking"]["total_frames"], 213)
        self.assertEqual(result["chunking"]["main_review_frames"], 48)
        self.assertEqual(result["chunking"]["channels"]["main_review"]["model_calls"], 2)

    def test_continuity_prompt_separates_context_and_target_frames(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update(
            {
                "analysis_mode": "object_continuity_only",
                "continuity_target_frame_indices": [4, 5],
            }
        )
        case["structured_business_context"] = structured
        case["frames"] = self.frames[1:5]
        prompt = build_selection_prompt(case)
        self.assertIn('"role": "context_only"', prompt)
        self.assertIn('"role": "target"', prompt)
        self.assertIn("最内层商品包装", prompt)

    def test_damage_causality_prompt_separates_video_scope_and_observability(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update({
            "analysis_mode": "damage_causality_only",
            "causality_target_frame_indices": [1, 2],
        })
        case["structured_business_context"] = structured
        case["frames"] = self.frames[:2]

        prompt = build_selection_prompt(case)

        self.assertIn("只判断主视频中的损伤", prompt)
        self.assertIn("补充图片由主审核通道独立记录", prompt)
        self.assertIn("damage_observability", prompt)

    def test_main_prompt_requires_supplemental_linkage_fields(self):
        prompt = build_selection_prompt(self.case)

        self.assertIn("same_item_linkage", prompt)
        self.assertIn("temporal_linkage", prompt)
        self.assertIn("仅补充图片证据填写", prompt)
        self.assertIn("视频文件/时间轴完整", prompt)
        self.assertIn("物流单号或关键关联字段清晰可读", prompt)
        self.assertIn("后补短视频或照片中的伤点不能计入", prompt)

    def test_unified_main_prompt_requires_every_target_frame_in_one_response(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update({
            "unified_multitask": True,
            "review_chunk": {"index": 1, "total": 1},
        })
        case["structured_business_context"] = structured
        case["frames"] = self.frames[:3]

        prompt = build_selection_prompt(case)

        self.assertIn("统一多任务", prompt)
        self.assertIn("本批全部 3 个目标帧", prompt)
        self.assertIn("shipping_package、product_package、claimed_item", prompt)
        self.assertIn("不得只返回关键帧", prompt)
        self.assertIn("全部目标帧各一条精简状态", prompt)
        self.assertNotIn("只记录对结论有贡献的关键状态帧", prompt)

    def test_damage_causality_pass_exposes_tendency_without_overriding_case_label(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured
        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["chunking"]["damage_causality_pass"]["status"], "completed")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["parsed"]["damage_evidence_tendency"], "does_not_support_claim")
        self.assertEqual(
            result["parsed"]["damage_causality_assessment"]["most_likely_origin"],
            "customer_opening_or_handling",
        )
        self.assertEqual(result["parsed"]["confidence_components"]["damage_origin"], 0.92)

    def test_video_only_causality_pass_keeps_main_observability_and_supplemental_evidence(self):
        case = dict(self.case)
        case["supplemental_images"] = [{"image_index": 1, "file": "damage-closeup.jpg"}]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        parsed = result["parsed"]
        self.assertEqual(parsed["damage_observability"]["status"], "fully_observable")
        source_summary = parsed["damage_causality_assessment"]["evidence_source_summary"]
        self.assertEqual(source_summary["primary_video"]["scope"], "sampled_opening_video")
        self.assertEqual(source_summary["supplemental_images"]["provided_count"], 1)
        self.assertEqual(source_summary["supplemental_images"]["referenced_count"], 1)
        self.assertIn("不能单独推翻", source_summary["decision_boundary"])

    def test_product_damage_batches_supplemental_images_without_losing_coverage(self):
        case = dict(self.case)
        case["supplemental_images"] = [
            {"image_index": index, "file": f"damage-{index}.jpg"}
            for index in range(1, 6)
        ]
        case["official_reference_images"] = [
            {"reference_index": 1},
            {"reference_index": 2},
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        dedicated_batches = []

        def supplemental_only_call(cfg, current_case, timeout, retries):
            review_chunk = (current_case.get("structured_business_context") or {}).get("review_chunk") or {}
            if review_chunk.get("pass_type") == "supplemental_evidence":
                dedicated_batches.append([
                    item["image_index"] for item in current_case.get("supplemental_images") or []
                ])
                result = self._fake_call(cfg, current_case, timeout, retries)
                if current_case["supplemental_images"][0]["image_index"] == 1:
                    result["parsed"]["adopted_evidence"] = []
                else:
                    for item in result["parsed"]["adopted_evidence"]:
                        item.pop("image_index", None)
                return result
            main_case = dict(current_case)
            main_case["supplemental_images"] = []
            return self._fake_call(cfg, main_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=supplemental_only_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        source_summary = result["parsed"]["damage_causality_assessment"]["evidence_source_summary"]
        self.assertEqual(dedicated_batches, [[1, 2, 3, 4, 5]])
        self.assertEqual(source_summary["supplemental_images"]["referenced_count"], 5)
        self.assertEqual(source_summary["supplemental_images"]["processed_count"], 5)
        self.assertEqual(source_summary["supplemental_images"]["unreferenced_image_indices"], [])
        self.assertEqual(result["chunking"]["supplemental_evidence_pass"]["status"], "completed")
        expected_media = min(6, len(case["frames"])) + 5 + 2
        self.assertEqual(
            result["chunking"]["channels"]["supplemental_evidence"]["model_images"],
            expected_media,
        )

    def test_linked_supplemental_damage_confirms_damage_without_inventing_cause(self):
        case = dict(self.case)
        case["supplemental_images"] = [{"image_index": 1, "file": "damage-closeup.jpg"}]
        main = {
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.5,
                "overall_audit": {"conclusion": "主视频未看清损伤"},
                "damage_causality_assessment": {
                    "damage_presence": "uncertain",
                    "damage_timing": "unknown",
                    "most_likely_origin": "indeterminate",
                    "causal_evidence_level": "insufficient",
                    "claim_support": "insufficient",
                },
            },
            "usage": {},
            "cost": {},
        }
        supplemental = {
            "parsed": {
                "adopted_evidence": [{
                    "source_type": "supplementary_image",
                    "image_index": 1,
                    "asset_ref": "supplemental_image_1",
                    "fact": "同一商品的耳羽已经断裂。",
                    "why_it_matters": "直接证明损伤存在，但不证明损伤成因。",
                    "damage_visible": True,
                    "confidence": 0.94,
                    "same_item_linkage": "high",
                    "temporal_linkage": "post_opening",
                }],
            },
            "usage": {},
            "cost": {},
        }

        result = _aggregate_chunk_results(case, [main], supplemental_results=[supplemental])

        assessment = result["parsed"]["damage_causality_assessment"]
        source_summary = assessment["evidence_source_summary"]["supplemental_images"]
        self.assertEqual(assessment["damage_presence"], "confirmed")
        self.assertEqual(assessment["most_likely_origin"], "indeterminate")
        self.assertEqual(assessment["causal_evidence_level"], "insufficient")
        self.assertEqual(assessment["first_visible_evidence"]["image_index"], 1)
        self.assertEqual(
            assessment["evidence_source_summary"]["primary_video"]["damage_presence"],
            "uncertain",
        )
        self.assertEqual(source_summary["linkage_status"], "verified")

    def test_partial_specialized_failure_only_degrades_its_evidence_dimension(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 17)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": True, "dedicated_chunk_frames": 8, "context_frames": 2}
        case["structured_business_context"] = structured

        def partial_call(cfg, current_case, timeout, retries):
            mode = (current_case.get("structured_business_context") or {}).get("analysis_mode")
            targets = (current_case.get("structured_business_context") or {}).get("causality_target_frame_indices") or []
            if mode == "damage_causality_only" and max(targets, default=0) > 8:
                return {
                    "status": "failed",
                    "error": "injected_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                    "latency_seconds": 0.2,
                }
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=partial_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)
        self.assertEqual(result["chunking"]["damage_causality_pass"]["status"], "degraded")
        self.assertTrue(result["chunking"]["damage_causality_pass"]["failures"])
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["parsed"]["damage_evidence_tendency"], "does_not_support_claim")
        self.assertEqual(result["parsed"]["pass_integrity_status"], "partial_specialized")
        self.assertNotIn("specialized_pass_guard_reason", result["parsed"])
        self.assertIn("补充图片专项", result["parsed"]["specialized_pass_warning"])
        self.assertIn("对应证据维度", result["parsed"]["specialized_pass_warning"])
        self.assertEqual(result["usage"]["total_tokens"], 50)
        self.assertEqual(result["cost"]["estimated_usd"], 0.007)
        self.assertEqual(result["chunking"]["damage_causality_pass"]["failures"][0]["usage"]["total_tokens"], 20)

    def test_main_chunk_failure_preserves_evidence_and_degrades_to_review(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        calls = 0

        def mixed_call(cfg, current_case, timeout, retries):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {
                    "status": "failed",
                    "error": "provider_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                    "latency_seconds": 0.2,
                }
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=mixed_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["chunking"]["main_review_pass"]["status"], "degraded")
        self.assertEqual(len(result["chunking"]["main_review_pass"]["failures"]), 1)
        self.assertEqual(result["usage"]["total_tokens"], 35)
        self.assertEqual(result["cost"]["estimated_usd"], 0.006)
        self.assertEqual(result["chunking"]["total_model_calls"], 2)
        self.assertEqual(result["cost_status"], "estimated")
        self.assertEqual(result["unknown_cost_calls"], 0)

    def test_unreported_provider_failure_marks_aggregate_cost_as_partially_unknown(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        calls = 0

        def mixed_call(cfg, current_case, timeout, retries):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError("provider did not return usage")
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=mixed_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 1)

    def test_all_main_chunks_failed_keeps_job_failed(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        with patch(
            "poc.visual_review_poc.model_selection_e2e.call_model",
            return_value={"status": "failed", "error": "provider_unavailable", "cost_status": "unknown"},
        ):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["cost_status"], "unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)

    def test_missing_provider_key_does_not_count_as_model_call(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        with patch(
            "poc.visual_review_poc.model_selection_e2e.call_model",
            return_value={"status": "skipped", "error": "missing_api_key", "cost_status": "not_incurred"},
        ):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["cost_status"], "not_incurred")
        self.assertEqual(result["chunking"]["total_model_calls"], 0)
        self.assertEqual(result["chunking"]["channels"]["main_review"]["model_calls"], 0)

    def test_duplicate_or_missing_target_frames_fail_schema_validation(self):
        frames = self.frames[:4]

        def incomplete(_case):
            finding = {
                "global_frame_index": 1,
                "timestamp": "00:00.00",
                "opening_stage": "unknown",
                "visible_facts": "重复帧",
                "subject_visibility": [
                    {"subject_id": subject, "state": "visible"}
                    for subject in ("shipping_package", "product_package", "claimed_item")
                ],
            }
            return {
                "status": "success",
                "parsed": {"frame_findings": [finding, finding]},
                "usage": {"input_tokens": 99, "output_tokens": 1, "total_tokens": 100},
                "cost": {"estimated_usd": 0.5},
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=incomplete,
        )
        self.assertEqual(results, [])
        self.assertEqual(failures[0]["error"], "target_frame_coverage_invalid")
        self.assertEqual(failures[0]["usage"]["total_tokens"], 100)
        self.assertEqual(failures[0]["cost"]["estimated_usd"], 0.5)

    def test_specialized_pass_repairs_only_missing_target_frames_once(self):
        frames = self.frames[:4]
        calls = []

        def finding(frame):
            return {
                "global_frame_index": frame["global_frame_index"],
                "timestamp": frame["timestamp"],
                "opening_stage": "contents_displayed",
                "visible_facts": "逐帧可见事实",
                "subject_visibility": [
                    {"subject_id": subject, "state": "visible"}
                    for subject in ("shipping_package", "product_package", "claimed_item")
                ],
            }

        def incomplete_then_repair(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            calls.append(list(targets))
            selected = [
                frame
                for frame in current_case["frames"]
                if frame["global_frame_index"] in targets
            ]
            if targets == [1, 2, 3, 4]:
                selected = selected[:-1]
            is_primary = targets == [1, 2, 3, 4]
            return {
                "status": "success",
                "parsed": {"frame_findings": [finding(frame) for frame in selected]},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "partial_unknown" if is_primary else "estimated",
                "unknown_cost_calls": 1 if is_primary else 0,
                "estimated_cost_calls": 1,
                "latency_seconds": 0.1,
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=incomplete_then_repair,
            repair_attempts=1,
        )

        self.assertEqual(calls, [[1, 2, 3, 4], [4]])
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repair_calls"], 1)
        self.assertEqual(results[0]["usage"]["total_tokens"], 30)
        self.assertEqual(results[0]["cost"]["estimated_usd"], 0.002)
        self.assertEqual(results[0]["cost_status"], "partial_unknown")
        self.assertEqual(results[0]["unknown_cost_calls"], 1)
        self.assertEqual(results[0]["estimated_cost_calls"], 2)
        self.assertEqual(
            [item["global_frame_index"] for item in results[0]["parsed"]["frame_findings"]],
            [1, 2, 3, 4],
        )

    def test_specialized_pass_normalizes_numeric_string_frame_indices(self):
        frames = self.frames[:4]

        def string_indices(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": str(index),
                            "timestamp": f"00:0{index - 1}.00",
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for index in targets
                    ]
                },
                "usage": {},
                "cost": {},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=string_indices,
        )

        self.assertEqual(failures, [])
        self.assertEqual(
            [item["global_frame_index"] for item in results[0]["parsed"]["frame_findings"]],
            [1, 2, 3, 4],
        )

    def test_specialized_pass_normalizes_invalid_semantic_fields_to_unknown(self):
        frames = self.frames[:2]

        def invalid_semantics(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": index,
                            "timestamp": "00:00.00",
                            "opening_stage": "maybe_open",
                            "visible_facts": "画面已审查",
                            "subject_visibility": [
                                {"subject_id": "shipping_package", "state": "in_view"},
                            ],
                        }
                        for index in targets
                    ]
                },
                "usage": {},
                "cost": {},
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=2,
            context_frame_count=1,
            workers=1,
            invoke=invalid_semantics,
            preserve_partial_coverage=True,
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["coverage_status"], "partial_unknown")
        finding = results[0]["parsed"]["frame_findings"][0]
        self.assertEqual(finding["opening_stage"], "unknown")
        self.assertEqual(
            {item["subject_id"]: item["state"] for item in finding["subject_visibility"]},
            {"claimed_item": "unknown", "product_package": "unknown", "shipping_package": "unknown"},
        )

    def test_partial_specialized_output_preserves_valid_findings_and_marks_missing_unknown(self):
        frames = self.frames[:4]

        def always_omit_last(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets and frame["global_frame_index"] != 4
            ]
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": frame["global_frame_index"],
                            "timestamp": frame["timestamp"],
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for frame in selected
                    ]
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=always_omit_last,
            repair_attempts=1,
            preserve_partial_coverage=True,
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["coverage_status"], "partial_unknown")
        self.assertEqual(results[0]["missing_target_frame_indices"], [4])
        findings = results[0]["parsed"]["frame_findings"]
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[-1]["observation_status"], "model_output_missing")
        self.assertTrue(all(item["state"] == "unknown" for item in findings[-1]["subject_visibility"]))

    def test_repair_calls_are_included_in_channel_and_total_model_call_counts(self):
        case = dict(self.case)
        case["frames"] = self.frames[:4]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        def incomplete_then_repair(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            targets = current_structured.get("continuity_target_frame_indices") or []
            if current_structured.get("analysis_mode") != "object_continuity_only":
                return self._fake_call(cfg, current_case, timeout, retries)
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets
            ]
            if targets == [1, 2, 3, 4]:
                selected = selected[:-1]
            parsed = {
                "frame_findings": [
                    {
                        "global_frame_index": frame["global_frame_index"],
                        "video_index": 1,
                        "timestamp": frame["timestamp"],
                        "opening_stage": "contents_displayed",
                        "visible_facts": "逐帧可见事实",
                        "subject_visibility": [
                            {"subject_id": subject, "state": "visible"}
                            for subject in ("shipping_package", "product_package", "claimed_item")
                        ],
                    }
                    for frame in selected
                ]
            }
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=incomplete_then_repair):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        continuity = result["chunking"]["channels"]["object_continuity"]
        self.assertEqual(continuity["repair_calls"], 1)
        self.assertEqual(continuity["model_calls"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 3)

    def test_chunk_aggregate_counts_physical_http_retries(self):
        row = self._fake_call({}, self.case, 30, 0)
        row.update({
            "model_http_request_count": 2,
            "model_latency_seconds_sum": 1.25,
            "http_attempts": [
                {"request_sent": True, "outcome": "http_503", "latency_seconds": 0.4},
                {"request_sent": True, "outcome": "success", "latency_seconds": 0.85},
            ],
        })

        result = _aggregate_chunk_results(self.case, [row])

        self.assertEqual(result["model_http_request_count"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 2)
        self.assertEqual(result["chunking"]["channels"]["main_review"]["model_calls"], 2)
        self.assertEqual(result["model_latency_seconds_sum"], 1.25)
        self.assertEqual(len(result["http_attempts"]), 2)

    def test_chunked_review_keeps_partial_continuity_evidence_and_reports_exact_gaps(self):
        case = dict(self.case)
        case["frames"] = self.frames[:4]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        def incomplete_continuity(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            targets = current_structured.get("continuity_target_frame_indices") or []
            if current_structured.get("analysis_mode") != "object_continuity_only":
                return self._fake_call(cfg, current_case, timeout, retries)
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets and frame["global_frame_index"] != 4
            ]
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": frame["global_frame_index"],
                            "timestamp": frame["timestamp"],
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for frame in selected
                    ]
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=incomplete_continuity):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        continuity_pass = result["chunking"]["continuity_pass"]
        self.assertEqual(continuity_pass["status"], "degraded")
        self.assertEqual(continuity_pass["coverage_gaps"][0]["missing_target_frame_indices"], [4])
        findings = result["parsed"]["continuity_frame_findings"]
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[-1]["observation_status"], "model_output_missing")

    def test_provider_payload_ignores_contact_sheet_override_and_keeps_individual_frames(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frame_path = root / "frame.jpg"
            sheet_path = root / "sheet.webp"
            Image.new("RGB", (640, 360), (10, 20, 30)).save(frame_path)
            Image.new("RGB", (1280, 800), (20, 30, 40)).save(sheet_path, format="WEBP")
            case = {
                "frames": [{**self.frames[0], "api_path": str(frame_path), "api_mime_type": "image/jpeg"}],
                "supplemental_images": [],
                "model_images_override": [
                    {"api_path": str(sheet_path), "api_mime_type": "image/webp", "label": "时序拼图映射"}
                ],
            }

            gemini = gemini_payload("system", "user", case)
            openai = openai_messages("system", "user", case)

            gemini_parts = gemini["contents"][0]["parts"]
            self.assertEqual(sum("inlineData" in item for item in gemini_parts), 1)
            self.assertTrue(any((item.get("inlineData") or {}).get("mimeType") == "image/jpeg" for item in gemini_parts))
            openai_content = openai[1]["content"]
            self.assertEqual(sum(item.get("type") == "image_url" for item in openai_content), 1)
            self.assertFalse(any("时序拼图映射" in str(item.get("text") or "") for item in openai_content))
            self.assertFalse(any("file_data" in item or "file_uri" in str(item) for item in gemini_parts))
            image_urls = [item["image_url"]["url"] for item in openai_content if item.get("type") == "image_url"]
            self.assertTrue(all(url.startswith("data:image/") for url in image_urls))


if __name__ == "__main__":
    unittest.main()
