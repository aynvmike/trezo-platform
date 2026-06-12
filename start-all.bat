@echo off
REM ============================================================
REM  Trezo - start-all.bat (v2 - self-healing)
REM ------------------------------------------------------------
REM  Pre-flight check: if a service is ALREADY running healthy
REM  on its port, skip starting another window (which was the
REM  root cause of 2026-06-04's "Trezo - Agents" restart loop -
REM  port 8001 was already held by an earlier manual uvicorn,
REM  the new window kept failing on WinError 10013, retrying
REM  forever).
REM
REM  After this script, you should see up to three new windows:
REM    "Trezo Web"    (port 3000)
REM    "Trezo API"    (port 8000)
REM    "Trezo Agents" (port 8001)
REM  Each window that was already healthy gets SKIPPED.
REM ============================================================

setlocal
cd /d "%~dp0"

echo.
echo === Trezo start-all.bat ===
echo Pre-flight check: are any tiers already running?
echo.

REM -- Check the WEB tier (port 3000) --------------------------
call :is_port_listening 3000
if "%PORT_LIVE%"=="1" (
  echo [SKIP] Web tier already listening on port 3000.
) else (
  echo [START] Web tier - launching new window.
  start "Trezo Web" cmd /k "%~dp0start-web.bat"
)

REM -- Check the API tier (port 8000) --------------------------
call :is_port_listening 8000
if "%PORT_LIVE%"=="1" (
  echo [SKIP] API tier already listening on port 8000.
) else (
  echo [START] API tier - launching new window.
  start "Trezo API" cmd /k "%~dp0start-api.bat"
)

REM -- Check the AGENTS tier (port 8001) -----------------------
REM  For agents we additionally probe /health - a port can be
REM  bound by a half-dead process. If /health doesn't answer
REM  inside 3 seconds we assume the process is bad and start
REM  fresh (start-agents.bat will free the port first).
call :is_port_listening 8001
if "%PORT_LIVE%"=="1" (
  call :is_agents_healthy
  if "%AGENTS_HEALTHY%"=="1" (
    echo [SKIP] Agents tier already listening on port 8001 and /health is OK.
  ) else (
    echo [WARN] Port 8001 is bound but /health is NOT responding.
    echo        Starting a fresh agents window - it will free the port first.
    start "Trezo Agents" cmd /k "%~dp0start-agents.bat"
  )
) else (
  echo [START] Agents tier - launching new window.
  start "Trezo Agents" cmd /k "%~dp0start-agents.bat"
)

echo.
echo Done. Open http://localhost:3000 when the Web window says "Ready".
timeout /t 4 >nul
endlocal
exit /b 0


REM ============================================================
REM  Helpers
REM ============================================================

:is_port_listening
REM  Sets PORT_LIVE=1 if something is LISTENING on %1, else 0.
set "PORT_LIVE=0"
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%~1 " ^| findstr "LISTENING"') do (
  if not "%%a"=="0" set "PORT_LIVE=1"
)
exit /b 0

:is_agents_healthy
REM  Sets AGENTS_HEALTHY=1 if http://localhost:8001/health returns
REM  HTTP 200 within 3 seconds, else 0. Uses PowerShell because
REM  curl behavior varies across Windows versions.
set "AGENTS_HEALTHY=0"
for /f "delims=" %%h in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8001/health' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { 'ok' } else { 'bad' } } catch { 'bad' }"') do (
  if "%%h"=="ok" set "AGENTS_HEALTHY=1"
)
exit /b 0
