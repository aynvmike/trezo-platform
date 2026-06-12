@echo off
REM Trezo - prune-agent-messages.bat
REM Just calls the .ps1 script with execution policy bypass.
REM All logic lives in prune-agent-messages.ps1 - cleaner that way.
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0prune-agent-messages.ps1"
echo.
pause
exit /b 0
