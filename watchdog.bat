@echo off
REM Trezo health watchdog. Polls /health every 30 seconds.
REM
REM When a port stops responding:
REM   - Kills the listening process (covers silent hangs that the
REM     in-bat restart loop can't detect)
REM   - Launches the relevant start script in a new window
REM
REM Run this alongside start-all.bat in its own window when you want
REM belt-and-suspenders durability. Optional - the restart loops in
REM start-agents.bat / start-web.bat already handle clean crashes.
REM Mike 2026-06-01.

cd /d "%~dp0"
title Trezo - Watchdog

set INTERVAL=30
set AGENTS_URL=http://localhost:8001/health
set WEB_URL=http://localhost:3000

:loop
REM Check agents
curl -s -o nul -m 5 -w "%%{http_code}" "%AGENTS_URL%" > "%TEMP%\trezo_agents_status.txt"
set /p AGENTS_STATUS=<"%TEMP%\trezo_agents_status.txt"
if not "%AGENTS_STATUS%"=="200" (
  echo [%TIME%] AGENTS DOWN ^(status=%AGENTS_STATUS%^). Restarting...
  call "%~dp0_freeport.bat" 8001
  start "Trezo - Agents (port 8001)" cmd /k "%~dp0start-agents.bat"
)

REM Check web. Next dev server returns 200 on / when alive.
curl -s -o nul -m 5 -w "%%{http_code}" "%WEB_URL%" > "%TEMP%\trezo_web_status.txt"
set /p WEB_STATUS=<"%TEMP%\trezo_web_status.txt"
if not "%WEB_STATUS%"=="200" (
  echo [%TIME%] WEB DOWN ^(status=%WEB_STATUS%^). Restarting...
  call "%~dp0_freeport.bat" 3000
  start "Trezo - Web (port 3000)" cmd /k "%~dp0start-web.bat"
)

if "%AGENTS_STATUS%"=="200" if "%WEB_STATUS%"=="200" (
  echo [%TIME%] Both services healthy. Next check in %INTERVAL%s.
)

timeout /t %INTERVAL% >nul
goto loop
