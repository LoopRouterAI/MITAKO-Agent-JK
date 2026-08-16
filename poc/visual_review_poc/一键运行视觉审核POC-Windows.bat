@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO 视觉审核 POC] 正在验证视频审核 / 商品有伤 / 未成年人资料审核...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\demo.py"
) else (
  python ".\poc\visual_review_poc\demo.py"
)

if errorlevel 1 (
  echo [MITAKO 视觉审核 POC] 验收失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO 视觉审核 POC] 验收通过。
pause
