# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from auth.jwt_utils import production_secret_ok
from main import app


def test_production_secret_rejects_short_and_public_startup_defaults(monkeypatch) -> None:
    for secret in ("x", "mitako-local-poc-secret-change-before-production"):
        monkeypatch.setenv("MITAKO_JWT_SECRET", secret)
        assert production_secret_ok() is False


def test_production_secret_accepts_random_secret_with_at_least_32_characters(monkeypatch) -> None:
    monkeypatch.setenv("MITAKO_JWT_SECRET", "a-random-runtime-secret-with-32-plus-characters")
    assert production_secret_ok() is True


def test_image_generation_rejects_anonymous_requests_before_provider_call() -> None:
    with patch("auth.middleware.protected_api_auth_required", return_value=True), patch(
        "main.generate_image", new_callable=AsyncMock
    ) as generate_image:
        response = TestClient(app).post(
            "/api/v1/images/generate",
            json={"prompt": "test", "model_id": "standard-image", "size": "2752x1536", "n": 1},
        )

    assert response.status_code == 401
    generate_image.assert_not_awaited()
