# -*- coding: utf-8 -*-
"""MITAKO App 内可分享资源 — SKU / 文章（Companion 伙伴专用）"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from companion_store import search_products

# 演示文章 — 对应 App 内资讯/攻略
_MOCK_ARTICLES: List[Dict[str, Any]] = [
    {
        "article_id": "ART_001",
        "title": "2024 谷圈入坑：如何理性吃谷不踩坑",
        "summary": "从预售、补款到物流时效，一篇搞懂虾淘下单节奏。",
        "cover": "https://picsum.photos/seed/mitako-art1/400/240",
        "tag": "攻略",
    },
    {
        "article_id": "ART_002",
        "title": "原神周边选购指南：比例手办 vs 吧唧",
        "summary": "不同品类适合什么场景，附虾淘热门 SKU 推荐。",
        "cover": "https://picsum.photos/seed/mitako-art2/400/240",
        "tag": "IP",
    },
    {
        "article_id": "ART_003",
        "title": "排球少年新番联动：登校系列值得冲吗？",
        "summary": "库存、再贩与二级市场走势简析。",
        "cover": "https://picsum.photos/seed/mitako-art3/400/240",
        "tag": "资讯",
    },
]


def list_share_catalog(limit: int = 20) -> Dict[str, Any]:
    skus = search_products("", limit=min(limit, 20))
    articles = _MOCK_ARTICLES[: min(limit, 10)]
    return {"skus": skus, "articles": articles}


def get_share_sku(product_id: str) -> Optional[Dict[str, Any]]:
    pid = (product_id or "").strip().upper()
    for p in search_products("", limit=20):
        if p.get("product_id", "").upper() == pid:
            return {
                "type": "sku",
                "product_id": p["product_id"],
                "name": p["name"],
                "price": p.get("price"),
                "stock": p.get("stock"),
                "image": f"https://picsum.photos/seed/sku-{p['product_id']}/320/320",
                "app_path": f"/app/sku/{p['product_id']}",
            }
    return None


def get_share_article(article_id: str) -> Optional[Dict[str, Any]]:
    aid = (article_id or "").strip().upper()
    for a in _MOCK_ARTICLES:
        if a["article_id"].upper() == aid:
            return {
                "type": "article",
                "article_id": a["article_id"],
                "title": a["title"],
                "summary": a["summary"],
                "cover": a["cover"],
                "tag": a.get("tag"),
                "app_path": f"/app/article/{a['article_id']}",
            }
    return None


def resolve_share_tag(tag: str) -> Optional[Dict[str, Any]]:
    """解析 <share:sku:P001> 或 <share:article:ART_001>"""
    raw = (tag or "").strip().lower()
    if raw.startswith("share:sku:"):
        return get_share_sku(raw.split(":", 2)[-1])
    if raw.startswith("share:article:"):
        return get_share_article(raw.split(":", 2)[-1])
    if raw.startswith("share:"):
        parts = raw.split(":")
        if len(parts) >= 3:
            kind, oid = parts[1], parts[2]
            if kind == "sku":
                return get_share_sku(oid)
            if kind == "article":
                return get_share_article(oid)
    return None
