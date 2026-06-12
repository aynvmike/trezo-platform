# compact-archive-to-mem0.ps1
# Takes a local archive JSON file (made by clean-slate-backup-wipe
# or the daily scheduled archive job) and pushes COMPACT SUMMARIES
# to Mem0 - ~30-100 memories per day instead of thousands of raw rows.
#
# Why compaction:
#   - Mem0 free tier rate-limits at 429 if you push hundreds of
#     records in quick succession
#   - Mem0's value is SEMANTIC RECALL, not row storage. One summary
#     "GM had 14 ORB vetoes today, all neutral direction" is FAR
#     more useful for next-day decisions than 14 individual rows.
#
# Rate limiting:
#   - 1 push every 2 seconds (30/min)
#   - Retry with exponential backoff on 429
#   - Total for ~50 summaries: ~3 minutes
#
# Usage:
#   .\compact-archive-to-mem0.ps1 -ArchiveFile "archives\agent_messages_2026-06-04_1738.json"
#   (no arg = uses the newest file in archives\)

param(
    [string]$ArchiveFile = ""
)

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"
$archiveDir = Join-Path $scriptDir "archives"
$logDir = Join-Path $scriptDir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

Write-Host ""
Write-Host "=== Trezo compact-archive-to-mem0 ===" -ForegroundColor Cyan
Write-Host ""

# Default to newest archive file
if (-not $ArchiveFile) {
    if (-not (Test-Path $archiveDir)) {
        Write-Host "ERROR: no archives folder" -ForegroundColor Red
        exit 1
    }
    $newest = Get-ChildItem $archiveDir -Filter "agent_messages_*.json" |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newest) {
        Write-Host "ERROR: no archive file found in $archiveDir" -ForegroundColor Red
        exit 1
    }
    $ArchiveFile = $newest.FullName
}

if (-not (Test-Path $ArchiveFile)) {
    Write-Host ("ERROR: archive file not found: " + $ArchiveFile) -ForegroundColor Red
    exit 1
}

Write-Host ("Archive: " + $ArchiveFile) -ForegroundColor Gray

# Read Mem0 key
$mem0Key = $null
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*MEM0_API_KEY\s*=\s*(.+?)\s*$') { $mem0Key = $matches[1].Trim('"').Trim("'") }
}
if (-not $mem0Key -or $mem0Key.Length -lt 10) {
    Write-Host "ERROR: MEM0_API_KEY missing or invalid in agents\.env" -ForegroundColor Red
    exit 1
}
Write-Host "Mem0 key: present" -ForegroundColor Gray
Write-Host ""

# Load archive
Write-Host "=== Loading archive ===" -ForegroundColor Cyan
$archive = Get-Content $ArchiveFile -Raw | ConvertFrom-Json
$vetos     = @($archive.by_kind.veto)
$approves  = @($archive.by_kind.approve)
$executes  = @($archive.by_kind.execute)
$closes    = @($archive.by_kind.close)
Write-Host ("  veto:    " + $vetos.Count) -ForegroundColor Gray
Write-Host ("  approve: " + $approves.Count) -ForegroundColor Gray
Write-Host ("  execute: " + $executes.Count) -ForegroundColor Gray
Write-Host ("  close:   " + $closes.Count) -ForegroundColor Gray
Write-Host ""

# ====== Build compact summaries ======
Write-Host "=== Building compact summaries ===" -ForegroundColor Cyan

$summaries = @()
$today = (Get-Date).ToString("yyyy-MM-dd")

# Summary 1: Daily brief (1 memory)
$totalRows = $vetos.Count + $approves.Count + $executes.Count + $closes.Count
$pnlTotal = 0.0
foreach ($c in $closes) {
    if ($c.payload -and $c.payload.realized_pnl_usd) { $pnlTotal += [double]$c.payload.realized_pnl_usd }
}
$pnlTotal = [Math]::Round($pnlTotal, 2)
$summaries += @{
    content  = "[DAILY BRIEF $today] $totalRows decisions: $($vetos.Count) vetoes, $($approves.Count) approves, $($executes.Count) executes, $($closes.Count) closes. Realized P&L: `$$pnlTotal."
    metadata = @{
        kind     = "daily_brief"
        date     = $today
        vetoes   = $vetos.Count
        approves = $approves.Count
        executes = $executes.Count
        closes   = $closes.Count
        realized_pnl_usd = $pnlTotal
    }
}

# Summary 2-N: per-ticker rollup of vetoes (grouped by ticker, top reasons)
$vetosByTicker = @{}
foreach ($v in $vetos) {
    if (-not $v.payload -or -not $v.payload.ticker) { continue }
    $t = [string]$v.payload.ticker
    if (-not $vetosByTicker.ContainsKey($t)) { $vetosByTicker[$t] = @() }
    $vetosByTicker[$t] += $v
}
$tickerCount = 0
foreach ($t in $vetosByTicker.Keys) {
    $rows = $vetosByTicker[$t]
    if ($rows.Count -lt 3) { continue }  # only summarize tickers with 3+ vetoes
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
        content  = "[VETO ROLLUP $today] $t had $($rows.Count) vetoes. Top reasons: $reasonText"
        metadata = @{
            kind   = "veto_rollup"
            ticker = $t
            count  = $rows.Count
            date   = $today
        }
    }
    $tickerCount += 1
}

