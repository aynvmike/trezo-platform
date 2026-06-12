@echo off
REM restart-web-clean.bat
REM Kills anything on port 3000, deletes web\.next cache, starts fresh.
REM Use when the dashboard shows: "TypeError: Cannot read properties of
REM null (reading 'useContext')" - a Next.js dev-server cache glitch
REM that happens after lots of hot-reloads in one session.

cd /d "%~dp0"

echo === Restarting web tier clean ===
echo.

echo Freeing port 3000...
call "%~dp0_freeport.bat" 3000
timeout /t 1 >nul

echo Deleting web\.next cache...
if exist "%~dp0web\.next" (
  rmdir /s /q "%~dp0web\.next"
  echo   cleared
) else (
  echo   already clean
)

echo Starting fresh web tier...
start "Trezo Web" cmd /k "%~dp0start-web.bat"

echo.
echo Done. The new Next.js window is opening - wait for "Ready"
echo then refresh your browser.
timeout /t 3 >nul
exit /b 0
