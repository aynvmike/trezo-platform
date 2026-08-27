@echo off
rem Double-click me at the ROOT of the Trezo USB stick to restore
rem C:\Trezo onto this PC. Details: Trezo\REBUILD-FROM-USB.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Trezo\RESTORE-FROM-USB.ps1"
pause
