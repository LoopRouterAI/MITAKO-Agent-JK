# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.jwt_utils import create_token
from auth.roles import Role
from review_service.router import router


class ReviewOpenApiContractTest(unittest.TestCase):
    def test_review_api_rejects_empty_tenant_claim(self):
        isolated_app = FastAPI()
        isolated_app.include_router(router)
        token = create_token(sub="legacy-supervisor", role=Role.SUPERVISOR.value, tenant_id="")

        with patch("auth.middleware.protected_api_auth_required", return_value=True):
            response = TestClient(isolated_app).get(
                "/api/v1/review/contracts",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "tenant_claim_required")

    def test_review_jobs_declares_bearer_auth_and_business_errors(self):
        app = FastAPI()
        app.include_router(router)
        schema = app.openapi()
        operation = schema["paths"]["/api/v1/review/jobs"]["post"]

        schemes = schema["components"]["securitySchemes"]
        self.assertTrue(any(value.get("scheme") == "bearer" for value in schemes.values()))
        self.assertTrue(operation["security"])
        self.assertTrue({"400", "409", "413", "415", "422"}.issubset(operation["responses"]))


if __name__ == "__main__":
    unittest.main()
