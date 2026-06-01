@echo off
REM Starts the Trezo web app on http://localhost:3000
REM Auto-restarts on crash so a Next dev-server hiccup doesn't take
REM the dashboard offline mid-trading. Mike 2026-06-01.

cd /d "%~dp0"
title Trezo - Web (port 3000)

set RESTART_COUNT=0

:retry
echo.
echo === Freeing port 3000 ===
call "%~dp0_freeport.bat" 3000

echo === Starting Next dev (attempt %RESTART_COUNT%) ===
npm run dev:web

set /a RESTART_COUNT=%RESTART_COUNT% + 1
echo.
echo --- web server exited (restart count: %RESTART_COUNT%) ---
echo Restarting in 5 seconds. Close this window to stop.
timeout /t 5 >nul
goto retry
