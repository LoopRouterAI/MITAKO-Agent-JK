from __future__ import annotations

import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseLayoutTest(unittest.TestCase):
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

    def test_pre_release_refreshes_dynamic_capacity_evidence_for_current_commit(self) -> None:
        script = (ROOT / "scripts" / "pre_release_internal_validation.ps1").read_text(encoding="utf-8-sig")

        self.assertIn("dynamic_material_capacity_http_latest.json", script)
        self.assertIn("check_dynamic_material_capacity_http.py", script)
        self.assertIn("git_commit", script)
        self.assertIn("requested_count", script)

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
            'Copy-Dir "dist\\memes"',
        ):
            self.assertIn(expected, customer_script)
        self.assertIn('name != "runtime/app_runtime.zip"', verifier)


if __name__ == "__main__":
    unittest.main()
