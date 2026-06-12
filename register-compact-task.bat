@echo off
REM register-compact-task.bat
REM Creates Windows Scheduled Task running compact-scheduled.ps1
REM DAILY at 5:00 PM (after US market close). Runs unattended.
REM Right-click + Run as Administrator the FIRST time only.

setlocal
cd /d "%~dp0"
set "TASKNAME=TrezoCompactToMem0Daily"
set "SCRIPT=%~dp0compact-scheduled.ps1"

echo Registering scheduled task: %TASKNAME%
echo Script: %SCRIPT%
echo Schedule: every day at 5:00 PM (local time)
echo.

schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

schtasks /Create ^
  /TN "%TASKNAME%" ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File \"%SCRIPT%\"" ^
  /SC DAILY ^
  /ST 17:00 ^
  /F ^
  /RL HIGHEST

if errorlevel 1 (
  echo.
  echo ERROR: scheduled task creation failed.
  echo If "Access is denied": right-click the .bat and "Run as Administrator".
  pause
  exit /b 1
)

echo.
echo === Done ===
echo Compaction will run every day at 5:00 PM.
echo Logs: %~dp0logs\compact-YYYY-MM-DD.log
echo Archives: %~dp0archives\
echo.
echo To verify:   schtasks /Query /TN %TASKNAME%
echo To delete:   schtasks /Delete /TN %TASKNAME% /F
echo.
pause
endlocal
exit /b 0
