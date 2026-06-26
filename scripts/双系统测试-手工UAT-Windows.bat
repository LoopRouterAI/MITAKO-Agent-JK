@echo off
chcp 65001 >nul
title MITAKO 双系统手工 UAT
cd /d "%~dp0.."

echo ===================================================
echo   双系统手工 UAT — 启动服务并打开五端
echo   详细步骤: docs\delivery\testing-guide.md
echo ===================================================

if not exist venv\Scripts\python.exe (
  echo [错误] 请先运行 setup_venv.bat
  pause
  exit /b 1
)

set PY=venv\Scripts\python.exe

echo [1/6] 释放端口 ...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\kill_mitako_ports.ps1

echo [2/6] 构建前端 ...
call npm run build
if errorlevel 1 (
  pause
  exit /b 1
)

echo [3/6] 初始化账号 ...
%PY% scripts\seed_auth.py

echo [4/6] 启动 MITAKO（开发模式 Mock Chatwoot）...
set APP_PORT=8000
set ALLOW_PORT_FALLBACK=0
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
set MITAKO_AUTH_REQUIRED=0
start "MITAKO-UAT" cmd /k "cd /d %~dp0.. && set APP_PORT=8000&& set HANDOFF_BACKEND=hybrid&& set CHATWOOT_MOCK=1&& set MITAKO_AUTH_REQUIRED=0&& %PY% main.py"
timeout /t 5 >nul

echo [5/6] 快速冒烟 ...
%PY% scripts\dual_system_smoke_test.py
set SMOKE=%ERRORLEVEL%

echo [6/6] 打开五端浏览器 ...
start http://127.0.0.1:8000/
timeout /t 1 >nul
start http://127.0.0.1:8000/desk
timeout /t 1 >nul
start http://127.0.0.1:8000/admin
timeout /t 1 >nul
start http://127.0.0.1:8000/companion
timeout /t 1 >nul
start http://127.0.0.1:8000/companion-desk

echo.
echo -------- 账号速查 --------
echo 系统 A  用户端 /           无需登录
echo 系统 A  坐席台 /desk       desk0816 / desk123
echo 系统 A  运营台 /admin      admin / admin123  |  supervisor / super123
echo 系统 B  /companion         Onboarding 后使用
echo 系统 B  /companion-desk    comp_ops / comp123
echo.
echo 手工清单见 testing-guide.md 第 3、4 节
echo 验收勾选见 docs\delivery\acceptance-checklist-v1.md 第三节
echo.
if %SMOKE% neq 0 (
  echo [WARN] 冒烟未全通过，请查看上方 FAIL 项
  pause
  exit /b 1
)
echo [OK] 服务已就绪，请按指南完成手工 UAT
pause
