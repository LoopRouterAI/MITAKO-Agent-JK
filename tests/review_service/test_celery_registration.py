# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
import asyncio
import importlib
from pathlib import Path
from unittest.mock import patch

import yaml


class CeleryRegistrationTest(unittest.TestCase):
    def test_sla_task_module_is_registered_for_worker_import(self):
        from sla_worker.celery_app import celery_app

        self.assertIn("sla_worker.tasks", tuple(celery_app.conf.imports or ()))

    def test_compose_disables_main_process_inline_sla_scheduler(self):
        root = Path(__file__).resolve().parents[2]
        compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))

        self.assertEqual(compose["services"]["main"]["environment"]["SLA_WORKER_MODE"], "celery")

    def test_review_router_starts_periodic_expired_lease_recovery(self):
        router_module = importlib.import_module("review_service.router")
        router_module._RECOVERY_TASK = None
        with patch.object(router_module.store, "init_db"), patch.object(
            router_module.service, "recover_jobs"
        ) as recover, patch.object(router_module.asyncio, "create_task") as create_task:
            asyncio.run(router_module.startup())

        recover.assert_called_once_with()
        create_task.assert_called_once()
        create_task.call_args.args[0].close()
        router_module._RECOVERY_TASK = None


if __name__ == "__main__":
    unittest.main()
