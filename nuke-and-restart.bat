@echo off
REM =====================================================================
REM Trezo - NUCLEAR clean restart
REM
REM Use only when clean-restart.bat didn't fix the issue. This:
REM  1. Kills ALL node.exe processes (any running web/api dev servers)
REM  2. Deletes web\.next AND web\node_modules\.cache
REM  3. Restarts the web server in a fresh window
REM
REM SAFE TO RUN. Doesn't touch your source code or .env files.
REM =====================================================================

cd /d "%~dp0"
title Trezo - Nuke ^& restart

echo.
echo === Killing all node processes ===
taskkill /F /IM node.exe >nul 2>&1
echo OK

echo.
echo === Deleting web\.next ===
if exist "web\.next" rmdir /s /q "web\.next"
echo OK

echo.
echo === Deleting web\node_modules\.cache ===
if exist "web\node_modules\.cache" rmdir /s /q "web\node_modules\.cache"
echo OK

echo.
echo === Starting web dev server ===
start "Trezo - Web (port 3000)" cmd /k "%~dp0start-web.bat"

echo.
echo Done. Wait until the new window says "Ready in Xs" — usually 5-15 sec.
echo Then refresh http://localhost:3000 with Ctrl+Shift+R.
echo.
echo Press any key to close this helper.
pause >nul
