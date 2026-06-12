# compact-scheduled.ps1
# Unattended end-of-day compaction. Runs from Windows Scheduled Task
# daily at 5:00 PM ET (after market close). Reads agent_messages live,
# builds compact summaries, archives a JSON copy, pushes to Mem0 with
# rate-limited POSTs. Logs everything to logs\compact-YYYY-MM-DD.log.
#
# Created 2026-06-04 evening. Replaces manual end-of-day push.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"
$archiveDir = Join-Path $scriptDir "archives"
$logDir = Join-Path $scriptDir "logs"
if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir | Out-Null }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$today = (Get-Date).ToString("yyyy-MM-dd")
$logFile = Join-Path $logDir ("compact-" + $today + ".log")
$archiveFile = Join-Path $archiveDir ("agent_messages_" + $today + ".json")
$digestFile = Join-Path $archiveDir ("digest_" + $today + ".json")

function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== compact-scheduled start ==="

if (-not (Test-Path $envPath)) { Log "ERROR: no agents\.env"; exit 1 }
$url = $null; $key = $null; $mem0Key = $null
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$') { $url = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*MEM0_API_KEY\s*=\s*(.+?)\s*$') { $mem0Key = $matches[1].Trim('"').Trim("'") }
}
if (-not $url -or -not $key) { Log "ERROR: missing Supabase creds"; exit 1 }
if (-not $mem0Key -or $mem0Key.Length -lt 10) { Log "ERROR: Mem0 key missing"; exit 1 }

$sbHeaders = @{ "apikey" = $key; "Authorization" = "Bearer $key" }

function Build-Url {
    param([string]$baseUrl, [string]$path, [hashtable]$query)
    $parts = @()
    foreach ($k in $query.Keys) { $parts += ($k + "=" + $query[$k]) }
    return ($baseUrl + $path + "?" + ($parts -join "&"))
}

# ====== Pull today's veto/approve/execute/close from agent_messages ======
Log "fetching today's decisions from Supabase..."
$cutoff = (Get-Date).Date.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$cutoffEnc = [uri]::EscapeDataString($cutoff)
$kinds = @("veto", "approve", "execute", "close")
$byKind = @{}
foreach ($k in $kinds) {
    $all = @()
    $offset = 0
    $pageSize = 1000
    $more = $true
    while ($more) {
        $q = @{
            "select"     = "*"
            "kind"       = "eq." + $k
            "created_at" = "gte." + $cutoffEnc
            "order"      = "created_at.desc"
            "limit"      = $pageSize
            "offset"     = $offset
        }
        $u = Build-Url -baseUrl $url -path "/rest/v1/agent_messages" -query $q
        try {
            $r = Invoke-RestMethod -Uri $u -Headers $sbHeaders -Method Get -TimeoutSec 60
            if (-not $r -or $r.Count -eq 0) { $more = $false }
            else { $all += $r; if ($r.Count -lt $pageSize) { $more = $false }; $offset += $pageSize }
        } catch { Log "fetch $k failed: $($_.Exception.Message)"; $more = $false }
    }
    $byKind[$k] = $all
    Log "  $k : $($all.Count) rows"
}

# ====== Save archive JSON ======
@{
    exported_at = (Get-Date).ToUniversalTime().ToString("o")
    date        = $today
    by_kind     = $byKind
} | ConvertTo-Json -Depth 10 -Compress | Set-Content -Path $archiveFile -Encoding UTF8
Log "archive written: $archiveFile"

# ====== Build compact summaries ======
$summaries = @()
$vetos = @($byKind.veto); $approves = @($byKind.approve)
$executes = @($byKind.execute); $closes = @($byKind.close)

$pnl = 0.0
foreach ($c in $closes) { if ($c.payload.realized_pnl_usd) { $pnl += [double]$c.payload.realized_pnl_usd } }
$pnl = [Math]::Round($pnl, 2)
$summaries += @{
    content = "[DAILY BRIEF $today] $($vetos.Count) vetoes, $($approves.Count) approves, $($executes.Count) executes, $($closes.Count) closes. Realized P&L: `$$pnl."
    metadata = @{ kind = "daily_brief"; date = $today; vetoes = $vetos.Count; approves = $approves.Count; executes = $executes.Count; closes = $closes.Count; realized_pnl_usd = $pnl }
}

