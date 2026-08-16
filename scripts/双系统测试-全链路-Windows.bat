@echo off
chcp 65001 >nul
title MITAKO 双系统全链路测试
cd /d "%~dp0.."

echo ===================================================
echo   双系统全链路: 自动化 E2E + 甲方联调实验室
echo   指南: docs\delivery\testing-guide.md 第 2、6 节
echo ===================================================

echo.
echo ===== [1/2] 自动化 E2E =====
call "%~dp0run_all_e2e.bat"
if errorlevel 1 (
  echo [FAIL] E2E 阶段失败，已中止
  pause
  exit /b 1
)

echo.
echo ===== [2/2] 甲方模拟终端联调 =====
call "%~dp0..\tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat"
set RC=%ERRORLEVEL%

if %RC% neq 0 (
  echo [FAIL] 联调阶段未通过
  pause
  exit /b 1
)

echo.
echo [OK] 双系统全链路测试通过（E2E + 联调实验室）
echo 手工 UAT 可选: scripts\双系统测试-手工UAT-Windows.bat
pause
exit /b 0
