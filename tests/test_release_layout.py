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


if __name__ == "__main__":
    unittest.main()
