@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."
echo [MITAKO] 开始下载视觉审核 POC 公开视频样例...
echo [MITAKO] 公开视频只用于验证本地视频读取、抽帧和模型调用链路，不代表甲方业务准确率。
python poc\visual_review_poc\download_public_samples.py --scenario all
if errorlevel 1 (
  echo [MITAKO] 公开视频下载没有全部成功。可直接用本地授权视频运行 local_video_triage_demo.py --video 路径。
  exit /b 1
)
echo [MITAKO] 公开视频样例下载完成，清单见 poc\visual_review_poc\sample_videos\download_manifest.json
endlocal
