# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_mock_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "users": {
                    "iso_user": {
                        "user_id": "iso_user",
                        "nickname": "覆盖用户",
                        "member_level": "gold",
                        "member_label": "覆盖会员",
                        "total_spent": 1,
                        "favorite_ips": [],
                        "communication_preferences": {},
                    }
                },
                "orders": {
                    "ORD_2024_001": {
                        "order_id": "ORD_2024_001",
                        "user_id": "iso_user",
                        "status": "delivered",
                        "items": [{"name": "覆盖订单A", "quantity": 1, "price": 1}],
                        "total_amount": 1,
                    },
                    "ORD_2025_012": {
                        "order_id": "ORD_2025_012",
                        "user_id": "iso_user",
                        "status": "delivered",
                        "items": [{"name": "覆盖订单B", "quantity": 1, "price": 1}],
                        "total_amount": 1,
                    },
                    "ORD_2025_044": {
                        "order_id": "ORD_2025_044",
                        "user_id": "iso_user",
                        "status": "delivered",
                        "items": [{"name": "覆盖订单C", "quantity": 1, "price": 1}],
                        "total_amount": 1,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    data_dir = Path(os.environ["MITAKO_DATA_DIR"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    from runtime_paths import mock_data_file, viking_memory_dir

    if "MITAKO_MOCK_DATA_FILE" not in os.environ:
        assert mock_data_file() == ROOT / "mock_data.json", mock_data_file()
        os.environ["MITAKO_MOCK_DATA_FILE"] = str(data_dir / "mock_data.override.json")
    if "MITAKO_VIKING_MEMORY_DIR" not in os.environ:
        assert viking_memory_dir() == data_dir / "viking_memory", viking_memory_dir()
        os.environ["MITAKO_VIKING_MEMORY_DIR"] = str(data_dir / "explicit_viking_memory")

    mock_override = Path(os.environ["MITAKO_MOCK_DATA_FILE"]).resolve()
    viking_override = Path(os.environ["MITAKO_VIKING_MEMORY_DIR"]).resolve()
    assert data_dir in mock_override.parents, f"mock override must stay under MITAKO_DATA_DIR: {mock_override}"
    assert data_dir in viking_override.parents, f"viking override must stay under MITAKO_DATA_DIR: {viking_override}"
    _write_mock_fixture(mock_override)

    import admin_store
    import auth.store as auth_store
    import auth.tenants as tenants
    import handoff_store
    import mock_api
    from viking_memory import MockOpenViking

    auth_store.upsert_user("isolation_user", "pass", "desk_agent", tenant_id="iso")
    auth_store.upsert_user("isolation_user", "other-pass", "super_admin", tenant_id="iso_other")
    assert auth_store.verify_user("isolation_user", "pass", tenant_id="iso"), "auth db not writable"
    assert auth_store.verify_user("isolation_user", "other-pass", tenant_id="iso_other"), "auth tenant isolation failed"
    assert not auth_store.verify_user("isolation_user", "pass", tenant_id="iso_other"), "auth tenant leaked password"
    assert tenants.list_tenants(enabled_only=False), "tenant db not readable"
    assert admin_store.list_agents(enabled_only=False), "admin db not readable"
    handoff_store.ensure_chat_session("iso_session", "iso_user", "iso")

    expected = {"auth.db", "admin.db", "handoff.db"}
    found = {p.name for p in data_dir.glob("*.db")}
    missing = expected - found
    assert not missing, f"missing isolated db files: {sorted(missing)}"

    for module in (auth_store, tenants, admin_store, handoff_store):
        db_path = Path(module._DB_PATH).resolve()
        assert data_dir in db_path.parents, f"{module.__name__} writes outside MITAKO_DATA_DIR: {db_path}"

    assert mock_data_file() == mock_override, mock_data_file()
    assert viking_memory_dir() == viking_override, viking_memory_dir()
    assert Path(mock_api.DATA_FILE).resolve() == mock_override
    viking = MockOpenViking()
    assert Path(viking.base_dir).resolve() == viking_override
    assert viking.exists("viking://user/iso_user/profile"), "viking mock fixture not loaded"
    print(f"data isolation ok: {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
