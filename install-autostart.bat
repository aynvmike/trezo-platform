@echo off
REM Registers Trezo to auto-launch at Windows logon.
REM
REM Creates a Task Scheduler entry named "Trezo Auto-Start" that
REM runs start-all.bat whenever you sign in. So you never have to
REM remember to start the platform - it's running before you open
REM the browser.
REM
REM To remove: run uninstall-autostart.bat
REM Mike 2026-06-01.

setlocal
set TASK_NAME=Trezo Auto-Start
set START_SCRIPT=%~dp0start-all.bat

echo.
echo === Trezo Auto-Start install ===
echo Task name:  %TASK_NAME%
echo Launches:   %START_SCRIPT%
echo Trigger:    Windows logon (your user account)
echo.

REM Delete any existing task with the same name (idempotent install).
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
  echo Removing previous registration...
  schtasks /delete /tn "%TASK_NAME%" /f >nul
)

REM Register. /sc onlogon = trigger at logon. /rl highest = run with
REM elevated privileges so it can free ports. /it = run only when the
REM user is logged in (no SYSTEM-account weirdness).
schtasks /create /tn "%TASK_NAME%" /tr "\"%START_SCRIPT%\"" /sc onlogon /rl highest /it /f

if errorlevel 1 (
  echo.
  echo ERROR: schtasks failed. Try running this script as Administrator
  echo        ^(right-click ^> Run as administrator^).
  pause
  exit /b 1
)

echo.
echo === Done ===
echo Trezo will auto-start the next time you sign in.
echo To verify: open Task Scheduler ^> Task Scheduler Library ^> Trezo Auto-Start
echo To remove: run uninstall-autostart.bat
pause
endlocal