# Per-ticker veto rollups (3+ vetoes)
$vetosByTicker = @{}
foreach ($v in $vetos) {
    if (-not $v.payload.ticker) { continue }
    $t = [string]$v.payload.ticker
    if (-not $vetosByTicker.ContainsKey($t)) { $vetosByTicker[$t] = @() }
    $vetosByTicker[$t] += $v
}
foreach ($t in $vetosByTicker.Keys) {
    $rows = $vetosByTicker[$t]
    if ($rows.Count -lt 3) { continue }
    $reasonCounts = @{}
    foreach ($r in $rows) {
        $reason = "unknown"
        if ($r.payload.reason) {
            $reason = ([string]$r.payload.reason) -replace '[^a-zA-Z ]', ''
            if ($reason.Length -gt 60) { $reason = $reason.Substring(0, 60) }
        }
        if (-not $reasonCounts.ContainsKey($reason)) { $reasonCounts[$reason] = 0 }
        $reasonCounts[$reason] += 1
    }
    $top = $reasonCounts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 3
    $reasonText = ($top | ForEach-Object { "$($_.Value)x $($_.Key)" }) -join "; "
    $summaries += @{
        content = "[VETO ROLLUP $today] $t had $($rows.Count) vetoes. Top reasons: $reasonText"
        metadata = @{ kind = "veto_rollup"; ticker = $t; count = $rows.Count; date = $today }
    }
}

# Per-(ticker, strategy) approves
$approvesGrouped = @{}
foreach ($a in $approves) {
    if (-not $a.payload.ticker) { continue }
    $t = [string]$a.payload.ticker
    $s = "default"
    if ($a.payload.strategy) { $s = [string]$a.payload.strategy }
    $kk = "$t::$s"
    if (-not $approvesGrouped.ContainsKey($kk)) { $approvesGrouped[$kk] = @() }
    $approvesGrouped[$kk] += $a
}
foreach ($kk in $approvesGrouped.Keys) {
    $rows = $approvesGrouped[$kk]
    $parts = $kk.Split("::"); $t = $parts[0]; $s = $parts[1]
    $tcsList = @()
    foreach ($r in $rows) { if ($r.payload.tcs) { $tcsList += [int]$r.payload.tcs } }
    $tcsStr = ""
    if ($tcsList.Count -gt 0) {
        $minT = ($tcsList | Measure-Object -Minimum).Minimum
        $maxT = ($tcsList | Measure-Object -Maximum).Maximum
        $tcsStr = " TCS range: $minT-$maxT."
    }
    $summaries += @{
        content = "[APPROVE $today] $t via $s approved $($rows.Count) time(s).$tcsStr"
        metadata = @{ kind = "approve_rollup"; ticker = $t; strategy = $s; count = $rows.Count; date = $today }
    }
}

# Each close as its own outcome memory
foreach ($c in $closes) {
    if (-not $c.payload) { continue }
    $t = [string]$c.payload.ticker
    $reason = "unknown"; if ($c.payload.reason) { $reason = [string]$c.payload.reason }
    $cpnl = 0.0; if ($c.payload.realized_pnl_usd) { $cpnl = [double]$c.payload.realized_pnl_usd }
    $cpnl = [Math]::Round($cpnl, 2)
    $exitStr = ""; if ($c.payload.exit_price) { $exitStr = " @ `$$($c.payload.exit_price)" }
    $summaries += @{
        content = "[CLOSE $today] $t closed $reason$exitStr. Realized: `$$cpnl."
        metadata = @{ kind = "close_outcome"; ticker = $t; exit_reason = $reason; realized_pnl_usd = $cpnl; date = $today }
    }
}

Log "built $($summaries.Count) summaries"
$summaries | ConvertTo-Json -Depth 10 | Set-Content -Path $digestFile -Encoding UTF8
Log "digest saved: $digestFile"

# ====== Push to Mem0 ======
$mem0Headers = @{ "Authorization" = "Token " + $mem0Key; "Content-Type" = "application/json" }
$pushed = 0
$idx = 0
foreach ($s in $summaries) {
    $idx += 1
    $body = @{
        messages = @( @{ role = "assistant"; content = $s.content } )
        user_id  = "trezo"
        metadata = $s.metadata
    } | ConvertTo-Json -Depth 8
    $attempt = 0
    $success = $false
    while ($attempt -lt 4 -and -not $success) {
        $attempt += 1
        try {
            Invoke-RestMethod -Uri "https://api.mem0.ai/v1/memories/" -Headers $mem0Headers -Method Post -Body $body -TimeoutSec 30 | Out-Null
            $success = $true; $pushed += 1
        }
        catch {
            $msg = $_.Exception.Message
            if ($msg -match "429") {
                $back = 2 * [Math]::Pow(2, $attempt - 1)
                Log "  rate-limited, waiting ${back}s"
                Start-Sleep -Seconds $back
            } else { Log "  push failed: $msg"; break }
        }
    }
    Start-Sleep -Seconds 2
}

Log "pushed=$pushed/$($summaries.Count) to Mem0"
Log "=== compact-scheduled done ==="
exit 0
