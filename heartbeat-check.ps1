# heartbeat-check.ps1 - runs every 15 min via Windows Scheduled Task.
# Verifies /health + Pattern Detection recent activity. Logs to
# logs\heartbeat-YYYY-MM-DD.log. Toast notification after 3 consecutive
# failures so Mike sees it before a multi-hour silence happens again.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"
$logDir = Join-Path $scriptDir "logs"
$stateDir = Join-Path $scriptDir "state"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir | Out-Null }
$today = (Get-Date).ToString("yyyy-MM-dd")
$logFile = Join-Path $logDir ("heartbeat-" + $today + ".log")
$failFile = Join-Path $stateDir "heartbeat-fails.txt"

function Log { param([string]$m) Add-Content -Path $logFile -Value "[$(Get-Date -Format 'HH:mm:ss')] $m"; Write-Host $m }
function Notify { param([string]$t, [string]$m)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $b = New-Object System.Windows.Forms.NotifyIcon
        $b.Icon = [System.Drawing.SystemIcons]::Warning
        $b.Visible = $true
        $b.ShowBalloonTip(10000, $t, $m, [System.Windows.Forms.ToolTipIcon]::Warning)
        Start-Sleep -Seconds 11
        $b.Dispose()
    } catch { }
}

Log "=== heartbeat start ==="
$problems = @()

# Check 1: /health
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8001/health" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { Log "OK /health" } else { $problems += "health=$($r.StatusCode)" }
} catch { $problems += "/health unreachable: $($_.Exception.Message)" }

# Check 2: Supabase + Pattern Detection recent activity
if (Test-Path $envPath) {
    $url = $null; $key = $null
    foreach ($line in Get-Content $envPath) {
        if ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$') { $url = $matches[1].Trim('"').Trim("'") }
        elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
    }
    if ($url -and $key) {
        $h = @{ "apikey" = $key; "Authorization" = "Bearer $key" }
        $cutoff = (Get-Date).ToUniversalTime().AddMinutes(-15).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
        try {
            $u = "$url/rest/v1/agent_messages?select=id&agent_name=eq.pattern_detection&created_at=gte." + [uri]::EscapeDataString($cutoff) + "&limit=1"
            $r = Invoke-WebRequest -Uri $u -Headers $h -UseBasicParsing -TimeoutSec 30
            $rows = ($r.Content | ConvertFrom-Json)
            if ($rows.Count -gt 0) { Log "OK Pattern Detection ticked 15min" } else { $problems += "Pattern Detection SILENT 15+ min" }
        } catch { Log "WARN Supabase: $($_.Exception.Message)" }
    }
}

# Fail counter + notify after 3
$fails = if (Test-Path $failFile) { [int](Get-Content $failFile -Raw).Trim() } else { 0 }
if ($problems.Count -gt 0) {
    $fails += 1
    Set-Content -Path $failFile -Value "$fails"
    Log "FAIL #$fails : $($problems -join '; ')"
    if ($fails -ge 3) { Notify "Trezo agents unhealthy" ($problems -join '; ') }
} else {
    if ($fails -gt 0) { Log "OK recovered" }
    Set-Content -Path $failFile -Value "0"
}
Log "=== heartbeat done ==="
