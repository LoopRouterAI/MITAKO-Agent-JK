from __future__ import annotations

import unittest
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

from scripts.check_release_packages import (
    _dynamic_capacity_evidence_matches_release,
    _media_asset_path,
    _verify_0812_four_scenario_acceptance,
    _verify_current_four_scenario_acceptance,
    _verify_evidence,
)
from scripts.run_final_commercial_acceptance import (
    UNSEEN_AUDIT_SCOPES,
    UNSEEN_AUDIT_VERSION,
    FORMALLY_UNRUN_AUDIT_SCOPES,
    FORMALLY_UNRUN_AUDIT_VERSION,
    case_ids_sha256,
)


ROOT = Path(__file__).resolve().parents[1]


def _scene_contract(scenario: str) -> dict:
    return {
        "product_damage": {
            "opening_video_evidence": {"present": True, "sop_compliant": True},
            "damage_presence": "confirmed",
            "claim_support": "supported",
            "severity": {"level": "moderate", "confidence": 0.91, "structural_failure": False},
            "severe_alert_eligible": False,
        },
        "wrong_item": {
            "observed_items_present": True,
            "package_observations_present": True,
            "identity_definition_fields_present": True,
            "same_package_evidence_present": True,
        },
        "missing_item": {
            "evidence_route": "static_three_images",
            "resolution_basis": "none",
            "warehouse_check": {"state": "pending", "outcome": None},
            "user_materials_complete": True,
        },
        "minor_refund": {
            "five_material_checklist_present": True,
            "payment_capability_risk": {
                "low_age": False,
                "under_nine": False,
                "age_confidence": "high",
                "process_evidence_status": "matched",
                "requires_more_material": False,
                "requires_review": False,
            },
        },
    }[scenario]


def _write_current_acceptance(root: Path) -> tuple[Path, dict]:
    report_dir = root / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    public_report_dir = root / "甲方沟通交付文档" / "四场景审核报告"
    public_report_dir.mkdir(parents=True, exist_ok=True)
    markers = {
        "product_damage": "当前商品有伤场景下的用户材料是否齐全 开箱视频九项核对 主视频损伤存在性 诉求支持度",
        "wrong_item": "当前发错货场景下的用户材料是否齐全 发错货应收与实收核对 身份定义属性 同包裹证据",
        "missing_item": "当前漏发货场景下的用户材料是否齐全 漏发货应发与实收核对 用户证据路线 最终事实依据",
        "minor_refund": "当前未成年人退款场景下的用户材料是否齐全 未成年人退款五类材料核对 视觉字段一致性初审",
    }
    cases = []
    for scenario in ("product_damage", "wrong_item", "missing_item", "minor_refund"):
        for index in (1, 2):
            case_id = f"{scenario}-{index}"
            job_id = f"RJ-{scenario}-{index}"
            stem = f"review_0816_blind_{scenario}_{index}"
            json_path = report_dir / f"{stem}.json"
            html_path = report_dir / f"{stem}.html"
            json_path.write_text(json.dumps({
                "job": {"job_id": job_id, "scenario": scenario, "status": "SUCCEEDED"},
            }), encoding="utf-8")
            html_path.write_text(markers[scenario], encoding="utf-8")
            (public_report_dir / html_path.name).write_text(markers[scenario], encoding="utf-8")
            cases.append({
                "case_id": case_id,
                "scenario": scenario,
                "job_id": job_id,
                "status": "SUCCEEDED",
                "predicted_label": "review" if scenario == "missing_item" else "positive",
                "material_readiness": {"scenario": scenario, "status": "complete"},
                "scene_contract": _scene_contract(scenario),
                "report_json": f"tests/reports/{stem}.json",
                "report_json_sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
                "report_html": f"tests/reports/{stem}.html",
                "report_html_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
            })
    payload = {
        "contract_version": "MITAKO-FOUR-SCENE@20260814.1",
        "label_state": "sealed",
        "unseen_audit": {
            "version": FORMALLY_UNRUN_AUDIT_VERSION,
            "status": "verified_before_freeze",
            "audited_at": "2026-08-16 10:50:00 +08:00",
            "checked_scopes": sorted(FORMALLY_UNRUN_AUDIT_SCOPES),
            "case_ids_sha256": case_ids_sha256([item["case_id"] for item in cases]),
            "matches": [],
        },
        "checks": {
            "all_required_random_cases_present": True,
            "all_current_business_contracts_valid": True,
            "api_html_same_job": True,
            "blind_input_audit_valid": True,
        },
        "cases": cases,
    }
    path = report_dir / "review_0816_four_scenario_blind_results_latest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    customer_docs = root / "甲方沟通交付文档"
    customer_docs.mkdir(parents=True, exist_ok=True)
    (customer_docs / "0817四场景审核业务理解与发布验收说明.html").write_text("<html>guide</html>", encoding="utf-8")
    (customer_docs / "0817甲方技术对接与私有化部署说明.html").write_text("<html>tech</html>", encoding="utf-8")
    (customer_docs / "0817四场景八份审核报告质量索引.html").write_text("<html>" + " ".join(["打开 HTML"] * 8) + "</html>", encoding="utf-8")
    return path, payload


