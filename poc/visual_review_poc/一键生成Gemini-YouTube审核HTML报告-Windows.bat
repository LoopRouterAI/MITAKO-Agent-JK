@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO Gemini YouTube E2E] 正在生成 YouTube 视频审核 HTML 报告...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\e2e_youtube_report.py"
) else (
  python ".\poc\visual_review_poc\e2e_youtube_report.py"
)

if errorlevel 1 (
  echo [MITAKO Gemini YouTube E2E] 运行失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO Gemini YouTube E2E] HTML 报告已生成。
pause
