@echo off
REM =====================================================================
REM Trezo - Install agent Python deps INTO the venv (not system Python)
REM
REM Use after editing agents\requirements.txt, or whenever the agents
REM service starts up missing something like yfinance.
REM =====================================================================

cd /d "%~dp0agents"
title Trezo - Install agent deps

if not exist ".venv\Scripts\pip.exe" (
  echo .venv not found. Creating it now...
  python -m venv .venv
  if errorlevel 1 (
    echo ERROR: could not create .venv. Is Python installed and on PATH?
    pause
    exit /b 1
  )
)

echo Upgrading pip inside the venv...
".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo Installing agent dependencies into the venv...
".\.venv\Scripts\pip.exe" install -r requirements.txt

echo.
echo =====================================================
echo Done. You can now close this window and double-click
echo start-agents.bat to restart the agents service.
echo =====================================================
pause
