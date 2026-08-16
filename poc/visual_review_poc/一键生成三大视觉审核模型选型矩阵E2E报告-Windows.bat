@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo [MITAKO] 开始生成两档视觉审核模型选型 E2E 报告...
echo [MITAKO] 本流程会真实请求 Gemini 3.5 Flash Lite 与 Gemini 3.7 Flash 高质量候选。
echo [MITAKO] 同一 Case 的多视频会合并为一个证据包；报告会输出帧数、耗时、Token、估算成本、原始返回和解析结果。
echo [MITAKO] 密钥只从 .env 读取，脚本不会输出密钥值。

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\visual_review_poc\model_selection_e2e.py" --models gemini35lite,gemini37 --concurrency 4 --max-frames-per-video 6 --api-frame-limit 18 --supplemental-image-limit 20 --request-timeout 300 --soft-retries 2
) else (
  python ".\poc\visual_review_poc\model_selection_e2e.py" --models gemini35lite,gemini37 --concurrency 4 --max-frames-per-video 6 --api-frame-limit 18 --supplemental-image-limit 20 --request-timeout 300 --soft-retries 2
)

if errorlevel 1 (
  echo [MITAKO] 报告生成失败，请查看上方错误日志。
  pause
  exit /b 1
)

echo [MITAKO] 报告生成完成，请打开终端输出中的 html_report 路径。
pause
endlocal
