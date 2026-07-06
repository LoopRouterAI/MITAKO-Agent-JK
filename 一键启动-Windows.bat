@echo off
chcp 65001 >nul
title MITAKO 本地验证启动

cd /d "%~dp0"

echo ===================================================
echo   MITAKO 本地验证环境 - 构建 / 初始化 / 启动
echo ===================================================

if not exist venv\Scripts\python.exe (
    echo [错误] 未找到 venv，请先创建虚拟环境并安装依赖。
    echo        python -m venv venv
    echo        venv\Scripts\python.exe -m pip install -r requirements.txt
    echo        npm install
    pause
    exit /b 1
)

echo [0/5] 释放本地服务端口 ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kill_mitako_ports.ps1"

echo [1/5] 构建前端 ...
call npm run build
if errorlevel 1 exit /b 1

echo [2/5] 初始化租户与账号 ...
venv\Scripts\python.exe scripts\seed_auth.py
if errorlevel 1 exit /b 1

echo [3/5] 写入本地验证环境变量 ...
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
set APP_PORT=8000
set ALLOW_PORT_FALLBACK=0
if "%MITAKO_JWT_SECRET%"=="" set MITAKO_JWT_SECRET=mitako-local-poc-secret-change-before-production
set MITAKO_AUTH_REQUIRED=1
set MITAKO_PROTECTED_API_AUTH_REQUIRED=1
set MITAKO_DEV_AUTH_BYPASS=0
set MITAKO_BUSINESS_DEMO_API_ENABLED=1

echo [4/7] 启动主服务 ...
start "MITAKO Main" venv\Scripts\python.exe main.py

echo 等待服务就绪 ...
for /l %%i in (1,1,30) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/auth/status', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto MITAKO_READY
  timeout /t 1 >nul
)
echo [错误] 主服务未能在 http://127.0.0.1:8000 就绪。
pause
exit /b 1

:MITAKO_READY
echo [5/7] 启动视觉审核工作台 ...
set VISUAL_WORKBENCH_PORT=7861
start "MITAKO Visual Review" venv\Scripts\python.exe -m poc.visual_review_poc.workbench_server

echo 等待视觉审核工作台就绪 ...
for /l %%i in (1,1,30) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:7861/api/health', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto VISUAL_READY
  timeout /t 1 >nul
)
echo [错误] 视觉审核工作台未能在 http://127.0.0.1:7861 就绪。
pause
exit /b 1

:VISUAL_READY
echo [6/7] 启动文档与报告预览服务 ...
start "MITAKO Docs Preview" venv\Scripts\python.exe -m http.server 8790 --bind 127.0.0.1 --directory "%~dp0"

echo [7/7] 打开浏览器 ...
start http://127.0.0.1:8000/
start http://127.0.0.1:7861/
start http://127.0.0.1:8790/甲方沟通交付文档/index.html
start http://127.0.0.1:8790/我方内部开发文档/index.html

echo.
echo 当前入口:
echo   用户客服端:       http://127.0.0.1:8000/
echo   人工客服工作台:   http://127.0.0.1:8000/desk
echo   运营后台:         http://127.0.0.1:8000/admin
echo   视觉审核工作台:   http://127.0.0.1:7861/
echo   甲方交付文档:     http://127.0.0.1:8790/甲方沟通交付文档/index.html
echo   我方开发文档:     http://127.0.0.1:8790/我方内部开发文档/index.html
echo   最新验收报告:     http://127.0.0.1:8790/tests/reports/poc_quality_fix_acceptance_20260705_202300.html
echo.
echo 回归脚本: scripts\run_all_e2e.bat
pause
