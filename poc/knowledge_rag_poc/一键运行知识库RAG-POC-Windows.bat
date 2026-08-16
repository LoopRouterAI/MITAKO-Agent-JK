@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0..\.."
echo [MITAKO 知识库 RAG POC] 正在验证客户自维护知识库 / 检索 / 引用回答...

if exist ".\venv\Scripts\python.exe" (
  ".\venv\Scripts\python.exe" ".\poc\knowledge_rag_poc\demo.py"
) else (
  python ".\poc\knowledge_rag_poc\demo.py"
)

if errorlevel 1 (
  echo [MITAKO 知识库 RAG POC] 验收失败，请查看上方错误信息。
  pause
  exit /b 1
)

echo [MITAKO 知识库 RAG POC] 验收通过。
pause
