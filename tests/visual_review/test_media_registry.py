# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from poc.visual_review_poc.media_registry import MediaRegistry


class MediaRegistryTest(unittest.TestCase):
    def test_multiple_instances_do_not_lose_concurrent_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "media.sqlite3"
            first = MediaRegistry(database, root)
            second = MediaRegistry(database, root)
            entries = [
                (f"{index:032x}", f"media/{index}.webp")
                for index in range(80)
            ]
            for _, relative_path in entries:
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"webp")

            def register(entry: tuple[str, str]) -> None:
                media_id, relative_path = entry
                registry = first if int(media_id, 16) % 2 == 0 else second
                registry.register(media_id, relative_path)

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(register, entries))

            reopened = MediaRegistry(database, root)
            self.assertEqual(
                {media_id: reopened.get(media_id) for media_id, _ in entries},
                dict(entries),
            )

    def test_prune_removes_expired_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = MediaRegistry(root / "media.sqlite3", root)
            valid = root / "media" / "valid.webp"
            expired = root / "media" / "expired.webp"
            valid.parent.mkdir(parents=True)
            valid.write_bytes(b"valid")
            expired.write_bytes(b"expired")

            registry.register("1" * 32, "media/valid.webp", expires_at=300)
            registry.register("2" * 32, "media/expired.webp", expires_at=100)
            registry.register("3" * 32, "media/missing.webp", expires_at=300)

            self.assertEqual(registry.prune(now=200), 2)
            self.assertEqual(registry.get("1" * 32, now=200), "media/valid.webp")
            self.assertIsNone(registry.get("2" * 32, now=200))
            self.assertIsNone(registry.get("3" * 32, now=200))

    def test_invalid_ids_and_unsafe_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = MediaRegistry(root / "media.sqlite3", root)

            self.assertIsNone(registry.get("../../secret"))
            self.assertIsNone(registry.get("g" * 32))
            with self.assertRaises(ValueError):
                registry.register("short", "media/evidence.webp")
            with self.assertRaises(ValueError):
                registry.register("4" * 32, "../secret.webp")
            with self.assertRaises(ValueError):
                registry.register("5" * 32, str((root / "secret.webp").resolve()))


if __name__ == "__main__":
    unittest.main()
