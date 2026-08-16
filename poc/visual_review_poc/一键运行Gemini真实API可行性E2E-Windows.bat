@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO Gemini 真实 API E2E] 正在下载公开素材并检查 Gemini API...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\e2e_real_api_report.py"
) else (
  python ".\poc\visual_review_poc\e2e_real_api_report.py"
)

if errorlevel 1 (
  echo [MITAKO Gemini 真实 API E2E] 运行失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO Gemini 真实 API E2E] 运行完成。
pause
