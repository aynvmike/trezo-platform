@echo off
REM Starts the Trezo API on http://localhost:8000
cd /d "%~dp0"
title Trezo - API (port 8000)
call "%~dp0_freeport.bat" 8000
npm run dev:api
echo.
echo --- api server stopped. Press any key to close. ---
pause >nul
