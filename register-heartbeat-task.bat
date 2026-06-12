@echo off
REM register-heartbeat-task.bat - run ONCE as Administrator.
setlocal
cd /d "%~dp0"
set "TASKNAME=TrezoHeartbeat"
set "SCRIPT=%~dp0heartbeat-check.ps1"

schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1
schtasks /Create /TN "%TASKNAME%" /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File \"%SCRIPT%\"" /SC MINUTE /MO 15 /F /RL HIGHEST

if errorlevel 1 ( echo Failed - run as Admin & pause & exit /b 1 )
echo Done. Heartbeat checks every 15 min. Logs at logs\heartbeat-YYYY-MM-DD.log
pause
