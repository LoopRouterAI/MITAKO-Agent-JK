@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO POC] 正在运行甲方新增需求独立 POC...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\customer_agent_expansion\demo.py"
) else (
  python ".\poc\customer_agent_expansion\demo.py"
)

if errorlevel 1 (
  echo [MITAKO POC] 验收失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO POC] 验收通过。
pause
