@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title MITAKO 全量 E2E 回归

if not exist venv\Scripts\python.exe (
  echo [错误] 请先创建 venv
  exit /b 1
)

echo [0] 释放端口 ...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kill_mitako_ports.ps1

echo [1] 启动服务 ...
set APP_PORT=8000
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
set MITAKO_AUTH_REQUIRED=0
start "MITAKO-E2E" /MIN venv\Scripts\python.exe main.py
timeout /t 6 >nul

set PY=venv\Scripts\python.exe
set FAIL=0

echo [2] full_pipeline ...
%PY% tests\e2e\run_full_pipeline_e2e.py || set FAIL=1
echo [3] admin_ops ...
%PY% tests\e2e\run_admin_operations_e2e.py || set FAIL=1
echo [4] companion ...
%PY% tests\e2e\run_companion_features_e2e.py || set FAIL=1
echo [5] enterprise ...
%PY% tests\e2e\run_enterprise_production_e2e.py || set FAIL=1

echo [6] 重启 AUTH=1 严格鉴权 ...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kill_mitako_ports.ps1
timeout /t 2 >nul
set MITAKO_AUTH_REQUIRED=1
start "MITAKO-E2E-AUTH" /MIN venv\Scripts\python.exe main.py
timeout /t 6 >nul
echo [7] auth_strict ...
%PY% tests\e2e\run_auth_strict_e2e.py || set FAIL=1

echo.
if "%FAIL%"=="1" (
  echo [FAIL] 存在失败套件，见 tests\reports\
  exit /b 1
)
echo [OK] 全量 E2E 通过，报告: tests\reports\
exit /b 0
