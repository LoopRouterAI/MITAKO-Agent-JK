# -*- coding: utf-8 -*-
"""客户自维护知识库/RAG 独立 POC。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from fixtures import EVAL_QUESTIONS, KNOWLEDGE_DOCS
from rag_engine import answer_with_citations, rollback_doc


def build_report() -> Dict[str, Any]:
    answers = [answer_with_citations(item["question"], KNOWLEDGE_DOCS) for item in EVAL_QUESTIONS]
    rolled_back = rollback_doc(KNOWLEDGE_DOCS, "policy_private_domain_draft", "2026-06-30-approved")
    return {
        "goal": "验证甲方自维护客服知识库/RAG 的最小契约",
        "candidate_backend": "WeKnora 或等价企业知识库/RAG 服务",
        "scope": "本 POC 使用本地 fixture 固定检索、引用、回滚契约，不代表已部署 WeKnora",
        "answers": answers,
        "maintenance": {
            "approved_docs_visible": [doc["doc_id"] for doc in KNOWLEDGE_DOCS if doc["approved"]],
            "draft_docs_blocked": [doc["doc_id"] for doc in KNOWLEDGE_DOCS if not doc["approved"]],
            "rollback_example": next(doc for doc in rolled_back if doc["doc_id"] == "policy_private_domain_draft"),
        },
        "acceptance": {
            "status": "passed",
            "next_real_work": [
                "用 WeKnora 接入真实 SOP/FAQ/商品资料样本",
                "准备至少 50 条甲方问题评测集",
                "统计命中率、引用正确率、幻觉率和更新生效时间",
            ],
        },
    }


def self_check(report: Dict[str, Any]) -> None:
    assert len(report["answers"]) == len(EVAL_QUESTIONS), report
    for item, expected in zip(report["answers"], EVAL_QUESTIONS):
        assert item["citations"], item
        assert item["citations"][0]["doc_id"] == expected["expected_doc"], item
        assert expected["must_contain"] in item["answer"], item
        assert item["boundary"].startswith("RAG 只提供"), item
    assert "policy_private_domain_draft" in report["maintenance"]["draft_docs_blocked"], report
    assert report["maintenance"]["rollback_example"]["approved"] is True, report


def main() -> int:
    report = build_report()
    self_check(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("知识库 RAG POC self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
