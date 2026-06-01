# =====================================================================
# Trezo - Doctor (PowerShell version)
# Shows what's installed and what's missing, plus writes doctor.log
# so you can re-read the results any time.
# =====================================================================

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$log = Join-Path $root "doctor.log"

# Tee output to a log file
Start-Transcript -Path $log -Force | Out-Null

function Ok($msg)      { Write-Host "  OK     : $msg" -ForegroundColor Green }
function Bad($msg)     { Write-Host "  MISSING: $msg" -ForegroundColor Yellow }
function Section($msg) { Write-Host ""; Write-Host "--- $msg ---" -ForegroundColor Cyan }

Write-Host "=== Trezo doctor ===" -ForegroundColor Cyan
Write-Host "Project: $root"
Write-Host "(log saved to doctor.log)"

# --- Node.js -----------------------------------------------------------------
Section "Node.js (need v20+)"
try {
    $v = node --version 2>$null
    if ($v) { Ok "node $v" } else { Bad "node not found" }
} catch { Bad "install from https://nodejs.org/ (LTS), then restart PC" }

Section "npm"
try {
    $v = npm --version 2>$null
    if ($v) { Ok "npm $v" } else { Bad "npm not found (install Node.js LTS)" }
} catch { Bad "npm not found (install Node.js LTS)" }

# --- Python ------------------------------------------------------------------
Section "Python (need 3.11+)"
$pythonOk = $false
foreach ($cmd in @("python", "py")) {
    try {
        $v = & $cmd --version 2>$null
        if ($v) { Ok "$cmd $v"; $pythonOk = $true; break }
    } catch { }
}
if (-not $pythonOk) {
    Bad "install from https://www.python.org/downloads/ (check 'Add Python to PATH'), restart PC"
}

# --- JS deps -----------------------------------------------------------------
Section "JavaScript dependencies"
if (Test-Path (Join-Path $root "node_modules\next")) {
    Ok "web/Next.js installed"
} else { Bad "web deps not installed — run setup.bat" }
if (Test-Path (Join-Path $root "node_modules\tsx")) {
    Ok "api/tsx installed"
} else { Bad "api deps not installed — run setup.bat" }

# --- Python venv -------------------------------------------------------------
Section "Python virtual env (agents)"
if (Test-Path (Join-Path $root "agents\.venv\Scripts\python.exe")) {
    Ok "agents/.venv exists"
} else { Bad "agents/.venv not created — run setup.bat" }

# --- .env files --------------------------------------------------------------
Section "Environment files"
foreach ($f in @("web\.env.local", "api\.env", "agents\.env")) {
    if (Test-Path (Join-Path $root $f)) { Ok "$f present" } else { Bad "$f missing" }
}

# --- Ports we'll use ---------------------------------------------------------
Section "Ports 3000 / 8000 / 8001 (should all be free before you start dev servers)"
foreach ($p in @(3000, 8000, 8001)) {
    $busy = (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
    if ($busy) {
        Write-Host "  IN USE : port $p (another program is using it)" -ForegroundColor Yellow
    } else {
        Ok "port $p free"
    }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Stop-Transcript | Out-Null
Write-Host "Press Enter to close this window..."
Read-Host | Out-Null
