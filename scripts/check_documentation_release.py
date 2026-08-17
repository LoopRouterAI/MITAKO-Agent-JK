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
    "docs/product/四场景审核业务决策与报告契约-20260812.md",
    "docs/product/四场景审核主线进度-20260814.md",
    "docs/product/四场景黄金审核经验/README.md",
    "docs/product/四场景黄金审核经验/01-商品有伤黄金审核经验.md",
    "docs/product/四场景黄金审核经验/02-发错货黄金审核经验.md",
    "docs/product/四场景黄金审核经验/03-漏发货黄金审核经验.md",
    "docs/product/四场景黄金审核经验/04-未成年人退款资料黄金审核经验.md",
    "docs/api/rest-api-overview.md",
    "docs/delivery/README.md",
    "docs/delivery/deployment-guide.md",
    "docs/delivery/testing-guide.md",
    "docs/delivery/acceptance-checklist-v1.md",
    "docs/delivery/java-client-sample.md",
    "docs/delivery/review-advisory-api.md",
    "docs/delivery/after-sales-agent-integration.md",
    "docs/delivery/甲方技术对接与私有化部署说明.html",
    "docs/delivery/openapi.yaml",
    "甲方沟通交付文档/README.md",
    "甲方沟通交付文档/index.html",
    "甲方沟通交付文档/0817四场景审核业务理解与发布验收说明.html",
    "甲方沟通交付文档/0817四场景八份审核报告质量索引.html",
    "甲方沟通交付文档/0817甲方技术对接与私有化部署说明.html",
    "我方内部开发文档/README.md",
    "我方内部开发文档/index.html",
    "我方内部开发文档/工程师入门.md",
    "我方内部开发文档/系统清单与代码地图.md",
    "我方内部开发文档/Java开发部署与联调指南.md",
    "我方内部开发文档/内部研发包交付说明.md",
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
    for marker in (
        "0817四场景审核业务理解与发布验收说明.html",
        "0817四场景八份审核报告质量索引.html",
        "review_0816_four_scenario_blind_results_latest.json",
        "_verify_current_four_scenario_acceptance",
    ):
        if marker not in package_script:
            errors.append(f"甲方打包脚本缺少当前四场景发布门禁: {marker}")
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
    for marker in (
        "四场景审核业务决策与报告契约-20260812.md",
        "0817四场景审核业务理解与发布验收说明.html",
        "0817四场景八份审核报告质量索引.html",
        "review_0816_four_scenario_blind_results_latest.json",
        "_verify_current_four_scenario_acceptance",
    ):
        if marker not in internal_package_script:
            errors.append(f"内部打包脚本缺少当前四场景发布门禁: {marker}")

    if errors:
        print("文档发布校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"文档发布校验通过：{len(REQUIRED_FILES)} 个必需文件，OpenAPI {len(paths)} 条路由。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
