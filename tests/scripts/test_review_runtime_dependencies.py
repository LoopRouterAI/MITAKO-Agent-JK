from __future__ import annotations

import io
import json
import os
import sys
import unittest
from collections import namedtuple
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import check_review_runtime_dependencies as runtime_check


class ReviewRuntimeDependenciesTest(unittest.TestCase):
    def test_storage_headroom_uses_configured_media_runtime_directory(self) -> None:
        usage = namedtuple("usage", "total used free")
        checked_paths: list[Path] = []

        with TemporaryDirectory() as temp_dir:
            runtime_dir = (Path(temp_dir) / "media-runtime").resolve()

            def fake_disk_usage(path: str | os.PathLike[str]) -> object:
                checked_paths.append(Path(path).resolve())
                return usage(10_000, 1_000, 9_000)

            completed = type("Completed", (), {"returncode": 0, "stdout": "ffprobe test\n"})()
            output = io.StringIO()
            with (
                patch.dict(os.environ, {"VISUAL_RUNTIME_MEDIA_DIR": str(runtime_dir)}),
                patch.object(runtime_check, "resolve_ffprobe", return_value="ffprobe"),
                patch.object(runtime_check.subprocess, "run", return_value=completed),
                patch.object(runtime_check.shutil, "disk_usage", side_effect=fake_disk_usage),
                patch.object(sys, "argv", ["check_review_runtime_dependencies.py", "--minimum-free-mb", "0"]),
                redirect_stdout(output),
            ):
                exit_code = runtime_check.main()

        payload = json.loads(output.getvalue())
        storage = next(item for item in payload["checks"] if item["name"] == "storage_headroom")
        self.assertEqual(exit_code, 0)
        self.assertEqual(checked_paths, [runtime_dir])
        self.assertEqual(Path(storage["checked_path"]), runtime_dir)


if __name__ == "__main__":
    unittest.main()
