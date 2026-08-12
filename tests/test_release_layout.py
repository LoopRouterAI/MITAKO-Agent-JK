from __future__ import annotations

import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseLayoutTest(unittest.TestCase):
    def test_one_click_startup_generates_runtime_jwt_secret(self) -> None:
        windows = (ROOT / "一键启动-Windows.bat").read_text(encoding="utf-8-sig")
        ubuntu = (ROOT / "一键启动-Ubuntu.sh").read_text(encoding="utf-8-sig")

        for script in (windows, ubuntu):
            self.assertIn("secrets.token_urlsafe(48)", script)
            self.assertNotIn("mitako-local-poc-secret-change-before-production", script)

    def test_all_publishable_files_default_to_dist(self) -> None:
        customer_script = (ROOT / "scripts" / "package_release.ps1").read_text(encoding="utf-8-sig")
        internal_script = (ROOT / "scripts" / "package_internal_release.ps1").read_text(encoding="utf-8-sig")
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        vite_config = (ROOT / "vite.config.js").read_text(encoding="utf-8")

        self.assertIn('$DeliveryDir = Join-Path $Root "dist"', customer_script)
        self.assertIn('$ZipPath = Join-Path $DeliveryDir $ZipName', customer_script)
        self.assertIn('$CustomerHtmlPath = Join-Path $DeliveryDir "MITAKO_Agent-customer-delivery.html"', customer_script)
        self.assertIn('Copy-Item -LiteralPath $CustomerHtmlSource -Destination $CustomerHtmlPath -Force', customer_script)

        self.assertIn('$DeliveryDir = Join-Path $Root "dist"', internal_script)
        self.assertIn('$ZipPath = Join-Path $DeliveryDir "MITAKO_Agent-internal-dev-$Date.zip"', internal_script)

        self.assertIn('ROOT / "dist" / f"MITAKO_Agent-internal-dev-{date}.zip"', verifier)
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
        self.assertIn("$DynamicCapacityEvidencePaths", script)
        self.assertIn("-not $RunModelBatch", script)

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

    def test_customer_acceptance_page_links_to_packaged_0807_guide(self) -> None:
        page = (ROOT / "docs" / "delivery" / "mitako-visual-evaluation-engineering-acceptance-20260716.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('href="mitako-0807-guide-acceptance-20260807.html"', page)
        self.assertIn(
            'href="../../甲方沟通交付文档/0807黄金指南学习与审核能力更新说明.html"',
            page,
        )

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
            '"poc\\visual_review_poc\\native_video_perception.py"',
            '"poc\\visual_review_poc\\secure_media_tunnel.py"',
            '"poc\\visual_review_poc\\internal_review_ledger.py"',
            '"poc\\visual_review_poc\\report_assets.py"',
            '"poc\\visual_review_poc\\report_evidence.py"',
        ):
            self.assertIn(runtime_module, customer_script)
        self.assertIn("imageio_ffmpeg", customer_script)
        self.assertIn("imageio-ffmpeg", customer_script)
        self.assertIn("Cloudflare.cloudflared", customer_script)
        verifier = (ROOT / "scripts" / "check_release_packages.py").read_text(encoding="utf-8-sig")
        self.assertIn('name.endswith("native_video_perception.pyc")', verifier)
        self.assertIn('name.endswith("secure_media_tunnel.pyc")', verifier)
        self.assertIn('name.endswith("internal_review_ledger.pyc")', verifier)
        self.assertIn('name.endswith("report_assets.pyc")', verifier)
        self.assertIn('name.endswith("report_evidence.pyc")', verifier)

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


if __name__ == "__main__":
    unittest.main()
