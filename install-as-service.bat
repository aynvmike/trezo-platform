@echo off
REM Task #52 - install Trezo Agents as a Windows Service via NSSM.
REM Run once as Administrator. After this, agents survive logoff +
REM auto-restart on crash + start at system boot.

setlocal
cd /d "%~dp0"

set "SERVICE=TrezoAgents"
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"

REM Check for nssm
where nssm >nul 2>&1
if errorlevel 1 (
  echo NSSM not found. Download + extract from %NSSM_URL%
  echo Then add nssm.exe to your PATH or to C:\Windows\System32
  echo Re-run this script after that.
  pause
  exit /b 1
)

REM Stop + remove existing service
nssm stop %SERVICE% 2>nul
nssm remove %SERVICE% confirm 2>nul

REM Install the service
REM SECURITY (Mike 2026-07-28): --host 0.0.0.0 would publish the TRADING
REM engine on every network interface. The agents API has 15 unauthenticated
REM state-changing endpoints (/admin/manual-trade, /wheel/place-leg,
REM /paper/positions/trim ...) that are safe ONLY because they answer
REM loopback. Bind 127.0.0.1 -- the web app runs on the same machine.
nssm install %SERVICE% "%~dp0agents\.venv\Scripts\python.exe" "-m" "uvicorn" "app.main:app" "--host" "127.0.0.1" "--port" "8001"
nssm set %SERVICE% AppDirectory "%~dp0agents"
nssm set %SERVICE% DisplayName "Trezo Trading Agents"
nssm set %SERVICE% Description "Trezo Layer-by-Layer Trading Bot - FastAPI agents service"
nssm set %SERVICE% Start SERVICE_AUTO_START
nssm set %SERVICE% AppStdout "%~dp0logs\agents-service.log"
nssm set %SERVICE% AppStderr "%~dp0logs\agents-service.err"
REM Kill the ENTIRE process tree on stop (2026-08-19). uvicorn spawns worker
REM processes; without this, nssm kills only the parent and the workers
REM orphan - which is how "nssm restart" kept leaving yesterday's engine
REM running underneath today's. A restart that leaves survivors is a spawn.
nssm set %SERVICE% AppKillProcessTree 1
nssm set %SERVICE% AppRotateFiles 1
nssm set %SERVICE% AppRotateBytes 10485760
nssm set %SERVICE% AppExit Default Restart
nssm set %SERVICE% AppRestartDelay 5000

REM Start
nssm start %SERVICE%

echo.
echo === Installed and started ===
echo Service: %SERVICE%
echo Logs:    %~dp0logs\agents-service.log
echo Manage:  nssm restart %SERVICE%
echo          nssm stop %SERVICE%
echo          nssm remove %SERVICE% confirm
echo.
pause
exit /b 0
