# verify-server.ps1 -- does the server actually have everything it needs?
#
# Mike, 2026-08-18: "we need to keep track of what is stored to the pc
# and the actual server."
#
# Written after a day in which FOUR separate things were true on Mike's
# PC and had never been established on the box:
#
#   1. main had no upstream, so every `git pull --ff-only` in the deploy
#      pulled nothing and restarted the engine anyway. Two outages.
#   2. install-web-as-service.bat and the web watchdog were never
#      committed, so the server could not run them.
#   3. migration 0054 -- the restart-didn't-return guard -- had never
#      been applied, so a five-hour outage went unannounced.
#   4. web\node_modules did not exist (workspaces hoist to the root), so
#      the dashboard service died with MODULE_NOT_FOUND.
#
# Every one failed SILENTLY, and every one was verified at the wrong end
# -- by looking at the PC, or at a row that said "done". This script
# looks at the box, and says what is missing rather than what is fine.
#
# Read-only. Changes nothing. Safe to run any time.
#   powershell -ExecutionPolicy Bypass -File verify-server.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$fail = 0
$warn = 0

function Ok   ($m) { Write-Host "  PASS  $m" -ForegroundColor Green }
function Bad  ($m) { Write-Host "  FAIL  $m" -ForegroundColor Red;    $script:fail++ }
function Warn ($m) { Write-Host "  WARN  $m" -ForegroundColor Yellow; $script:warn++ }
function Section ($m) { Write-Host ""; Write-Host "== $m" -ForegroundColor Cyan }

Write-Host "Trezo server verification -- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Repo: $root"

# ---------------------------------------------------------------- code
Section "Code and the path that updates it"

$head = (git -C $root rev-parse --short HEAD 2>$null)
if ($head) { Ok "HEAD is $head" } else { Bad "not a git checkout" }

# THE bug of 2026-08-18. Without an upstream, `git pull --ff-only` with
# no arguments exits non-zero having done nothing at all.
$upstream = (git -C $root rev-parse --abbrev-ref '@{u}' 2>$null)
if ($upstream) {
    Ok "branch tracks $upstream"
    git -C $root fetch --quiet origin 2>$null
    $behind = (git -C $root rev-list --count "HEAD..$upstream" 2>$null)
    if ($behind -and [int]$behind -gt 0) {
        Warn "$behind commit(s) behind $upstream -- deploy has not landed"
    } else { Ok "up to date with $upstream" }
} else {
    Bad "branch has NO upstream -- every `git pull --ff-only` is a silent no-op"
    Write-Host "        fix: git branch --set-upstream-to=origin/main main" -ForegroundColor Yellow
}

$dirty = (git -C $root status --porcelain 2>$null)
if ($dirty) { Warn "working tree not clean -- a pull may refuse to fast-forward" }
else        { Ok "working tree clean" }

# ------------------------------------------------------------ services
Section "Services"

foreach ($svc in @("TrezoAgents", "TrezoWeb", "TrezoApi")) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if (-not $s) { Bad "$svc is not installed" ; continue }
    if ($s.Status -ne "Running") { Bad "$svc is $($s.Status)" }
    else                          { Ok  "$svc running" }
    if ($s.StartType -ne "Automatic") {
        Warn "$svc start type is $($s.StartType) -- it will not come back after a reboot"
    }
}

# --------------------------------------------------------------- ports
Section "Listening"

# Ports corrected 2026-08-18 on the verifier's FIRST run: it claimed the
# api was down on 4000. The api listens on 8000 (api\src\core\config.ts,
# PORT ?? "8000") and binds 127.0.0.1 deliberately -- it was reachable
# from the whole network in July and collected IoT exploit probes.
#
# A verifier that reports a failure that is not real is the same defect
# as the system it checks: it teaches you to skim past red.
foreach ($p in @(@(8001,"engine"), @(3000,"dashboard"), @(8000,"api"))) {
    $port = $p[0]; $what = $p[1]
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { Ok "$what listening on $port" } else { Bad "nothing listening on $port ($what)" }
}

# -------------------------------------------------------- dependencies
Section "Dependencies"

