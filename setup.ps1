# =====================================================================
# Trezo — One-click local setup (Windows PowerShell)
#
# Right-click this file -> "Run with PowerShell"
# Or open PowerShell here and run:  .\setup.ps1
#
# What it does:
#   1. Checks Node.js >= 20 and Python >= 3.11 are installed
#   2. Runs `npm install` at the repo root (installs web + api together)
#   3. Creates a Python virtual env in agents\ and installs requirements
#   4. Prints next steps
# =====================================================================

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "    WARNING: $msg" -ForegroundColor Yellow
}

# --- Check prerequisites -----------------------------------------------------
Write-Step "Checking prerequisites"

try {
    $nodeVersion = node --version
    Write-Ok "Node.js $nodeVersion"
}
catch {
    Write-Warn "Node.js not found. Install from https://nodejs.org/ (LTS, version 20 or higher), then re-run this script."
    exit 1
}

try {
    $pyVersion = python --version
    Write-Ok "Python $pyVersion"
}
catch {
    try {
        $pyVersion = py --version
        Write-Ok "Python $pyVersion (via py launcher)"
        Set-Alias -Name python -Value py -Scope Script
    }
    catch {
        Write-Warn "Python not found. Install from https://www.python.org/ (3.11 or higher), then re-run this script."
        exit 1
    }
}

# --- npm install -------------------------------------------------------------
Write-Step "Installing JavaScript dependencies (web + api)"
Push-Location $PSScriptRoot
try {
    npm install
    Write-Ok "JS dependencies installed"
}
finally {
    Pop-Location
}

# --- Python venv -------------------------------------------------------------
Write-Step "Setting up Python virtual environment for agents/"
Push-Location (Join-Path $PSScriptRoot "agents")
try {
    if (-not (Test-Path ".venv")) {
        python -m venv .venv
        Write-Ok "Created .venv"
    } else {
        Write-Ok ".venv already exists"
    }
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & ".\.venv\Scripts\pip.exe" install -r requirements.txt
    Write-Ok "Python dependencies installed"
}
finally {
    Pop-Location
}

# --- Final message -----------------------------------------------------------
Write-Step "Setup complete!"
Write-Host @"

Next steps — open THREE PowerShell windows in this folder and run, one per window:

    Window 1 (web):     npm run dev:web        -> http://localhost:3000
    Window 2 (api):     npm run dev:api        -> http://localhost:8000/health
    Window 3 (agents):  cd agents
                        .\.venv\Scripts\Activate.ps1
                        uvicorn app.main:app --reload --port 8001

Then open your browser to http://localhost:3000 and try the sign-up flow.

Reminder: also apply the Supabase database migrations in your project's SQL editor:
    db\migrations\0001_initial_schema.sql
    db\migrations\0002_rls_policies.sql

"@ -ForegroundColor Green
