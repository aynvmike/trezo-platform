@echo off
REM Free a TCP port by killing whatever is listening on it.
REM Usage: call _freeport.bat 3000
setlocal
set "PORT=%~1"
if "%PORT%"=="" exit /b 0

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  if not "%%a"=="0" taskkill /F /PID %%a >nul 2>&1
)
endlocal
exit /b 0
