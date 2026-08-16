# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from review_service import media_processing


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_review_derivative_is_persisted_before_model_call_and_reused(tmp_path, monkeypatch):
    source = tmp_path / "001_source.mp4"
    source.write_bytes(b"source-video")
    cached = tmp_path / "cached.webm"
    cached.write_bytes(b"review-video")
    calls = []

    monkeypatch.setattr(
        media_processing,
        "video_proxy_recommendation",
        lambda _path: {
            "recommended": True,
            "reasons": ["source_above_100mb"],
            "source_metadata": {"width": 3840, "height": 2160, "fps": 30, "bit_rate_bps": 8_000_000},
        },
    )

    def prepare(*_args, **_kwargs):
        calls.append(True)
        return {
            "status": "ready",
            "path": str(cached),
            "mime_type": "video/webm",
            "profile": "vp9_webm",
            "source_sha256": _sha256(source),
            "proxy_sha256": _sha256(cached),
            "source_width": 3840,
            "source_height": 2160,
            "proxy_width": 2560,
            "proxy_height": 1440,
            "proxy_fps": 24,
            "proxy_bitrate_bps": 5_500_000,
            "cache_hit": True,
        }

    monkeypatch.setattr(media_processing, "prepare_native_video_proxy", prepare)
    assets = [{
        "asset_id": "asset-1",
        "stored_name": source.name,
        "original_name": "original.mp4",
        "mime_type": "video/mp4",
        "size": source.stat().st_size,
        "sha256": _sha256(source),
    }]

    first = media_processing.prepare_job_review_media(tmp_path, assets, tmp_path / "cache")
    submitted = Path(first["files"]["asset-1"])
    assert submitted.name == "browser_preview_001.webm"
    assert submitted.read_bytes() == b"review-video"
    assert len(calls) == 1

    manifest = json.loads((tmp_path / "review_media_derivatives.json").read_text(encoding="utf-8"))
    record = manifest["videos"][0]
    assert record["source_sha256"] == _sha256(source)
    assert record["review_sha256"] == _sha256(submitted)
    assert record["model_input_kind"] == "review_derivative"
    assert record["validation_status"] == "ready"

    second = media_processing.prepare_job_review_media(tmp_path, assets, tmp_path / "cache")
    assert Path(second["files"]["asset-1"]) == submitted
    assert len(calls) == 1
