@echo off
:: CLAIM-TREZO-USB -- double-click this ON THE STICK to tell Trezo
:: "this is the USB". It writes the TREZO-USB.json marker at the root of
:: whatever drive this file is sitting on, labels the volume TREZO, and
:: (if C:\Trezo exists on this machine) runs a mirror right away.
::
:: Safe to run any number of times, on any machine, any drive letter.
setlocal
set "ROOT=%~d0"
echo.
echo   Claiming %ROOT% as the Trezo USB stick...
> "%ROOT%\TREZO-USB.json" (
  echo {"head":"unclaimed","mirrored_at":"1970-01-01T00:00:00","from":"%COMPUTERNAME%","robocopy":-1,"claimed_by_click":true}
)
if exist "%ROOT%\TREZO-USB.json" (
  echo   Marker written: %ROOT%\TREZO-USB.json
) else (
  echo   COULD NOT write the marker - is the stick write-protected?
  pause
  exit /b 1
)
label %ROOT% TREZO >nul 2>&1 && echo   Volume labelled TREZO.
if exist "C:\Trezo\BACKUP-USB.ps1" (
  echo   Mirroring C:\Trezo onto %ROOT%\Trezo now - this can take a few quiet minutes...
  powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Trezo\BACKUP-USB.ps1" -Drive %ROOT:~0,1%
) else (
  echo   No C:\Trezo on this machine - marker only. AUTO-PUSH will mirror from a machine that has it.
)
echo.
echo   Done. From now on AUTO-PUSH finds this stick automatically, whatever letter it gets.
pause
