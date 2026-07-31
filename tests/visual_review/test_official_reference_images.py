# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import httpx
import numpy as np
from PIL import Image

from poc.visual_review_poc.official_reference_images import (
    collect_official_image_references,
    official_reference_cache_dir,
    prepare_official_reference_images,
)


def png_bytes() -> bytes:
    image = np.full((12, 16, 3), 180, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("test_png_encode_failed")
    return encoded.tobytes()


def case_with_urls(*urls: str) -> dict:
    return {
        "structured_business_context": {
            "fulfillment_baseline": {
                "expected_items": [{
                    "item_ref": "ORDER-LINE-001",
                    "sku": "SKU-001",
                    "product_name": "测试商品",
                    "expected_quantity": 1,
                    "master_image_urls": list(urls),
                }],
            },
            "product_master_data": {
                "ORDER-LINE-001": {
                    "sku": "SKU-001",
                    "master_image_urls": list(urls),
                },
            },
        },
    }


class OfficialReferenceImagesTest(unittest.TestCase):
    def _public_dns(self):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def test_cache_path_follows_runtime_data_dir_and_allows_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict("os.environ", {"MITAKO_DATA_DIR": str(root / "data"), "REVIEW_PRODUCT_IMAGE_CACHE_DIR": ""}):
                self.assertEqual(official_reference_cache_dir(), (root / "data" / "visual_review_product_refs").resolve())
            with patch.dict("os.environ", {"REVIEW_PRODUCT_IMAGE_CACHE_DIR": str(root / "cache")}):
                self.assertEqual(official_reference_cache_dir(), (root / "cache").resolve())

    def test_fetches_only_deduplicated_current_order_images_and_reuses_cache(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png_bytes())

        case = case_with_urls(
            "https://cdn-qiniu.danhaotuan.com/a.png",
            "https://cdn-qiniu.danhaotuan.com/a.png",
            "https://cdn-qiniu.danhaotuan.com/b.png",
        )
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch(
            "poc.visual_review_poc.official_reference_images.socket.getaddrinfo",
            return_value=self._public_dns(),
        ):
            first = prepare_official_reference_images(copy.deepcopy(case), Path(directory), client=client, limit=1)
            second = prepare_official_reference_images(copy.deepcopy(case), Path(directory), client=client, limit=1)

        self.assertEqual(calls, 1)
        self.assertEqual(len(first["official_reference_images"]), 1)
        self.assertFalse(first["official_reference_images"][0]["cache_hit"])
        self.assertTrue(second["official_reference_images"][0]["cache_hit"])
        self.assertEqual(first["official_reference_status"]["requested_count"], 1)
        self.assertEqual(first["official_reference_status"]["available_count"], 1)
        self.assertEqual(first["official_reference_images"][0]["evidence_role"], "official_product_reference")

    def test_rejects_unsafe_or_invalid_resources_without_failing_the_case(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("redirect.png"):
                return httpx.Response(302, headers={"location": "https://evil.example/x.png"})
            if request.url.path.endswith("fake.png"):
                return httpx.Response(200, headers={"content-type": "image/png"}, content=b"not-an-image")
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png_bytes())

        case = case_with_urls(
            "http://cdn-qiniu.danhaotuan.com/plain.png",
            "https://127.0.0.1/private.png",
            "https://evil.example/not-allowed.png",
            "https://cdn-qiniu.danhaotuan.com/redirect.png",
            "https://cdn-qiniu.danhaotuan.com/fake.png",
            "https://cdn-qiniu.danhaotuan.com/ok.png",
        )
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch(
            "poc.visual_review_poc.official_reference_images.socket.getaddrinfo",
            return_value=self._public_dns(),
        ):
            result = prepare_official_reference_images(case, Path(directory), client=client, limit=8)

        reasons = {item["reason"] for item in result["official_reference_status"]["failures"]}
        self.assertEqual(result["official_reference_status"]["available_count"], 1)
        self.assertIn("https_required", reasons)
        self.assertIn("host_not_allowed", reasons)
        self.assertIn("redirect_not_allowed", reasons)
        self.assertIn("invalid_image_content", reasons)

    def test_oversized_response_is_stopped_and_reported(self) -> None:
        body = b"\x89PNG\r\n\x1a\n" + b"x" * 2048

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

        case = case_with_urls("https://cdn-qiniu.danhaotuan.com/large.png")
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch(
            "poc.visual_review_poc.official_reference_images.socket.getaddrinfo",
            return_value=self._public_dns(),
        ), patch.dict("os.environ", {"REVIEW_PRODUCT_IMAGE_MAX_BYTES": "1024"}):
            result = prepare_official_reference_images(case, Path(directory), client=client)

        self.assertEqual(result["official_reference_images"], [])
        self.assertEqual(result["official_reference_status"]["failures"][0]["reason"], "response_too_large")

    def test_claimed_item_is_prioritized_and_shared_url_keeps_all_item_relations(self) -> None:
        shared = "https://cdn-qiniu.danhaotuan.com/shared.png"
        case = {
            "structured_business_context": {
                "claim_scope": {"item_refs": ["LINE-2"]},
                "fulfillment_baseline": {"expected_items": [
                    {"item_ref": "LINE-1", "sku": "SKU-1", "master_image_urls": [shared]},
                    {"item_ref": "LINE-2", "sku": "SKU-2", "master_image_urls": [shared]},
                    {"item_ref": "LINE-3", "sku": "SKU-3", "master_image_urls": ["https://cdn-qiniu.danhaotuan.com/other.png"]},
                ]},
            },
        }
        references = collect_official_image_references(case)
        self.assertEqual(references[0]["url"], shared)
        self.assertEqual(references[0]["item_refs"], ["LINE-1", "LINE-2"])

    def test_claim_identity_change_reselects_the_matching_reference(self) -> None:
        case = {
            "structured_business_context": {
                "fulfillment_baseline": {"expected_items": [
                    {
                        "item_ref": "LINE-1",
                        "sku": "SKU-1",
                        "master_image_urls": ["https://cdn-qiniu.danhaotuan.com/first.png"],
                    },
                    {
                        "item_ref": "LINE-2",
                        "sku": "SKU-2",
                        "master_image_urls": ["https://cdn-qiniu.danhaotuan.com/claimed.png"],
                    },
                ]},
            },
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png_bytes())

        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch(
            "poc.visual_review_poc.official_reference_images.socket.getaddrinfo",
            return_value=self._public_dns(),
        ):
            prepare_official_reference_images(case, Path(directory), client=client, limit=1)
            self.assertEqual(case["official_reference_images"][0]["item_ref"], "LINE-1")
            case["structured_business_context"]["continuity_claim_identity"] = {
                "item_ref": "LINE-2",
                "sku": "SKU-2",
            }
            prepare_official_reference_images(case, Path(directory), client=client, limit=1)

        self.assertEqual(case["official_reference_images"][0]["item_ref"], "LINE-2")

    def test_image_pixel_limit_falls_back_without_decoding_unbounded_image(self) -> None:
        payload = io.BytesIO()
        Image.new("RGB", (1100, 1100), "white").save(payload, format="PNG")
        body = payload.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

        case = case_with_urls("https://cdn-qiniu.danhaotuan.com/pixels.png")
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(handler)) as client, patch(
            "poc.visual_review_poc.official_reference_images.socket.getaddrinfo",
            return_value=self._public_dns(),
        ), patch.dict("os.environ", {"REVIEW_PRODUCT_IMAGE_MAX_PIXELS": "1000000"}):
            result = prepare_official_reference_images(case, Path(directory), client=client)

        self.assertEqual(result["official_reference_images"], [])
        self.assertEqual(result["official_reference_status"]["failures"][0]["reason"], "image_pixel_limit")


if __name__ == "__main__":
    unittest.main()
