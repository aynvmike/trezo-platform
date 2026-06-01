@echo off
REM Double-click this to run the doctor. -NoExit keeps the PowerShell window
REM open after the script finishes — close it yourself with the X button.
cd /d "%~dp0"
powershell -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0doctor.ps1"
