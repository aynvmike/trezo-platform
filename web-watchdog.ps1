# web-watchdog.ps1
# Runs every 5 min via Windows Scheduled Task (TrezoWebWatchdog).
# Watches the DASHBOARD tier on port 3000 and auto-repairs it.
#
# Mike 2026-08-18: dashboard was unreachable over Tailscale
# (ERR_CONNECTION_RESET on 100.115.119.32:3000) while the trading
# engine kept running fine. Root cause: the web tier was a console
# window launched by a /sc onlogon /it scheduled task, so it dies on
# logoff / reboot-without-signin, while TrezoAgents (an NSSM service)
# survives. install-web-as-service.bat is the structural fix; this
# script is defense-in-depth for hangs NSSM can't see.
#
# ---------------------------------------------------------------
# HARD RULE: this script NEVER touches port 8001 / TrezoAgents.
# The engine is watched by health-watchdog.ps1 alone. Two scripts
# racing to start the engine could put two engines on one Alpaca
# account. Web tier only. Do not add agent logic here.
# ---------------------------------------------------------------
#
# Repair ladder:
#   1st failed probe  -> log only (ride out transient reloads)
#   2nd failed probe  -> repair (restart service, or relaunch console)
#   3rd+ repair       -> repair AND clear the .next cache
#   3 repairs, still down -> raise an urgent row in ops_health_alerts
#                            so the daily sentinel sweep surfaces it,
#                            plus a desktop toast.

