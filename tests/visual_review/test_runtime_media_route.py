# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class RuntimeMediaRouteTest(unittest.TestCase):
    def test_generated_frame_is_available_after_report_reload(self):
        workbench_server.RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.RUNTIME_MEDIA_DIR) as temp_dir:
            frame = Path(temp_dir) / "frame.png"
            frame.write_bytes(PNG_1X1)
            relative = frame.relative_to(workbench_server.ROOT).as_posix()
            response = TestClient(workbench_server.app).get(f"/media/{relative}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, PNG_1X1)

    def test_media_route_does_not_expose_other_workspace_files(self):
        response = TestClient(workbench_server.app).get("/media/.env")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
