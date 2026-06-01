@echo off
REM Removes the Trezo Auto-Start Task Scheduler entry.

set TASK_NAME=Trezo Auto-Start

echo.
echo === Removing %TASK_NAME% ===
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if errorlevel 1 (
  echo Task "%TASK_NAME%" is not registered. Nothing to remove.
  pause
  exit /b 0
)

schtasks /delete /tn "%TASK_NAME%" /f
if errorlevel 1 (
  echo.
  echo ERROR: schtasks /delete failed. Try running this script as
  echo        Administrator ^(right-click ^> Run as administrator^).
  pause
  exit /b 1
)

echo.
echo Done. Trezo will not auto-start at logon anymore.
echo You can still launch manually via start-all.bat.
pause