# Workspaces hoist to the ROOT. Assuming web\node_modules is what killed
# TrezoWeb with MODULE_NOT_FOUND.
$nextWeb  = Join-Path $root "web\node_modules\next\dist\bin\next"
$nextRoot = Join-Path $root "node_modules\next\dist\bin\next"
if     (Test-Path $nextWeb)  { Ok "next found in web\node_modules" }
elseif (Test-Path $nextRoot) { Ok "next found in root node_modules (workspaces hoist)" }
else   { Bad "next not found -- run `npm install` from the REPO ROOT, not web\" }

$venv = Join-Path $root "agents\.venv\Scripts\python.exe"
if (Test-Path $venv) { Ok "agents venv present" } else { Bad "agents venv missing" }

# --------------------------------------------------------- credentials
Section "Credentials"

$envPath = Join-Path $root "agents\.env"
if (-not (Test-Path $envPath)) {
    Bad "agents\.env missing -- the one file a rebuild cannot fetch for itself"
} else {
    Ok "agents\.env present"
    $text = Get-Content $envPath -Raw
    foreach ($k in @("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
                     "ALPACA_API_KEY", "TREZO_ALERT_WEBHOOK")) {
        if ($text -match ("(?m)^\s*" + [regex]::Escape($k) + "\s*=\s*\S")) { Ok "  $k set" }
        else { Bad "  $k missing or empty" }
    }
}

# ------------------------------------------------------------- guards
Section "Guard suites"

if (Test-Path $venv) {
    Push-Location (Join-Path $root "agents")
    $out = & $venv -m tests.run_all 2>&1 | Out-String
    Pop-Location
    if ($out -match "all green across") { Ok "guards green" }
    else { Bad "guards NOT green -- do not restart the engine on this code" }
} else { Warn "skipped (no venv)" }

# ------------------------------------------------- one engine, exactly
# Added 2026-08-19, the day we found EIGHTEEN pythons: uvicorn --reload
# engines (spawned by the old health-watchdog path) racing the nssm service
# for port 8001, several trading the same Alpaca account at once. One
# account, one engine. This check would have gone red within minutes of
# the first orphan.
Section "engine singleton"
$uvicorns = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "uvicorn" -and $_.CommandLine -match "app\.main" })
$parents = @($uvicorns | Where-Object { $_.CommandLine -notmatch "multiprocessing" })
if ($parents.Count -gt 2) {
    Bad "MULTIPLE ENGINES: $($parents.Count) uvicorn parents (expected <=2: supervisor+worker). PIDs: $($parents.ProcessId -join ', '). Two engines on one Alpaca account can double-trade it."
} elseif ($parents.Count -eq 0) {
    Bad "NO ENGINE: no uvicorn app.main process found at all."
} else {
    Ok "single engine ($($parents.Count) uvicorn process(es))"
}
$reloaders = @($uvicorns | Where-Object { $_.CommandLine -match "--reload" })
if ($reloaders.Count -gt 0) {
    Bad "--reload ENGINE RUNNING: PIDs $($reloaders.ProcessId -join ', '). Dev flag in production; kill it and find what launched it."
} else {
    Ok "no --reload engines"
}

# ----------------------------------------------------- scheduled tasks
Section "Scheduled tasks"

$tasks = @{
    "TrezoHealthWatchdog" = "the ENGINE's self-healing restart -- without it a dead engine stays dead until a human notices (5h30m on 2026-08-18). Register: register-watchdog-task.bat as Admin"
    "TrezoWebWatchdog"    = "the dashboard's self-healing restart. Register: register-web-watchdog-task.bat as Admin"
}
foreach ($t in $tasks.Keys) {
    $q = schtasks /Query /TN $t 2>$null
    if ($LASTEXITCODE -eq 0) { Ok "$t registered" }
    else {
        Bad "$t NOT registered"
        Write-Host "        $($tasks[$t])" -ForegroundColor Yellow
    }
}

# --------------------------------------------------------------- logs
Section "Logs"

foreach ($d in @("C:\Trezo\logs", (Join-Path $root "logs"))) {
    if (Test-Path $d) { Ok "$d exists" }
    else { Bad "$d missing -- NSSM cannot create it, and fails the start with no log to say so" }
}

# ------------------------------------------------------------ summary
Write-Host ""
Write-Host ("=" * 62)
if ($fail -eq 0 -and $warn -eq 0) {
    Write-Host "Everything established. $head" -ForegroundColor Green
} else {
    Write-Host "$fail failure(s), $warn warning(s). $head" -ForegroundColor Red
    Write-Host "A FAIL is something that is true on the PC and not on this box."
}
exit $fail
