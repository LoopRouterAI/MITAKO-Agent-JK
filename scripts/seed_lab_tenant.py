# -*- coding: utf-8 -*-
"""写入联调实验室租户 OIDC 配置 — python scripts/seed_lab_tenant.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import auth.store as auth_store
import auth.tenants as tenant_store
from runtime_paths import db_path

LAB_ISSUER = "http://127.0.0.1:9101"
LAB_REDIRECT = "http://127.0.0.1:8000/admin?sso=1"
LAB_MAPPING = '{"desk_agent":["mitako-desk"],"super_admin":["mitako-admin"]}'


def main() -> None:
    import sqlite3

    auth_store.list_users()
    tenant_store.list_tenants(enabled_only=False)
    db = db_path("MITAKO_AUTH_DB_PATH", "auth.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        UPDATE tenants SET
            sso_enabled = 1,
            oidc_issuer = ?,
            oidc_client_id = 'mitako-lab',
            oidc_client_secret = 'lab-secret',
            oidc_redirect_uri = ?,
            oidc_scopes = 'openid profile email groups',
            oidc_token_url = ?,
            oidc_userinfo_url = ?,
            oidc_role_mapping_json = ?
        WHERE tenant_id = 'bpo-east'
        """,
        (
            LAB_ISSUER,
            LAB_REDIRECT,
            f"{LAB_ISSUER}/oauth/token",
            f"{LAB_ISSUER}/oauth/userinfo",
            LAB_MAPPING,
        ),
    )
    conn.commit()
    conn.close()
    print("[seed_lab] bpo-east OIDC -> Mock IdP :9101")
    print("[seed_lab] redirect_uri:", LAB_REDIRECT)
    print("[seed_lab] 联调时设: MITAKO_SSO_DEMO=0")


if __name__ == "__main__":
    main()
