#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

PY="python3"
if [ -x "venv/bin/python" ]; then
  PY="venv/bin/python"
fi

echo "[MITAKO] 启动视觉审核工作台 POC..."
echo "[MITAKO] 浏览器打开：http://127.0.0.1:7861"
echo "[MITAKO] 支持本地视频上传和公开视频 URL 下载审核。"
exec "$PY" poc/visual_review_poc/workbench_server.py
