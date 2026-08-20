# ==============================================================
#  SHIP THE PROFIT-LADDER FIX TO TREZO-SERVER
#  Where: on YOUR PC, right-click Start -> Terminal.
#  What:  copies 12 changed engine files to the server, runs the
#         guard tests there, restarts the engine, health-checks it.
#  Not:   no npm, no rebuild, no venv rebuild -- Python only, and
#         no new dependencies. Web and API are untouched.
#  Asks for the server password twice (screen stays blank while
#  you type; right-click pastes).
# ==============================================================
$ErrorActionPreference = "Stop"
$srv  = "administrator@3.232.192.79"
$repo = "C:\Trezo"

Write-Host ""
Write-Host "  TREZO -- ship profit-ladder fix" -ForegroundColor Cyan
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray

# --- market-hours guard ---------------------------------------
# The server's standing rule: no code changes 9:30-16:00 ET. The
# engine restart below drops every in-flight tick, so this is not
# a formality.
$et = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
        (Get-Date), "Eastern Standard Time")
$open = ($et.DayOfWeek -ne "Saturday" -and $et.DayOfWeek -ne "Sunday" -and
         $et.TimeOfDay -ge [TimeSpan]"09:30" -and $et.TimeOfDay -lt [TimeSpan]"16:00")
if ($open) {
  Write-Host ""
  Write-Host "  It is $($et.ToString('HH:mm')) ET -- the market is OPEN." -ForegroundColor Yellow
  Write-Host "  Restarting the engine now interrupts live position" -ForegroundColor Yellow
  Write-Host "  monitoring. Ship after 16:00 ET unless you mean it." -ForegroundColor Yellow
  $go = Read-Host "  Type SHIP to go anyway, anything else to stop"
  if ($go -ne "SHIP") { Write-Host "  Stopped. Nothing sent." -ForegroundColor Green; return }
}

# --- 1. sanity: are the files actually here? ------------------
$files = @(
  "trezo-platform\agents\app\agents\position_monitor.py",
  "trezo-platform\agents\app\paper\engine.py",
  "trezo-platform\agents\app\paper\stocks_reconcile.py",
  "trezo-platform\agents\app\paper\adoption.py",
  "trezo-platform\agents\app\paper\position_status.py",
  "trezo-platform\agents\app\runtime\book_scope.py",
  "trezo-platform\agents\app\runtime\asset_policy.py",
  "trezo-platform\agents\tests\_bootstrap.py",
  "trezo-platform\agents\tests\test_asset_policy.py",
  "trezo-platform\agents\tests\test_book_scope.py",
  "trezo-platform\agents\tests\test_position_status.py",
  "trezo-platform\db\migrations\0051_position_status_partial.sql"
)
cd $repo
$missing = $files | Where-Object { -not (Test-Path $_) }
if ($missing) {
  Write-Host "  Missing on this PC:" -ForegroundColor Red
  $missing | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
  return
}
Write-Host "  [1/5] All 12 files present." -ForegroundColor Green

# --- 2. pack ---------------------------------------------------
if (Test-Path trezo-ladder-fix.tar) { Remove-Item trezo-ladder-fix.tar }
tar -cf trezo-ladder-fix.tar $files
$kb = [math]::Round((Get-Item trezo-ladder-fix.tar).Length/1KB)
if ($kb -lt 50) { Write-Host "  PACK FAILED ($kb KB) -- are you in C:\Trezo?" -ForegroundColor Red; return }
Write-Host "  [2/5] Packed $kb KB." -ForegroundColor Green

