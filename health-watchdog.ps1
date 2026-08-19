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

# Kill anything on port 8001 - but NOT the service engine mid-start.
# If TrezoAgents is RUNNING, whatever holds 8001 is either the service
# (leave it alone) or a zombie the service will report failing against;
# nssm restart below handles both without this script firing blind.
$svcPre = Get-Service -Name "TrezoAgents" -ErrorAction SilentlyContinue
$pids = @()
if ($null -eq $svcPre -or $svcPre.Status -ne "Running") {
    $pids = (Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}
foreach ($p in $pids) {
    try {
        Stop-Process -Id $p -Force -ErrorAction Stop
        Log "  killed PID $p (was holding 8001)"
    } catch { }
}

Start-Sleep -Seconds 2

# RECOVER VIA THE SERVICE, NEVER BY LAUNCHING OUR OWN ENGINE.
# (2026-08-19.) This block used to launch start-agents.bat directly. The
# engine is managed by nssm, so that made TWO independent things whose job
# was "make sure an engine is running" - and they fought: every deliberate
# nssm stop looked like an outage to this watchdog, which then spawned a
# rival engine (with --reload, no less) that took port 8001, which made the
# real service crash-loop, which looked like another outage... Eighteen
# pythons deep, several were live trading engines on ONE Alpaca account.
# A watchdog may poke the manager; it must never become a second manager.
$svc = Get-Service -Name "TrezoAgents" -ErrorAction SilentlyContinue
if ($null -ne $svc) {
    Log "  restarting via nssm (service state was: $($svc.Status))"
    & nssm restart TrezoAgents 2>&1 | ForEach-Object { Log "  nssm: $_" }
} else {
    # No service on this box (dev machine) - the old path is acceptable here,
    # and start-agents.bat no longer carries --reload.
    $startBat = Join-Path $scriptDir "start-agents.bat"
    if (Test-Path $startBat) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start", '"Trezo - Agents"', "cmd.exe", "/k", "`"$startBat`""
        Log "  no TrezoAgents service; start-agents.bat launched in new window"
    } else {
        Log "  ERROR no TrezoAgents service AND start-agents.bat not found"
    }
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
