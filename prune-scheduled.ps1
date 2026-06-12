# prune-scheduled.ps1
# Unattended version of prune-agent-messages.ps1 - no pauses, exit codes,
# minimal output. Designed to be run from Windows Task Scheduler every 3h.
# Writes a small log to logs\prune-YYYY-MM-DD.log so Mike can audit.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"
$logDir = Join-Path $scriptDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("prune-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== prune-scheduled start ==="

if (-not (Test-Path $envPath)) { Log "ERROR: no agents\.env"; exit 1 }

$url = $null; $key = $null
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$') { $url = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
}
if (-not $url -or -not $key) { Log "ERROR: missing SUPABASE creds"; exit 1 }

$headers = @{ "apikey" = $key; "Authorization" = "Bearer $key" }

function Get-RowCount {
    param([string]$filter = "")
    try {
        $h = $headers.Clone(); $h["Prefer"] = "count=exact"
        $u = "$url/rest/v1/agent_messages?select=id&limit=1"
        if ($filter) { $u = "$u&$filter" }
        $r = Invoke-WebRequest -Uri $u -Headers $h -Method Get -UseBasicParsing -TimeoutSec 60
        $cr = $r.Headers["Content-Range"]; if ($cr -is [array]) { $cr = $cr[0] }
        if ($cr -match '/(\d+)$') { return [int64]$matches[1] }
    } catch {}
    return -1
}

function Delete-Filter {
    param([string]$filter, [string]$label)
    try {
        $h = $headers.Clone(); $h["Prefer"] = "return=minimal"
        $r = Invoke-WebRequest -Uri "$url/rest/v1/agent_messages?$filter" -Headers $h `
            -Method Delete -UseBasicParsing -TimeoutSec 300
        Log "OK   $label : $($r.StatusCode)"
    } catch {
        $msg = $_.Exception.Message
        if ($msg -match "500|504|timeout") { Log "SKIP $label : Supabase overloaded" }
        else { Log "FAIL $label : $msg" }
    }
}

$before = Get-RowCount
Log "before=$before rows"

$now = (Get-Date).ToUniversalTime()

# Noisy kinds: prune in age tiers (oldest first; smaller deletes succeed)
foreach ($tier in @(
    @{ d = 30; lab = "30d" }, @{ d = 14; lab = "14d" },
    @{ d = 7; lab = "7d" }, @{ d = 3; lab = "3d" },
    @{ h = 48; lab = "48h" }, @{ h = 24; lab = "24h" }
)) {
    if ($tier.d) { $cut = $now.AddDays(-$tier.d) } else { $cut = $now.AddHours(-$tier.h) }
    $cs = $cut.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    foreach ($k in @("signal", "info", "error")) {
        $f = "kind=eq.$k&created_at=lt." + [uri]::EscapeDataString($cs)
        Delete-Filter -filter $f -label "$k>$($tier.lab)"
        Start-Sleep -Milliseconds 1000
    }
}

# Audit kinds: keep 30d, drop older (Mem0 has them)
$thirty = $now.AddDays(-30).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
foreach ($k in @("veto", "approve", "execute", "close")) {
    $f = "kind=eq.$k&created_at=lt." + [uri]::EscapeDataString($thirty)
    Delete-Filter -filter $f -label "$k>30d"
    Start-Sleep -Milliseconds 1000
}

$after = Get-RowCount
Log "after=$after rows (delta=$($before - $after))"
Log "=== prune-scheduled done ==="
exit 0
