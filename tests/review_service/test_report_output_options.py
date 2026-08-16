# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import html as html_module
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server
from review_service import router, service


def successful_workbench_review() -> dict:
    return {
        "ok": True,
        "source_status": "folder_ready",
        "review": {
            "review_label": "商品有伤审核",
            "summary": {"predicted_label": "positive", "confidence": 0.91, "review_status": "completed"},
            "agent_brief": {"conclusion": "当前证据支持商品存在可见损伤。"},
            "agent_report": {
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.91,
                    "overall_audit": {"conclusion": "当前证据支持商品存在可见损伤。"},
                }
            },
        },
    }


class ReportOutputOptionsTest(unittest.TestCase):
    def test_formal_report_receives_media_forensics_contract(self):
        forensics = {
            "assets": [{
                "file": "evidence.mp4",
                "playback_speed_assessment": {
                    "status": "unknown",
                    "constant_speed_multiplier": None,
                    "reason_code": "source_clock_reference_unavailable",
                },
            }]
        }
        job = {
            "job_id": "RJ-FORENSIC-REPORT",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "result": {
                "media_forensics": forensics,
                "review": {
                    "summary": {"review_status": "completed"},
                    "agent_report": {"parsed": {"predicted_label": "review"}},
                },
            },
        }

        with patch.object(service, "render_public_report", side_effect=lambda data: data):
            rendered_data = service.render_job_report(job)

        self.assertEqual(rendered_data["media_forensics"], forensics)

    def test_formal_report_receives_media_preflight_execution(self):
        execution = {
            "status": "completed",
            "video": {
                "submitted_source": "quality_proxy",
                "delivery": "https_url",
                "native_sampling_fps": 1.0,
            },
            "images": {"representation": "individual_webp", "collage_used": False},
            "frame_fallback": {"used": False},
        }
        job = {
            "job_id": "RJ-PREFLIGHT-REPORT",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "result": {
                "review": {
                    "summary": {"review_status": "completed"},
                    "agent_report": {"parsed": {"predicted_label": "review"}},
                    "media_preflight_execution": execution,
                },
            },
        }

        with patch.object(service, "render_public_report", side_effect=lambda data: data):
            rendered_data = service.render_job_report(job)

        self.assertEqual(rendered_data["media_preflight_execution"], execution)

    def test_job_json_rewrites_media_to_authenticated_job_route(self):
        media_id = "d" * 32
        job = {
            "job_id": "RJ-JSON-MEDIA",
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}?expires=99&sig=old"}],
            }}}},
        }

        public = service.public_job(job)

        self.assertEqual(
            public["result"]["review"]["agent_report"]["media_gallery"]["frames"][0]["url"],
            f"/api/v1/review/jobs/{job['job_id']}/media/{media_id}",
        )

    def test_job_json_hides_internal_inference_usage_and_cost(self):
        job = {
            "job_id": "RJ-PUBLIC-METRICS",
            "result": {"review": {"agent_report": {"inference_estimate": {
                "total_tokens": 120,
                "estimated_usd": 0.01,
                "channel_route_attempts": [{"channel": "internal", "model": "internal-model"}],
                "concurrency": {"configured_workers": 2},
            }}}},
        }

        public = service.public_job(job)
        agent_report = public["result"]["review"]["agent_report"]

        self.assertNotIn("inference_estimate", agent_report)

    def test_job_json_uses_strict_public_projection(self):
        job = {
            "job_id": "RJ-PUBLIC-PROJECTION",
            "tenant_id": "tenant-secret",
            "client_case_id": "CASE-PUBLIC-1",
            "idempotency_key": "private-key",
            "scenario": "minor_refund",
            "status": "SUCCEEDED",
            "metadata": {"source_record": {"name": "张三", "phone": "13800138000"}},
            "assets": [{
                "asset_id": "RA-PUBLIC-1",
                "original_name": "张三身份证.jpg",
                "stored_name": "001_private.jpg",
                "mime_type": "image/jpeg",
                "size": 123,
                "sha256": "secret-sha",
                "fields": ["guardian_id"],
            }],
            "result": {
                "review": {"summary": {"predicted_label": "review"}},
                "boundary": "仅提供审核建议",
                "source_record": {"local_path": "E:/private/sample"},
                "workbench_transport": {"attempts": [{"internal_url": "http://127.0.0.1"}]},
            },
            "diagnostics": {"message": "provider secret"},
            "attempts": 1,
            "created_at": 1.0,
            "started_at": 2.0,
            "completed_at": 3.0,
            "updated_at": 4.0,
            "unexpected_private_field": "must-not-leak",
        }

        public = service.public_job(job)
        serialized = str(public)

        self.assertEqual(
            set(public),
            {
                "job_id", "client_case_id", "scenario", "status", "assets", "result",
                "attempts", "created_at", "started_at", "completed_at", "updated_at",
            },
        )
        self.assertEqual(set(public["assets"][0]), {"asset_id", "mime_type", "size", "fields"})
        self.assertEqual(set(public["result"]), {"review", "boundary"})
        for secret in ("张三", "13800138000", "private-key", "E:/private", "provider secret"):
            self.assertNotIn(secret, serialized)

    def test_batch_json_rewrites_media_to_authenticated_job_route(self):
        media_id = "e" * 32
        job = {
            "job_id": "RJ-BATCH-MEDIA",
            "status": "SUCCEEDED",
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}"}],
            }}}},
        }
        with patch.object(service.store, "list_batch", return_value=[job]), patch.object(
            service.store,
            "batch_snapshot",
            return_value=[{"status": "SUCCEEDED", "count": 1, "total_tokens": 0, "estimated_usd": 0}],
        ):
            result = service.batch_status("mitako", "BATCH-1")

        self.assertEqual(
            result["jobs"][0]["result"]["review"]["agent_report"]["media_gallery"]["frames"][0]["url"],
            f"/api/v1/review/jobs/{job['job_id']}/media/{media_id}",
        )

    def test_media_route_openapi_declares_binary_content_not_json(self):
        route = next(
            item for item in router.router.routes
            if isinstance(item, APIRoute) and item.path == "/api/v1/review/jobs/{job_id}/media/{media_id}"
        )
        responses = route.responses[200]["content"]

        self.assertIn("image/jpeg", responses)
        self.assertIn("video/mp4", responses)
        self.assertIn("application/octet-stream", responses)
        self.assertNotIn("application/json", responses)
        for definition in responses.values():
            self.assertEqual(definition["schema"], {"type": "string", "format": "binary"})
        self.assertEqual(route.responses[206]["content"], responses)

    def test_formal_report_uses_tenant_job_and_media_bound_api_urls(self):
        media_id = "a" * 32
        job = {
            "job_id": "RV-MEDIA-PROXY",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "metadata": {"output_options": {"include_html_report": True}},
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "parsed": {"predicted_label": "review"},
                    "media_gallery": {
                        "frames": [{
                            "url": f"http://127.0.0.1:7861/media-item/{media_id}?expires=99&sig=old",
                            "timestamp": "00:01.00",
                        }],
                    },
                },
            }},
        }

        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            html = service.render_job_report(job)

        match = re.search(
            rf'src="([^"]*/api/v1/review/jobs/{job["job_id"]}/media/{media_id}\?[^"]+)"',
            html,
        )
        self.assertIsNotNone(match)
        media_url = html_module.unescape(match.group(1))
        query = parse_qs(urlsplit(media_url).query)
        expires = query["expires"][0]
        signature = query["sig"][0]
        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            self.assertTrue(service.verify_job_media_signature(
                job["tenant_id"], job["job_id"], media_id, expires, signature
            ))
            self.assertFalse(service.verify_job_media_signature(
                "other-tenant", job["job_id"], media_id, expires, signature
            ))
            self.assertFalse(service.verify_job_media_signature(
                job["tenant_id"], "other-job", media_id, expires, signature
            ))
            self.assertFalse(service.verify_job_media_signature(
                job["tenant_id"], job["job_id"], "b" * 32, expires, signature
            ))
        self.assertNotIn("review.example.test", html)
        self.assertNotIn("127.0.0.1:7861", html)

    def test_formal_report_video_evidence_keeps_signed_timestamp_preview(self):
        media_id = "e" * 32
        job = {
            "job_id": "RV-VIDEO-PREVIEW",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "parsed": {
                        "predicted_label": "review",
                        "adopted_evidence": [{
                            "source_type": "video_frame",
                            "video_index": 1,
                            "timestamp": "00:12.50",
                            "fact": "该时间点可见争议部位。",
                        }],
                    },
                    "media_gallery": {
                        "videos": [{
                            "video_index": 1,
                            "url": f"/media-item/{media_id}",
                        }],
                    },
                },
            }},
        }

        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            html = service.render_job_report(job)

        self.assertRegex(
            html,
            rf'data-preview-src="/api/v1/review/jobs/{job["job_id"]}/media/{media_id}\?[^\"]+#t=12\.500"',
        )
        self.assertIn('data-preview-seconds="12.500"', html)
        self.assertIn("video.currentTime = seekSeconds", html)
        self.assertIn("video.controls = true", html)

    def test_formal_report_replaces_transient_workbench_media_with_durable_job_assets(self):
        job_id = "RV-DURABLE-MEDIA"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / job_id
            job_dir.mkdir()
            (job_dir / "001_video.mp4").write_bytes(b"video")
            (job_dir / "002_image.jpg").write_bytes(b"image")
            job = {
                "job_id": job_id,
                "tenant_id": "mitako",
                "status": "SUCCEEDED",
                "completed_at": 1,
                "assets": [
                    {
                        "asset_id": "RA-VIDEO",
                        "stored_name": "001_video.mp4",
                        "original_name": "video.mp4",
                        "mime_type": "video/mp4",
                    },
                    {
                        "asset_id": "RA-IMAGE",
                        "stored_name": "002_image.jpg",
                        "original_name": "image.jpg",
                        "mime_type": "image/jpeg",
                    },
                ],
                "result": {"review": {
                    "summary": {"review_status": "completed"},
                    "agent_report": {
                        "scenario": "product_damage",
                        "parsed": {"predicted_label": "review"},
                        "media_gallery": {
                            "videos": [{"video_index": 1, "url": f"/media-item/{'a' * 32}"}],
                            "frames": [{
                                "video_index": 1,
                                "timestamp": "00:12.50",
                                "url": f"/media-item/{'b' * 32}",
                            }],
                            "images": [{"image_index": 1, "url": f"/media-item/{'c' * 32}"}],
                        },
                    },
                }},
            }

            with patch.object(service, "upload_root", return_value=root), patch.object(
                service, "render_public_report", side_effect=lambda data: data
            ), patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
                rendered = service.render_job_report(job)
                public = service.public_job(job)

            gallery = rendered["agent_report"]["media_gallery"]
            video_url = gallery["videos"][0]["url"]
            image_url = gallery["images"][0]["url"]
            self.assertIn(f"/api/v1/review/jobs/{job_id}/media/", video_url)
            self.assertIn(f"/api/v1/review/jobs/{job_id}/media/", image_url)
            self.assertNotIn("url", gallery["frames"][0])
            self.assertEqual(gallery["frames"][0]["video_url"].split("#", 1)[1], "t=12.5")
            self.assertNotIn("/media/" + "a" * 32, str(rendered))
            self.assertIn(f"/api/v1/review/jobs/{job_id}/media/", str(public))

    def test_formal_media_route_streams_durable_job_asset_with_range(self):
        job_id = "RV-DURABLE-RANGE"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / job_id
            job_dir.mkdir()
            (job_dir / "001_video.mp4").write_bytes(b"0123456789")
            job = {
                "job_id": job_id,
                "tenant_id": "mitako",
                "assets": [{
                    "asset_id": "RA-VIDEO",
                    "stored_name": "001_video.mp4",
                    "original_name": "video.mp4",
                    "mime_type": "video/mp4",
                }],
                "result": {"review": {"agent_report": {}}},
            }
            media_id = service.job_asset_media_id(job_id, "RA-VIDEO")
            app = FastAPI()
            app.include_router(router.router)
            with patch.dict("os.environ", {
                "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
                "VISUAL_REPORT_SIGNING_SECRET": "shared-secret",
            }), patch.object(service, "upload_root", return_value=root), patch.object(
                router.store, "get_job", return_value=job
            ):
                signed_url = service.signed_job_media_url("mitako", job_id, media_id)
                response = TestClient(app).get(signed_url, headers={"Range": "bytes=2-5"})

            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, b"2345")
            self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
            self.assertEqual(response.headers["content-type"], "video/mp4")
            self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_formal_report_prefers_persisted_browser_compatible_video_proxy(self):
        job_id = "RV-BROWSER-PREVIEW"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / job_id
            job_dir.mkdir()
            (job_dir / "001_video.mp4").write_bytes(b"original-hevc")
            (job_dir / "browser_preview_001.webm").write_bytes(b"webm-vp9")
            job = {
                "job_id": job_id,
                "tenant_id": "mitako",
                "status": "SUCCEEDED",
                "assets": [{
                    "asset_id": "RA-VIDEO",
                    "stored_name": "001_video.mp4",
                    "original_name": "video.mp4",
                    "mime_type": "video/mp4",
                }],
                "result": {"review": {"agent_report": {
                    "media_gallery": {"videos": [{"video_index": 1, "url": f"/media-item/{'a' * 32}"}]},
                }}},
            }

            with patch.object(service, "upload_root", return_value=root), patch.object(
                service, "render_public_report", side_effect=lambda data: data
            ), patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
                rendered = service.render_job_report(job)
                video = rendered["agent_report"]["media_gallery"]["videos"][0]
                review_media_id = urlsplit(video["review_url"]).path.rsplit("/", 1)[-1]
                original_media_id = urlsplit(video["original_url"]).path.rsplit("/", 1)[-1]
                resolved = service.resolve_job_media_path(job, review_media_id)
                original = service.resolve_job_media_path(job, original_media_id)

            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[0].name, "browser_preview_001.webm")
            self.assertEqual(resolved[1], "video/webm")
            self.assertEqual(original[0].name, "001_video.mp4")
            self.assertEqual(video["url"], video["review_url"])
            self.assertTrue(video["comparison_available"])

            with patch.object(service, "upload_root", return_value=root), patch.dict(
                "os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}
            ):
                report_html = service.render_job_report(job)

            self.assertIn("原片与模型送审版对照", report_html)
            self.assertIn("查看原片", report_html)
            self.assertIn("查看模型送审版", report_html)

    def test_workbench_quality_proxy_is_persisted_for_formal_report(self):
        job_id = "RV-PERSIST-PREVIEW"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / job_id).mkdir()
            source = root / job_id / "001_video.mp4"
            source.write_bytes(b"original-video")
            source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            job = {"job_id": job_id, "assets": [{
                "asset_id": "RA-VIDEO",
                "stored_name": source.name,
                "mime_type": "video/mp4",
                "size": source.stat().st_size,
                "sha256": source_sha256,
            }]}
            payload = {"review": {
                "media_preflight_execution": {"video": {
                    "submitted_source": "quality_proxy",
                    "proxy_codec": "vp9",
                    "source_width": 3840,
                    "source_height": 2160,
                    "submitted_width": 2560,
                    "submitted_height": 1440,
                    "native_sampling_fps": 1.0,
                }},
                "agent_report": {"media_gallery": {"videos": [{
                    "video_index": 1,
                    "url": f"/media-item/{'a' * 32}?expires=99&sig=signed",
                }]}},
            }}

            def write_preview(_url, target, _max_bytes):
                target.write_bytes(b"webm-vp9")
                return True

            with patch.object(service, "upload_root", return_value=root), patch.object(
                service, "_download_workbench_media", side_effect=write_preview
            ) as download:
                service._persist_workbench_video_previews(job, payload)

            self.assertEqual((root / job_id / "browser_preview_001.webm").read_bytes(), b"webm-vp9")
            self.assertEqual(download.call_count, 1)
            manifest = json.loads((root / job_id / "review_media_derivatives.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], 2)
            derivative = manifest["videos"][0]
            self.assertEqual(derivative["source_asset_id"], "RA-VIDEO")
            self.assertEqual(derivative["source_sha256"], source_sha256)
            self.assertEqual(
                derivative["review_sha256"],
                hashlib.sha256(b"webm-vp9").hexdigest(),
            )
            self.assertEqual(derivative["model_input_kind"], "review_derivative")
            self.assertEqual(derivative["transformation"]["proxy_codec"], "vp9")
            self.assertEqual(derivative["validation_status"], "ready")

    def test_workbench_receives_the_persisted_review_derivative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_dir = root / "RV-PREPARED-BEFORE-MODEL"
            job_dir.mkdir()
            source = job_dir / "001_video.mp4"
            source.write_bytes(b"original-video")
            derivative = job_dir / "browser_preview_001.webm"
            derivative.write_bytes(b"review-video")
            captured = {}

            class Response:
                status_code = 200
                is_error = False

                @staticmethod
                def json():
                    return {"ok": False, "review": {}}

            class Client:
                def __init__(self, *args, **kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def post(self, _url, **kwargs):
                    captured["filename"] = kwargs["files"][0][1][0]
                    captured["mime_type"] = kwargs["files"][0][1][2]
                    captured["content"] = kwargs["files"][0][1][1].read()
                    return Response()

            manifest = {"version": 2, "videos": [{"video_index": 1, "validation_status": "ready"}]}
            job = {
                "job_id": job_dir.name,
                "client_case_id": "CASE-PREPARED",
                "scenario": "product_damage",
                "tenant_id": "mitako",
                "attempts": 1,
                "assets": [{
                    "asset_id": "RA-VIDEO",
                    "stored_name": source.name,
                    "original_name": "customer.mp4",
                    "mime_type": "video/mp4",
                }],
                "metadata": {},
            }
            prepared = {
                "files": {"RA-VIDEO": str(derivative)},
                "mime_types": {"RA-VIDEO": "video/webm"},
                "manifest": manifest,
            }

            with patch.object(service, "upload_root", return_value=root), patch.object(
                service, "prepare_job_review_media", return_value=prepared
            ), patch.object(service, "_check_workbench_health"), patch.object(
                service.httpx, "Client", Client
            ), patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "internal-secret"}):
                payload = service._call_workbench(job)

            self.assertEqual(captured["filename"], derivative.name)
            self.assertEqual(captured["mime_type"], "video/webm")
            self.assertEqual(captured["content"], b"review-video")
            self.assertEqual(payload["_review_media_processing"], manifest)

    def test_formal_media_signature_rejects_expired_url(self):
        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            media_url = service.signed_job_media_url(
                "mitako",
                "RV-EXPIRED",
                "a" * 32,
                expires=int(time.time()) - 1,
            )
            query = parse_qs(urlsplit(media_url).query)

            self.assertFalse(service.verify_job_media_signature(
                "mitako",
                "RV-EXPIRED",
                "a" * 32,
                query["expires"][0],
                query["sig"][0],
            ))

    def test_formal_media_proxy_accepts_valid_signature_without_bearer(self):
        media_id = "c" * 32
        job = {
            "job_id": "RV-SIGNED-MEDIA",
            "tenant_id": "mitako",
            "result": {"review": {"agent_report": {"media_gallery": {
                "images": [{"url": f"/media-item/{media_id}"}],
            }}}},
        }

        class Upstream:
            status_code = 200
            headers = {"content-type": "image/jpeg", "content-length": "5"}

            async def aiter_bytes(self):
                yield b"image"

            async def aclose(self):
                return None

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def build_request(self, method, url, headers=None):
                return {"method": method, "url": url, "headers": headers or {}}

            async def send(self, request, stream=False):
                return Upstream()

            async def aclose(self):
                return None

        app = FastAPI()
        app.include_router(router.router)
        with patch.dict("os.environ", {
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "1",
            "VISUAL_REPORT_SIGNING_SECRET": "shared-secret",
        }), patch.object(router.store, "get_job", return_value=job), patch.object(
            router.service, "resolve_job_media_url", return_value="http://workbench/media-item/source"
        ), patch.object(router.httpx, "AsyncClient", Client):
            signed_url = service.signed_job_media_url(job["tenant_id"], job["job_id"], media_id)
            client = TestClient(app)
            unsigned = client.get(urlsplit(signed_url).path)
            response = client.get(signed_url)
            tampered = client.get(signed_url.replace(media_id, "d" * 32))

        self.assertEqual(unsigned.status_code, 401)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"image")
        self.assertEqual(tampered.status_code, 403)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_formal_report_hides_internal_inference_costs(self):
        job = {
            "job_id": "RV-NO-INTERNAL-METRICS",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {
                    "scenario_label": "未成年人资料审核",
                    "parsed": {"predicted_label": "review"},
                    "inference_estimate": {"total_tokens": 987654, "estimated_usd": 12.34},
                },
            }},
        }

        html = service.render_job_report(job)

        self.assertNotIn("987654", html)
        self.assertNotIn("12.34", html)

    def test_job_media_resolution_is_limited_to_media_referenced_by_that_job(self):
        media_id = "b" * 32
        job = {
            "result": {"review": {"agent_report": {"media_gallery": {
                "frames": [{"url": f"/media-item/{media_id}?expires=99&sig=old"}],
            }}}},
        }

        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "shared-secret"}):
            resolved = service.resolve_job_media_url(job, media_id)

        self.assertTrue(resolved.startswith("http://127.0.0.1:"))
        self.assertIn(f"/media-item/{media_id}", resolved)
        with self.assertRaises(ValueError):
            service.resolve_job_media_url(job, "c" * 32)

    def test_report_explains_internal_processing_retry_without_asking_customer_for_material(self):
        job = {
            "job_id": "RV-SYSTEM-RETRY",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "result": {"review": {
                "summary": {"review_status": "completed"},
                "agent_report": {"scenario_label": "未成年人资料审核", "parsed": {}},
                "advisory_assessment": {
                    "workflow_recommendation": "system_retry",
                    "assessment": {"conclusion": "本轮技术处理未完成"},
                    "human_review": {"level": "not_required"},
                    "signals": [{
                        "code": "technical_processing_incomplete",
                        "effect": "当前请求已完成逐张恢复；仍未覆盖时可受控重跑整案，可能重复模型成本。",
                    }],
                },
            }},
        }

        html = service.render_job_report(job)

        self.assertIn("受控重跑整案", html)
        self.assertIn("可能重复模型成本", html)
        self.assertIn("技术处理未完成", html)

    def test_workbench_json_only_does_not_write_html_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_dir = root / "case"
            sample_dir.mkdir()
            case = {
                "case_id": "CASE-JSON-ONLY",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
                "structured_business_context": {
                    "business_scenario": "product_damage",
                    "review_routing_policy": {"policy_ref": "MITAKO-ROUTING@20260815.1"},
                },
            }
            result = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "confidence": 0.91,
                    "overall_audit": {"conclusion": "当前证据支持商品存在可见损伤。"},
                },
            }
            with patch.object(workbench_server, "PUBLIC_SUMMARY_DIR", root / "summaries"), patch.object(
                workbench_server, "score_result", return_value={}
            ):
                before = set(workbench_server.ALLOWED_REPORTS)
                response = workbench_server._agent_report_response(
                    case,
                    sample_dir,
                    result,
                    "json_only",
                    include_html_report=False,
                )

            self.assertEqual(response["report"]["status"], "not_requested")
            self.assertIsNone(response["report"]["html_url"])
            self.assertEqual(set(workbench_server.ALLOWED_REPORTS), before)
            self.assertFalse((root / "summaries").exists())
            self.assertEqual(response["advisory_assessment"]["human_review"]["level"], "not_required")

    def test_formal_job_json_only_keeps_structured_result_without_report_url(self):
        job = {
            "job_id": "RV-JSON-ONLY",
            "tenant_id": "mitako",
            "client_case_id": "CASE-JSON-ONLY",
            "scenario": "product_damage",
            "metadata": {
                "scenario": "product_damage",
                "output_options": {"include_html_report": False},
                "review_routing_policy": {},
            },
            "assets": [],
        }

        def finish(job_id, *, status, result, diagnostics, expected_attempts=None):
            return {**job, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service.store, "finish_job", side_effect=finish), patch.object(
            service, "_media_forensics", return_value={"summary": {"risk_signal_count": 0}}
        ), patch.object(
            service, "assess_input_readiness", return_value={"full_review_ready": True, "missing_required": []}
        ), patch.object(service, "_call_workbench", return_value=successful_workbench_review()):
            completed = service.run_job(job["job_id"])

        review = completed["result"]["review"]
        self.assertEqual(review["report"]["status"], "not_requested")
        self.assertIsNone(review["report"]["html_url"])
        self.assertEqual(review["advisory_assessment"]["workflow_recommendation"], "request_more_material")
        self.assertEqual(review["advisory_assessment"]["human_review"]["level"], "not_required")

    def test_public_job_drops_nested_review_diagnostics(self):
        job = {
            "job_id": "RV-PUBLIC-PROJECTION",
            "client_case_id": "CASE-PUBLIC-PROJECTION",
            "scenario": "product_damage",
            "status": "SUCCEEDED",
            "assets": [],
            "attempts": 1,
            "created_at": 1,
            "started_at": 2,
            "completed_at": 3,
            "updated_at": 3,
            "result": {
                "review": {
                    "review_label": "positive",
                    "sampling": {"strategy": "native_video"},
                    "media_preflight_execution": {"status": "completed"},
                    "diagnostics": {"provider": "internal-provider"},
                    "unexpected_internal": "secret",
                }
            },
        }

        public = service.public_job(job)

        self.assertEqual(public["result"]["review"]["sampling"], {"strategy": "native_video"})
        self.assertEqual(
            public["result"]["review"]["media_preflight_execution"],
            {"status": "completed"},
        )
        self.assertNotIn("diagnostics", public["result"]["review"])
        self.assertNotIn("unexpected_internal", public["result"]["review"])

    def test_public_job_strips_private_fields_and_local_paths_inside_allowed_sections(self):
        private_path = r"D:\private\review_jobs\case-1\frame.jpg"
        job = {
            "job_id": "RV-NESTED-PUBLIC-PROJECTION",
            "client_case_id": "CASE-NESTED-PUBLIC-PROJECTION",
            "scenario": "product_damage",
            "status": "SUCCEEDED",
            "assets": [],
            "attempts": 1,
            "created_at": 1,
            "started_at": 2,
            "completed_at": 3,
            "updated_at": 3,
            "result": {
                "review": {
                    "agent_report": {
                        "case_id": "CASE-NESTED-PUBLIC-PROJECTION",
                        "public_brief": {"conclusion": "evidence requires review"},
                        "diagnostics": {"provider": "internal-provider"},
                        "system_prompt": "private system prompt",
                        "parsed": {
                            "decision": "manual_review",
                            "source_record": {"phone": "13800138000"},
                            "debug": {"local_path": private_path},
                            "message": f"failed to read {private_path}",
                            "supporting_evidence": [{"fact": f"证据来源={private_path}"}],
                        },
                    },
                    "media_forensics": {
                        "assets": [{"asset_id": "RA-PUBLIC", "file": private_path}],
                    },
                },
            },
        }

        public = service.public_job(job)
        serialized = str(public)

        self.assertEqual(
            public["result"]["review"]["agent_report"]["public_brief"]["conclusion"],
            "evidence requires review",
        )
        for secret in (
            "diagnostics", "internal-provider", "system_prompt", "private system prompt",
            "source_record", "13800138000", "local_path", private_path,
        ):
            self.assertNotIn(secret, serialized)

    def test_public_job_redacts_shipping_tracking_number_from_model_text(self):
        job = {
            "job_id": "RV-PUBLIC-SHIPPING-ID",
            "client_case_id": "CASE-PUBLIC-SHIPPING-ID",
            "scenario": "product_damage",
            "status": "SUCCEEDED",
            "assets": [],
            "result": {
                "review": {
                    "agent_report": {
                        "parsed": {
                            "supporting_evidence": [{
                                "fact": "运单号：JT0023964811882，面单清晰可见",
                            }],
                        },
                    },
                },
            },
        }

        serialized = str(service.public_job(job))
        self.assertNotIn("JT0023964811882", serialized)
        self.assertIn("[已脱敏]", serialized)

    def test_public_json_and_html_share_sensitive_text_redaction(self):
        sensitive_values = (
            "张三",
            "李晓明",
            "李四",
            "北京市朝阳区幸福路1号",
            "上海市浦东新区世纪大道88号",
            "13800138000",
            "Alice.Service+vip@example.com",
            "6222020202020202020",
            "pay_account_9988",
            "wx_demo_20260812",
            "JT0023964811882",
        )
        sensitive_fact = (
            "张三本人提交，住在北京市朝阳区幸福路1号；"
            "材料由李晓明提交，客户称收货地点为上海市浦东新区世纪大道88号，联系人李四；"
            "手机号：13800138000；邮箱：Alice.Service+vip@example.com；"
            "银行卡号：6222020202020202020；支付账号：pay_account_9988；"
            "微信号：wx_demo_20260812；运单号：JT0023964811882。"
        )
        job = {
            "job_id": "RV-PUBLIC-REDACTION-PARITY",
            "tenant_id": "mitako",
            "client_case_id": "CASE-PUBLIC-REDACTION-PARITY",
            "scenario": "product_damage",
            "status": "SUCCEEDED",
            "completed_at": 1,
            "metadata": {"output_options": {"include_html_report": True}},
            "assets": [],
            "result": {
                "review": {
                    "summary": {"predicted_label": "review", "confidence": 0.8},
                    "agent_brief": {"conclusion": sensitive_fact},
                    "agent_report": {
                        "scenario": "product_damage",
                        "scenario_label": "商品有伤审核",
                        "public_brief": {"conclusion": sensitive_fact},
                        "parsed": {
                            "predicted_label": "review",
                            "confidence": 0.8,
                            "overall_audit": {"conclusion": sensitive_fact},
                            "supporting_evidence": [{"fact": sensitive_fact}],
                        },
                    },
                },
            },
        }

        public_json = str(service.public_job(job))
        report_html = service.render_job_report(job)

        for secret in sensitive_values:
            self.assertNotIn(secret, public_json)
            self.assertNotIn(secret, report_html)
        self.assertIn("[已脱敏]", public_json)
        self.assertIn("[已脱敏]", report_html)

    def test_formal_deferred_postprocess_replaces_stale_next_step_with_final_advisory(self):
        stale_next_step = "必须进入VIP人工复核。"
        job = {
            "job_id": "RV-FINAL-NEXT-STEP",
            "tenant_id": "mitako",
            "client_case_id": "CASE-FINAL-NEXT-STEP",
            "scenario": "video_unboxing",
            "metadata": {
                "scenario": "video_unboxing",
                "output_options": {"include_html_report": True},
            },
            "assets": [],
        }
        upstream = successful_workbench_review()
        upstream["review"]["agent_brief"]["next_step"] = stale_next_step
        upstream["review"]["agent_report"]["scenario"] = "video_unboxing"
        upstream["review"]["agent_report"]["scenario_label"] = "开箱审核"
        upstream["review"]["agent_report"]["public_brief"] = {
            "conclusion": "旧结论",
            "next_step": stale_next_step,
        }
        upstream["review"]["agent_report"]["parsed"]["next_step"] = stale_next_step

        def finish(job_id, *, status, result, diagnostics, expected_attempts=None):
            return {**job, "status": status, "completed_at": 1, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service.store, "finish_job", side_effect=finish), patch.object(
            service, "_media_forensics", return_value={"summary": {"risk_signal_count": 0}}
        ), patch.object(
            service, "assess_input_readiness", return_value={"full_review_ready": True, "missing_required": []}
        ), patch.object(service, "_call_workbench", return_value=upstream):
            completed = service.run_job(job["job_id"])

        review = completed["result"]["review"]
        recommendation = review["advisory_assessment"]["human_review"]["recommendation"]
        self.assertEqual(review["advisory_assessment"]["human_review"]["level"], "not_required")
        self.assertEqual(review["advisory_assessment"]["workflow_recommendation"], "continue_by_customer_policy")
        self.assertEqual(recommendation, "")
        self.assertNotIn("next_step", review["agent_brief"])
        self.assertNotIn("next_step", review["agent_report"]["public_brief"])
        self.assertNotIn("next_step", review["agent_report"]["parsed"])
        report_html = service.render_job_report(completed)
        self.assertNotIn("建议下一步", report_html)
        self.assertNotIn(stale_next_step, report_html)

    def test_final_sync_removes_stale_minor_noop_next_step(self):
        review = {
            "material_readiness": {"scenario": "minor_refund", "status": "complete"},
            "advisory_assessment": {
                "scenario": "minor_refund",
                "assessment": {"conclusion": "五类材料的事实审核已完成。"},
                "human_review": {"level": "not_required", "recommendation": ""},
                "workflow_recommendation": "continue_by_customer_policy",
            },
            "agent_brief": {"next_step": "旧逻辑要求进入人工审核。"},
            "agent_report": {
                "parsed": {"next_step": "旧逻辑要求进入人工审核。"},
                "public_brief": {"next_step": "旧逻辑要求进入人工审核。"},
            },
        }

        synced = service._sync_final_advisory_brief(review)

        self.assertNotIn("next_step", synced["agent_brief"])
        self.assertNotIn("next_step", synced["agent_report"]["parsed"])
        self.assertNotIn("next_step", synced["agent_report"]["public_brief"])

    def test_report_route_rejects_job_that_did_not_request_html(self):
        job = {
            "job_id": "RV-JSON-ONLY",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "metadata": {"output_options": {"include_html_report": False}},
            "result": {},
        }
        with patch.object(router.store, "get_job", return_value=job):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(router.job_report(job["job_id"], user={"tenant_id": "mitako"}))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "review_report_not_requested")

    def test_report_route_rejects_job_that_is_not_ready(self):
        job = {
            "job_id": "RV-PENDING",
            "tenant_id": "mitako",
            "status": "RUNNING",
            "metadata": {"output_options": {"include_html_report": True}},
            "result": {},
        }
        with patch.object(router.store, "get_job", return_value=job):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(router.job_report(job["job_id"], user={"tenant_id": "mitako"}))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "review_report_not_ready")

    def test_report_route_sets_private_no_store_security_headers(self):
        job = {
            "job_id": "RV-SECURE-REPORT-HEADERS",
            "tenant_id": "mitako",
            "status": "SUCCEEDED",
            "metadata": {"output_options": {"include_html_report": True}},
            "result": {},
        }
        with patch.object(router.store, "get_job", return_value=job), patch.object(
            router.service, "render_job_report", return_value="<html></html>"
        ):
            response = asyncio.run(router.job_report(job["job_id"], user={"tenant_id": "mitako"}))

        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_formal_job_failure_still_returns_primary_advisory_contract(self):
        job = {
            "job_id": "RV-FAILED-CONTRACT",
            "tenant_id": "mitako",
            "client_case_id": "CASE-FAILED-CONTRACT",
            "scenario": "product_damage",
            "metadata": {
                "scenario": "product_damage",
                "output_options": {"include_html_report": True},
            },
            "assets": [],
        }

        def finish(job_id, *, status, result, diagnostics, expected_attempts=None):
            return {**job, "status": status, "result": result, "diagnostics": diagnostics}

        with patch.object(service.store, "claim_job", return_value=True), patch.object(
            service.store, "get_job", return_value=job
        ), patch.object(service.store, "finish_job", side_effect=finish), patch.object(
            service, "_media_forensics", return_value={"summary": {"risk_signal_count": 0}}
        ), patch.object(service, "_call_workbench", side_effect=RuntimeError("upstream unavailable")):
            completed = service.run_job(job["job_id"])

        review = completed["result"]["review"]
        self.assertEqual(review["advisory_assessment"]["human_review"]["level"], "required")
        self.assertEqual(review["advisory_assessment"]["workflow_recommendation"], "human_review")
        self.assertEqual(review["report"]["status"], "unavailable")
        self.assertIsNone(review["report"]["html_url"])


if __name__ == "__main__":
    unittest.main()
