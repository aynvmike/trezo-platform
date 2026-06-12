@echo off
REM compact-archive-to-mem0.bat
REM Reads the newest archive file in archives\ and pushes COMPACT
REM summaries to Mem0 (rate-limit-safe). Use end of day.
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0compact-archive-to-mem0.ps1"
echo.
pause
exit /b 0
