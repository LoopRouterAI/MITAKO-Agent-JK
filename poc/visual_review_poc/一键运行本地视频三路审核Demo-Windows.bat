@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo [MITAKO] 开始运行 Gemini 3.5 Flash 单样本审核 Demo...
echo [MITAKO] 用法：可传入本地视频路径，例如：
echo [MITAKO]   poc\visual_review_poc\一键运行本地视频三路审核Demo-Windows.bat D:\demo\sample.mp4
echo [MITAKO] 不传视频路径时，会使用甲方授权 sample_001；报告不会输出 .env 密钥。

if "%~1"=="" (
  python poc\visual_review_poc\local_video_triage_demo.py --video "docs\三大审核场景的小量样本\sample_001\005_cWKxEnRn.mp4" --fps 1 --max-frames 12 --api-frame-limit 12 --probe-seconds 0
) else (
  python poc\visual_review_poc\local_video_triage_demo.py --video "%~1" --fps 1 --max-frames 12 --api-frame-limit 12 --probe-seconds 0
)

if errorlevel 1 (
  echo [MITAKO] Gemini 3.5 Flash 单样本审核 Demo 运行失败，请查看上方错误日志。
  pause
  exit /b 1
)

echo [MITAKO] Gemini 3.5 Flash 单样本审核 Demo 完成，请打开终端输出中的 html_report 路径。
pause
endlocal
