# -*- coding: utf-8 -*-
"""解压并验收内部源码包与甲方预览包。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
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
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_final_commercial_acceptance import (
    CONTRACT_VERSION,
    REQUIRED_CASES_PER_SCENE,
    SCENARIOS,
    _blind_audit_valid,
    _scene_contract_valid,
)


REPORT_DIR = ROOT / "tests" / "reports"
DYNAMIC_CAPACITY_EVIDENCE_PATHS = (
    ".env.example",
    "auth",
    "main.py",
    "prompts",
    "review_service",
    "poc/visual_review_poc/minor_material_pipeline.py",
    "poc/visual_review_poc/model_selection_e2e.py",
    "poc/visual_review_poc/workbench_server.py",
    "scripts/check_dynamic_material_capacity_http.py",
)
FOUR_SCENARIO_ACCEPTANCE = "tests/reports/review_0816_four_scenario_blind_results_latest.json"
FOUR_SCENARIO_CONTRACT = "docs/product/四场景审核业务决策与报告契约-20260812.md"
FOUR_SCENARIO_CUSTOMER_GUIDE = "甲方沟通交付文档/0814四场景审核业务理解与功能验收说明.html"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _dynamic_capacity_evidence_matches_release(evidence_commit: str, release_commit: str) -> bool:
    commit_pattern = re.compile(r"^[0-9a-fA-F]{40}$")
    if not commit_pattern.fullmatch(evidence_commit) or not commit_pattern.fullmatch(release_commit):
        return False
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", evidence_commit, release_commit],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if ancestor.returncode != 0:
            return False
        unchanged = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                f"{evidence_commit}..{release_commit}",
                "--",
                *DYNAMIC_CAPACITY_EVIDENCE_PATHS,
            ],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return unchanged.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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


def _resolve_acceptance_artifact(root: Path, relative: str) -> Path:
    _assert(bool(relative) and not Path(relative).is_absolute(), f"当前盲测报告路径无效：{relative or '-'}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    _assert(resolved_root in resolved.parents, f"当前盲测报告路径越界：{relative}")
    _assert(resolved.is_file(), f"当前盲测报告文件不存在：{relative}")
    return resolved


def _verify_acceptance_report(
    *,
    root: Path,
    case: dict[str, Any],
    key: str,
) -> Path:
    relative = str(case.get(key) or "")
    _assert(
        "review_0816_blind_" in relative and not any(old in relative for old in ("0809", "0812", "0813", "0815")),
        f"当前盲测 case 引用了过期报告：{case.get('case_id') or '-'} / {key}",
    )
    path = _resolve_acceptance_artifact(root, relative)
    expected_hash = str(case.get(f"{key}_sha256") or "").lower()
    _assert(
        bool(re.fullmatch(r"[0-9a-f]{64}", expected_hash)),
        f"当前盲测 case 缺少有效报告哈希：{case.get('case_id') or '-'} / {key}",
    )
    _assert(_sha256(path) == expected_hash, f"当前盲测报告哈希不一致：{relative}")
    return path


def _verify_current_four_scenario_acceptance(path: Path, *, root: Path = ROOT) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"当前四场景盲测清单不可读：{path}") from exc
    _assert(
        payload.get("contract_version") == CONTRACT_VERSION and payload.get("label_state") == "sealed",
        "四场景盲测不是当前 MITAKO-FOUR-SCENE@20260814.1 密封契约",
    )
    _assert(_blind_audit_valid(payload), "当前四场景盲测缺少有效的盲验输入审计")
    checks = payload.get("checks") if isinstance(payload, dict) else None
    _assert(
        isinstance(checks, dict) and bool(checks) and all(value is True for value in checks.values()),
        "当前四场景盲测门禁尚未全部通过",
    )
    for key in (
        "all_required_random_cases_present",
        "all_current_business_contracts_valid",
        "api_html_same_job",
        "blind_input_audit_valid",
    ):
        _assert(checks.get(key) is True, f"当前四场景盲测缺少门禁：{key}")
    cases = payload.get("cases")
    _assert(isinstance(cases, list), "当前四场景盲测清单缺少 cases")
    counts = {scenario: 0 for scenario in SCENARIOS}
    case_ids: set[str] = set()
    for case in cases:
        _assert(isinstance(case, dict), "当前四场景盲测清单包含无效 case")
        scenario = str(case.get("scenario") or "")
        case_id = str(case.get("case_id") or "")
        _assert(
            scenario in SCENARIOS
            and bool(case_id)
            and case_id not in case_ids
            and not {"expected_label", "manual_baseline", "manual_source"}.intersection(case),
            f"当前四场景盲测 case 字段无效：{case_id or '-'}",
        )
        _assert(_scene_contract_valid(case), f"当前盲测 case 违反业务契约：{case_id}")
        counts[scenario] += 1
        case_ids.add(case_id)
        job_id = str(case.get("job_id") or "")
        _assert(bool(job_id), f"当前盲测 case 缺少 job_id：{case_id}")
        json_path = _verify_acceptance_report(root=root, case=case, key="report_json")
        html_path = _verify_acceptance_report(root=root, case=case, key="report_html")
        try:
            report_payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"当前盲测 JSON 报告不可读：{json_path}") from exc
        report_job = report_payload.get("job") if isinstance(report_payload, dict) else None
        report_job = report_job if isinstance(report_job, dict) else {}
        _assert(report_job.get("job_id") == job_id, f"当前盲测 JSON 工单不一致：{case_id}")
        _assert(report_job.get("scenario") == scenario, f"当前盲测 JSON 场景不一致：{case_id}")
        _assert(report_job.get("status") == "SUCCEEDED", f"当前盲测 JSON 工单未成功：{case_id}")
        html = html_path.read_text(encoding="utf-8-sig", errors="strict")
        required_markers = {
            "product_damage": (
                "当前商品有伤场景下的用户材料是否齐全", "开箱视频九项核对",
                "主视频损伤存在性", "诉求支持度",
            ),
            "wrong_item": (
                "当前发错货场景下的用户材料是否齐全", "发错货应收与实收核对",
                "身份定义属性", "同包裹证据",
            ),
            "missing_item": (
                "当前漏发货场景下的用户材料是否齐全", "漏发货应发与实收核对",
                "用户证据路线", "最终事实依据",
            ),
            "minor_refund": (
                "当前未成年人退款场景下的用户材料是否齐全",
                "未成年人退款五类材料核对", "视觉字段一致性初审",
            ),
        }.get(scenario, ())
        _assert(
            required_markers and all(marker in html for marker in required_markers),
            f"当前盲测 HTML 缺少场景专属结构：{case_id}",
        )
        if scenario == "minor_refund":
            forbidden = ("包裹开启过程完整性", "包裹与实收展示连续性")
            _assert(not any(marker in html for marker in forbidden), "未成年人报告混入商品履约视频模板")
    _assert(
        len(cases) == len(SCENARIOS) * REQUIRED_CASES_PER_SCENE
        and all(count == REQUIRED_CASES_PER_SCENE for count in counts.values()),
        "当前四场景盲测必须恰好包含每场景 2 个密封 Case",
    )


def _verify_0812_four_scenario_acceptance(path: Path, *, root: Path = ROOT) -> None:
    del path, root
    raise RuntimeError("0812 正负槽位验收已退役；必须使用当前四场景密封盲测结果")


class _LocalLinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() in {"href", "src"} and value:
                self.links.append(value.strip())


def _verify_local_html_links(root: Path) -> None:
    root = root.resolve()
    missing: list[str] = []
    for html_path in root.rglob("*.html"):
        parser = _LocalLinkCollector()
        parser.feed(html_path.read_text(encoding="utf-8-sig", errors="ignore"))
        for raw in parser.links:
            split = urlsplit(raw)
            if not split.path or split.scheme or split.netloc or split.path.startswith("/"):
                continue
            target = (html_path.parent / unquote(split.path)).resolve()
            if root not in target.parents or not target.is_file():
                missing.append(f"{html_path.relative_to(root).as_posix()} -> {raw}")
    _assert(not missing, f"甲方包 HTML 存在离线断链：{missing[:20]}")


def _verify_internal(zip_path: Path, root: Path, expected_commit: str) -> dict[str, Any]:
    names = _zip_names(zip_path)
    required = {
        "README.md",
        "requirements.txt",
        "internal-package-manifest.json",
        "我方内部开发文档/Java开发部署与联调指南.md",
        FOUR_SCENARIO_CONTRACT,
        FOUR_SCENARIO_ACCEPTANCE,
        "docs/delivery/review-advisory-api.md",
        "docs/delivery/after-sales-agent-integration.md",
        "tests/reports/dynamic_material_capacity_http_latest.json",
        "tests/reports/dynamic_material_capacity_http_51_20260730.json",
        "tests/reports/dynamic_material_capacity_http_62_20260730.json",
        "tests/reports/customer_order_info_sync_strict_verify_20260720.json",
        "tests/reports/customer_order_info_reconcile_applied_20260720.json",
        "tests/reports/customer_order_info_integration_strict_final_20260720.json",
    }
    missing = sorted(required - names)
    _assert(not missing, f"内部包缺少文件：{missing}")

    blocked_roots = (".venv/", "venv/", "node_modules/", ".git/", ".codegraph/", "tmp/", "logs/", "archive/", "data/review_jobs/")
    blocked = sorted(name for name in names if name.startswith(blocked_roots) or "__pycache__/" in name or name.endswith(".pyc"))
    _assert(not blocked, f"内部包包含禁止路径：{blocked[:20]}")

    manifest = json.loads((root / "internal-package-manifest.json").read_text(encoding="utf-8-sig"))
    _assert(manifest.get("secrets_included") is False, "默认内部包不得包含运行密钥或数据库")
    _assert(manifest.get("env_included") is False, "默认内部包不得包含 .env")
    _assert(".env" not in names, "默认内部包包含 .env")
    _assert(
        all(not name.startswith("data/") or not name.endswith(".db") for name in names),
        "默认内部包包含运行数据库",
    )
    _assert(manifest.get("git_commit") == expected_commit, "内部包提交号不是当前验收提交")
    dynamic_report = json.loads(
        (root / "tests/reports/dynamic_material_capacity_http_latest.json").read_text(encoding="utf-8")
    )
    _assert(dynamic_report.get("release_gate_ok") is True, "动态素材真实 HTTP 容量与降级证据未通过")
    _assert(dynamic_report.get("requested_count") == 62, "动态素材证据不是 62 份资料")
    evidence_commit = str(dynamic_report.get("git_commit") or "")
    _assert(
        _dynamic_capacity_evidence_matches_release(evidence_commit, expected_commit),
        "动态素材证据不是当前验收提交的可信祖先，或相关审核实现已发生变化",
    )
    _verify_hashes(root, list(manifest.get("evidence") or []))
    _verify_current_four_scenario_acceptance(root / FOUR_SCENARIO_ACCEPTANCE, root=root)
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
        "甲方沟通交付文档/README.md",
        FOUR_SCENARIO_CUSTOMER_GUIDE,
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
    _verify_local_html_links(root)

    manifest = json.loads((root / "customer-package-manifest.json").read_text(encoding="utf-8-sig"))
    _assert(manifest.get("git_commit") == expected_commit, "甲方包提交号不是当前验收提交")
    _assert(manifest.get("delivery_mode") == "customer_demo_preview", "甲方包未声明演示交付边界")
    _assert(manifest.get("runtime_python_version") == "3.11", "甲方编译运行时未锁定 Python 3.11")
    _verify_hashes(root, list(manifest.get("evidence") or []))

    with zipfile.ZipFile(root / "runtime" / "app_runtime.zip") as runtime:
        runtime_names = [item.filename.replace("\\", "/") for item in runtime.infolist() if not item.is_dir()]
    _assert(not any(name.endswith(".py") for name in runtime_names), "甲方运行时仍包含 Python 源码")
    _assert(any(name.endswith("review_media_safety.pyc") for name in runtime_names), "甲方运行时缺少媒体上传安全模块")
    _assert(any(name.endswith("minor_material_pipeline.pyc") for name in runtime_names), "甲方运行时缺少未成年人资料审核管线")
    _assert(any(name.endswith("minor_material_model_prompt.pyc") for name in runtime_names), "甲方运行时缺少未成年人资料识别协议")
    _assert(any(name.endswith("prompts/customer_service.pyc") for name in runtime_names), "甲方运行时缺少集中客服规则模块")
    _assert(any(name.endswith("prompts/visual_review/core.pyc") for name in runtime_names), "甲方运行时缺少集中视觉审核规则模块")
    _assert(any(name.endswith("prompts/visual_review/schemas.pyc") for name in runtime_names), "甲方运行时缺少四场景结构化契约模块")
    _assert(any(name.endswith("configs/model_catalog.pyc") for name in runtime_names), "甲方运行时缺少统一模型目录模块")
    _assert(any(name.endswith("official_reference_images.pyc") for name in runtime_names), "甲方运行时缺少官方商品图按需读取模块")
    _assert(any(name.endswith("order_info_adapter.pyc") for name in runtime_names), "甲方运行时缺少订单快照适配模块")
    _assert(any(name.endswith("advisory_assessment.pyc") for name in runtime_names), "甲方运行时缺少统一审核建议模块")
    _assert(any(name.endswith("model_auth.pyc") for name in runtime_names), "甲方运行时缺少模型认证适配模块")
    _assert(any(name.endswith("observability.pyc") for name in runtime_names), "甲方运行时缺少视觉调用可观测模块")
    _assert(any(name.endswith("native_video_perception.pyc") for name in runtime_names), "甲方运行时缺少原生视频感知模块")
    _assert(any(name.endswith("media_preflight.pyc") for name in runtime_names), "甲方运行时缺少媒体送审预检模块")
    _assert(any(name.endswith("secure_media_tunnel.pyc") for name in runtime_names), "甲方运行时缺少安全媒体隧道模块")
    _assert(any(name.endswith("report_assets.pyc") for name in runtime_names), "甲方运行时缺少报告静态资源模块")
    _assert(any(name.endswith("report_evidence.pyc") for name in runtime_names), "甲方运行时缺少报告证据回链模块")
    _assert(
        any(name.endswith("internal_review_ledger.pyc") for name in runtime_names),
        "customer runtime is missing the persistent review request ledger",
    )
    _assert(
        any(name.endswith("review_public_safety.pyc") for name in runtime_names),
        "customer runtime is missing the public review safety module",
    )
    _assert(
        any(name.endswith("review_service/material_readiness.pyc") for name in runtime_names),
        "customer runtime is missing the scene material readiness module",
    )
    _assert(
        any(name.endswith("review_service/media_processing.pyc") for name in runtime_names),
        "customer runtime is missing the persistent review media processing module",
    )
    installer = (root / "install-runtime-windows.bat").read_text(encoding="utf-8-sig")
    _assert(
        "imageio-ffmpeg" in installer and "imageio_ffmpeg" in installer,
        "customer runtime installer is missing video transcoding support",
    )
    _assert("pypdf==6.15.0" in installer, "customer runtime installer is missing PDF inventory support")
    _assert(
        "Cloudflare.cloudflared" in installer,
        "customer runtime installer is missing secure large-video tunnel support",
    )
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


def _request_text(url: str, expected_status: int = 200) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        _assert(response.status == expected_status, f"HTTP 状态不符：{url}")
        return response.read().decode("utf-8-sig")


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
    data_dir = customer_root / "data"
    data_dir.mkdir(exist_ok=True)
    signing_secret_path = data_dir / "report-signing-secret.txt"
    if not signing_secret_path.exists():
        signing_secret_path.write_text(secrets.token_hex(32), encoding="ascii")
    signing_secret = signing_secret_path.read_text(encoding="ascii").strip()
    _assert(len(signing_secret) >= 32, "持久化报告签名密钥生成失败")
    report_name = "cold-start-signature.html"
    report_path = f"/reports/{quote(report_name, safe='')}"
    report_expiry = int(time.time()) + 600
    report_signature = hmac.new(
        signing_secret.encode("utf-8"),
        f"{report_path}\n{report_expiry}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signed_report_url = (
        f"http://127.0.0.1:{visual_port}{report_path}"
        f"?expires={report_expiry}&sig={report_signature}"
    )
    public_summary_dir = customer_root / "visual_review_workbench" / "reports" / "public_summaries"
    public_summary_dir.mkdir(parents=True, exist_ok=True)
    (public_summary_dir / "cold-start-signature.json").write_text(
        json.dumps(
            {
                "ok": True,
                "review_label": "冷启动签名验收",
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "summary": {
                    "cases": 1,
                    "total_reviews": 1,
                    "successful_reviews": 1,
                    "predicted_label": "review",
                    "confidence": 0.5,
                    "needs_human_review": False,
                    "review_status": "completed",
                },
                "conclusion": "冷启动签名验收报告。",
                "agent_report": {
                    "parsed": {
                        "predicted_label": "review",
                        "confidence": 0.5,
                        "overall_audit": {"conclusion": "冷启动签名验收报告。"},
                        "material_gaps": [],
                    },
                    "public_brief": {
                        "conclusion": "冷启动签名验收报告。",
                        "next_step": "无需业务操作。",
                    },
                },
                "media_warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(customer_root / "runtime" / "app_runtime.zip") + os.pathsep + env.get("PYTHONPATH", ""),
            "APP_PORT": str(main_port),
            "ALLOW_PORT_FALLBACK": "0",
            "VISUAL_WORKBENCH_PORT": str(visual_port),
            "VISUAL_WORKBENCH_PUBLIC_URL": f"http://127.0.0.1:{visual_port}",
            "VISUAL_REPORT_SIGNING_SECRET": signing_secret,
            "VISUAL_REQUIRE_PERSISTENT_SIGNING_SECRET": "1",
            "MITAKO_APP_ROOT": str(customer_root),
            "MITAKO_DATA_DIR": str(customer_root / ".runtime-data"),
            "MITAKO_MOCK_DATA_FILE": str(customer_root / "sample_data.json"),
            "MITAKO_VISUAL_WORKBENCH_DIR": str(customer_root / "visual_review_workbench"),
            "MITAKO_BUSINESS_DEMO_API_ENABLED": "1",
            "MITAKO_AUTH_REQUIRED": "0",
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "0",
            "MITAKO_DEV_AUTH_BYPASS": "1",
            "PYTHONIOENCODING": "utf-8",
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
        _assert("冷启动签名验收报告" in _request_text(signed_report_url), "首次启动无法访问签名报告")

        _terminate(visual_process)
        with visual_log_path.open("a", encoding="utf-8") as visual_log:
            visual_process = subprocess.Popen(
                [str(python), "-m", "poc.visual_review_poc.workbench_server"],
                cwd=customer_root,
                env=env,
                stdout=visual_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        _wait_json(f"http://127.0.0.1:{visual_port}/api/health")
        _assert("冷启动签名验收报告" in _request_text(signed_report_url), "服务重启后旧签名报告失效")

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
            "review_routing_policy": {"policy_ref": "MITAKO-ROUTING@20260815.1"},
        }
        validated = _request_json(
            f"http://127.0.0.1:{main_port}/api/v1/review/metadata/validate",
            method="POST",
            data=json.dumps(metadata).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        _assert(validated["metadata"]["output_options"]["include_html_report"] is False, "JSON-only 配置未生效")
        invalid = {**metadata, "review_routing_policy": {"required_below_confidence": 0.9}}
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
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        _assert(
            smoke.returncode == 0,
            f"甲方包 API 冒烟失败：\n{(smoke.stdout or '')[-4000:]}\n{(smoke.stderr or '')[-2000:]}",
        )
        return {
            "main_port": main_port,
            "visual_port": visual_port,
            "auth_mode": "demo_bypass",
            "api_smoke": "14/14",
            "advisory_contract": "compiled runtime + metadata validation + JSON-only report 409",
            "visual_health": True,
            "report_signature_survives_restart": True,
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
            "internal_package": "包含源码、内部文档与验收证据；默认不含 Key、运行数据库或用户附件，仅限我方研发。",
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
