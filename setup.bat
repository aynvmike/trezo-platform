@echo off
REM =====================================================================
REM Trezo - One-click local setup (Windows, click-to-run)
REM
REM Double-click this file in File Explorer. It will:
REM   1. Bypass PowerShell execution policy for this run only
REM   2. Run setup.ps1
REM   3. Keep the window open at the end so you can read the result
REM =====================================================================

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
echo =====================================================
echo Setup finished. Read above for OK or ERROR messages.
echo Press any key to close this window.
echo =====================================================
pause >nul
