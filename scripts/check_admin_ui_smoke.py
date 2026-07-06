# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    required = [
        ROOT / "dist" / "admin.html",
        ROOT / "src" / "admin" / "AdminApp.jsx",
        ROOT / "src" / "admin" / "AdminLogin.jsx",
        ROOT / "src" / "admin" / "HandoffAdmin.jsx",
        ROOT / "src" / "admin" / "AdminShell.jsx",
        ROOT / "src" / "admin" / "pages" / "AgentManagement.jsx",
        ROOT / "src" / "admin" / "pages" / "Approvals.jsx",
        ROOT / "src" / "admin" / "pages" / "AuditLog.jsx",
        ROOT / "src" / "admin" / "pages" / "Dashboard.jsx",
        ROOT / "src" / "admin" / "pages" / "ObserverQC.jsx",
        ROOT / "src" / "admin" / "pages" / "OpsMonitor.jsx",
        ROOT / "src" / "admin" / "pages" / "QueueMonitor.jsx",
        ROOT / "src" / "admin" / "pages" / "Reports.jsx",
        ROOT / "src" / "lib" / "authClient.js",
    ]
    missing = [str(p) for p in required if not p.exists()]
    assert not missing, f"missing admin ui files: {missing}"

    bad_tokens = ("�", "鈥", "涓", "绠", "瀹", "鎶", "娴", "杞")
    for path in required[1:]:
        text = path.read_text(encoding="utf-8")
        hits = [token for token in bad_tokens if token in text]
        assert not hits, f"mojibake in {path}: {hits}"

    admin_app = (ROOT / "src" / "admin" / "AdminApp.jsx").read_text(encoding="utf-8")
    assert "setAuthSession" in admin_app and "import {" in admin_app, "AdminApp SSO session import missing"

    dist = (ROOT / "dist" / "admin.html").read_text(encoding="utf-8")
    assert 'type="module"' in dist and "assets/" in dist, "admin build does not reference bundled assets"
    assets = set(re.findall(r'/(assets/[^"\']+)', dist))
    assert assets, "admin build does not contain asset references"
    missing_assets = [asset for asset in assets if not (ROOT / "dist" / asset).exists()]
    assert not missing_assets, f"missing admin build assets: {missing_assets}"
    print("admin ui smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