# Summary: per-(ticker,strategy) approves
$approvesGrouped = @{}
foreach ($a in $approves) {
    if (-not $a.payload -or -not $a.payload.ticker) { continue }
    $t = [string]$a.payload.ticker
    $s = "default"
    if ($a.payload.strategy) { $s = [string]$a.payload.strategy }
    $key = "$t::$s"
    if (-not $approvesGrouped.ContainsKey($key)) { $approvesGrouped[$key] = @() }
    $approvesGrouped[$key] += $a
}
foreach ($key in $approvesGrouped.Keys) {
    $rows = $approvesGrouped[$key]
    $parts = $key.Split("::")
    $t = $parts[0]; $s = $parts[1]
    $tcsList = @()
    foreach ($r in $rows) { if ($r.payload.tcs) { $tcsList += [int]$r.payload.tcs } }
    $tcsStr = ""
    if ($tcsList.Count -gt 0) {
        $minT = ($tcsList | Measure-Object -Minimum).Minimum
        $maxT = ($tcsList | Measure-Object -Maximum).Maximum
        $tcsStr = " TCS range: $minT-$maxT."
    }
    $summaries += @{
        content  = "[APPROVE $today] $t via $s approved $($rows.Count) time(s).$tcsStr"
        metadata = @{
            kind     = "approve_rollup"
            ticker   = $t
            strategy = $s
            count    = $rows.Count
            date     = $today
        }
    }
}

# Summary: each close gets its own (these are real outcomes worth semantic recall)
foreach ($c in $closes) {
    if (-not $c.payload) { continue }
    $t = [string]$c.payload.ticker
    $reason = "unknown"
    if ($c.payload.reason) { $reason = [string]$c.payload.reason }
    $pnl = 0.0
    if ($c.payload.realized_pnl_usd) { $pnl = [double]$c.payload.realized_pnl_usd }
    $pnl = [Math]::Round($pnl, 2)
    $exitPrice = ""
    if ($c.payload.exit_price) { $exitPrice = " @ `$$($c.payload.exit_price)" }
    $summaries += @{
        content  = "[CLOSE $today] $t closed $reason$exitPrice. Realized: `$$pnl."
        metadata = @{
            kind             = "close_outcome"
            ticker           = $t
            exit_reason      = $reason
            realized_pnl_usd = $pnl
            date             = $today
        }
    }
}

Write-Host ("  Built " + $summaries.Count + " compact summaries.") -ForegroundColor Green
Write-Host ""

# Save digest to disk before push (so we have it even if Mem0 fails)
$digestPath = Join-Path $archiveDir ("digest_" + $today + ".json")
$summaries | ConvertTo-Json -Depth 10 | Set-Content -Path $digestPath -Encoding UTF8
Write-Host ("Digest saved: " + $digestPath) -ForegroundColor Green
Write-Host ""

# ====== Push to Mem0 with rate limiting + retry ======
Write-Host "=== Pushing to Mem0 (2s/request, retry on 429) ===" -ForegroundColor Cyan

$mem0Headers = @{
    "Authorization" = "Token " + $mem0Key
    "Content-Type"  = "application/json"
}

$pushed = 0
$failed = 0
$idx = 0
foreach ($s in $summaries) {
    $idx += 1
    $body = @{
        messages = @( @{ role = "assistant"; content = $s.content } )
        user_id  = "trezo"
        metadata = $s.metadata
    } | ConvertTo-Json -Depth 8

    $attempt = 0
    $maxAttempts = 4
    $delay = 2
    $success = $false
    while ($attempt -lt $maxAttempts -and -not $success) {
        $attempt += 1
        try {
            Invoke-RestMethod -Uri "https://api.mem0.ai/v1/memories/" -Headers $mem0Headers -Method Post -Body $body -TimeoutSec 30 | Out-Null
            $success = $true
            $pushed += 1
            Write-Host ("  [" + $idx + "/" + $summaries.Count + "] ok: " + $s.content.Substring(0, [Math]::Min(70, $s.content.Length))) -ForegroundColor Green
        }
        catch {
            $msg = $_.Exception.Message
            if ($msg -match "429") {
                $backoff = $delay * [Math]::Pow(2, $attempt - 1)
                Write-Host ("    rate-limited, waiting " + $backoff + "s...") -ForegroundColor DarkYellow
                Start-Sleep -Seconds $backoff
            }
            else {
                Write-Host ("  [" + $idx + "/" + $summaries.Count + "] fail: " + $msg) -ForegroundColor Red
                $failed += 1
                break
            }
        }
    }
    Start-Sleep -Seconds 2  # base rate limit
}

Write-Host ""
Write-Host ("=== Done ===") -ForegroundColor Cyan
Write-Host ("Pushed to Mem0: " + $pushed) -ForegroundColor Green
if ($failed -gt 0) { Write-Host ("Failed: " + $failed) -ForegroundColor Red }
Write-Host ("Local digest:   " + $digestPath) -ForegroundColor Gray
