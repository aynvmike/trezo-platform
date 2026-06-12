# health-watchdog.ps1
# Runs every 15 min via Windows Scheduled Task. Pings /health.
# If unreachable for 2 consecutive checks, kills any stale uvicorn
# on port 8001 and starts agents fresh via start-agents.bat.
#
# Mike 2026-06-10: bot went silent for 2 days because no external
# process was watching it. NSSM service (Task #52) is the real fix
# but this script provides defense-in-depth.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $scriptDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("watchdog-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
$stateFile = Join-Path $scriptDir ".watchdog-state.txt"

function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

# Health check
$healthy = $false
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { $healthy = $true }
} catch { }

if ($healthy) {
    Log "OK /health responsive"
    if (Test-Path $stateFile) { Remove-Item $stateFile -Force }
    exit 0
}

# Track consecutive failures (need 2 in a row before restart to avoid
# false-positive on a brief transient hiccup)
$failures = 0
if (Test-Path $stateFile) {
    $failures = [int](Get-Content $stateFile -ErrorAction SilentlyContinue)
}
$failures += 1
Set-Content -Path $stateFile -Value $failures

Log "FAIL /health unreachable (consecutive failures: $failures)"

if ($failures -lt 2) {
    Log "  waiting for next tick to confirm before restart"
    exit 0
}

# Restart
Log "RESTART agents service (failures=$failures)"

# Kill anything on port 8001
$pids = (Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($p in $pids) {
    try {
        Stop-Process -Id $p -Force -ErrorAction Stop
        Log "  killed PID $p (was holding 8001)"
    } catch { }
}

Start-Sleep -Seconds 2

# Launch start-agents.bat in a NEW window so it survives this script
$startBat = Join-Path $scriptDir "start-agents.bat"
if (Test-Path $startBat) {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start", '"Trezo - Agents"', "cmd.exe", "/k", "`"$startBat`""
    Log "  start-agents.bat launched in new window"
} else {
    Log "  ERROR start-agents.bat not found at $startBat"
}

# Clear the failure counter
Remove-Item $stateFile -Force -ErrorAction SilentlyContinue

# Wait + verify
Start-Sleep -Seconds 30
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Log "  VERIFIED /health responding after restart"
    } else {
        Log "  WARN /health returned $($r.StatusCode) - next tick will retry"
    }
} catch {
    Log "  WARN /health still not responding after restart - next tick will retry"
}
