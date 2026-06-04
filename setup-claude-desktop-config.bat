@echo off
setlocal enabledelayedexpansion
echo ============================================================
echo Claude Desktop Config Setup - creates config file with Mem0
echo ============================================================
echo.

set "CONFIG_DIR=%APPDATA%\Claude"
set "CONFIG_FILE=%CONFIG_DIR%\claude_desktop_config.json"

REM 1. Create the folder if missing
if not exist "%CONFIG_DIR%" (
  echo Folder did not exist - creating: %CONFIG_DIR%
  mkdir "%CONFIG_DIR%"
) else (
  echo Folder exists: %CONFIG_DIR%
)
echo.

REM 2. Read MEM0_API_KEY from agents\.env so we don't echo it on screen
set "MEM0_KEY="
for /f "tokens=1,* delims==" %%a in ('findstr /b "MEM0_API_KEY=" "%~dp0agents\.env" 2^>nul') do (
  set "MEM0_KEY=%%b"
)
if not defined MEM0_KEY (
  echo ERROR: Could not read MEM0_API_KEY from agents\.env.
  echo Open that file in Notepad, find the MEM0_API_KEY line, and try again.
  pause
  exit /b 1
)
echo Mem0 API key loaded from agents\.env (hidden for safety).
echo.

REM 3. Backup any existing config
if exist "%CONFIG_FILE%" (
  copy "%CONFIG_FILE%" "%CONFIG_FILE%.bak" >nul
  echo Existing config backed up to: %CONFIG_FILE%.bak
)

REM 4. Write the config (this WILL overwrite any existing one; safe because of backup)
(
echo {
echo   "mcpServers": {
echo     "mem0": {
echo       "type": "http",
echo       "url": "https://mcp.mem0.ai/mcp",
echo       "headers": {
echo         "Authorization": "Bearer !MEM0_KEY!"
echo       }
echo     }
echo   }
echo }
) > "%CONFIG_FILE%"

echo Config written to:
echo     %CONFIG_FILE%
echo.
echo Restart the Claude desktop app fully (system tray - Quit, then reopen).
echo Then in a new Cowork conversation, ask me to verify Mem0.
echo.
echo If you already had OTHER MCP servers in this config (Alpaca etc.), they are
echo preserved in the .bak file - tell me and I will merge them back.
pause
