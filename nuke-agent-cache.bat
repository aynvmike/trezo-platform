@echo off
REM =====================================================================
REM Trezo - Nuke agent Python bytecode cache and restart
REM
REM Use when uvicorn's reloader serves stale code despite edits — usually
REM after I (Nova) push new agent endpoints. This forces Python to
REM recompile every .py file from source.
REM =====================================================================

cd /d "%~dp0"
title Trezo - Nuke agent cache

echo.
echo === Killing anything on port 8001 ===
call "%~dp0_freeport.bat" 8001

echo.
echo === Killing any leftover python processes from this venv ===
REM Conservative — only kill python.exe processes whose path includes our venv
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe'" get processid^,executablepath /format:csv ^| findstr /i "trezo-platform"') do (
  echo Killing python PID %%p
  taskkill /F /PID %%p >nul 2>&1
)

echo.
echo === Deleting all __pycache__ folders under agents\app ===
for /d /r "%~dp0agents\app" %%d in (__pycache__) do (
  if exist "%%d" (
    echo  removing %%d
    rmdir /s /q "%%d"
  )
)
echo Done deleting cache.

echo.
echo === Starting agents service fresh ===
start "Trezo - Agents (port 8001)" cmd /k "%~dp0start-agents.bat"

echo.
echo Wait 10-15 seconds for the Agents window to print:
echo    agents.bootstrap.complete count=8
echo    Application startup complete.
echo Then refresh http://localhost:8001/docs in your browser.
echo You should now see an "agents" section listing 5 endpoints.
echo.
pause
