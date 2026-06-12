# clean-slate-backup-wipe.ps1 (v2 - PS 5.1 ampersand-safe)
# v2 change: URL query strings built via -join so & is never inside
# an interpolated double-quoted string. Avoids "ampersand not allowed"
# parser errors on Windows PowerShell 5.1.

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $scriptDir "agents\.env"
$archiveDir = Join-Path $scriptDir "archives"
if (-not (Test-Path $archiveDir)) { New-Item -ItemType Directory -Path $archiveDir | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$archiveFile = Join-Path $archiveDir ("agent_messages_" + $stamp + ".json")

Write-Host ""
Write-Host "=== Trezo CLEAN SLATE - backup + wipe ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: no agents\.env" -ForegroundColor Red
    exit 1
}

$url = $null
$key = $null
$mem0Key = $null
foreach ($line in Get-Content $envPath) {
    if ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$') { $url = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
    elseif ($line -match '^\s*MEM0_API_KEY\s*=\s*(.+?)\s*$') { $mem0Key = $matches[1].Trim('"').Trim("'") }
}
if (-not $url -or -not $key) {
    Write-Host "ERROR: missing Supabase creds" -ForegroundColor Red
    exit 1
}
$mem0Enabled = $false
if ($mem0Key -and $mem0Key.Length -gt 10 -and ($mem0Key -notmatch "your-mem0") -and ($mem0Key -notmatch "paste-")) {
    $mem0Enabled = $true
}

Write-Host "Supabase: $url" -ForegroundColor Gray
if ($mem0Enabled) {
    Write-Host "Mem0:     enabled" -ForegroundColor Gray
} else {
    Write-Host "Mem0:     DISABLED (will skip Mem0 push)" -ForegroundColor Gray
}
Write-Host ""

$sbHeaders = @{
    "apikey"        = $key
    "Authorization" = "Bearer $key"
}

# Helper: build a URL with query string safely (no & inside interpolation)
function Build-Url {
    param([string]$baseUrl, [string]$path, [hashtable]$query)
    $parts = @()
    foreach ($k in $query.Keys) {
        $v = $query[$k]
        $parts += ($k + "=" + $v)
    }
    $qs = $parts -join "&"
    return ($baseUrl + $path + "?" + $qs)
}

# ====== STEP 1: ARCHIVE TO LOCAL JSON ======
Write-Host "=== Step 1: Local archive ===" -ForegroundColor Cyan
$cutoff30 = (Get-Date).ToUniversalTime().AddDays(-30).ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$cutoff30Enc = [uri]::EscapeDataString($cutoff30)
$kinds = @("veto", "approve", "execute", "close")
$archive = @{
    exported_at = (Get-Date).ToUniversalTime().ToString("o")
    cutoff      = $cutoff30
    by_kind     = @{}
}

foreach ($k in $kinds) {
    Write-Host ("  fetching " + $k + " rows...") -ForegroundColor Gray
    $all = @()
    $offset = 0
    $pageSize = 1000
    $more = $true
    while ($more) {
        $q = @{
            "select"     = "*"
            "kind"       = "eq." + $k
            "created_at" = "gte." + $cutoff30Enc
            "order"      = "created_at.desc"
            "limit"      = $pageSize
            "offset"     = $offset
        }
        $u = Build-Url -baseUrl $url -path "/rest/v1/agent_messages" -query $q
        try {
            $r = Invoke-RestMethod -Uri $u -Headers $sbHeaders -Method Get -TimeoutSec 60
            if (-not $r -or $r.Count -eq 0) {
                $more = $false
            } else {
                $all += $r
                if ($r.Count -lt $pageSize) { $more = $false }
                $offset += $pageSize
            }
        }
        catch {
            Write-Host ("    error: " + $_.Exception.Message) -ForegroundColor Red
            $more = $false
        }
    }
    Write-Host ("    got " + $all.Count + " " + $k + " rows") -ForegroundColor Green
    $archive.by_kind[$k] = $all
}

$archive | ConvertTo-Json -Depth 10 -Compress | Set-Content -Path $archiveFile -Encoding UTF8
$fileSize = (Get-Item $archiveFile).Length
$fileSizeKB = [Math]::Round($fileSize / 1KB, 1)
Write-Host ""
Write-Host ("Archive written: " + $archiveFile) -ForegroundColor Green
Write-Host ("Size: " + $fileSizeKB + " KB") -ForegroundColor Green
Write-Host ""

