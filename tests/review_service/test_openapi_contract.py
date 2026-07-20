# -*- coding: utf-8 -*-
import unittest

from fastapi import FastAPI

from review_service.router import router


class ReviewOpenApiContractTest(unittest.TestCase):
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
