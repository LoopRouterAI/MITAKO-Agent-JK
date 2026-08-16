from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.run_openai_candidate_ab import _output_text, build_payload


class OpenAICandidateABTest(unittest.TestCase):
    def test_payload_uses_high_detail_images_and_strict_schema_without_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "candidate.jpg"
            image.write_bytes(b"jpeg-bytes")
            payload = build_payload(
                "gpt-5.6-terra",
                [image],
                [image],
                [image],
                [image],
            )

        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["reasoning"]["effort"], "high")
        self.assertNotIn("max_output_tokens", payload)
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(serialized.count("data:image/jpeg;base64,"), 4)
        self.assertNotIn(str(image), serialized)

    def test_output_text_reads_responses_message_content(self) -> None:
        data = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"preferred_candidate":"b"}'}],
                }
            ]
        }
        self.assertEqual(_output_text(data), '{"preferred_candidate":"b"}')


if __name__ == "__main__":
    unittest.main()
