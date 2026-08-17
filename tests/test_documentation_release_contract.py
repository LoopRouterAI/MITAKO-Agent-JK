# -*- coding: utf-8 -*-
from pathlib import Path

from scripts.check_documentation_release import REQUIRED_FILES


ROOT = Path(__file__).resolve().parents[1]


def test_documentation_gate_uses_current_four_scene_contract_not_historical_delivery_notes() -> None:
    required = set(REQUIRED_FILES)

    assert "docs/product/四场景审核业务决策与报告契约-20260812.md" in required
    assert "docs/product/四场景审核主线进度-20260814.md" in required
    assert "docs/product/四场景黄金审核经验/README.md" in required
    assert "甲方沟通交付文档/0817四场景审核业务理解与发布验收说明.html" in required
    assert "甲方沟通交付文档/0817四场景八份审核报告质量索引.html" in required
    assert "甲方沟通交付文档/0817甲方技术对接与私有化部署说明.html" in required
    assert not any(
        Path(item).name.startswith(("0717", "0722", "0723", "0728"))
        for item in required
    )


def test_documentation_gate_checks_current_release_allowlist_markers() -> None:
    source = (ROOT / "scripts/check_documentation_release.py").read_text(encoding="utf-8")

    assert "review_0816_four_scenario_blind_results_latest.json" in source
    assert "0817四场景审核业务理解与发布验收说明.html" in source
    assert "0817四场景八份审核报告质量索引.html" in source
    assert "0728 最新" not in source
    assert "$obsoleteCustomerDocs" not in source