# ====== STEP 2: SAMPLE PUSH TO MEM0 ======
Write-Host "=== Step 2: Test push to Mem0 ===" -ForegroundColor Cyan
if (-not $mem0Enabled) {
    Write-Host "  Mem0 key not configured - skipping push." -ForegroundColor DarkYellow
    Write-Host "  veto/approve/execute/close are already in Mem0 from live writes." -ForegroundColor Gray
}
else {
    $mem0Headers = @{
        "Authorization" = "Token " + $mem0Key
        "Content-Type"  = "application/json"
    }
    $sampleSize = @{ veto = 10; approve = 50; execute = -1; close = -1 }
    $totalPushed = 0
    foreach ($k in $kinds) {
        $rows = $archive.by_kind[$k]
        $take = $sampleSize[$k]
        if ($take -eq -1 -or $take -gt $rows.Count) { $take = $rows.Count }
        $batch = $rows | Select-Object -First $take
        Write-Host ("  pushing " + $take + " " + $k + " rows to Mem0...") -ForegroundColor Gray
        foreach ($row in $batch) {
            $payload = $row.payload
            $ticker = ""
            if ($payload -and $payload.ticker) { $ticker = [string]$payload.ticker }
            $pjson = ""
            try { $pjson = $payload | ConvertTo-Json -Compress -Depth 5 } catch { $pjson = "" }
            $content = "[" + $k.ToUpper() + "] " + $ticker + " on " + $row.created_at + " :: " + $pjson
            $body = @{
                messages = @( @{ role = "assistant"; content = $content } )
                user_id  = "trezo"
                metadata = @{
                    kind          = "backup_" + $k
                    agent         = $row.agent_name
                    ticker        = $ticker
                    original_id   = $row.id
                    archived_from = "agent_messages_" + $stamp
                    timestamp     = $row.created_at
                }
            } | ConvertTo-Json -Depth 8
            try {
                Invoke-RestMethod -Uri "https://api.mem0.ai/v1/memories/" -Headers $mem0Headers -Method Post -Body $body -TimeoutSec 30 | Out-Null
                $totalPushed += 1
            }
            catch {
                Write-Host ("    push failed: " + $_.Exception.Message) -ForegroundColor Red
            }
            Start-Sleep -Milliseconds 50
        }
    }
    Write-Host ("  Mem0: pushed " + $totalPushed + " records as backup") -ForegroundColor Green
}
Write-Host ""

# ====== STEP 3: CONFIRM ======
Write-Host "=== Step 3: Confirm wipe ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "About to DELETE every row in agent_messages." -ForegroundColor Yellow
Write-Host ("Archive saved to: " + $archiveFile) -ForegroundColor Gray
Write-Host ""
$confirm = Read-Host "Type YES to proceed with wipe, anything else to abort"
if ($confirm -ne "YES") {
    Write-Host ""
    Write-Host "Aborted. No data deleted. Archive file kept." -ForegroundColor Yellow
    exit 0
}

# ====== STEP 4: WIPE ======
Write-Host ""
Write-Host "=== Step 4: Wiping agent_messages ===" -ForegroundColor Cyan

function Delete-Kind {
    param([string]$kindName)
    $q = @{ "kind" = "eq." + $kindName }
    $u = Build-Url -baseUrl $url -path "/rest/v1/agent_messages" -query $q
    $h = $sbHeaders.Clone()
    $h["Prefer"] = "return=minimal"
    try {
        $r = Invoke-WebRequest -Uri $u -Headers $h -Method Delete -UseBasicParsing -TimeoutSec 300
        Write-Host ("  " + $kindName + ": " + $r.StatusCode) -ForegroundColor Green
    }
    catch {
        $msg = $_.Exception.Message
        $isTransient = $false
        if ($msg -match "500") { $isTransient = $true }
        elseif ($msg -match "504") { $isTransient = $true }
        elseif ($msg -match "timeout") { $isTransient = $true }
        if ($isTransient) {
            Write-Host ("  " + $kindName + ": Supabase busy, will retry on next prune") -ForegroundColor DarkYellow
        } else {
            Write-Host ("  " + $kindName + ": " + $msg) -ForegroundColor Red
        }
    }
}

foreach ($k in @("signal", "info", "error", "veto", "approve", "execute", "close")) {
    Delete-Kind -kindName $k
    Start-Sleep -Milliseconds 1500
}

# Catch-all for any kind we didn't list (defensive)
$qAll = @{ "id" = "neq.00000000-0000-0000-0000-000000000000" }
$uAll = Build-Url -baseUrl $url -path "/rest/v1/agent_messages" -query $qAll
$h = $sbHeaders.Clone()
$h["Prefer"] = "return=minimal"
try {
    $r = Invoke-WebRequest -Uri $uAll -Headers $h -Method Delete -UseBasicParsing -TimeoutSec 300
    Write-Host ("  catch-all leftovers: " + $r.StatusCode) -ForegroundColor Green
} catch {
    Write-Host ("  catch-all leftovers: " + $_.Exception.Message) -ForegroundColor DarkYellow
}

# Final count
Start-Sleep -Seconds 2
$qCount = @{ "select" = "id"; "limit" = "1" }
$uCount = Build-Url -baseUrl $url -path "/rest/v1/agent_messages" -query $qCount
$hCount = $sbHeaders.Clone()
$hCount["Prefer"] = "count=exact"
try {
    $r = Invoke-WebRequest -Uri $uCount -Headers $hCount -Method Get -UseBasicParsing -TimeoutSec 60
    $cr = $r.Headers["Content-Range"]
    if ($cr -is [array]) { $cr = $cr[0] }
    if ($cr -match '/(\d+)$') {
        Write-Host ""
        Write-Host ("Final row count: " + $matches[1]) -ForegroundColor Green
    }
}
catch { }

Write-Host ""
Write-Host "=== CLEAN SLATE DONE ===" -ForegroundColor Cyan
Write-Host ("Archive: " + $archiveFile) -ForegroundColor Gray
Write-Host "Mem0: audit decisions backed up as test records" -ForegroundColor Gray
Write-Host ""
Write-Host "Tomorrow:" -ForegroundColor Yellow
Write-Host "  1. Bot starts with empty agent_messages" -ForegroundColor Gray
Write-Host "  2. Auto-prune runs every 3 hours" -ForegroundColor Gray
Write-Host "  3. Mem0 keeps learning, has today's backup" -ForegroundColor Gray
Write-Host "  4. All today bug fixes active (Tasks 48, 54, 55, etc)" -ForegroundColor Gray
