@echo off
REM register-web-watchdog-task.bat
REM Schedules web-watchdog.ps1 every 5 minutes. Right-click and
REM "Run as Administrator" the FIRST time only.
REM
REM Why 5 min and not 15 like the agents watchdog: restarting the
REM dashboard carries zero trading risk, so it can be aggressive.
REM The agents watchdog stays at 15 min on purpose.
REM
REM /RU SYSTEM so it runs whether or not anyone is signed in - which is
REM the entire point, since the old failure was "nobody logged on".
REM Mike 2026-08-18.

setlocal
cd /d "%~dp0"
set "TASKNAME=TrezoWebWatchdog"
set "SCRIPT=%~dp0web-watchdog.ps1"

if not exist "%SCRIPT%" (
  echo ERROR: web-watchdog.ps1 not found next to this script.
  pause
  exit /b 1
)

echo Registering: %TASKNAME%
echo Schedule:    every 5 minutes, as SYSTEM
echo Script:      %SCRIPT%
echo.

schtasks /Delete /TN "%TASKNAME%" /F >nul 2>&1

schtasks /Create ^
  /TN "%TASKNAME%" ^
  /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File \"%SCRIPT%\"" ^
  /SC MINUTE ^
  /MO 5 ^
  /RU SYSTEM ^
  /RL HIGHEST ^
  /F

if errorlevel 1 (
  echo.
  echo ERROR: scheduled task creation failed.
  echo Right-click this .bat and "Run as Administrator".
  pause
  exit /b 1
)

echo.
echo === Done ===
echo Watchdog runs every 5 minutes. Logs:
echo   %~dp0logs\web-watchdog-YYYY-MM-DD.log
echo.
echo Run it once now to confirm it works:
echo   powershell -ExecutionPolicy Bypass -File "%SCRIPT%"
echo.
echo To verify:  schtasks /Query /TN %TASKNAME%
echo To delete:  schtasks /Delete /TN %TASKNAME% /F
echo.
pause
endlocal
exit /b 0
