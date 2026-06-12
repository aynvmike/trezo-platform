@echo off
REM clean-slate-backup-wipe.bat
REM Calls clean-slate-backup-wipe.ps1.
REM Archives audit data, tests Mem0 push, wipes agent_messages.
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0clean-slate-backup-wipe.ps1"
echo.
pause
exit /b 0
