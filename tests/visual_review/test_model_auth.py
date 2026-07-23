# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from unittest.mock import patch


class ModelAuthTest(unittest.TestCase):
    def test_baidu_endpoint_uses_bearer_and_full_url_is_not_duplicated(self):
        from poc.visual_review_poc.model_auth import gemini_auth_headers, gemini_generate_endpoint

        endpoint = gemini_generate_endpoint(
            "https://vod.bj.baidubce.com/v3/chat/gc",
            "gemini-3.5-flash",
        )
        self.assertEqual(
            endpoint,
            "https://vod.bj.baidubce.com/v3/chat/gc/v1beta/models/gemini-3.5-flash:generateContent",
        )
        self.assertEqual(
            gemini_auth_headers(endpoint, "secret-value"),
            {"Authorization": "Bearer secret-value", "Content-Type": "application/json"},
        )
        self.assertEqual(gemini_generate_endpoint(endpoint, "ignored"), endpoint)

    def test_google_endpoint_uses_native_header_and_template(self):
        from poc.visual_review_poc.model_auth import gemini_auth_headers, gemini_generate_endpoint

        endpoint = gemini_generate_endpoint(
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "gemini-3.5-flash",
        )
        self.assertIn("gemini-3.5-flash:generateContent", endpoint)
        self.assertEqual(
            gemini_auth_headers(endpoint, "secret-value"),
            {"x-goog-api-key": "secret-value", "Content-Type": "application/json"},
        )

    def test_actual_review_channels_use_shared_auth_rules(self):
        from poc.visual_review_poc.local_video_triage_demo import gemini_channels
        from poc.visual_review_poc.model_selection_e2e import gemini_request_options

        env = {
            "VISION_REVIEW_API_KEY": "gateway-secret",
            "VISION_REVIEW_GEMINI_BASE_URL": "https://vod.bj.baidubce.com/v3/chat/gc",
            "VISION_REVIEW_GEMINI_AUTH_MODE": "auto",
        }
        with patch.dict("os.environ", env, clear=True):
            channel = gemini_channels()[0]
            option = gemini_request_options({"model": "gemini-3.5-flash"})[0]

        self.assertEqual(channel["headers"]["Authorization"], "Bearer gateway-secret")
        self.assertNotIn("x-goog-api-key", channel["headers"])
        self.assertEqual(option["headers"]["Authorization"], "Bearer gateway-secret")
        self.assertTrue(option["endpoint"].endswith("/v1beta/models/gemini-3.5-flash:generateContent"))

    def test_unknown_auth_mode_is_rejected_instead_of_silent_fallback(self):
        from poc.visual_review_poc.model_auth import gemini_auth_headers

        with self.assertRaises(ValueError):
            gemini_auth_headers("https://example.com/v1/models/demo:generateContent", "secret", "bearr")


if __name__ == "__main__":
    unittest.main()
