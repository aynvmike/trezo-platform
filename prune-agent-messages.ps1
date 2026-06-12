# prune-agent-messages.ps1 (v3 - audit-safe + batched)
# v3 change: selective by kind.
#   - DELETE signal/info/error rows older than 24h (the noise)
#   - KEEP veto/approve/execute/close rows up to 30 days
#     (audit trail; Mem0 has these too via mem.log_decision/log_outcome)
# Anything older than 30 days from ANY kind is also deleted - by then
# the decision-loop value has decayed AND Mem0 has a permanent copy.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"

Write-Host ""
Write-Host "=== Trezo agent_messages prune (v3 audit-safe) ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "This will:" -ForegroundColor Gray
Write-Host "  * DELETE signal/info/error rows older than 24 hours (the noise)" -ForegroundColor Gray
Write-Host "  * KEEP veto/approve/execute/close rows up to 30 days (audit trail)" -ForegroundColor Gray
Write-Host "  * Mem0 keeps the important decisions + outcomes anyway" -ForegroundColor Gray
Write-Host ""

if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: Could not find $envPath" -ForegroundColor Red
    exit 1
}

$url = $null
$key = $null
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$') { $url = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
}
if (-not $url) { Write-Host "ERROR: SUPABASE_URL missing" -ForegroundColor Red; exit 1 }
if (-not $key) { Write-Host "ERROR: SUPABASE_SERVICE_ROLE_KEY missing" -ForegroundColor Red; exit 1 }

Write-Host "Found SUPABASE_URL: $($url.Substring(0, [Math]::Min(50, $url.Length)))..."
Write-Host ""

$headers = @{
    "apikey"        = $key
    "Authorization" = "Bearer $key"
}

function Get-RowCount {
    param([hashtable]$baseHeaders, [string]$baseUrl, [string]$filter = "")
    try {
        $h = $baseHeaders.Clone()
        $h["Prefer"] = "count=exact"
        $u = "$baseUrl/rest/v1/agent_messages?select=id&limit=1"
        if ($filter) { $u = "$u&$filter" }
        $r = Invoke-WebRequest -Uri $u -Headers $h -Method Get -UseBasicParsing -TimeoutSec 60
        $cr = $r.Headers["Content-Range"]
        if ($cr -is [array]) { $cr = $cr[0] }
        if ($cr -match '/(\d+)$') { return [int64]$matches[1] }
        return -1
    }
    catch { return -1 }
}

function Delete-Matching {
    param([hashtable]$baseHeaders, [string]$baseUrl, [string]$filter, [string]$label)
    Write-Host ""
    Write-Host "--- $label ---" -ForegroundColor Yellow
    $h = $baseHeaders.Clone()
    $h["Prefer"] = "return=minimal"
    $uri = "$baseUrl/rest/v1/agent_messages?$filter"
    try {
        $r = Invoke-WebRequest -Uri $uri -Headers $h -Method Delete -UseBasicParsing -TimeoutSec 300
        Write-Host "  status: $($r.StatusCode) $($r.StatusDescription)" -ForegroundColor Green
        return $true
    }
    catch {
        $msg = $_.Exception.Message
        if ($msg -match "500" -or $msg -match "504" -or $msg -match "timeout") {
            Write-Host "  Supabase overloaded - skipping this tier" -ForegroundColor DarkYellow
        }
        else { Write-Host "  failed: $msg" -ForegroundColor Red }
        return $false
    }
}

# ---- BEFORE ----
Write-Host "=== Counting rows BEFORE prune ===" -ForegroundColor Cyan
$before = Get-RowCount -baseHeaders $headers -baseUrl $url
if ($before -ge 0) { Write-Host "Before: $before rows total" -ForegroundColor Green }

# Per-kind breakdown so Mike sees what's noise vs. signal
foreach ($k in @("signal", "info", "error", "veto", "approve", "execute", "close")) {
    $c = Get-RowCount -baseHeaders $headers -baseUrl $url -filter "kind=eq.$k"
    if ($c -ge 0) {
        Write-Host ("  {0,-10} {1,10}" -f $k, $c) -ForegroundColor Gray
    }
}

# ---- Delete NOISY kinds (signal/info/error) in age tiers ----
Write-Host ""
Write-Host "=== Pruning noise (signal/info/error) ===" -ForegroundColor Cyan
$now = (Get-Date).ToUniversalTime()
$noisyKinds = @("signal", "info", "error")

# Try progressively-tighter cutoffs so first tiers are tiny and succeed
$cutoffs = @(
    @{ days = 30; label = "30+ days" }
    @{ days = 14; label = "14+ days" }
    @{ days = 7;  label = "7+ days" }
    @{ days = 3;  label = "3+ days" }
    @{ hours = 48; label = "48+ hours" }
    @{ hours = 24; label = "24+ hours" }
)
foreach ($tier in $cutoffs) {
    if ($tier.days) { $cutoff = $now.AddDays(-$tier.days) }
    else { $cutoff = $now.AddHours(-$tier.hours) }
    $cs = $cutoff.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    foreach ($k in $noisyKinds) {
        $filter = "kind=eq.$k&created_at=lt." + [uri]::EscapeDataString($cs)
        Delete-Matching -baseHeaders $headers -baseUrl $url -filter $filter -label "$k $($tier.label)"
        Start-Sleep -Milliseconds 1500
    }
}

# ---- Delete OLD audit kinds (older than 30 days) ----
# These are also in Mem0 so we can safely drop the SQL copy past 30 days
Write-Host ""
Write-Host "=== Pruning very old audit rows (>30 days, kept in Mem0) ===" -ForegroundColor Cyan
$thirtyDays = $now.AddDays(-30).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
foreach ($k in @("veto", "approve", "execute", "close")) {
    $filter = "kind=eq.$k&created_at=lt." + [uri]::EscapeDataString($thirtyDays)
    Delete-Matching -baseHeaders $headers -baseUrl $url -filter $filter -label "$k older than 30 days"
    Start-Sleep -Milliseconds 1500
}

# ---- AFTER ----
Write-Host ""
Write-Host "=== Counting rows AFTER prune ===" -ForegroundColor Cyan
Start-Sleep -Seconds 2
$after = Get-RowCount -baseHeaders $headers -baseUrl $url
if ($after -ge 0) {
    Write-Host "After:  $after rows total" -ForegroundColor Green
    if ($before -ge 0) {
        Write-Host "Net change: $($before - $after) rows deleted" -ForegroundColor Cyan
    }
    foreach ($k in @("signal", "info", "error", "veto", "approve", "execute", "close")) {
        $c = Get-RowCount -baseHeaders $headers -baseUrl $url -filter "kind=eq.$k"
        if ($c -ge 0) { Write-Host ("  {0,-10} {1,10} (remaining)" -f $k, $c) -ForegroundColor Gray }
    }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "Audit trail preserved: every veto/approve/execute/close from last 30 days is still here." -ForegroundColor Gray
Write-Host "Mem0 keeps all decisions + outcomes regardless of this prune." -ForegroundColor Gray
Write-Host ""
Write-Host "Next: restart agents with start-agents.bat"
