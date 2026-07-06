@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."
echo [MITAKO] 启动视觉审核工作台 POC...
echo [MITAKO] 浏览器打开：http://127.0.0.1:7861
echo [MITAKO] 支持本地视频上传和公开视频 URL 下载审核。
python poc\visual_review_poc\workbench_server.py
if errorlevel 1 (
  echo [MITAKO] 工作台启动失败，请检查 fastapi、uvicorn、python-multipart、yt-dlp 是否可用。
  exit /b 1
)
endlocal
