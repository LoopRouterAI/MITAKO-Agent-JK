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
    "docs/README.md",
    "docs/api/rest-api-overview.md",
    "docs/delivery/README.md",
    "docs/delivery/deployment-guide.md",
    "docs/delivery/testing-guide.md",
    "docs/delivery/acceptance-checklist-v1.md",
    "docs/delivery/java-client-sample.md",
    "docs/delivery/review-advisory-api.md",
    "docs/delivery/after-sales-agent-integration.md",
    "docs/delivery/openapi.yaml",
    "docs/delivery/mitako-full-requirement-reaudit-20260711.html",
    "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
    "docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html",
    "docs/delivery/客服Agent与私域Agent正式接入前人工UAT指南_20260716.md",
    "甲方沟通交付文档/README.md",
    "甲方沟通交付文档/index.html",
    "甲方沟通交付文档/0717网页端视频读取问题整改与验收报告.html",
    "甲方沟通交付文档/0717四样本审核工程整改与验收报告.html",
    "甲方沟通交付文档/144989未成年人资料审核整改与验收报告.html",
    "甲方沟通交付文档/未成年人资料字段一致性审核升级说明-2026-07-20.html",
    "甲方沟通交付文档/订单SKU快照接入与审核安全升级说明-2026-07-20.html",
    "甲方沟通交付文档/0722订单资料与官方商品图按需接入说明.html",
    "甲方沟通交付文档/0723审核结论置信度与人工复审分级说明.html",
    "甲方沟通交付文档/0723客诉审核Agent接口联调与商务沟通说明.html",
    "甲方沟通交付文档/0728事实结论与人工复审闭环更新说明.html",
    "甲方沟通交付文档/0728动态素材与统一审核链路更新说明.html",
    "我方内部开发文档/README.md",
    "我方内部开发文档/index.html",
    "我方内部开发文档/工程师入门.md",
    "我方内部开发文档/系统清单与代码地图.md",
    "我方内部开发文档/Java开发部署与联调指南.md",
    "我方内部开发文档/内部研发包交付说明.md",
    "我方内部开发文档/升级日志-2026-07-11.md",
    "我方内部开发文档/升级日志-2026-07-15.md",
    "我方内部开发文档/升级日志-2026-07-16.md",
    "我方内部开发文档/升级日志-2026-07-17.md",
    "我方内部开发文档/升级日志-2026-07-17-四样本审核.md",
    "我方内部开发文档/升级日志-2026-07-20-未成年人资料字段一致性.md",
    "我方内部开发文档/升级日志-2026-07-20-视觉证据安全与SKU基准.md",
    "我方内部开发文档/升级日志-2026-07-22-订单基线与官方商品图按需接入.md",
    "我方内部开发文档/升级日志-2026-07-23-审核建议契约与可选HTML.md",
    "我方内部开发文档/升级日志-2026-07-23-多源证据与接口联调.md",
    "我方内部开发文档/升级日志-2026-07-28-事实结论与人工复审闭环.md",
)
REQUIRED_API_PATHS = (
    "/api/v1/review/contracts",
    "/api/v1/review/metadata/validate",
    "/api/v1/review/sampling-plan",
    "/api/v1/review/jobs",
    "/api/v1/review/readiness",
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
        security_schemes = ((spec.get("components") or {}).get("securitySchemes") or {})
        if not any((value or {}).get("scheme") == "bearer" for value in security_schemes.values()):
            errors.append("OpenAPI 缺少 Bearer 安全方案")
        create_job = ((paths.get("/api/v1/review/jobs") or {}).get("post") or {})
        if not create_job.get("security"):
            errors.append("审核创建接口未声明 Bearer 鉴权")
        declared_responses = set((create_job.get("responses") or {}).keys())
        missing_errors = {"400", "409", "413", "415", "422"} - declared_responses
        if missing_errors:
            errors.append(f"审核创建接口缺少错误响应: {sorted(missing_errors)}")
        metadata_schema = (((spec.get("components") or {}).get("schemas") or {}).get("ReviewCaseMetadata") or {})
        metadata_properties = metadata_schema.get("properties") or {}
        for field in ("output_options", "review_routing_policy", "logistics", "customer_risk_context"):
            if field not in metadata_properties:
                errors.append(f"审核 metadata 缺少字段: {field}")
        schemas = ((spec.get("components") or {}).get("schemas") or {})
        for schema_name in (
            "ReviewAdvisoryAssessment",
            "ReviewHumanReviewAdvice",
            "ReviewAdvisorySignal",
            "ReviewAdvisoryPolicy",
            "ReviewReportReference",
            "ReviewLogisticsContext",
            "ReviewLogisticsPackage",
            "ReviewLogisticsEvent",
            "ReviewCustomerRiskContext",
        ):
            if schema_name not in schemas:
                errors.append(f"OpenAPI 缺少审核结果类型: {schema_name}")
        report_responses = (((paths.get("/api/v1/review/jobs/{job_id}/report") or {}).get("get") or {}).get("responses") or {})
        for status in ("404", "409"):
            if status not in report_responses:
                errors.append(f"审核报告接口缺少错误响应: {status}")
        if "/api/v1/review/jobs/{job_id}/media/{media_id}" not in paths:
            errors.append("OpenAPI 缺少任务级报告媒体访问端点")

    java_guide = (ROOT / "我方内部开发文档/Java开发部署与联调指南.md").read_text(encoding="utf-8")
    if "/api/v1/review/contracts" not in java_guide:
        errors.append("Java 联调指南缺少真实审核契约端点 /api/v1/review/contracts")
    if re.search(r"/api/v1/review/contract(?!s)", java_guide):
        errors.append("Java 联调指南仍包含错误端点 /api/v1/review/contract")
    if "advisory_assessment" not in java_guide or "include_html_report=false" not in java_guide:
        errors.append("Java 联调指南缺少统一建议结果或 JSON-only 说明")

    advisory_guide = (ROOT / "docs/delivery/review-advisory-api.md").read_text(encoding="utf-8")
    for term in (
        "required",
        "optional",
        "not_required",
        "request_more_material",
        "system_retry",
        "technical_processing_incomplete",
        "business_action_allowed",
    ):
        if term not in advisory_guide:
            errors.append(f"审核建议 API 文档缺少关键字段: {term}")

    package_script = (ROOT / "scripts/package_release.ps1").read_text(encoding="utf-8")
    if "param(" not in package_script or "[string]$BaseUrl" not in package_script or "[string]$VisualUrl" not in package_script:
        errors.append("甲方打包脚本必须支持显式传入主服务和视觉服务验收地址")
    if "-BaseUrl $BaseUrl -VisualUrl $VisualUrl" not in package_script:
        errors.append("甲方打包脚本没有把验收地址传给内部预发布门禁")
    if "我方内部开发文档" in package_script:
        errors.append("打包脚本出现内部文档明文，请确认未复制到客户包")
    if "$obsoleteCustomerDocs" not in package_script or "[System.IO.File]::Delete($obsoletePath)" not in package_script:
        errors.append("打包脚本未启用过时甲方文档排除规则")
    if "0728事实结论与人工复审闭环更新说明.html" not in package_script:
        errors.append("甲方打包证据清单缺少 0728 最新非技术更新说明")
    if "0728动态素材与统一审核链路更新说明.html" not in package_script:
        errors.append("甲方打包证据清单缺少 0728 动态素材更新说明")
    for marker in (
        "report-signing-secret.txt",
        "secrets.token_hex(32)",
        "set VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET=1",
    ):
        if marker not in package_script:
            errors.append(f"甲方启动脚本缺少持久报告签名配置: {marker}")

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET=1" not in env_example:
        errors.append(".env.example 未默认要求持久报告签名密钥")

    internal_package_script = (ROOT / "scripts/package_internal_release.ps1").read_text(encoding="utf-8")
    if "升级日志-2026-07-28-事实结论与人工复审闭环.md" not in internal_package_script:
        errors.append("内部打包证据清单缺少 0728 最新升级日志")

    if errors:
        print("文档发布校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"文档发布校验通过：{len(REQUIRED_FILES)} 个必需文件，OpenAPI {len(paths)} 条路由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
