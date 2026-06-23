@echo off
REM Trezo integrity audit — positions vs real Alpaca. Read-only report.
REM   double-click          = report only
REM   integrity-audit.bat --repair  = also quarantine confirmed stock phantoms
cd /d C:\Trezo\trezo-platform\agents
uv run python -m app.integrity.audit %*
pause