$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir    = Join-Path $scriptDir "logs"
$stateDir  = Join-Path $scriptDir "state"
foreach ($d in @($logDir, $stateDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

$logFile     = Join-Path $logDir ("web-watchdog-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
$failFile    = Join-Path $stateDir "web-fails.txt"
$repairFile  = Join-Path $stateDir "web-repairs.txt"
$envPath     = Join-Path $scriptDir "agents\.env"
$serviceName = "TrezoWeb"
$webUrl      = "http://localhost:3000"

function Log {
    param([string]$msg)
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Add-Content -Path $logFile -Value $line
    Write-Host $line
}

function Read-Counter {
    param([string]$path)
    if (Test-Path $path) {
        $v = (Get-Content $path -Raw -ErrorAction SilentlyContinue)
        if ($v) { return [int]($v.Trim()) }
    }
    return 0
}

function Notify {
    param([string]$title, [string]$msg)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $b = New-Object System.Windows.Forms.NotifyIcon
        $b.Icon = [System.Drawing.SystemIcons]::Warning
        $b.Visible = $true
        $b.ShowBalloonTip(10000, $title, $msg, [System.Windows.Forms.ToolTipIcon]::Warning)
        Start-Sleep -Seconds 11
        $b.Dispose()
    } catch { }
}

function Resolve-Nssm {
    $candidates = @(
        "C:\ProgramData\chocolatey\bin\nssm.exe",
        "C:\Windows\System32\nssm.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $w = (Get-Command nssm.exe -ErrorAction SilentlyContinue)
    if ($w) { return $w.Source }
    return $null
}

# Read one key out of agents\.env. Duplicate keys: last value wins,
# matching how the Python loader behaves.
function Read-EnvValue {
    param([string]$name)
    if (-not (Test-Path $envPath)) { return $null }
    $val = $null
    foreach ($line in Get-Content $envPath) {
        if ($line -match ("^\s*" + [regex]::Escape($name) + "\s*=\s*(.+?)\s*$")) {
            $val = $matches[1].Trim('"').Trim("'")
        }
    }
    return $val
}

# Say it where Mike will actually see it.
#
# Added 2026-08-18 (evening). The escalation path here was a Supabase
# row plus a desktop toast. The row waits for a daily sweep, and the
# toast pops on a headless VM nobody is looking at -- so a dashboard
# that died at 2am announced itself to an empty room. The engine already
# has a Discord webhook Mike carries in his pocket; use the same one.
function Send-DiscordAlert {
    param([string]$message)
    $hook = Read-EnvValue "TREZO_ALERT_WEBHOOK"
    if (-not $hook) { Log "  (no TREZO_ALERT_WEBHOOK - skipping Discord)"; return }
    try {
        $body = @{ content = ":red_circle: **Dashboard down** - " + $message } |
                ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $hook -Method Post -ContentType "application/json" `
            -Body $body -TimeoutSec 20 | Out-Null
        Log "  Discord alert sent"
    } catch {
        Log "  WARN Discord alert failed: $($_.Exception.Message)"
    }
}

# Raise an alert row in Supabase so it shows up in the daily sentinel
# sweep even if Mike never sees the toast.
function Raise-SupabaseAlert {
    param([string]$message)
    if (-not (Test-Path $envPath)) { Log "  (no agents\.env - skipping Supabase alert)"; return }

    $url = $null; $key = $null
    foreach ($line in Get-Content $envPath) {
        # duplicate keys: last value wins, matching the loader elsewhere
        if     ($line -match '^\s*SUPABASE_URL\s*=\s*(.+?)\s*$')              { $url = $matches[1].Trim('"').Trim("'") }
        elseif ($line -match '^\s*SUPABASE_SERVICE_ROLE_KEY\s*=\s*(.+?)\s*$') { $key = $matches[1].Trim('"').Trim("'") }
    }
    if (-not $url -or -not $key) { Log "  (Supabase creds not found - skipping alert)"; return }

    $body = @{
        alert_kind  = "web_tier_down"
        target_name = "web"
        severity    = "urgent"
        message     = $message
        raised_at   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    } | ConvertTo-Json -Compress

    try {
        Invoke-RestMethod -Uri ($url.TrimEnd('/') + "/rest/v1/ops_health_alerts") `
            -Method Post `
            -Headers @{ "apikey" = $key; "Authorization" = "Bearer $key"; "Content-Type" = "application/json"; "Prefer" = "return=minimal" } `
            -Body $body -TimeoutSec 30 | Out-Null
        Log "  raised ops_health_alerts row (web_tier_down)"
    } catch {
        Log "  WARN could not raise Supabase alert: $($_.Exception.Message)"
    }
}

# Probe. We are testing "is the tier serving HTTP", not "am I logged
# in" - the auth middleware redirects to /login, and a 401/403/307 all
# still prove the process is alive. Only a dead socket or a 5xx counts
# against it.
#   returns: "ok" | "dead" | "broken"
function Test-Web {
    try {
        $r = Invoke-WebRequest -Uri $webUrl -TimeoutSec 15 -UseBasicParsing -MaximumRedirection 5
        if ([int]$r.StatusCode -ge 500) { return "broken" }
        return "ok"
    } catch {
        $resp = $_.Exception.Response
        if ($resp -ne $null) {
            try {
                $code = [int]$resp.StatusCode
                if ($code -ge 500) { return "broken" }
                return "ok"     # 4xx = server alive and answering
            } catch { return "ok" }
        }
        return "dead"           # refused / reset / timeout = nothing listening
    }
}

Log "=== web watchdog start ==="

$status = Test-Web

if ($status -eq "ok") {
    $prevFails = Read-Counter $failFile
    if ($prevFails -gt 0) { Log "OK web recovered after $prevFails failed probe(s)" }
    else                  { Log "OK web responding on 3000" }
    Set-Content -Path $failFile   -Value "0"
    Set-Content -Path $repairFile -Value "0"
    Log "=== web watchdog done ==="
    exit 0
}

$fails = (Read-Counter $failFile) + 1
Set-Content -Path $failFile -Value "$fails"
Log "FAIL web status=$status (consecutive failed probes: $fails)"

if ($fails -lt 2) {
    Log "  holding one tick to rule out a transient reload"
    Log "=== web watchdog done ==="
    exit 0
}

# ---- repair ----
$repairs = (Read-Counter $repairFile) + 1
Set-Content -Path $repairFile -Value "$repairs"
Log "REPAIR attempt #$repairs (status=$status)"

# From the 2nd repair on - or any time the tier answers 5xx - clear the
# Next build cache. That is the known fix for the dev-server
# "Cannot read properties of null (reading 'useContext')" wedge.
$clearCache = ($repairs -ge 2 -or $status -eq "broken")
if ($clearCache) {
    $nextDir = Join-Path $scriptDir "web\.next"
    if (Test-Path $nextDir) {
        try {
            Remove-Item -Recurse -Force $nextDir -ErrorAction Stop
            Log "  cleared web\.next cache"
        } catch {
            Log "  WARN could not clear .next: $($_.Exception.Message)"
        }
    }
}

$nssm = Resolve-Nssm
$svc  = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if ($svc -and $nssm) {
    # Preferred path: the web tier is an NSSM service, so a restart
    # works with no interactive session and survives logoff.
    Log "  restarting service $serviceName via nssm"
    & $nssm restart $serviceName 2>&1 | ForEach-Object { Log "    $_" }
} else {
    # Fallback: legacy console-window mode. Free the port, relaunch.
    Log "  $serviceName service not installed - falling back to console relaunch"
    Log "  (run install-web-as-service.bat as Admin to make this durable)"

    $pids = (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
             Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($p in $pids) {
        if ($p -and $p -ne 0) {
            try { Stop-Process -Id $p -Force -ErrorAction Stop; Log "    killed PID $p (held 3000)" } catch { }
        }
    }
    Start-Sleep -Seconds 2

    $startBat = Join-Path $scriptDir "start-web.bat"
    if (Test-Path $startBat) {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "start", '"Trezo - Web"', "cmd.exe", "/k", "`"$startBat`""
        Log "    start-web.bat launched in new window"
    } else {
        Log "    ERROR start-web.bat not found at $startBat"
    }
}

# ---- verify ----
# next dev needs a beat to compile the first route after a cold start.
Log "  waiting 45s for the tier to come up"
Start-Sleep -Seconds 45

$after = Test-Web
if ($after -eq "ok") {
    Log "  VERIFIED web responding after repair"
    Set-Content -Path $failFile   -Value "0"
    Set-Content -Path $repairFile -Value "0"
} else {
    Log "  WARN still status=$after after repair #$repairs"
    if ($repairs -ge 3) {
        $msg = "Trezo dashboard (port 3000) still $after after $repairs auto-repair attempts. Engine on 8001 is unaffected and not touched by this watchdog. Check logs\web-watchdog-$(Get-Date -Format 'yyyy-MM-dd').log on Trezo-Server."
        Log "  ESCALATING after $repairs failed repairs"
        Send-DiscordAlert $msg
        Raise-SupabaseAlert $msg
        Notify "Trezo dashboard down" $msg
        Set-Content -Path $repairFile -Value "0"   # reset so it re-escalates later, not every 5 min
    }
}

Log "=== web watchdog done ==="
