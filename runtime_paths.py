# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def app_root() -> Path:
    return Path(os.getenv("MITAKO_APP_ROOT") or ROOT_DIR).resolve()


def data_dir() -> Path:
    return Path(os.getenv("MITAKO_DATA_DIR") or app_root() / "data").resolve()


def db_path(env_name: str, filename: str) -> Path:
    return Path(os.getenv(env_name) or data_dir() / filename).resolve()


def mock_data_file() -> Path:
    return Path(os.getenv("MITAKO_MOCK_DATA_FILE") or app_root() / "mock_data.json").resolve()


def viking_memory_dir() -> Path:
    explicit = os.getenv("MITAKO_VIKING_MEMORY_DIR")
    if explicit:
        return Path(explicit).resolve()
    if os.getenv("MITAKO_DATA_DIR"):
        return (data_dir() / "viking_memory").resolve()
    return (app_root() / "viking_memory").resolve()
