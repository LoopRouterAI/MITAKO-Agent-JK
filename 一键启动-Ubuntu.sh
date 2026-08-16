#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==================================================="
echo "  MITAKO 本地验证环境 - 构建 / 初始化 / 启动"
echo "==================================================="

if [ ! -x "venv/bin/python" ]; then
  echo "[错误] 未找到 venv，请先执行："
  echo "       python3 -m venv venv"
  echo "       venv/bin/pip install -r requirements.txt"
  echo "       npm install"
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "[错误] 未找到 ffprobe，Strong/Forensic 媒体取证不可用。"
  echo "       Ubuntu 请执行: sudo apt-get update && sudo apt-get install -y ffmpeg"
  exit 1
fi
echo "[OK] ffprobe: $(command -v ffprobe)"

echo "[1/5] 构建前端 ..."
npm run build

echo "[2/5] 初始化租户与账号 ..."
venv/bin/python scripts/seed_auth.py

echo "[3/5] 写入本地验证环境变量 ..."
export HANDOFF_BACKEND=hybrid
export CHATWOOT_MOCK=1
export APP_PORT=8000
export ALLOW_PORT_FALLBACK=0
export MITAKO_JWT_SECRET="${MITAKO_JWT_SECRET:-$(venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')}"
export MITAKO_AUTH_REQUIRED=1
export MITAKO_PROTECTED_API_AUTH_REQUIRED=1
export MITAKO_DEV_AUTH_BYPASS=0
export MITAKO_BUSINESS_DEMO_API_ENABLED=1

echo "[4/6] 准备启动服务 ..."
echo "[MITAKO] 用户客服端:     http://127.0.0.1:8000/"
echo "[MITAKO] VIP客服工作台: http://127.0.0.1:8000/desk"
echo "[MITAKO] 运营后台:       http://127.0.0.1:8000/admin"
echo "[MITAKO] 视觉审核工作台: http://127.0.0.1:7861/"
echo "[MITAKO] 甲方交付文档:   http://127.0.0.1:8790/甲方沟通交付文档/index.html"
echo "[MITAKO] 我方开发文档:   http://127.0.0.1:8790/我方内部开发文档/index.html"
echo "[MITAKO] 最新验收报告:   http://127.0.0.1:8790/tests/reports/poc_quality_fix_acceptance_20260705_202300.html"
echo "[4/6] 后台启动视觉审核工作台 ..."
VISUAL_WORKBENCH_PORT=7861 venv/bin/python -m poc.visual_review_poc.workbench_server &
VISUAL_PID=$!
echo "[5/6] 后台启动文档与报告预览服务 ..."
venv/bin/python -m http.server 8790 --bind 127.0.0.1 --directory "$(pwd)" &
DOCS_PID=$!
trap 'kill "$VISUAL_PID" "$DOCS_PID" 2>/dev/null || true' EXIT

echo "[6/6] 启动主服务 ..."
exec venv/bin/python main.py
