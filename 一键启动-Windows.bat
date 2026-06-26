@echo off
chcp 65001 >nul
title MITAKO Agent 一键启动

cd /d "%~dp0"

echo ===================================================
echo   MITAKO 商业生产版 — 构建 / 初始化 / 启动
echo ===================================================

if not exist venv (
    echo [错误] 未找到 venv，请先运行 setup_venv.bat
    pause
    exit /b 1
)

echo [0/5] 释放 8000-8003 端口 ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kill_mitako_ports.ps1"

echo [1/5] 构建前端 ...
call npm run build
if errorlevel 1 exit /b 1

echo [2/5] 初始化租户与账号 ...
venv\Scripts\python.exe scripts\seed_auth.py

echo [3/5] 设置企业 Mock 环境变量（Chatwoot/混合 IM）...
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
set APP_PORT=8000
set ALLOW_PORT_FALLBACK=0

echo [4/5] 启动主服务 ...
start "MITAKO Main" venv\Scripts\python.exe main.py

timeout /t 4 >nul

echo [5/5] 打开浏览器 ...
start http://127.0.0.1:8000/

echo.
echo 入口: /  /desk  /admin  /companion  /companion-desk
echo E2E: venv\Scripts\python.exe tests\e2e\run_enterprise_production_e2e.py
echo 生产鉴权: .env 中 MITAKO_AUTH_REQUIRED=1 后重启
pause
