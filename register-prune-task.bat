@echo off
REM register-prune-task.bat
REM Creates a Windows Scheduled Task that runs prune-scheduled.ps1
REM every 3 hours, unattended. Logs go to logs\prune-YYYY-MM-DD.log.
REM Run ONCE (right-click, Run as Administrator).

setlocal
cd /d "%~dp0"

set "TASKNAME=TrezoPruneAgentMessages"
set "SCRIPT=%~dp0prune-scheduled.ps1"

echo Registering scheduled task: %TASKNAME%
echo Script: %SCRIPT%
echo Schedule: every 3 hours, starting in 5 minutes
echo.

REM Delete any prior version of this task (idempotent)
schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

REM Create the new task: run as the current user, every 3 hours, no UI
schtasks /Create ^
  /TN "%TASKNAME%" ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File \"%SCRIPT%\"" ^
  /SC HOURLY ^
  /MO 3 ^
  /F ^
  /RL HIGHEST

if errorlevel 1 (
  echo.
  echo ERROR: scheduled task creation failed.
  echo If you got "Access is denied", right-click this .bat and "Run as Administrator".
  pause
  exit /b 1
)

echo.
echo === Done ===
echo The prune will run every 3 hours in the background.
echo Logs: %~dp0logs\prune-YYYY-MM-DD.log
echo.
echo To verify:
echo   schtasks /Query /TN %TASKNAME%
echo To delete (unregister):
echo   schtasks /Delete /TN %TASKNAME% /F
echo.
pause
endlocal
exit /b 0
