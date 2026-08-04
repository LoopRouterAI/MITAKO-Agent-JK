# -*- coding: utf-8 -*-
"""解压并验收内部源码包与甲方预览包。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "tests" / "reports"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _verify_customer_text_boundary(root: Path) -> None:
    blocked_terms = (
        "chatwoot", "langgraph", "openviking", "viking_memory", "api_key",
        "provider_id", "show_provider", "gemini", "openai", "deepseek", "doubao",
        "sensenova", "weknora", "mitako_jwt_secret", "mitako_dev_auth_bypass",
    )
    secret_assignment = re.compile(
        r"(?i)(?:api[_-]?key|secret|access[_-]?token)\s*[:=]\s*[\"']?[A-Za-z0-9_./+:-]{16,}"
    )
    text_suffixes = {".md", ".html", ".txt", ".json", ".yaml", ".yml", ".js", ".css", ".bat", ".ps1"}
    violations: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        lowered = text.lower()
        term = next((item for item in blocked_terms if item in lowered), "")
        if term or secret_assignment.search(text):
            violations.append(f"{path.relative_to(root).as_posix()}:{term or 'secret_assignment'}")
    _assert(not violations, f"甲方包正文包含内部渠道或疑似凭证：{violations[:20]}")


def _zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        names: set[str] = set()
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = item.filename.replace("\\", "/")
            if name.startswith("./"):
                name = name[2:]
            names.add(name)
        return names


def _extract(path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        resolved_target = target.resolve()
        for item in archive.infolist():
            resolved_item = (target / item.filename).resolve()
            _assert(
                resolved_item == resolved_target or resolved_target in resolved_item.parents,
                f"ZIP 包含越界路径：{item.filename}",
            )
        archive.extractall(target)


def _verify_hashes(root: Path, entries: list[dict[str, Any]]) -> None:
    for item in entries:
        relative = str(item.get("path") or "")
        expected = str(item.get("sha256") or "").lower()
        file_path = root / relative
        _assert(file_path.is_file(), f"证据文件缺失：{relative}")
        _assert(_sha256(file_path) == expected, f"证据哈希不一致：{relative}")


def _verify_internal(zip_path: Path, root: Path, expected_commit: str) -> dict[str, Any]:
    names = _zip_names(zip_path)
    required = {
        ".env",
        "README.md",
        "requirements.txt",
        "internal-package-manifest.json",
        "我方内部开发文档/Java开发部署与联调指南.md",
        "我方内部开发文档/升级日志-2026-07-31-商品有伤SOP与报告一致性.md",
        "我方内部开发文档/升级日志-2026-07-28-事实结论与人工复审闭环.md",
        "我方内部开发文档/升级日志-2026-07-23-审核建议契约与可选HTML.md",
        "我方内部开发文档/升级日志-2026-07-23-多源证据与接口联调.md",
        "我方内部开发文档/升级日志-2026-07-17.md",
        "我方内部开发文档/升级日志-2026-07-17-提交模式与双包.md",
        "我方内部开发文档/升级日志-2026-07-17-144989未成年人资料审核.md",
        "我方内部开发文档/升级日志-2026-07-20-未成年人资料字段一致性.md",
        "我方内部开发文档/升级日志-2026-07-20-视觉证据安全与SKU基准.md",
        "我方内部开发文档/升级日志-2026-07-20-独立逐帧审核与资料质量分层.md",
        "我方内部开发文档/升级日志-2026-07-22-订单基线与官方商品图按需接入.md",
        "我方内部开发文档/升级日志-2026-07-16.md",
        "我方内部开发文档/升级日志-2026-07-15.md",
        "docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html",
        "docs/delivery/mitako-0731-product-damage-sop-acceptance-20260731.html",
        "甲方沟通交付文档/0731商品有伤SOP与报告一致性更新说明.html",
        "tests/reports/blind_damage_0731_case_001_latest.json",
        "tests/reports/blind_damage_0731_cases_002_004_latest.json",
        "docs/delivery/mitako-0730-minor-report-acceptance-20260730.html",
        "我方内部开发文档/升级日志-2026-07-30-未成年人策略与客服报告.md",
        "甲方沟通交付文档/0730未成年人资料审核与客服报告升级说明.html",
        "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
        "甲方沟通交付文档/0717网页端视频读取问题整改与验收报告.html",
        "甲方沟通交付文档/甲方测试版与本轮更新说明-2026-07-17.html",
        "甲方沟通交付文档/144989未成年人资料审核整改与验收报告.html",
        "甲方沟通交付文档/未成年人资料字段一致性审核升级说明-2026-07-20.html",
        "甲方沟通交付文档/订单SKU快照接入与审核安全升级说明-2026-07-20.html",
        "甲方沟通交付文档/视觉审核逐帧与资料审核整改说明-2026-07-20.html",
        "甲方沟通交付文档/0722订单资料与官方商品图按需接入说明.html",
        "甲方沟通交付文档/0723审核结论置信度与人工复审分级说明.html",
        "甲方沟通交付文档/0723客诉审核Agent接口联调与商务沟通说明.html",
        "甲方沟通交付文档/0728事实结论与人工复审闭环更新说明.html",
        "甲方沟通交付文档/0728动态素材与统一审核链路更新说明.html",
        "docs/delivery/review-advisory-api.md",
        "docs/delivery/after-sales-agent-integration.md",
        "tests/reports/minor_refund_144989_20260717-final.json",
        "tests/reports/minor_refund_144989_20260720-latest.json",
        "tests/reports/minor_refund_144989_20260720-latest.html",
        "tests/reports/review_617911_individual24_20260720-latest.json",
        "tests/reports/review_617911_individual24_20260720-latest.html",
        "tests/reports/review_submission_modes_20260717-final.json",
        "tests/reports/review_submission_modes_20260717-final.html",
        "tests/reports/dynamic_material_capacity_http_latest.json",
        "tests/reports/dynamic_material_capacity_http_51_20260730.json",
        "tests/reports/dynamic_material_capacity_http_62_20260730.json",
        "tests/reports/minor_refund_144989_20260730_223430.json",
        "tests/reports/customer_order_info_sync_strict_verify_20260720.json",
        "tests/reports/customer_order_info_reconcile_applied_20260720.json",
        "tests/reports/customer_order_info_integration_strict_final_20260720.json",
        "data/admin.db",
        "data/auth.db",
        "data/handoff.db",
        "data/private_domain.db",
        "data/review_service.db",
    }
    missing = sorted(required - names)
    _assert(not missing, f"内部包缺少文件：{missing}")

    blocked_roots = (".venv/", "venv/", "node_modules/", ".git/", ".codegraph/", "tmp/", "logs/", "archive/", "data/review_jobs/")
    blocked = sorted(name for name in names if name.startswith(blocked_roots) or "__pycache__/" in name or name.endswith(".pyc"))
    _assert(not blocked, f"内部包包含禁止路径：{blocked[:20]}")

    manifest = json.loads((root / "internal-package-manifest.json").read_text(encoding="utf-8-sig"))
    _assert(manifest.get("env_included") is True, "内部包清单未确认 .env")
    _assert(manifest.get("git_commit") == expected_commit, "内部包提交号不是当前验收提交")
    dynamic_report = json.loads(
        (root / "tests/reports/dynamic_material_capacity_http_latest.json").read_text(encoding="utf-8")
    )
    _assert(dynamic_report.get("ok") is True, "动态素材真实 HTTP 证据未通过")
    _assert(dynamic_report.get("requested_count") == 62, "动态素材证据不是 62 份资料")
    _assert(dynamic_report.get("git_commit") == expected_commit, "动态素材证据未绑定当前验收提交")
    _verify_hashes(root, list(manifest.get("evidence") or []))
    return {"entries": len(names), "manifest_commit": manifest.get("git_commit"), "evidence": len(manifest.get("evidence") or [])}


def _verify_customer(zip_path: Path, root: Path, expected_commit: str) -> dict[str, Any]:
    names = _zip_names(zip_path)
    nested_release_zips = sorted(
        name for name in names if name.lower().endswith(".zip") and name != "runtime/app_runtime.zip"
    )
    _assert(not nested_release_zips, f"甲方包包含嵌套发布 ZIP：{nested_release_zips[:20]}")
    required = {
        "start-windows.bat",
        "install-runtime-windows.bat",
        "runtime/app_runtime.zip",
        "customer-package-manifest.json",
        "docs/delivery/openapi.yaml",
        "docs/delivery/review-advisory-api.md",
        "docs/delivery/after-sales-agent-integration.md",
        "docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html",
        "docs/delivery/mitako-0731-product-damage-sop-acceptance-20260731.html",
        "甲方沟通交付文档/0731商品有伤SOP与报告一致性更新说明.html",
        "docs/delivery/mitako-0730-minor-report-acceptance-20260730.html",
        "甲方沟通交付文档/0730未成年人资料审核与客服报告升级说明.html",
        "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
        "甲方沟通交付文档/甲方测试版与本轮更新说明-2026-07-17.html",
        "甲方沟通交付文档/未成年人资料字段一致性审核升级说明-2026-07-20.html",
        "甲方沟通交付文档/订单SKU快照接入与审核安全升级说明-2026-07-20.html",
        "甲方沟通交付文档/视觉审核逐帧与资料审核整改说明-2026-07-20.html",
        "甲方沟通交付文档/0722订单资料与官方商品图按需接入说明.html",
        "甲方沟通交付文档/0723审核结论置信度与人工复审分级说明.html",
        "甲方沟通交付文档/0723客诉审核Agent接口联调与商务沟通说明.html",
        "甲方沟通交付文档/0728事实结论与人工复审闭环更新说明.html",
        "甲方沟通交付文档/0728动态素材与统一审核链路更新说明.html",
        "甲方沟通交付文档/144989未成年人资料审核整改与验收报告.html",
        "甲方沟通交付文档/0717网页端视频读取问题整改与验收报告.html",
        "甲方沟通交付文档/README.md",
        "visual_review_workbench/workbench.html",
    }
    missing = sorted(required - names)
    _assert(not missing, f"甲方包缺少文件：{missing}")

    blocked_roots = (".git/", "data/", "src/", "tests/", "specs/", "我方内部开发文档/")
    blocked = sorted(
        name
        for name in names
        if name == ".env"
        or name.startswith(blocked_roots)
        or name.lower().endswith((".db", ".sqlite", ".py"))
        or "sample_labels" in name.lower()
        or "ground_truth" in name.lower()
    )
    _assert(not blocked, f"甲方包包含内部或敏感文件：{blocked[:20]}")
    _verify_customer_text_boundary(root)

    manifest = json.loads((root / "customer-package-manifest.json").read_text(encoding="utf-8-sig"))
    _assert(manifest.get("git_commit") == expected_commit, "甲方包提交号不是当前验收提交")
    _assert(manifest.get("delivery_mode") == "customer_demo_preview", "甲方包未声明演示交付边界")
    _verify_hashes(root, list(manifest.get("evidence") or []))

    with zipfile.ZipFile(root / "runtime" / "app_runtime.zip") as runtime:
        runtime_names = [item.filename.replace("\\", "/") for item in runtime.infolist() if not item.is_dir()]
    _assert(not any(name.endswith(".py") for name in runtime_names), "甲方运行时仍包含 Python 源码")
    _assert(any(name.endswith("review_media_safety.pyc") for name in runtime_names), "甲方运行时缺少媒体上传安全模块")
    _assert(any(name.endswith("minor_material_pipeline.pyc") for name in runtime_names), "甲方运行时缺少未成年人资料审核管线")
    _assert(any(name.endswith("minor_material_model_prompt.pyc") for name in runtime_names), "甲方运行时缺少未成年人资料识别协议")
    _assert(any(name.endswith("official_reference_images.pyc") for name in runtime_names), "甲方运行时缺少官方商品图按需读取模块")
    _assert(any(name.endswith("order_info_adapter.pyc") for name in runtime_names), "甲方运行时缺少订单快照适配模块")
    _assert(any(name.endswith("advisory_assessment.pyc") for name in runtime_names), "甲方运行时缺少统一审核建议模块")
    _assert(any(name.endswith("model_auth.pyc") for name in runtime_names), "甲方运行时缺少模型认证适配模块")
    _assert(any(name.endswith("observability.pyc") for name in runtime_names), "甲方运行时缺少视觉调用可观测模块")
    workbench_html = (root / "visual_review_workbench" / "workbench.html").read_text(encoding="utf-8-sig")
    _assert("/api/review-folders-batch" in workbench_html and "batchFolderTab" in workbench_html, "甲方工作台缺少批量工单入口")
    return {"entries": len(names), "runtime_entries": len(runtime_names), "manifest_commit": manifest.get("git_commit"), "evidence": len(manifest.get("evidence") or [])}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.5)
    raise RuntimeError(f"服务未就绪：{url}；最后错误：{last_error}")


def _request_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            payload = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = exc.read()
    _assert(status == expected_status, f"HTTP 状态不符：{url}，expected={expected_status}, actual={status}")
    return json.loads(payload.decode("utf-8-sig")) if payload else {}


def _multipart_review_job(metadata: dict[str, Any]) -> tuple[bytes, str]:
    boundary = "----MITAKOReleaseContractBoundary"
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n".encode("utf-8"),
        json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"contract.png\"\r\nContent-Type: image/png\r\n\r\n".encode("utf-8"),
        png,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _terminate(process: subprocess.Popen[Any] | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _verify_runtime(customer_root: Path, python: Path) -> dict[str, Any]:
    main_port = _free_port()
    visual_port = _free_port()
    log_dir = customer_root / ".verification-logs"
    log_dir.mkdir(exist_ok=True)
    main_log_path = log_dir / "main.log"
    visual_log_path = log_dir / "visual.log"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(customer_root / "runtime" / "app_runtime.zip") + os.pathsep + env.get("PYTHONPATH", ""),
            "APP_PORT": str(main_port),
            "ALLOW_PORT_FALLBACK": "0",
            "VISUAL_WORKBENCH_PORT": str(visual_port),
            "VISUAL_WORKBENCH_PUBLIC_URL": f"http://127.0.0.1:{visual_port}",
            "VISUAL_REPORT_SIGNING_SECRET": secrets.token_hex(32),
            "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET": "1",
            "MITAKO_APP_ROOT": str(customer_root),
            "MITAKO_DATA_DIR": str(customer_root / ".runtime-data"),
            "MITAKO_MOCK_DATA_FILE": str(customer_root / "sample_data.json"),
            "MITAKO_VISUAL_WORKBENCH_DIR": str(customer_root / "visual_review_workbench"),
            "MITAKO_BUSINESS_DEMO_API_ENABLED": "1",
            "MITAKO_AUTH_REQUIRED": "0",
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "0",
            "MITAKO_DEV_AUTH_BYPASS": "1",
        }
    )
    main_process: subprocess.Popen[Any] | None = None
    visual_process: subprocess.Popen[Any] | None = None
    try:
        with visual_log_path.open("w", encoding="utf-8") as visual_log:
            visual_process = subprocess.Popen(
                [str(python), "-m", "poc.visual_review_poc.workbench_server"],
                cwd=customer_root,
                env=env,
                stdout=visual_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        visual_health = _wait_json(f"http://127.0.0.1:{visual_port}/api/health")
        _assert(visual_health.get("ok") is True, "甲方包视觉服务健康检查失败")
        _assert(visual_health.get("built_in_samples_available") is False, "甲方包不应宣称附带内部审核样本")

        with main_log_path.open("w", encoding="utf-8") as main_log:
            main_process = subprocess.Popen(
                [str(python), "-m", "main"],
                cwd=customer_root,
                env=env,
                stdout=main_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        auth_status = _wait_json(f"http://127.0.0.1:{main_port}/api/v1/auth/status")
        _assert(auth_status.get("ok") is True, "甲方包主服务健康检查失败")

        runtime_contract = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from review_service.advisory_assessment import attach_advisory_assessment;"
                    "r=attach_advisory_assessment({'summary':{'predicted_label':'positive','confidence':0.91},"
                    "'agent_report':{'parsed':{'predicted_label':'positive','confidence':0.91}}},"
                    "{'scenario':'product_damage'},readiness={'full_review_ready':True,'missing_required':[]});"
                    "a=r['advisory_assessment'];"
                    "assert a['human_review']['level']=='not_required';"
                    "assert a['policy']['business_action_allowed'] is False;"
                    "assert r['agent_report']['parsed']['human_required'] is False"
                ),
            ],
            cwd=customer_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        _assert(runtime_contract.returncode == 0, f"甲方编译运行时审核契约失败：{runtime_contract.stderr[-2000:]}")

        metadata = {
            "client_case_id": "RELEASE-CONTRACT-JSON-ONLY",
            "scenario": "product_damage",
            "output_options": {"include_html_report": False},
            "review_routing_policy": {
                "required_below_confidence": 0.5,
                "optional_below_confidence": 0.8,
                "out_of_frame_resubmit_seconds": 3.0,
            },
        }
        validated = _request_json(
            f"http://127.0.0.1:{main_port}/api/v1/review/metadata/validate",
            method="POST",
            data=json.dumps(metadata).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert(validated["metadata"]["output_options"]["include_html_report"] is False, "JSON-only 配置未生效")
        invalid = {**metadata, "review_routing_policy": {"required_below_confidence": 0.9, "optional_below_confidence": 0.2}}
        _request_json(
            f"http://127.0.0.1:{main_port}/api/v1/review/metadata/validate",
            method="POST",
            data=json.dumps(invalid).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            expected_status=422,
        )
        body, content_type = _multipart_review_job(metadata)
        created = _request_json(
            f"http://127.0.0.1:{main_port}/api/v1/review/jobs",
            method="POST",
            data=body,
            headers={"Content-Type": content_type, "Idempotency-Key": "release-contract-json-only"},
            expected_status=202,
        )
        job_id = created["job"]["job_id"]
        report_error = _request_json(
            f"http://127.0.0.1:{main_port}/api/v1/review/jobs/{job_id}/report",
            expected_status=409,
        )
        _assert(report_error.get("detail") == "review_report_not_requested", "JSON-only 报告路由未返回预期错误")

        smoke_env = env.copy()
        smoke_env["E2E_BASE_URL"] = f"http://127.0.0.1:{main_port}"
        smoke = subprocess.run(
            [str(python), str(ROOT / "scripts" / "check_private_deployment_api.py")],
            cwd=ROOT,
            env=smoke_env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        _assert(smoke.returncode == 0, f"甲方包 API 冒烟失败：\n{smoke.stdout[-4000:]}\n{smoke.stderr[-2000:]}")
        return {
            "main_port": main_port,
            "visual_port": visual_port,
            "auth_mode": "demo_bypass",
            "api_smoke": "14/14",
            "advisory_contract": "compiled runtime + metadata validation + JSON-only report 409",
            "visual_health": True,
            "built_in_samples_available": False,
        }
    except Exception as exc:
        main_tail = main_log_path.read_text(encoding="utf-8", errors="replace")[-3000:] if main_log_path.exists() else ""
        visual_tail = visual_log_path.read_text(encoding="utf-8", errors="replace")[-3000:] if visual_log_path.exists() else ""
        raise RuntimeError(f"{exc}\n主服务日志：\n{main_tail}\n视觉服务日志：\n{visual_tail}") from exc
    finally:
        _terminate(main_process)
        _terminate(visual_process)


def _verify_internal_python(root: Path, python: Path) -> None:
    targets = [root / "main.py", root / "agent.py", root / "business_readiness_service.py"]
    targets.extend(sorted((root / "review_service").glob("*.py")))
    result = subprocess.run([str(python), "-m", "py_compile", *map(str, targets)], cwd=root, capture_output=True, text=True, timeout=120)
    _assert(result.returncode == 0, f"内部包 Python 编译失败：{result.stderr[-3000:]}")


def main() -> int:
    date = time.strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="MITAKO 发布包解压后验收")
    parser.add_argument("--internal-zip", type=Path, default=ROOT / "dist" / f"MITAKO_Agent-internal-dev-{date}.zip")
    parser.add_argument("--customer-zip", type=Path, default=ROOT / "dist" / f"MITAKO_Agent-customer-preview-{date}.zip")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()

    internal_zip = args.internal_zip.resolve()
    customer_zip = args.customer_zip.resolve()
    python = args.python.resolve()
    for path in (internal_zip, customer_zip, python):
        _assert(path.exists(), f"文件不存在：{path}")
    expected_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    started = time.time()
    with tempfile.TemporaryDirectory(prefix="mitako-release-verify-") as temp:
        temp_root = Path(temp)
        internal_root = temp_root / "internal"
        customer_root = temp_root / "customer"
        _extract(internal_zip, internal_root)
        _extract(customer_zip, customer_root)
        internal = _verify_internal(internal_zip, internal_root, expected_commit)
        customer = _verify_customer(customer_zip, customer_root, expected_commit)
        _verify_internal_python(internal_root, python)
        runtime = _verify_runtime(customer_root, python)

    report = {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": expected_commit,
        "duration_seconds": round(time.time() - started, 3),
        "internal_zip": {"path": str(internal_zip), "bytes": internal_zip.stat().st_size, "sha256": _sha256(internal_zip), **internal},
        "customer_zip": {"path": str(customer_zip), "bytes": customer_zip.stat().st_size, "sha256": _sha256(customer_zip), **customer},
        "extracted_runtime": runtime,
        "boundaries": {
            "internal_package": "包含源码、内部文档、当前环境配置与数据库快照，仅限我方研发。",
            "customer_package": "仅含演示运行时和公开文档，不含 Key、数据库、源码、内部文档或盲测标签。",
        },
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_path = REPORT_DIR / f"release_packages_{time.strftime('%Y%m%d_%H%M%S')}.json"
    latest_path = REPORT_DIR / "release_packages_latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    timestamp_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    print(payload)
    print(f"[PASS] 发布包解压验收通过：{timestamp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
