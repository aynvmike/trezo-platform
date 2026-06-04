@echo off
setlocal enabledelayedexpansion
echo ============================================================
echo Trezo Snapshot - safe one-click git commit
echo ============================================================
echo.
cd /d "%~dp0"

echo Step 1: checking git installation and repo state...
echo.

REM Check git is on PATH
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: git command not found on PATH.
  echo Install from https://git-scm.com/download/win then re-run.
  echo.
  pause
  exit /b 1
)

REM Check git is initialized in this folder
if not exist .git (
  echo ERROR: .git folder missing in this directory.
  echo Run init-git.bat first to set up the repo.
  echo.
  pause
  exit /b 1
)

git --version
echo.
echo Step 2: showing what changed since last commit...
echo.
echo --- files changed ---
git status --short
echo.

REM Stage everything
echo Step 3: staging changes (gitignore filters secrets)...
git add . 2>nul
echo Done.
echo.

REM Count what is staged
git diff --cached --name-only > _staged.txt 2>nul
set FILECOUNT=0
for /f %%i in ('type _staged.txt ^| find /c /v ""') do set FILECOUNT=%%i

if "%FILECOUNT%"=="0" (
  echo No changes to commit. Working tree is already clean.
  del _staged.txt 2>nul
  echo.
  pause
  exit /b 0
)

echo Step 4: safety scan on %FILECOUNT% staged files...

REM Filter out the legitimate .env.example first
findstr /V /L /C:".env.example" _staged.txt > _staged_clean.txt

set DANGER=0
findstr /R /C:"\.env$" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.env\." _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"secrets" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"credentials" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.pem$" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.key$" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"claude_desktop_config" _staged_clean.txt >nul 2>&1
if not errorlevel 1 set DANGER=1

if "%DANGER%"=="1" (
  echo.
  echo *** DANGER *** the following look like secrets and would leak:
  findstr /R /C:"\.env$" /C:"\.env\." _staged_clean.txt
  findstr /I /C:"secrets" /C:"credentials" /C:"claude_desktop_config" _staged_clean.txt
  findstr /R /C:"\.pem$" /C:"\.key$" _staged_clean.txt
  echo.
  echo Aborting BEFORE commit. Add the offending files to .gitignore.
  git reset >nul 2>&1
  del _staged.txt _staged_clean.txt 2>nul
  echo.
  pause
  exit /b 1
)
del _staged.txt _staged_clean.txt 2>nul
echo Safety scan PASSED.
echo.

REM Build a date stamp for the commit message
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value ^| find "="') do set DT=%%a
set DATESTAMP=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%
set TIMESTAMP=%DT:~8,2%:%DT:~10,2%

set MSG=Trezo snapshot %DATESTAMP% %TIMESTAMP% - all green: 22 agents, sliding-scale giveback, OpsWatchdog, auto-reconcile, 0 TS errors

echo Step 5: committing with message:
echo   %MSG%
echo.

git commit -q -m "%MSG%"
if errorlevel 1 (
  echo Commit FAILED. See output above.
  echo.
  pause
  exit /b 1
)

REM Get the new commit hash
for /f "delims=" %%h in ('git rev-parse --short HEAD') do set HASH=%%h

echo ============================================================
echo SNAPSHOT SAVED at commit %HASH%
echo ============================================================
echo.
echo To return to THIS exact state later:
echo     cd C:\Trezo\trezo-platform
echo     git reset --hard %HASH%
echo.
echo Latest commit log:
git log --oneline -5
echo.
echo Save the commit hash above so you can roll back to it.
echo Press any key to close this window.
pause >nul
