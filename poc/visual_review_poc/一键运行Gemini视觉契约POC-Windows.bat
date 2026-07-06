@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO Gemini 视觉 POC] 正在验证 Gemini 结构化输出契约...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\gemini_adapter.py"
) else (
  python ".\poc\visual_review_poc\gemini_adapter.py"
)

if errorlevel 1 (
  echo [MITAKO Gemini 视觉 POC] 验收失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO Gemini 视觉 POC] 验收通过。
pause
