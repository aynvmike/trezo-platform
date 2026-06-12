@echo off
REM register-watchdog-task.bat
REM Schedules health-watchdog.ps1 every 15 minutes. Right-click + Run
REM as Administrator the FIRST time only.

setlocal
cd /d "%~dp0"
set "TASKNAME=TrezoHealthWatchdog"
set "SCRIPT=%~dp0health-watchdog.ps1"

echo Registering: %TASKNAME%
echo Schedule:    every 15 minutes
echo.

schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

schtasks /Create ^
  /TN "%TASKNAME%" ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File \"%SCRIPT%\"" ^
  /SC MINUTE ^
  /MO 15 ^
  /F ^
  /RL HIGHEST

if errorlevel 1 (
  echo.
  echo ERROR: scheduled task creation failed.
  echo Right-click this .bat and "Run as Administrator".
  pause
  exit /b 1
)

echo.
echo === Done ===
echo Watchdog runs every 15 minutes. Logs:
echo   %~dp0logs\watchdog-YYYY-MM-DD.log
echo.
echo To verify:  schtasks /Query /TN %TASKNAME%
echo To delete:  schtasks /Delete /TN %TASKNAME% /F
echo.
pause
endlocal
exit /b 0