class ReleaseLayoutTest(unittest.TestCase):
    def test_media_manifest_path_keeps_media_directory(self) -> None:
        root = Path("D:/MITAKO-release-test")
        self.assertEqual(
            _media_asset_path(root, "media/592717/user_001.webp"),
            root / "甲方沟通交付文档" / "四场景审核报告" / "media" / "592717" / "user_001.webp",
        )

    def test_release_verifier_supports_documented_direct_execution(self) -> None:
        result = subprocess.run(
            [
                str(ROOT / ".venv" / "Scripts" / "python.exe"),
                str(ROOT / "scripts" / "check_release_packages.py"),
                "--help",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_verifier_rejects_legacy_0812_positive_negative_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_dir = root / "tests" / "reports"
            report_dir.mkdir(parents=True)
            path = report_dir / "review_0812_four_scenario_acceptance_latest.json"
            path.write_text(json.dumps({
                "checks": {"all_jobs_succeeded": True},
                "cases": [
                    {
                        "case_id": f"{scenario}-{label}",
                        "scenario": scenario,
                        "expected_label": label,
                        "job_id": f"RJ-{scenario}-{label}",
                    }
                    for scenario in ("product_damage", "wrong_item", "missing_item", "minor_refund")
                    for label in ("positive", "negative")
                ],
            }, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                _verify_0812_four_scenario_acceptance(path, root=root)

    def test_current_release_acceptance_rejects_stale_case_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, payload = _write_current_acceptance(root)
            _verify_current_four_scenario_acceptance(path, root=root)

            payload["cases"][0]["report_html"] = "tests/reports/review_0809_old.html"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _verify_current_four_scenario_acceptance(path, root=root)

    def test_current_release_acceptance_rejects_tampered_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance, payload = _write_current_acceptance(root)
            _verify_current_four_scenario_acceptance(acceptance, root=root)

            (root / payload["cases"][0]["report_json"]).write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _verify_current_four_scenario_acceptance(acceptance, root=root)

    def test_current_release_acceptance_rejects_missing_unseen_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acceptance, payload = _write_current_acceptance(root)
            payload.pop("unseen_audit")
            acceptance.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "盲验输入审计"):
                _verify_current_four_scenario_acceptance(acceptance, root=root)

    def test_current_release_acceptance_rejects_reversed_product_and_minor_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, payload = _write_current_acceptance(root)
            product = next(item for item in payload["cases"] if item["scenario"] == "product_damage")
            product["predicted_label"] = "negative"
            product["scene_contract"]["opening_video_evidence"] = {
                "present": False,
                "sop_compliant": False,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _verify_current_four_scenario_acceptance(path, root=root)

            path, payload = _write_current_acceptance(root)
            minor = next(item for item in payload["cases"] if item["scenario"] == "minor_refund")
            minor["predicted_label"] = "positive"
            minor["scene_contract"]["payment_capability_risk"].update({
                "low_age": True,
                "process_evidence_status": "unresolved",
                "requires_more_material": False,
            })
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _verify_current_four_scenario_acceptance(path, root=root)

    def test_current_release_verifier_uses_current_sealed_contract_only(self) -> None:
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        self.assertIn("review_0816_four_scenario_blind_results_latest.json", verifier)
        self.assertIn("MITAKO-FOUR-SCENE@20260814.1", verifier)
        self.assertIn("docs/product/四场景审核业务决策与报告契约-20260812.md", verifier)
        self.assertNotIn('FOUR_SCENARIO_ACCEPTANCE = "tests/reports/review_0812_', verifier)

    def test_package_scripts_use_current_blind_gate_and_customer_doc_allowlist(self) -> None:
        customer = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        internal = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")

        for script in (customer, internal):
            self.assertIn("review_0816_four_scenario_blind_results_latest.json", script)
            self.assertIn("_verify_current_four_scenario_acceptance", script)
            self.assertNotIn("review_0812_four_scenario_acceptance_latest.json", script)
            self.assertNotIn("_verify_0812_four_scenario_acceptance", script)
            self.assertIn("0817四场景审核业务理解与发布验收说明.html", script)
            self.assertIn("0817四场景八份审核报告质量索引.html", script)

        self.assertNotIn('Copy-Dir "docs\\delivery"', customer)
        self.assertNotIn('Copy-Dir $customerDocsName $customerDocsName', customer)
        self.assertNotIn("0807黄金指南学习与审核能力更新说明.html", customer)
        self.assertNotIn("mitako-0806-four-scenario-minor-material", customer)

    def test_customer_runtime_installer_enforces_security_dependency_floors(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8-sig")
        customer = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("aiohttp>=3.14.3", requirements)
        self.assertIn("cryptography>=50.0.0", requirements)
        for dependency in (
            '"pip>=26.1.2"',
            '"setuptools>=83.0.0"',
            '"aiohttp>=3.14.3"',
            '"cryptography>=50.0.0"',
        ):
            self.assertIn(dependency, customer)

    def test_pre_release_runs_current_contract_and_real_api_web_report_gates(self) -> None:
        source = (ROOT / "scripts" / "pre_release_internal_validation.ps1").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("tests\\test_final_commercial_acceptance.py", source)
        self.assertIn("tests\\test_final_ui_acceptance_contract.py", source)
        self.assertIn("review_0816_four_scenario_blind_results_latest.json", source)
        self.assertIn("_verify_current_four_scenario_acceptance", source)
        self.assertIn("tests\\e2e\\run_final_ui_acceptance.py", source)
        self.assertIn("tests\\acceptance\\test_media_preflight_real_execution.py", source)
        self.assertIn("scripts\\run_final_commercial_acceptance.py", source)
        self.assertNotIn("scripts\\check_review_0717_four_samples.py", source)

    def test_customer_package_does_not_generate_dead_visual_review_config(self) -> None:
        source = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")

        self.assertNotIn("visual_review_admin_config.json", source)
        self.assertFalse((ROOT / "config" / "visual_review_admin_config.json").exists())

    def test_release_verifier_does_not_require_retired_business_acceptance_evidence(self) -> None:
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        for retired in (
            "review_0807_random_acceptance_latest.json",
            "blind_0806_final_product_p1.json",
            "blind_damage_0731_case_001_latest.json",
            "minor_refund_144989_20260717-final.json",
            "minor_refund_144989_20260730_223430.json",
            "review_617911_individual24_20260720-latest.json",
            "review_submission_modes_20260717-final.json",
        ):
            self.assertNotIn(retired, verifier)

        customer_required = verifier.split("def _verify_customer(zip_path", 1)[1].split("missing = sorted", 1)[0]
        self.assertIn(
            'FOUR_SCENARIO_CUSTOMER_GUIDE = "甲方沟通交付文档/0817四场景审核业务理解与发布验收说明.html"',
            verifier,
        )
        self.assertIn("FOUR_SCENARIO_CUSTOMER_GUIDE", customer_required)
        self.assertNotIn("FOUR_SCENARIO_CONTRACT", customer_required)

    def test_one_click_startup_generates_runtime_jwt_secret(self) -> None:
        windows = (ROOT / "一键启动-Windows.bat").read_text(encoding="utf-8-sig")
        ubuntu = (ROOT / "一键启动-Ubuntu.sh").read_text(encoding="utf-8-sig")

        for script in (windows, ubuntu):
            self.assertIn("secrets.token_urlsafe(48)", script)
            self.assertNotIn("mitako-local-poc-secret-change-before-production", script)

    def test_all_publishable_files_default_to_dist(self) -> None:
        customer_script = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        internal_script = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")
        evidence_script = (ROOT / "scripts" / "package_four_scenario_evidence.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        vite_config = (ROOT / "vite.config.js").read_text(encoding="utf-8")

        self.assertIn('$DeliveryDir = Join-Path $Root "dist"', customer_script)
        self.assertIn('$ZipPath = Join-Path $DeliveryDir $ZipName', customer_script)
        self.assertIn('$CustomerHtmlPath = Join-Path $DeliveryDir "MITAKO_Agent-customer-delivery.html"', customer_script)
        self.assertIn('Copy-Item -LiteralPath $CustomerHtmlSource -Destination $CustomerHtmlPath -Force', customer_script)

        self.assertIn('$DeliveryDir = Join-Path $Root "dist"', internal_script)
        self.assertIn('$ZipPath = Join-Path $DeliveryDir "MITAKO_Agent-internal-dev-$Date.zip"', internal_script)

        self.assertIn('$DeliveryDir = Join-Path $Root "dist"', evidence_script)
        self.assertIn('MITAKO_Agent-four-scenario-evidence-$Date.zip', evidence_script)

        self.assertIn('ROOT / "dist" / f"MITAKO_Agent-internal-dev-{date}.zip"', verifier)
        self.assertIn('ROOT / "dist" / f"MITAKO_Agent-four-scenario-evidence-{date}.zip"', verifier)
        self.assertIn('ROOT / "dist" / f"MITAKO_Agent-customer-preview-{date}.zip"', verifier)

        self.assertIn('dist/assets', package["scripts"]["prebuild"])
        self.assertNotIn('MITAKO_Agent-customer-delivery.html', package["scripts"]["prebuild"])
        self.assertIn('emptyOutDir: false', vite_config)

    def test_pre_release_reuses_dynamic_capacity_evidence_only_when_related_code_is_unchanged(self) -> None:
        script = (ROOT / "scripts" / "pre_release_internal_validation.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("dynamic_material_capacity_http_latest.json", script)
        self.assertIn("check_dynamic_material_capacity_http.py", script)
        self.assertIn("git_commit", script)
        self.assertIn("requested_count", script)
        self.assertIn("merge-base --is-ancestor", script)
        self.assertIn("diff --quiet", script)
        self.assertIn("git diff --quiet -- $DynamicCapacityEvidencePaths", script)
        self.assertIn("git diff --cached --quiet -- $DynamicCapacityEvidencePaths", script)
        self.assertIn("$DynamicCapacityEvidencePaths", script)
        self.assertIn("-not $RunModelBatch", script)

    def test_package_verifier_accepts_unchanged_ancestor_dynamic_capacity_evidence(self) -> None:
        report = json.loads(
            (ROOT / "tests" / "reports" / "dynamic_material_capacity_http_latest.json").read_text(
                encoding="utf-8"
            )
        )
        current_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()

        self.assertTrue(
            _dynamic_capacity_evidence_matches_release(report["git_commit"], current_commit)
        )
        self.assertFalse(_dynamic_capacity_evidence_matches_release("not-a-commit", current_commit))

    def test_customer_package_excludes_previous_release_archives(self) -> None:
        customer_script = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        self.assertNotIn('Copy-Dir "dist"', customer_script)
        for expected in (
            'Copy-File "dist\\index.html"',
            'Copy-File "dist\\admin.html"',
            'Copy-File "dist\\desk.html"',
            'Copy-File "dist\\xiaojiao_avatar.png"',
            'Copy-Dir "dist\\assets"',
            'Copy-Dir "public\\memes" "memes"',
        ):
            self.assertIn(expected, customer_script)
        self.assertNotIn('Copy-Dir "dist\\memes"', customer_script)
        self.assertIn('name != "runtime/app_runtime.zip"', verifier)

    def test_release_dirty_gate_checks_index_and_tracked_worktree(self) -> None:
        for script_name in ("package_release.ps1", "package_internal_release.ps1"):
            script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8-sig")
            self.assertNotIn("--untracked-files=no", script)
            self.assertIn("git diff --quiet --", script)
            self.assertIn("git diff --cached --quiet --", script)
            self.assertIn("git ls-files --others --exclude-standard", script)
            self.assertNotIn('"*.py" "*.js"', script)
            self.assertIn("Assert-NoUntrackedCode", script)

    def test_release_model_batch_requires_explicit_opt_in(self) -> None:
        for script_name in ("package_release.ps1", "package_internal_release.ps1"):
            script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8-sig")
            self.assertIn("[switch]$RunModelBatch", script)
            self.assertIn("if ($RunModelBatch)", script)
            self.assertNotIn("-VisualUrl $VisualUrl -RunModelBatch", script)

    def test_package_scripts_support_windows_powershell_5(self) -> None:
        for script_name in ("package_release.ps1", "package_internal_release.ps1"):
            script = (ROOT / "scripts" / script_name).read_text(encoding="utf-8-sig")
            self.assertNotIn("[System.IO.Path]::GetRelativePath", script)
            self.assertIn("function Get-RepositoryRelativePath", script)

    def test_customer_package_only_copies_committed_inputs(self) -> None:
        customer_script = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("function Assert-CommittedPath", customer_script)
        self.assertIn("ls-files --error-unmatch", customer_script)
        for copy_function in (
            "Copy-File",
            "Copy-Dir",
            "Copy-RuntimeSource",
            "Copy-RuntimeDir",
        ):
            function_body = customer_script.split(f"function {copy_function}", 1)[1].split("\n}", 1)[0]
            self.assertIn("Assert-CommittedPath", function_body)
        runtime_dir_body = customer_script.split("function Copy-RuntimeDir", 1)[1].split("\n}", 1)[0]
        self.assertIn("-IgnorePythonCaches", runtime_dir_body)
        self.assertIn('Assert-CommittedPath "poc\\visual_review_poc\\local_video_triage_demo.py"', customer_script)
        self.assertIn("Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256", customer_script)
        for expected_hash in (
            "b670602fa00934ca27c4351bb0efe7ea7a07fae57284e44226025eeed7c51254",
            "b2ded9ae5a20fa36ca8cec49ef923bffb5e1a51d9e8c1f8336273d2fa9d35ff0",
            "0cd83d944a6ca7822b4a8306cecc60a36e859b041f6702c6a1ad9ead78924451",
        ):
            self.assertIn(expected_hash, customer_script.lower())

        for runtime_module in (
            '"review_public_safety.py"',
            '"poc\\visual_review_poc\\native_video_perception.py"',
            '"poc\\visual_review_poc\\sampled_video_perception.py"',
            '"poc\\visual_review_poc\\video_role_preflight.py"',
            '"poc\\visual_review_poc\\secure_media_tunnel.py"',
            '"poc\\visual_review_poc\\internal_review_ledger.py"',
            '"poc\\visual_review_poc\\media_preflight.py"',
            '"poc\\visual_review_poc\\report_assets.py"',
            '"poc\\visual_review_poc\\report_evidence.py"',
        ):
            self.assertIn(runtime_module, customer_script)
        self.assertIn("imageio_ffmpeg", customer_script)
        self.assertIn("imageio-ffmpeg", customer_script)
        self.assertIn("pypdf==6.15.0", customer_script)
        self.assertIn("Cloudflare.cloudflared", customer_script)
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")
        self.assertIn('name.endswith("native_video_perception.pyc")', verifier)
        self.assertIn('name.endswith("sampled_video_perception.pyc")', verifier)
        self.assertIn('name.endswith("video_role_preflight.pyc")', verifier)
        self.assertIn('name.endswith("secure_media_tunnel.pyc")', verifier)
        self.assertIn('name.endswith("internal_review_ledger.pyc")', verifier)
        self.assertIn('name.endswith("media_preflight.pyc")', verifier)
        self.assertIn('name.endswith("report_assets.pyc")', verifier)
        self.assertIn('name.endswith("report_evidence.pyc")', verifier)
        self.assertIn('name.endswith("review_public_safety.pyc")', verifier)
        self.assertIn('name.endswith("review_service/material_readiness.pyc")', verifier)
        self.assertIn('name.endswith("review_service/media_processing.pyc")', verifier)
        self.assertIn('name.endswith("prompts/visual_review/schemas.pyc")', verifier)
        self.assertIn('name.endswith("configs/model_catalog.pyc")', verifier)
        self.assertIn('Copy-RuntimeDir "configs"', customer_script)

    def test_compiled_customer_runtime_locks_python_minor_version(self) -> None:
        customer_script = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        self.assertIn('$RuntimePythonVersion = (& $py -c', customer_script)
        self.assertIn('if ($RuntimePythonVersion -ne "3.11")', customer_script)
        self.assertIn('py -3.11 -m venv venv', customer_script)
        self.assertNotIn('py -3.13 -m venv venv', customer_script)
        self.assertNotIn('py -3.12 -m venv venv', customer_script)
        self.assertIn('runtime_python_version = $RuntimePythonVersion', customer_script)
        self.assertIn('manifest.get("runtime_python_version") == "3.11"', verifier)

    def test_internal_package_excludes_runtime_secrets_by_default(self) -> None:
        internal_script = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        self.assertIn("[switch]$IncludeSecrets", internal_script)
        self.assertIn("if ($IncludeSecrets)", internal_script)
        self.assertNotIn('Copy-Path "data\\chat_attachments"', internal_script)
        self.assertNotIn('Copy-Path "data\\private_domain_uploads"', internal_script)
        self.assertNotIn('    ".env",', internal_script)
        self.assertIn('manifest.get("secrets_included") is False', verifier)
        self.assertIn('".env" not in names', verifier)
        self.assertIn('not name.startswith("data/") or not name.endswith(".db")', verifier)

    def test_internal_package_marks_latest_reports_as_runtime_snapshots(self) -> None:
        internal_script = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")

        self.assertIn('source_type = "runtime_report_snapshot"', internal_script)
        self.assertIn('runtime_snapshots = @($RuntimeSnapshots)', internal_script)

    def test_release_splits_source_runtime_and_offline_evidence(self) -> None:
        internal = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")
        evidence = (ROOT / "scripts" / "package_four_scenario_evidence.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")
        report_index = (ROOT / "甲方沟通交付文档" / "0817四场景八份审核报告质量索引.html").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn('docs\\三大审核场景的小量样本\\sample_002\\', internal)
        self.assertIn('甲方沟通交付文档\\四场景审核报告\\media\\', internal)
        self.assertNotIn('Copy-Path "$fourScenarioPublicReportDir\\media"', internal)
        self.assertNotIn('samples = @("sample_002", "sample_003", "sample_004"', internal)

        self.assertIn('$mediaManifest.reports.PSObject.Properties', evidence)
        self.assertIn('media_asset_count', evidence)
        self.assertIn('evidence-package-manifest.json', evidence)
        self.assertIn('证据包说明.md', evidence)

        self.assertIn('def _verify_evidence(', verifier)
        self.assertIn('"evidence_zip"', verifier)
        evidence_verifier = verifier.split("def _verify_evidence(", 1)[1].split("def _free_port", 1)[0]
        self.assertIn("_verify_local_html_links(root)", evidence_verifier)
        internal_required = verifier.split("def _verify_internal(zip_path", 1)[1].split("def _verify_customer", 1)[0]
        self.assertNotIn("FOUR_SCENARIO_REPORT_MEDIA_MANIFEST", internal_required)
        self.assertIn("FOUR_SCENARIO_REPORT_MEDIA_MANIFEST", verifier.split("def _verify_evidence(", 1)[1])
        self.assertIn('三份交付 ZIP', report_index)
        self.assertIn('独立验收证据包', report_index)
        self.assertNotIn('只随内部研发包保留', report_index)

    def test_evidence_packaging_script_keeps_utf8_bom_for_windows_powershell(self) -> None:
        script = (ROOT / "scripts" / "package_four_scenario_evidence.ps1").read_bytes()

        self.assertTrue(script.startswith(b"\xef\xbb\xbf"))

    def test_evidence_zip_verifier_checks_report_and_media_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit = "a" * 40
            required_paths = [
                Path("甲方沟通交付文档/0817四场景审核业务理解与发布验收说明.html"),
                Path("甲方沟通交付文档/0817四场景八份审核报告质量索引.html"),
                Path("甲方沟通交付文档/0817甲方技术对接与私有化部署说明.html"),
                Path("证据包说明.md"),
            ]
            report_paths = [
                Path("甲方沟通交付文档/四场景审核报告") / name
                for name in (
                    "review_0816_blind_product_damage_611941.html",
                    "review_0816_blind_product_damage_592717.html",
                    "review_0816_blind_wrong_item_515028.html",
                    "review_0816_blind_wrong_item_310508.html",
                    "review_0816_blind_missing_item_289433.html",
                    "review_0816_blind_missing_item_319303.html",
                    "review_0816_blind_minor_refund_554611.html",
                    "review_0816_blind_minor_refund_511007.html",
                )
            ]
            for path in required_paths + report_paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("verified", encoding="utf-8")

            asset_path = root / "甲方沟通交付文档/四场景审核报告/media/CASE/user_001.webp"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(b"webp-evidence")
            media_manifest_path = root / "甲方沟通交付文档/四场景审核报告/media/manifest.json"
            media_manifest = {
                "scope": "internal_review_only",
                "reports": {str(index): {"file": path.name} for index, path in enumerate(report_paths)},
                "assets": [{"asset": "media/CASE/user_001.webp", "sha256": hashlib.sha256(asset_path.read_bytes()).hexdigest()}],
            }
            media_manifest_path.write_text(json.dumps(media_manifest), encoding="utf-8")
            package_manifest_path = root / "evidence-package-manifest.json"
            package_manifest_path.write_text(json.dumps({
                "package_type": "four_scenario_offline_evidence",
                "git_commit": commit,
                "report_count": 8,
                "media_asset_count": 1,
                "media_manifest_sha256": hashlib.sha256(media_manifest_path.read_bytes()).hexdigest(),
            }), encoding="utf-8")

            zip_path = root / "evidence.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                for path in root.rglob("*"):
                    if path.is_file() and path != zip_path:
                        archive.write(path, path.relative_to(root).as_posix())

            result = _verify_evidence(zip_path, root, commit)
            self.assertEqual(result["reports"], 8)
            self.assertEqual(result["media_assets"], 1)

    def test_docs_only_release_can_explicitly_reuse_frozen_acceptance(self) -> None:
        for script_name in ("package_release.ps1", "package_internal_release.ps1"):
            source = (ROOT / "scripts" / script_name).read_text(encoding="utf-8-sig")
            self.assertIn("[switch]$ReuseValidatedAcceptanceEvidence", source)
            self.assertIn("if ($ReuseValidatedAcceptanceEvidence)", source)
            self.assertIn("_verify_current_four_scenario_acceptance", source)
            self.assertIn("pre_release_internal_validation.ps1", source)

    def test_customer_package_includes_customer_release_notes_and_package_layout(self) -> None:
        customer = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")

        for path in (
            "docs\\release\\2026-08-18-customer-update-notes.md",
            "docs\\release\\2026-08-18-package-layout.md",
        ):
            self.assertIn(f'Copy-File "{path}"', customer)
        self.assertIn('"docs/release/2026-08-18-customer-update-notes.md"', verifier)
        self.assertIn('"docs/release/2026-08-18-package-layout.md"', verifier)


if __name__ == "__main__":
    unittest.main()
