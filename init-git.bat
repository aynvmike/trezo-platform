@echo off
setlocal enabledelayedexpansion
echo ============================================================
echo Trezo Git Init - safe one-click setup
echo ============================================================
echo.
cd /d "%~dp0"

REM 1. Check git is installed
where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git is not installed or not in PATH.
  echo Download it from https://git-scm.com/download/win and re-run this.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('git --version') do set GITVER=%%v
echo Found %GITVER%
echo.

REM 2. If .git exists, check whether it's a partial init (no commits)
REM    or a real repo with history. Partial = safe to continue; real = bail.
if exist .git (
  git log --oneline -1 >nul 2>&1
  if not errorlevel 1 (
    echo This folder is ALREADY a real git repository with commits.
    echo If you want to add more changes, do:
    echo     git add . ^&^& git commit -m "Your message"
    pause
    exit /b 0
  )
  echo Detected partial .git from a previous aborted run. Continuing...
  echo.
)

REM 3. Verify .gitignore exists
if not exist .gitignore (
  echo ERROR: .gitignore is missing. Aborting before any commit.
  pause
  exit /b 1
)

REM 4. Init (skip if .git is already present from prior aborted run)
if not exist .git (
  echo Initializing git repository...
  git init -b main >nul
)
git config user.email "mike@trezo.local"
git config user.name "Mike (Trezo)"
echo.

REM 5. Stage everything that gitignore allows
echo Staging files...
git add .

REM 6. SAFETY SCAN
REM    Dump staged file list, exclude .env.example explicitly, then scan
REM    for any other suspicious patterns. If anything dangerous remains,
REM    abort BEFORE the commit happens.
echo Running safety scan...
git diff --cached --name-only > _staged_raw.txt 2>nul

REM 6a. Remove .env.example lines (legitimate tracked template)
findstr /V /L /C:".env.example" _staged_raw.txt > _staged.txt

REM 6b. Search the filtered list for the dangerous patterns
set DANGER=0
findstr /R /C:"\.env$" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.env\." _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"secrets" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"credentials" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.pem$" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /R /C:"\.key$" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1
findstr /I /C:"claude_desktop_config" _staged.txt >nul 2>&1
if not errorlevel 1 set DANGER=1

if "%DANGER%"=="1" (
  echo.
  echo *** DANGER *** the following files would be committed but look like secrets:
  echo.
  findstr /R /C:"\.env$" /C:"\.env\." _staged.txt
  findstr /I /C:"secrets" /C:"credentials" /C:"claude_desktop_config" _staged.txt
  findstr /R /C:"\.pem$" /C:"\.key$" _staged.txt
  echo.
  echo Aborting BEFORE commit. Edit .gitignore to exclude these files, then re-run.
  git reset >nul 2>&1
  del _staged_raw.txt _staged.txt 2>nul
  pause
  exit /b 1
)

REM 7. Summary
git diff --cached --name-only | find /c /v "" > _count.txt
set /p FILECOUNT=<_count.txt
del _staged_raw.txt _staged.txt _count.txt 2>nul
echo     %FILECOUNT% files staged.
echo     No .env or secret-shaped files in the staging list (other than .env.example template).
echo.

REM 8. Commit
git commit -q -m "Trezo baseline 2026-06-01 - paper page recovered, capital pressure shipped"
if errorlevel 1 (
  echo Commit failed. See output above.
  pause
  exit /b 1
)

echo ============================================================
echo SUCCESS. Trezo is now under version control.
echo ============================================================
echo.
echo From now on, any disaster reverses with one command:
echo     git checkout HEAD -- path\to\file.tsx
echo.
echo At the end of each session, commit your work:
echo     git add . ^&^& git commit -m "Today's progress note"
echo.
pause
