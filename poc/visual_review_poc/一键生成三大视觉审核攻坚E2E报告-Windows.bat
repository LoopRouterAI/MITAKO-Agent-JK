@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo [MITAKO 三大视觉审核攻坚 E2E] 正在生成多模态模型稳定性对比报告...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\e2e_breakthrough_report.py"
) else (
  python ".\poc\visual_review_poc\e2e_breakthrough_report.py"
)

if errorlevel 1 (
  echo [MITAKO 三大视觉审核攻坚 E2E] 运行失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO 三大视觉审核攻坚 E2E] 报告已生成。
pause
endlocal