# --- 3. upload + unpack ---------------------------------------
# Reachability FIRST. On 8/17 scp died on a connection timeout before
# it ever printed a prompt, so the password being pasted landed at the
# PowerShell prompt instead -- into the shell, into the saved history
# file, and into a screenshot. Never ask for a credential before you
# know something is listening.
Write-Host "  [3/5] Checking the server is reachable..." -ForegroundColor Cyan
$reach = Test-NetConnection -ComputerName ($srv.Split("@")[1]) -Port 22 `
           -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $reach) {
  Remove-Item trezo-ladder-fix.tar -ErrorAction SilentlyContinue
  Write-Host ""
  Write-Host "  Port 22 on $($srv.Split('@')[1]) is not answering." -ForegroundColor Red
  Write-Host "  DO NOT paste your password anywhere -- nothing will ask" -ForegroundColor Yellow
  Write-Host "  for it, so it would go straight into your shell history." -ForegroundColor Yellow
  Write-Host ""
  Write-Host "  The server itself is probably fine (the ops relay keeps" -ForegroundColor DarkGray
  Write-Host "  posting to Supabase). Check Lightsail -> the instance ->" -ForegroundColor DarkGray
  Write-Host "  Networking -> IPv4 Firewall: the SSH rule is likely still" -ForegroundColor DarkGray
  Write-Host "  pinned to an old source IP." -ForegroundColor DarkGray
  Write-Host ""
  Write-Host "  Better: stop using this script. Run" -ForegroundColor Cyan
  Write-Host "  C:\Trezo\SETUP-GITHUB-DEPLOY.ps1 once and deploy through" -ForegroundColor Cyan
  Write-Host "  the ops relay instead -- no SSH, no password." -ForegroundColor Cyan
  return
}
Write-Host "        reachable." -ForegroundColor Green

Write-Host "  [3/5] Uploading -- password prompt #1:" -ForegroundColor Cyan
scp -o StrictHostKeyChecking=accept-new trezo-ladder-fix.tar "${srv}:C:/Trezo/"
if ($LASTEXITCODE -ne 0) { Write-Host "  Upload failed. Nothing changed on the server." -ForegroundColor Red; return }

Write-Host "  [4/5] Unpacking, testing, restarting -- password prompt #2:" -ForegroundColor Cyan
$remote = @'
cd /d C:\Trezo && tar -xf trezo-ladder-fix.tar && del trezo-ladder-fix.tar && ^
echo. && echo === GUARD TESTS === && ^
cd /d C:\Trezo\trezo-platform\agents && ^
.venv\Scripts\python.exe tests\test_asset_policy.py && ^
.venv\Scripts\python.exe tests\test_book_scope.py && ^
.venv\Scripts\python.exe tests\test_position_status.py && ^
echo. && echo === RESTARTING ENGINE === && ^
C:\ProgramData\chocolatey\bin\nssm.exe restart TrezoAgents && ^
timeout /t 12 /nobreak > nul && ^
C:\ProgramData\chocolatey\bin\nssm.exe status TrezoAgents
'@
ssh -o StrictHostKeyChecking=accept-new $srv $remote
$sshExit = $LASTEXITCODE
Remove-Item trezo-ladder-fix.tar -ErrorAction SilentlyContinue

if ($sshExit -ne 0) {
  Write-Host ""
  Write-Host "  A step on the server failed (see output above)." -ForegroundColor Red
  Write-Host "  If the GUARD TESTS failed, the engine was NOT restarted" -ForegroundColor Yellow
  Write-Host "  and is still running the old code -- that is deliberate." -ForegroundColor Yellow
  Write-Host "  Send Nova the output." -ForegroundColor Yellow
  return
}

# --- 5. health ------------------------------------------------
Write-Host "  [5/5] Health check -- password prompt #3:" -ForegroundColor Cyan
ssh $srv "curl -s http://localhost:8001/health"

Write-Host ""
Write-Host "  SHIPPED." -ForegroundColor Green
Write-Host ""
Write-Host "  STILL TO DO -- the migration. The code change alone does" -ForegroundColor Yellow
Write-Host "  not widen the database constraint, and without it every" -ForegroundColor Yellow
Write-Host "  profit step still banks at the broker and records nothing." -ForegroundColor Yellow
Write-Host "  Open Supabase -> SQL Editor and run:" -ForegroundColor Yellow
Write-Host "    C:\Trezo\trezo-platform\db\migrations\0051_position_status_partial.sql" -ForegroundColor White
Write-Host ""
