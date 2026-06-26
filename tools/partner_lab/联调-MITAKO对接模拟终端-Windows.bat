@echo off
chcp 65001 >nul
title MITAKO 联调模式 — 对接甲方模拟终端
cd /d "%~dp0..\.."

echo ===================================================
echo   1. 启动甲方模拟终端 (9101/9102/9103)
echo   2. 写入 bpo-east OIDC 联调配置
echo   3. 以 Live Chatwoot + OIDC 模式启动 MITAKO
echo ===================================================

if exist venv\Scripts\python.exe (
  set PY=venv\Scripts\python.exe
) else (
  set PY=python
)

start "Mock-IdP-9101" cmd /k "cd /d %~dp0..\.. && %PY% tools\partner_lab\mock_idp_server.py"
start "Mock-Chatwoot-9102" cmd /k "cd /d %~dp0..\.. && %PY% tools\partner_lab\mock_chatwoot_server.py"
start "Mock-Biz-9103" cmd /k "cd /d %~dp0..\.. && %PY% tools\partner_lab\mock_business_api.py"
timeout /t 2 >nul

echo [seed] bpo-east OIDC -> Mock IdP ...
%PY% scripts\seed_lab_tenant.py

echo [kill] 释放 8000 ...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kill_mitako_ports.ps1
timeout /t 2 >nul

echo [env] MITAKO 联调环境 ...
set APP_PORT=8000
set ALLOW_PORT_FALLBACK=0
set HANDOFF_BACKEND=hybrid
set MITAKO_SSO_DEMO=0
set MITAKO_AUTH_REQUIRED=0
set CHATWOOT_MOCK=0
set CHATWOOT_BASE_URL=http://127.0.0.1:9102
set CHATWOOT_API_TOKEN=lab-token
set CHATWOOT_ACCOUNT_ID=1
set CHATWOOT_INBOX_ID=1

echo [start] MITAKO main.py ...
start "MITAKO-Lab" cmd /k "cd /d %~dp0..\.. && set APP_PORT=8000&& set HANDOFF_BACKEND=hybrid&& set MITAKO_SSO_DEMO=0&& set CHATWOOT_MOCK=0&& set CHATWOOT_BASE_URL=http://127.0.0.1:9102&& set CHATWOOT_API_TOKEN=lab-token&& set CHATWOOT_ACCOUNT_ID=1&& set CHATWOOT_INBOX_ID=1&& %PY% main.py"
timeout /t 5 >nul

echo [test] 自联调脚本 ...
%PY% tools\partner_lab\self_integration_test.py
set RC=%ERRORLEVEL%

echo.
echo Chatwoot 事件日志: http://127.0.0.1:9102/events
echo Admin SSO 测试:   http://127.0.0.1:8000/admin  (租户 bpo-east)
echo 日常开发请用:     一键启动-Windows.bat
echo.
if %RC% neq 0 (
  echo [FAIL] self_integration_test 未全通过
  pause
  exit /b 1
)
echo [OK] 联调自测通过
pause
