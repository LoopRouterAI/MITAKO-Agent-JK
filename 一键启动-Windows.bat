@echo off
chcp 65001 >nul
title MITAKO 本地演示启动

cd /d "%~dp0"

echo ===================================================
echo   MITAKO 本地演示环境 - 构建 / 初始化 / 启动
echo ===================================================
echo.

if not exist venv\Scripts\python.exe (
    echo [错误] 未找到 venv，请先创建虚拟环境并安装依赖：
    echo        python -m venv venv
    echo        venv\Scripts\python.exe -m pip install -r requirements.txt
    echo        npm install
    pause
    exit /b 1
)

echo [0/9] 释放本地服务端口...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kill_mitako_ports.ps1"

echo [1/9] 构建前端资源...
call npm run build
if errorlevel 1 (
    echo [错误] 前端构建失败，请查看上方 npm 输出。
    pause
    exit /b 1
)

echo [2/9] 初始化租户与后台账号...
venv\Scripts\python.exe scripts\seed_auth.py
if errorlevel 1 (
    echo [错误] 初始化账号失败。
    pause
    exit /b 1
)

echo [3/9] 写入本地演示环境变量...
set HANDOFF_BACKEND=hybrid
set CHATWOOT_MOCK=1
set APP_PORT=8000
set ALLOW_PORT_FALLBACK=0
if "%MITAKO_JWT_SECRET%"=="" set MITAKO_JWT_SECRET=mitako-local-poc-secret-change-before-production
set MITAKO_AUTH_REQUIRED=1
set MITAKO_PROTECTED_API_AUTH_REQUIRED=1
set MITAKO_DEV_AUTH_BYPASS=0
set MITAKO_BUSINESS_DEMO_API_ENABLED=1

echo [4/9] 检查关键环境变量...
venv\Scripts\python.exe scripts\check_runtime_env.py
if errorlevel 1 (
    echo [错误] 环境变量检查失败。
    pause
    exit /b 1
)

echo [5/9] 写入虾淘私域 Agent 演示数据...
venv\Scripts\python.exe -c "from private_domain import service; result = service.load_demo_data(); print('[MITAKO] 私域演示数据已加载：群=%s，客服任务=%s，审核任务=%s，候选触达=%s' % (result['summary']['groups'], result['summary']['customer_service_tasks'], result['summary']['review_tasks'], result['summary']['campaign_candidates']))"
if errorlevel 1 (
    echo [错误] 私域演示数据加载失败。
    pause
    exit /b 1
)

echo [6/9] 启动主服务...
start "MITAKO Main" venv\Scripts\python.exe main.py

echo 等待主服务就绪...
for /l %%i in (1,1,30) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/auth/status', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto MITAKO_READY
  timeout /t 1 >nul
)
echo [错误] 主服务未能在 http://127.0.0.1:8000 就绪。
pause
exit /b 1

:MITAKO_READY
echo [7/9] 启动视觉审核工作台...
set VISUAL_WORKBENCH_PORT=7861
start "MITAKO Visual Review" venv\Scripts\python.exe -m poc.visual_review_poc.workbench_server

echo 等待视觉审核工作台就绪...
for /l %%i in (1,1,30) do (
  venv\Scripts\python.exe -c "import json,sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:7861/api/health', timeout=2); d=json.loads(r.read().decode('utf-8')); sys.exit(0 if d.get('ok') else 1)" >nul 2>nul
  if not errorlevel 1 goto VISUAL_READY
  timeout /t 1 >nul
)
echo [错误] 视觉审核工作台未能在 http://127.0.0.1:7861 就绪。
pause
exit /b 1

:VISUAL_READY
echo [8/9] 启动文档与报告预览服务...
start "MITAKO Docs Preview" venv\Scripts\python.exe -m http.server 8790 --bind 127.0.0.1 --directory "%~dp0"

echo [9/9] 打开演示入口...
start http://127.0.0.1:8000/
start http://127.0.0.1:8000/admin
start http://127.0.0.1:7861/
start http://127.0.0.1:8790/docs/private_domain_agent_cross_review_20260709.html

echo.
echo 当前入口：
echo   用户 AI 客服端：       http://127.0.0.1:8000/
echo   VIP 客服工作台：       http://127.0.0.1:8000/desk
echo   运营后台：             http://127.0.0.1:8000/admin
echo   私域 Agent：           进入运营后台后点击左侧“私域 Agent”
echo   视觉审核工作台：       http://127.0.0.1:7861/
echo   私域交叉验证报告：     http://127.0.0.1:8790/docs/private_domain_agent_cross_review_20260709.html
echo.
echo 后台演示账号：
echo   账号：admin
echo   密码：admin123
echo.
echo 说明：本地演示数据用于 P0 展示；企微、商品库、订单系统、飞书仍按后台接口契约等待真实权限联调。
pause
