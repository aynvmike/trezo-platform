@echo off
REM install-web-as-service.bat
REM Installs the Trezo DASHBOARD (port 3000) as a Windows Service via
REM NSSM, mirroring what install-as-service.bat does for the agents.
REM Run ONCE as Administrator.
REM
REM Mike 2026-08-18: the web tier used to be a console window started
REM by the "Trezo Auto-Start" task (/sc onlogon /it), so it died the
REM moment nobody was signed in - dashboard unreachable over Tailscale
REM while the engine kept trading. As a service it starts at BOOT,
REM survives logoff, and NSSM auto-restarts it on crash.
REM
REM NOTE: this runs `next dev`, deliberately. The deploy path
REM (git pull -> restart) picks up code changes with no build step
REM that way. Switching to `next build` + `next start` is faster and
REM more robust, but then the deploy flow MUST run build:web first or
REM you will silently serve a stale bundle. Left as a later phase.

setlocal
cd /d "%~dp0"

set "SERVICE=TrezoWeb"
set "PORT=3000"

REM --- locate nssm ---
set "NSSM="
if exist "C:\ProgramData\chocolatey\bin\nssm.exe" set "NSSM=C:\ProgramData\chocolatey\bin\nssm.exe"
if not defined NSSM (
  for /f "delims=" %%i in ('where nssm.exe 2^>nul') do set "NSSM=%%i"
)
if not defined NSSM (
  echo ERROR: nssm.exe not found.
  echo Install with:  choco install nssm
  echo Then re-run this script as Administrator.
  pause
  exit /b 1
)
echo Using NSSM: %NSSM%

REM --- locate node ---
set "NODE="
for /f "delims=" %%i in ('where node.exe 2^>nul') do set "NODE=%%i"
if not defined NODE (
  echo ERROR: node.exe not found on PATH.
  pause
  exit /b 1
)
echo Using Node: %NODE%

set "NEXTBIN=%~dp0web\node_modules\next\dist\bin\next"
if not exist "%NEXTBIN%" (
  echo ERROR: next binary not found at %NEXTBIN%
  echo Run: npm install
  pause
  exit /b 1
)

REM --- stop the legacy console-window autostart so we do not end up
REM     with two things fighting over port 3000 ---
echo.
echo Disabling the old logon-triggered autostart task if present...
schtasks /query /tn "Trezo Auto-Start" >nul 2>&1
if not errorlevel 1 (
  schtasks /change /tn "Trezo Auto-Start" /disable >nul 2>&1
  echo   "Trezo Auto-Start" disabled ^(it also started the agents, which
  echo   are already an NSSM service, so nothing is lost^).
) else (
  echo   not registered - nothing to do
)

REM --- free the port so install can bind cleanly ---
echo Freeing port %PORT%...
call "%~dp0_freeport.bat" %PORT%

REM --- (re)install the service ---
"%NSSM%" stop %SERVICE% >nul 2>&1
"%NSSM%" remove %SERVICE% confirm >nul 2>&1

REM SECURITY (Mike 2026-08-18): -H 0.0.0.0 makes the dashboard listen on
REM EVERY interface, including the Lightsail PUBLIC IP. That is how it
REM behaves today, so this preserves current behaviour - but confirm the
REM Lightsail firewall does NOT expose 3000 to the internet. Tailscale
REM should be the only path in. If you want belt-and-braces, swap
REM 0.0.0.0 for the Tailscale address 100.115.119.32.
"%NSSM%" install %SERVICE% "%NODE%" "%NEXTBIN%" "dev" "-H" "0.0.0.0" "-p" "%PORT%"
"%NSSM%" set %SERVICE% AppDirectory "%~dp0web"
"%NSSM%" set %SERVICE% DisplayName "Trezo Dashboard (web)"
"%NSSM%" set %SERVICE% Description "Trezo Next.js dashboard on port %PORT%"
"%NSSM%" set %SERVICE% Start SERVICE_AUTO_START
"%NSSM%" set %SERVICE% AppStdout "%~dp0logs\web-service.log"
"%NSSM%" set %SERVICE% AppStderr "%~dp0logs\web-service.err"
"%NSSM%" set %SERVICE% AppRotateFiles 1
"%NSSM%" set %SERVICE% AppRotateBytes 10485760
"%NSSM%" set %SERVICE% AppExit Default Restart
"%NSSM%" set %SERVICE% AppRestartDelay 5000
"%NSSM%" set %SERVICE% AppStopMethodSkip 6
"%NSSM%" set %SERVICE% NODE_ENV development

"%NSSM%" start %SERVICE%

echo.
echo === Installed and started ===
echo Service: %SERVICE%
echo Logs:    %~dp0logs\web-service.log
echo Manage:  "%NSSM%" restart %SERVICE%
echo          "%NSSM%" status  %SERVICE%
echo.
echo Give it ~45s to compile the first route, then browse to:
echo   http://100.115.119.32:%PORT%
echo.
echo Next step: run register-web-watchdog-task.bat (also as Admin) so a
echo watchdog catches silent hangs that NSSM cannot see.
echo.
pause
endlocal
exit /b 0
