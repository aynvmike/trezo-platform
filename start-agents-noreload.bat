@echo off
REM =====================================================================
REM Trezo - Start agents WITHOUT --reload
REM
REM Use this when start-agents.bat is serving stale code because
REM uvicorn's reload child-process is caching old modules.
REM
REM Tradeoff: you have to manually restart this window after any
REM Python code change. But the runtime is rock-solid — no stale state.
REM =====================================================================

cd /d "%~dp0agents"
title Trezo - Agents (NO RELOAD - port 8001)
call "%~dp0_freeport.bat" 8001

if not exist ".venv\Scripts\uvicorn.exe" (
  echo ERROR: agents\.venv not found. Run setup.bat first.
  pause
  exit /b 1
)

.\.venv\Scripts\uvicorn.exe app.main:app --port 8001 --host 127.0.0.1

echo.
echo --- agents stopped. Press any key to close. ---
pause >nul
