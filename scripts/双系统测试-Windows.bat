@echo off
chcp 65001 >nul
title MITAKO 双系统测试入口
cd /d "%~dp0.."

:menu
cls
echo ===================================================
echo   MITAKO 双系统测试入口
echo   指南: docs\delivery\testing-guide.md
echo ===================================================
echo.
echo   [1] 手工 UAT — 启动服务 + 打开五端 + 冒烟
echo   [2] 自动化 E2E — 全量 Playwright/API 回归
echo   [3] 快速冒烟 — 仅 API/页面（需服务已启动）
echo   [4] 甲方联调 — Mock IdP/Chatwoot + Live 自测
echo   [5] 全链路 — E2E + 联调（发版前推荐）
echo   [0] 退出
echo.
set /p CHOICE=请选择 [0-5]:

if "%CHOICE%"=="1" goto uat
if "%CHOICE%"=="2" goto e2e
if "%CHOICE%"=="3" goto smoke
if "%CHOICE%"=="4" goto lab
if "%CHOICE%"=="5" goto full
if "%CHOICE%"=="0" exit /b 0
goto menu

:uat
call "%~dp0双系统测试-手工UAT-Windows.bat"
goto menu

:e2e
call "%~dp0双系统测试-自动化-Windows.bat"
goto menu

:smoke
if not exist venv\Scripts\python.exe (
  echo [错误] 请先 setup_venv.bat
  pause
  goto menu
)
venv\Scripts\python.exe scripts\dual_system_smoke_test.py
pause
goto menu

:lab
call "%~dp0..\tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat"
goto menu

:full
call "%~dp0双系统测试-全链路-Windows.bat"
goto menu
