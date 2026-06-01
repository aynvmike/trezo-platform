@echo off
REM Starts the Trezo agents service on http://localhost:8001
REM Auto-restarts on crash. The :retry loop comes back up after a
REM short backoff so a transient uvicorn death doesn't stop trading.
REM Mike 2026-06-01.

cd /d "%~dp0agents"
title Trezo - Agents (port 8001)

if not exist ".venv\Scripts\uvicorn.exe" (
  echo ERROR: agents\.venv not found. Run setup.bat first.
  pause
  exit /b 1
)

set RESTART_COUNT=0

:retry
echo.
echo === Freeing port 8001 ===
call "%~dp0_freeport.bat" 8001

echo === Clearing __pycache__ ===
for /d /r "%~dp0agents\app" %%d in (__pycache__) do (
  if exist "%%d" rmdir /s /q "%%d"
)

echo === Starting uvicorn (attempt %RESTART_COUNT%) ===
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8001

set /a RESTART_COUNT=%RESTART_COUNT% + 1
echo.
echo --- uvicorn exited (restart count: %RESTART_COUNT%) ---
echo Restarting in 5 seconds. Close this window to stop.
timeout /t 5 >nul
goto retry
