# -*- coding: utf-8 -*-
"""最小 RAG 契约 POC：固定“检索-引用-回答”字段，后续替换为 WeKnora。"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


def tokenize(text: str) -> List[str]:
    return [item for item in re.split(r"[\s，。、“”！？；：,.!?;:()/\\-]+", text.lower()) if item]


def retrieve(question: str, docs: Iterable[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    query_tokens = set(tokenize(question))
    important_terms = [term for term in ("商品有伤", "划痕", "拒赔", "未成年人", "退款", "物流", "发货", "承诺") if term in question]
    scored: List[Dict[str, Any]] = []
    for doc in docs:
        if not doc.get("approved"):
            continue
        text = f"{doc.get('title', '')} {doc.get('category', '')} {doc.get('content', '')}"
        doc_tokens = set(tokenize(text))
        overlap = query_tokens & doc_tokens
        keyword_hits = [key for key in query_tokens if key and key in text.lower()]
        keyword_hits.extend(term for term in important_terms if term in text)
        score = len(overlap) * 2 + len(keyword_hits)
        if score:
            scored.append({"score": score, "doc": doc, "matched_terms": sorted(overlap | set(keyword_hits))})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def answer_with_citations(question: str, docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    hits = retrieve(question, docs)
    if not hits:
        return {
            "question": question,
            "answer": "当前知识库没有找到可引用依据，建议转人工或主管确认。",
            "confidence": 0,
            "citations": [],
            "needs_human": True,
            "boundary": "RAG 只提供可追溯依据，不执行退款、拒赔、补发或改工单状态。",
        }
    best = hits[0]["doc"]
    confidence = min(0.95, 0.45 + hits[0]["score"] * 0.08)
    return {
        "question": question,
        "answer": _compose_answer(best),
        "confidence": round(confidence, 2),
        "citations": [
            {
                "doc_id": item["doc"]["doc_id"],
                "title": item["doc"]["title"],
                "source": item["doc"]["source"],
                "version": item["doc"]["version"],
                "matched_terms": item["matched_terms"],
            }
            for item in hits
        ],
        "needs_human": confidence < 0.7,
        "boundary": "RAG 只提供可追溯依据，不执行退款、拒赔、补发或改工单状态。",
    }


def _compose_answer(doc: Dict[str, Any]) -> str:
    content = doc["content"]
    if "不得自动拒赔" in content:
        return "不能直接拒赔。应先核对订单和材料，低置信度时转人工复核，不自动拒赔、补发或退款。"
    if "不得自动退款" in content:
        return "不能自动退款。未成年人退款即使材料齐全，也必须人工审批。"
    if "不承诺具体发货日期" in content:
        return "不承诺具体发货日期。应先查询物流状态并生成仓库核查任务，等待反馈后再同步用户。"
    return content


def rollback_doc(docs: List[Dict[str, Any]], doc_id: str, previous_version: str) -> List[Dict[str, Any]]:
    updated = []
    for doc in docs:
        item = dict(doc)
        if item["doc_id"] == doc_id:
            item["version"] = previous_version
            item["approved"] = True
        updated.append(item)
    return updated
