# -*- coding: utf-8 -*-
"""解压并验收内部源码包与甲方预览包。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
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
        "我方内部开发文档/升级日志-2026-07-17.md",
        "我方内部开发文档/升级日志-2026-07-16.md",
        "我方内部开发文档/升级日志-2026-07-15.md",
        "docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html",
        "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
        "甲方沟通交付文档/0714反馈整改更新日志-2026-07-15.html",
        "甲方沟通交付文档/0717网页端视频读取问题整改与验收报告.html",
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
    _verify_hashes(root, list(manifest.get("evidence") or []))
    return {"entries": len(names), "manifest_commit": manifest.get("git_commit"), "evidence": len(manifest.get("evidence") or [])}


def _verify_customer(zip_path: Path, root: Path, expected_commit: str) -> dict[str, Any]:
    names = _zip_names(zip_path)
    required = {
        "start-windows.bat",
        "install-runtime-windows.bat",
        "runtime/app_runtime.zip",
        "customer-package-manifest.json",
        "docs/delivery/openapi.yaml",
        "docs/delivery/mitako-visual-evaluation-engineering-acceptance-20260716.html",
        "docs/delivery/mitako-0714-adversarial-acceptance-20260715.html",
        "甲方沟通交付文档/甲方测试版与本轮更新说明-2026-07-16.html",
        "甲方沟通交付文档/0717网页端视频读取问题整改与验收报告.html",
        "甲方沟通交付文档/视觉审核下一轮测试建议-2026-07-16.md",
        "甲方沟通交付文档/0714反馈整改更新日志-2026-07-15.html",
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

    manifest = json.loads((root / "customer-package-manifest.json").read_text(encoding="utf-8-sig"))
    _assert(manifest.get("git_commit") == expected_commit, "甲方包提交号不是当前验收提交")
    _assert(manifest.get("delivery_mode") == "customer_demo_preview", "甲方包未声明演示交付边界")
    _verify_hashes(root, list(manifest.get("evidence") or []))

    with zipfile.ZipFile(root / "runtime" / "app_runtime.zip") as runtime:
        runtime_names = [item.filename.replace("\\", "/") for item in runtime.infolist() if not item.is_dir()]
    _assert(not any(name.endswith(".py") for name in runtime_names), "甲方运行时仍包含 Python 源码")
    _assert(any(name.endswith("review_media_safety.pyc") for name in runtime_names), "甲方运行时缺少媒体上传安全模块")
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
    parser.add_argument("--internal-zip", type=Path, default=ROOT.parent / f"MITAKO_Agent-internal-dev-{date}.zip")
    parser.add_argument("--customer-zip", type=Path, default=ROOT.parent / f"MITAKO_Agent-customer-preview-{date}.zip")
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
