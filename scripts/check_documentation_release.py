# -*- coding: utf-8 -*-
"""校验新版本文档、接口契约与客户包边界。"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "docs/delivery/README.md",
    "docs/delivery/deployment-guide.md",
    "docs/delivery/testing-guide.md",
    "docs/delivery/acceptance-checklist-v1.md",
    "docs/delivery/java-client-sample.md",
    "docs/delivery/openapi.yaml",
    "docs/delivery/mitako-full-requirement-reaudit-20260711.html",
    "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
    "甲方沟通交付文档/README.md",
    "甲方沟通交付文档/index.html",
    "甲方沟通交付文档/0714反馈整改与验收说明-2026-07-15.md",
    "甲方沟通交付文档/新版本交付说明-2026-07-11.md",
    "我方内部开发文档/README.md",
    "我方内部开发文档/index.html",
    "我方内部开发文档/工程师入门.md",
    "我方内部开发文档/系统清单与代码地图.md",
    "我方内部开发文档/Java开发部署与联调指南.md",
    "我方内部开发文档/内部研发包交付说明.md",
    "我方内部开发文档/升级日志-2026-07-11.md",
    "我方内部开发文档/升级日志-2026-07-15.md",
)
REQUIRED_API_PATHS = (
    "/api/v1/review/contracts",
    "/api/v1/review/metadata/validate",
    "/api/v1/review/sampling-plan",
    "/api/v1/review/jobs",
    "/api/v1/review/batches/{batch_id}",
    "/api/v1/private-domain/dashboard",
)
LINK_RE = re.compile(r"(?:href=[\"']([^\"']+)[\"']|\[[^\]]+\]\(([^)]+)\))")


def local_links(path: Path) -> list[tuple[str, Path]]:
    text = path.read_text(encoding="utf-8")
    links: list[tuple[str, Path]] = []
    for match in LINK_RE.finditer(text):
        raw = (match.group(1) or match.group(2) or "").strip().strip("<>")
        if not raw or raw.startswith(("#", "http://", "https://", "mailto:", "javascript:")):
            continue
        clean = unquote(raw.split("#", 1)[0].split("?", 1)[0])
        if not clean:
            continue
        links.append((raw, (path.parent / clean).resolve()))
    return links


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"缺少文件: {relative}")

    for relative in REQUIRED_FILES:
        path = ROOT / relative
        if path.suffix.lower() not in {".md", ".html"} or not path.is_file():
            continue
        for raw, target in local_links(path):
            try:
                target.relative_to(ROOT)
            except ValueError:
                errors.append(f"链接越出仓库: {relative} -> {raw}")
                continue
            if not target.exists():
                errors.append(f"断链: {relative} -> {raw}")

    openapi_path = ROOT / "docs/delivery/openapi.yaml"
    if openapi_path.is_file():
        spec = yaml.safe_load(openapi_path.read_text(encoding="utf-8")) or {}
        paths = spec.get("paths") or {}
        if len(paths) < 60:
            errors.append(f"OpenAPI 路由数异常: {len(paths)}，期望不少于 60")
        for route in REQUIRED_API_PATHS:
            if route not in paths:
                errors.append(f"OpenAPI 缺少路由: {route}")

    package_script = (ROOT / "scripts/package_release.ps1").read_text(encoding="utf-8")
    if "我方内部开发文档" in package_script:
        errors.append("打包脚本出现内部文档明文，请确认未复制到客户包")
    if "$obsoleteCustomerDocs" not in package_script or "[System.IO.File]::Delete($obsoletePath)" not in package_script:
        errors.append("打包脚本未启用过时甲方文档排除规则")

    if errors:
        print("文档发布校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"文档发布校验通过：{len(REQUIRED_FILES)} 个必需文件，OpenAPI {len(paths)} 条路由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
