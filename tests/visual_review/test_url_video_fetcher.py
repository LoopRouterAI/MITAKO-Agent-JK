# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from poc.visual_review_poc import url_video_fetcher


class UrlVideoFetcherTest(unittest.TestCase):
    def test_direct_video_redirect_to_private_host_is_blocked_before_following(self) -> None:
        headers = Message()
        headers["Location"] = "https://127.0.0.1/private.mp4"
        redirect = HTTPError(
            "https://cdn.example.com/public.mp4",
            302,
            "Found",
            headers,
            None,
        )

        with patch.object(url_video_fetcher._DIRECT_URL_OPENER, "open", side_effect=redirect) as opener:
            with self.assertRaisesRegex(ValueError, "内网"):
                url_video_fetcher._open_public_direct_url(
                    "https://cdn.example.com/public.mp4",
                    method="GET",
                    timeout=5,
                )

        opener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
