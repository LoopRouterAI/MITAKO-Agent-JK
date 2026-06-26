@echo off
chcp 65001 >nul
title MITAKO 双系统自动化 E2E
cd /d "%~dp0.."

echo ===================================================
echo   双系统自动化 E2E（L1 全量回归）
echo   报告: tests\reports\*.html
echo   说明: docs\delivery\testing-guide.md 第 2 节
echo ===================================================

call "%~dp0run_all_e2e.bat"
set RC=%ERRORLEVEL%

if %RC% neq 0 (
  echo.
  echo [FAIL] 自动化 E2E 未通过，请打开 tests\reports\ 查看 HTML 报告
  pause
  exit /b 1
)

echo.
echo [OK] 自动化 E2E 全部通过
echo 建议继续: tools\partner_lab\联调-MITAKO对接模拟终端-Windows.bat
pause
exit /b 0
