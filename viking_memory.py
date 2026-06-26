# -*- coding: utf-8 -*-
"""OpenViking 本地虚拟文件系统 — 客服 Agent 与 Companion 共用"""
from __future__ import annotations

import json
import os

try:
    import openviking  # noqa: F401

    HAS_OPENVIKING = True
except ImportError:
    HAS_OPENVIKING = False


class MockOpenViking:
    """本地实现的虚拟文件系统 (viking://)，支持 L0/L1/L2 自动分层加载"""

    def __init__(self, base_dir: str = "viking_memory"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self._init_default_data()

    def _init_default_data(self) -> None:
        mock_data_path = os.path.join(os.path.dirname(__file__), "mock_data.json")
        if os.path.exists(mock_data_path):
            try:
                with open(mock_data_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
                    for user_id, profile in db.get("users", {}).items():
                        profile_uri = f"viking://user/{user_id}/profile"
                        if not self.exists(profile_uri):
                            self.write_json(
                                profile_uri,
                                {
                                    "user_id": user_id,
                                    "nickname": profile.get("nickname"),
                                    "metadata": {
                                        "member_level": profile.get("member_level"),
                                        "total_spent": profile.get("total_spent"),
                                        "favorite_ips": profile.get("favorite_ips"),
                                        "favorite_characters": [],
                                        "registration_date": "2024-01-01",
                                    },
                                    "communication_preferences": profile.get("communication_preferences", {}),
                                    "behavior_patterns": {
                                        "avg_emotion_level": 2.0,
                                        "inquiry_frequency": "normal",
                                        "complaint_count": 0,
                                        "compensations": [],
                                    },
                                    "chat_history": [],
                                },
                            )
            except Exception as e:
                print(f"[OpenViking] 初始化 Mock 用户画像失败: {e}")

        case_uri = "viking://user/usr_001/cases/case_001"
        if not self.exists(case_uri):
            self.write_json(
                case_uri,
                {
                    "case_id": "case_001",
                    "title": "2024年6月盲盒出荷延期客诉",
                    "status": "resolved",
                    "detail": "用户曾因排球少年盲盒出荷延期120天发起激烈投诉。后通过发放优惠券解决。该用户情绪阈值较低，对官方腔回复极度敏感，偏好口语化人设沟通。",
                    "created_at": "2024-10-01",
                },
            )

    def _resolve_path(self, uri: str) -> str:
        rel_path = uri.replace("viking://", "").strip("/")
        return os.path.join(self.base_dir, rel_path)

    def exists(self, uri: str) -> bool:
        return os.path.exists(self._resolve_path(uri))

    def read_json(self, uri: str) -> dict:
        path = self._resolve_path(uri)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def write_json(self, uri: str, data: dict) -> None:
        path = self._resolve_path(uri)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[OpenViking] 写入虚拟文件失败: {e}")

    def list_dir(self, uri: str) -> list:
        path = self._resolve_path(uri)
        if os.path.exists(path) and os.path.isdir(path):
            try:
                return os.listdir(path)
            except Exception:
                return []
        return []


viking_db = MockOpenViking()
