@echo off
REM Launches all three Trezo dev servers in separate windows.
REM Double-click this and three black windows will pop up; leave them running.
cd /d "%~dp0"
start "Trezo Web"    cmd /k "%~dp0start-web.bat"
start "Trezo API"    cmd /k "%~dp0start-api.bat"
start "Trezo Agents" cmd /k "%~dp0start-agents.bat"
echo Started web (port 3000), api (port 8000), agents (port 8001).
echo Open http://localhost:3000 in your browser when "Ready" appears in the Web window.
timeout /t 4 >nul
