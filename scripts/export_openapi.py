# -*- coding: utf-8 -*-
"""从当前 FastAPI 应用生成 Java/部署使用的 OpenAPI 契约。"""
from __future__ import annotations

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app


OUTPUT = ROOT / "docs" / "delivery" / "openapi.yaml"


def main() -> int:
    schema = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"OpenAPI 已生成：{OUTPUT}，路由 {len(schema.get('paths') or {})} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
