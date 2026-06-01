@echo off
REM =====================================================================
REM Trezo - Free up ports 3000, 8000, 8001
REM Safe — only kills what's listening on those three ports.
REM =====================================================================

echo.
echo Freeing port 3000...
call "%~dp0_freeport.bat" 3000

echo Freeing port 8000...
call "%~dp0_freeport.bat" 8000

echo Freeing port 8001...
call "%~dp0_freeport.bat" 8001

echo.
echo Done. Ports 3000, 8000, 8001 should now be free.
echo You can close this window.
pause
