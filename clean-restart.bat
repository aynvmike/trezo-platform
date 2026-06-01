@echo off
REM =====================================================================
REM Trezo - Clean & restart web dev cache
REM
REM Use when localhost:3000 shows "missing required error components"
REM or you just want a clean Next.js build.
REM
REM 1. Stops any existing web dev process (the one running on port 3000)
REM 2. Deletes web\.next build cache
REM 3. Restarts the web dev server in a new window
REM =====================================================================

cd /d "%~dp0"
title Trezo - Clean restart

echo.
echo === Killing anything on port 3000 ===
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3000 ^| findstr LISTENING') do (
  echo Stopping PID %%a
  taskkill /F /PID %%a >nul 2>&1
)

echo.
echo === Deleting web\.next build cache ===
if exist "web\.next" (
  rmdir /s /q "web\.next"
  echo OK: deleted web\.next
) else (
  echo (nothing to delete)
)

echo.
echo === Starting web dev server in a new window ===
start "Trezo - Web (port 3000)" cmd /k "%~dp0start-web.bat"

echo.
echo Done. The new Web window will say "Ready" in a few seconds —
echo then refresh http://localhost:3000.
echo.
echo Press any key to close this helper window.
pause >nul
