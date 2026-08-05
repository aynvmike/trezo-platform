@echo off
REM =====================================================================
REM  Trezo - stop-all.bat
REM ---------------------------------------------------------------------
REM  Stops all three tiers: Web (3000), API (8000), Agents (8001).
REM
REM  WHY THIS IS NOT JUST kill-ports.bat:
REM  the scheduled task "TrezoHealthWatchdog" runs every 15 minutes and
REM  RESTARTS the agents whenever port 8001 stops answering. Freeing the
REM  ports on their own therefore looks like it worked and then quietly
REM  undoes itself within a quarter of an hour. This script pauses that
REM  watchdog first, so the stop actually holds.
REM
REM  start-all.bat re-arms the watchdog when you bring things back up.
REM  If you stop and do NOT restart, the engine will not self-heal until
REM  you run start-all.bat or re-enable the task by hand.
REM
REM  Open positions are protected while the engine is down: stops and
REM  targets are resting GTC orders held at the broker, not in Trezo.
REM =====================================================================

setlocal
cd /d "%~dp0"

echo.
echo === Trezo stop-all.bat ===
echo.

REM -- Warn if the US market is currently open --------------------------
REM  Integer-only comparison on purpose: single quotes inside a for /f
REM  command string confuse cmd's parser, so no string literals here.
REM  810..1260 minutes UTC spans 09:30-16:00 ET across both EDT and EST;
REM  erring toward over-warning is harmless for a confirmation prompt.
for /f "delims=" %%m in ('powershell -NoProfile -Command "$d=(Get-Date).ToUniversalTime(); $w=[int]$d.DayOfWeek; $n=[int]$d.TimeOfDay.TotalMinutes; if($w -ge 1 -and $w -le 5 -and $n -ge 810 -and $n -lt 1260){1}else{0}"') do set "MKT=%%m"

if "%MKT%"=="1" (
  echo  *** WARNING: the US market is OPEN right now. ***
  echo.
  echo  Stopping the engine means no monitoring of open positions:
  echo  no trailing stops, no profit harvests, no new entries. Broker
  echo  GTC stop/target orders stay live, so the book is not naked,
  echo  but anything Trezo manages in software pauses.
  echo.
  choice /c YN /n /m "  Stop anyway? [Y/N] "
  if errorlevel 2 (
    echo.
    echo  Cancelled. Nothing was stopped.
    timeout /t 3 >nul
    exit /b 0
  )
  echo.
)

REM -- 1. Pause the health watchdog so it cannot undo this --------------
echo [1/3] Pausing the TrezoHealthWatchdog scheduled task...
schtasks /query /tn "TrezoHealthWatchdog" >nul 2>&1
if errorlevel 1 (
  echo       [skip] task not registered on this machine - nothing to pause.
) else (
  schtasks /change /tn "TrezoHealthWatchdog" /disable >nul 2>&1
  if errorlevel 1 (
    echo       [WARN] could not disable it. Re-run this file as Administrator,
    echo              or the agents may restart themselves within 15 minutes.
  ) else (
    echo       [ok] paused. start-all.bat will re-arm it.
  )
)

REM -- 2. Free the three ports -----------------------------------------
echo.
echo [2/3] Stopping the tiers...
echo       Web    (3000)
call "%~dp0_freeport.bat" 3000
echo       API    (8000)
call "%~dp0_freeport.bat" 8000
echo       Agents (8001)
call "%~dp0_freeport.bat" 8001

REM -- 3. Verify they are actually down ---------------------------------
echo.
echo [3/3] Verifying...
set "STILL_UP="
call :check_port 3000 Web
call :check_port 8000 API
call :check_port 8001 Agents

echo.
if defined STILL_UP (
  echo  === NOT FULLY STOPPED ===
  echo  Something is still holding:%STILL_UP%
  echo  Close the matching "Trezo ..." window by hand, or re-run this
  echo  file as Administrator.
) else (
  echo  === ALL STOPPED ===
  echo  Ports 3000, 8000 and 8001 are free.
  echo.
  echo  REMEMBER: the health watchdog is PAUSED. Run start-all.bat to
  echo  bring Trezo back up and re-arm it.
)
echo.
pause
endlocal
exit /b 0


:check_port
set "FOUND="
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%~1 " ^| findstr "LISTENING"') do (
  if not "%%a"=="0" set "FOUND=1"
)
if defined FOUND (
  echo       [STILL UP] %~2 on port %~1
  set "STILL_UP=%STILL_UP% %~2(%~1)"
) else (
  echo       [down] %~2 on port %~1
)
exit /b 0
