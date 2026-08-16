@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_all_e2e.ps1"
exit /b %ERRORLEVEL%
