@echo off
chcp 65001 >nul
title MITAKO 甲方联调实验室
cd /d "%~dp0..\.."

echo ===================================================
echo   甲方模拟终端（IdP / Chatwoot / 业务 API）
echo   与 MITAKO 主代码解耦，仅 HTTP 契约对接
echo ===================================================

start "Mock-IdP-9101" cmd /k "cd /d %~dp0..\.. && python tools\partner_lab\mock_idp_server.py"
start "Mock-Chatwoot-9102" cmd /k "cd /d %~dp0..\.. && python tools\partner_lab\mock_chatwoot_server.py"
start "Mock-Biz-9103" cmd /k "cd /d %~dp0..\.. && python tools\partner_lab\mock_business_api.py"

timeout /t 2 >nul
echo.
echo 已启动:
echo   IdP:      http://127.0.0.1:9101
echo   Chatwoot: http://127.0.0.1:9102/events
echo   业务API:  http://127.0.0.1:9103
echo.
echo 下一步: 运行 scripts\seed_lab_tenant.py 后启动 MITAKO，再运行:
echo   python tools\partner_lab\self_integration_test.py
pause
