@echo off
chcp 65001 >nul
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\run_cs_agent_acceptance.ps1"
exit /b %ERRORLEVEL%
