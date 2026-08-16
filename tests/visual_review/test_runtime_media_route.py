# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from poc.visual_review_poc import workbench_server


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class RuntimeMediaRouteTest(unittest.TestCase):
    def test_standalone_workbench_loads_runtime_env_before_security_constants(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "VISUAL_REPORT_SIGNING_SECRET=test-only-signing-secret\n"
                "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET=1\n",
                encoding="utf-8",
            )
            process_env = dict(os.environ)
            process_env.pop("VISUAL_REPORT_SIGNING_SECRET", None)
            process_env.pop("VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET", None)
            process_env["MITAKO_ENV_FILE"] = str(env_file)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json; "
                        "from poc.visual_review_poc import workbench_server as w; "
                        "print(json.dumps([w.REPORT_SIGNING_SECRET_CONFIGURED, "
                        "w.REQUIRE_PERSISTENT_REPORT_SIGNING_SECRET]))"
                    ),
                ],
                cwd=workbench_server.PROJECT_ROOT,
                env=process_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            self.assertEqual(json.loads(completed.stdout.strip()), [True, True])

    def test_generated_frame_is_available_after_report_reload(self):
        workbench_server.RUNTIME_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workbench_server.RUNTIME_MEDIA_DIR) as temp_dir:
            frame = Path(temp_dir) / "frame.png"
            frame.write_bytes(PNG_1X1)
            response = TestClient(workbench_server.app).get(
                workbench_server._media_url(frame)
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, PNG_1X1)

    def test_legacy_media_route_is_disabled(self):
        response = TestClient(workbench_server.app).get(
            workbench_server._sign_public_url("/media/.env")
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
