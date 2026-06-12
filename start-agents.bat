@echo off
REM ============================================================
REM  Trezo - start-agents.bat (v2 - bounded restart)
REM ------------------------------------------------------------
REM  Old version: looped forever on WinError 10013 when port
REM  was already held (2026-06-04 incident - filled the screen
REM  with red errors during trading hours).
REM
REM  New version:
REM    1. Pre-flight: if /health already responds, do NOTHING.
REM       This is what makes start-all.bat safe to run twice.
REM    2. Free port 8001 with verification (taskkill + wait +
REM       confirm port released).
REM    3. Bounded restart - max 5 attempts with growing backoff
REM       (5s, 10s, 20s, 40s, 60s). Then stops with a clear
REM       message instead of red-screen looping forever.
REM ============================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0agents"
title Trezo - Agents (port 8001)

if not exist ".venv\Scripts\uvicorn.exe" (
  echo ERROR: agents\.venv not found. Run setup.bat first.
  pause
  exit /b 1
)

echo.
echo === Trezo Agents - pre-flight ===

REM -- Pre-flight: is the service ALREADY healthy? -----------
call :check_health
if "%AGENTS_OK%"=="1" (
  echo.
  echo [SKIP] Agents service is ALREADY running and /health is OK.
  echo        Nothing to do. Closing this window in 5 seconds.
  echo        ^(To force a restart, close the existing agents
  echo        window first, then re-run start-agents.bat.^)
  timeout /t 5 >nul
  endlocal
  exit /b 0
)

set "RESTART_COUNT=0"
set "MAX_RESTARTS=5"

:retry
echo.
echo === Freeing port 8001 ===
call "%~dp0_freeport.bat" 8001
REM Give Windows a beat to actually release the socket
timeout /t 1 >nul

echo === Clearing __pycache__ ===
for /d /r "%~dp0agents\app" %%d in (__pycache__) do (
  if exist "%%d" rmdir /s /q "%%d"
)

set /a "DISPLAY_ATTEMPT=%RESTART_COUNT% + 1"
echo === Starting uvicorn ^(attempt !DISPLAY_ATTEMPT! of %MAX_RESTARTS%^) ===
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8001

set /a "RESTART_COUNT=%RESTART_COUNT% + 1"
echo.
echo --- uvicorn exited ^(attempt %RESTART_COUNT% of %MAX_RESTARTS%^) ---

if %RESTART_COUNT% GEQ %MAX_RESTARTS% (
  echo.
  echo ============================================================
  echo  STOPPED RETRYING after %MAX_RESTARTS% failed attempts.
  echo  This usually means:
  echo    * Another process is holding port 8001 ^(WinError 10013^)
  echo    * Python crashed during bootstrap - check the red error
  echo      lines above for a traceback
  echo    * Antivirus / firewall is blocking the socket bind
  echo.
  echo  Quick fixes:
  echo    [PowerShell] Invoke-RestMethod http://localhost:8001/health
  echo      ^- if it answers, the old service is still alive
  echo      ^- close this window and you are done
  echo    [PowerShell] netstat -ano ^| findstr :8001
  echo      ^- shows the PID holding the port; taskkill /F /PID ^<id^>
  echo ============================================================
  pause
  endlocal
  exit /b 1
)

REM Exponential backoff: 5, 10, 20, 40, 60 seconds
set "SLEEP_SECONDS=5"
if %RESTART_COUNT% GEQ 2 set "SLEEP_SECONDS=10"
if %RESTART_COUNT% GEQ 3 set "SLEEP_SECONDS=20"
if %RESTART_COUNT% GEQ 4 set "SLEEP_SECONDS=40"

echo Restarting in %SLEEP_SECONDS% seconds. Close this window to stop.
timeout /t %SLEEP_SECONDS% >nul
goto retry


REM ============================================================
REM  Helpers
REM ============================================================

:check_health
set "AGENTS_OK=0"
for /f "delims=" %%h in ('powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:8001/health' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { 'ok' } else { 'bad' } } catch { 'bad' }"') do (
  if "%%h"=="ok" set "AGENTS_OK=1"
)
exit /b 0
