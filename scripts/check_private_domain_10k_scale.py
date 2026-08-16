# -*- coding: utf-8 -*-
"""使用临时 SQLite 验证单个商品事件可处理 1 万群。"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from private_domain import service, store


REPORT = ROOT / "tests" / "reports" / "private_domain_10k_scale_latest.json"
TEST_TENANT = "scale-test"


def main() -> int:
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="private-domain-10k-", dir=ROOT / "tmp") as workdir:
        store.DB_PATH = Path(workdir) / "private_domain.db"
        store.init_db()
        now = time.time()
        with store._connect() as conn:
            conn.executemany(
                """
                INSERT INTO private_groups(
                  tenant_id, group_id, group_name, owner_id, member_count, status, risk_level,
                  fatigue_score, health_score, marketing_disabled_until, tags, metrics, updated_at
                ) VALUES (?, ?, ?, '', 200, ?, ?, 0, 100, 0, ?, '{}', ?)
                """,
                [
                    (
                        TEST_TENANT,
                        f"scale-group-{index:05d}",
                        f"规模测试群 {index}",
                        "marketing_disabled" if index % 10 == 0 else "normal",
                        3 if index % 10 == 0 else 0,
                        json.dumps({"ip": ["蓝色监狱"]}, ensure_ascii=False),
                        now,
                    )
                    for index in range(10000)
                ],
            )
        started = time.perf_counter()
        result = service.process_product_event(
            {
                "event_id": "scale-event-10000",
                "event_type": "stock_arrived",
                "item_id": "scale-item",
                "ip_name": "蓝色监狱",
                "stock": 100,
            },
            tenant_id=TEST_TENANT,
        )
        elapsed = round(time.perf_counter() - started, 3)
        with store._connect() as conn:
            stored = int(conn.execute(
                "SELECT COUNT(*) FROM private_campaign_candidates WHERE tenant_id=? AND event_id=?",
                (TEST_TENANT, "scale-event-10000"),
            ).fetchone()[0])
        checks = {
            "all_groups_evaluated": len(result.get("candidates") or []) == 10000,
            "all_candidates_persisted": stored == 10000,
            "risk_groups_blocked": sum(1 for item in result.get("candidates") or [] if item.get("decision") == "blocked") == 1000,
            "local_processing_under_10s": elapsed < 10,
        }
    report = {"ok": all(checks.values()), "elapsed_seconds": elapsed, "checks": checks}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
