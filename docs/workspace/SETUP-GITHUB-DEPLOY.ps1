# ==============================================================
#  SET UP THE GITHUB DEPLOY PATH  (run once, on YOUR PC)
#
#  Why: today's ship failed because it depended on SSH being
#  reachable, and it wasn't. The ops relay already runs jobs on
#  the server via Supabase -- including 'git_pull_restart' -- but
#  the repo has no remote, so there is nowhere to pull from.
#  This adds it. After this, deploying is: commit, push, queue
#  one row. No SSH, no passwords typed into terminals.
#
#  BEFORE RUNNING: create an EMPTY PRIVATE repo on github.com.
#  No README, no .gitignore, no licence -- empty. Copy its URL.
#
#  Usage:
#    & C:\Trezo\SETUP-GITHUB-DEPLOY.ps1 -RepoUrl "https://github.com/<you>/trezo-platform.git"
# ==============================================================
param(
  [Parameter(Mandatory=$true)][string]$RepoUrl
)
$ErrorActionPreference = "Stop"
$repo = "C:\Trezo\trezo-platform"
cd $repo

Write-Host ""
Write-Host "  TREZO -- GitHub deploy path setup" -ForegroundColor Cyan
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray

# --- 1. SECRET PRE-FLIGHT ------------------------------------
# This repo sits next to broker credentials and a Supabase
# service-role key. A private repo is not an excuse to skip the
# check -- private repos get shared, forked and made public.
Write-Host "  [1/6] Secret pre-flight..." -ForegroundColor Cyan

$envTracked = git ls-files | Where-Object { $_ -match '\.env$' -or $_ -match '\.env\.' } |
              Where-Object { $_ -notmatch '\.env\.example$' }
if ($envTracked) {
  Write-Host "  STOP -- a .env file is tracked by git:" -ForegroundColor Red
  $envTracked | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
  Write-Host "  Do not push. Send Nova this list." -ForegroundColor Red
  return
}

$envHistory = git log --oneline --all -- "*.env" "*/.env" 2>$null
if ($envHistory) {
  Write-Host "  STOP -- a .env appears in git HISTORY:" -ForegroundColor Red
  $envHistory | Select-Object -First 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
  Write-Host "  Pushing would publish those keys. Send Nova this." -ForegroundColor Red
  return
}

# 2026-08-17: the first version of this used '(PK|AK)[A-Z0-9]{18,}',
# which matches by chance inside the base64 integrity hashes in
# package-lock.json and pnpm-lock.yaml -- so it blocked the push over
# two lockfiles containing no secret at all. A pre-flight that cries
# wolf gets switched off, which is worse than not having one. The
# patterns below are anchored to real credential prefixes, and lock
# files are skipped outright: their contents are hashes by definition.
$pattern = 'eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}'
$skip = '\.env\.example$|package-lock\.json$|pnpm-lock\.yaml$|yarn\.lock$|\.min\.(js|css)$'
$hits = @()
foreach ($f in (git ls-files)) {
  if ($f -match $skip) { continue }
  if (-not (Test-Path $f)) { continue }
  $m = Select-String -Path $f -Pattern $pattern -ErrorAction SilentlyContinue |
       Select-Object -First 1
  if ($m) { $hits += "$f : line $($m.LineNumber)" }
}
if ($hits) {
  Write-Host "  STOP -- credential-shaped strings in tracked files:" -ForegroundColor Red
  $hits | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
  return
}
Write-Host "        clean -- no .env tracked, none in history, no key-shaped strings." -ForegroundColor Green

# --- 2. untrack the runtime counter ---------------------------
# It is rewritten constantly and is not source of truth. Tracked,
# it would dirty the server's tree and block every --ff-only pull.
Write-Host "  [2/6] Untracking agents\app\memory\.usage_budget.json..." -ForegroundColor Cyan
git rm --cached -q "agents/app/memory/.usage_budget.json" 2>$null
if (-not (Select-String -Path .gitignore -Pattern 'usage_budget' -Quiet)) {
  Add-Content .gitignore "`n# Runtime counter, rewritten constantly -- never source of truth.`nagents/app/memory/.usage_budget.json"
}
Write-Host "        done." -ForegroundColor Green

# --- 3. commit -------------------------------------------------
Write-Host "  [3/6] Committing..." -ForegroundColor Cyan
if (-not (git config user.name))  { git config user.name  "Nova" }
if (-not (git config user.email)) { git config user.email "nova@trezo.local" }
git add -A
$msg = @"
profit ladder: scope every broker read to its own book, and let a partial close be written down

Four defects, found 8/17 when GDX and LINKUSD sat in profit without
stepping and the 75k book's XRP round-tripped into the red.

1. position_monitor read the broker's held-symbol set ONCE, before the
   per-row account binding, so all three books were judged against the
   primary's holdings. Rows the primary did not also hold were closed as
   phantoms -- nine positions in the 75k, eight in the 25k, all still
   live at Alpaca and none of them managed. Alpaca holds no bracket on
   crypto, so those coins had no stop anywhere.
2. record_external_partial_close wrote status 'closed_partial', which
   migration 0008's CHECK constraint never allowed. Every profit step
   since 7/02 sold at the broker and booked nothing; the step counter
   never persisted, so step 1 re-fired (GDX 4x on 8/11); by step 2 the
   OCO re-protect failed and remainders sat naked.
3. Broker-routed crypto was excluded from the step ladder by an
   `at == "stock"` gate -- true by accident of history, not by decision.
4. The continuous giveback trail was hand-wired to SWING and SCALP, so
   DCA (first rung +3% against a ~6% target) had nothing protecting a
   gain below +3%. That is the XRP giveback.

New: runtime/book_scope.py binds the book as part of answering, so the
wrong order is no longer expressible; runtime/asset_policy.py declares
per asset class what may be stepped, sliced, adopted and session-gated
(stock, crypto, option, forex, future, bond, fund/401k) and per strategy
how a gain is protected; paper/adoption.py writes rows for broker
positions the ledger has lost; paper/position_status.py gives code and
schema one shared list; migration 0051 widens the constraint.

31 guard tests, green, runnable in a bare checkout. One greps the source
and fails if any asset_type comparison has no policy. One asserts the
account binding still appears before the held-symbols read.
"@
git commit -q -m $msg
Write-Host "        $(git rev-parse --short HEAD) committed." -ForegroundColor Green

# --- 4. remote + push -----------------------------------------
Write-Host "  [4/6] Adding remote and pushing..." -ForegroundColor Cyan
git remote remove origin 2>$null
git remote add origin $RepoUrl
$branch = git rev-parse --abbrev-ref HEAD
git push -u origin $branch
if ($LASTEXITCODE -ne 0) {
  Write-Host "  Push failed. Nothing else was changed; fix the auth and re-run" -ForegroundColor Red
  Write-Host "  just: git push -u origin $branch" -ForegroundColor Red
  return
}
Write-Host "        pushed to $RepoUrl ($branch)." -ForegroundColor Green

# --- 5 + 6. what is left, printed as a checklist ---------------
Write-Host ""
Write-Host "  [5/6] SERVER SIDE -- do this over RDP, once" -ForegroundColor Yellow
Write-Host "  (you are already RDP-ing in to rotate the password)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "   a. On github.com: Settings -> Developer settings ->" -ForegroundColor White
Write-Host "      Personal access tokens -> Fine-grained tokens." -ForegroundColor White
Write-Host "      Repository access: ONLY this repo." -ForegroundColor White
Write-Host "      Permissions: Contents = READ-ONLY. Nothing else." -ForegroundColor White
Write-Host "      A read-only token cannot damage the repo if the box is" -ForegroundColor DarkGray
Write-Host "      ever compromised -- and that box holds broker keys." -ForegroundColor DarkGray
Write-Host ""
Write-Host "   b. In the server's PowerShell:" -ForegroundColor White
Write-Host ""
Write-Host '      cd C:\Trezo\trezo-platform' -ForegroundColor Gray
Write-Host '      git stash -u' -ForegroundColor Gray
Write-Host '      git remote remove origin' -ForegroundColor Gray
Write-Host '      git remote add origin https://x-access-token:<TOKEN>@github.com/<you>/trezo-platform.git' -ForegroundColor Gray
Write-Host '      git fetch origin' -ForegroundColor Gray
Write-Host ("      git reset --hard origin/" + $branch) -ForegroundColor Gray
Write-Host ""
Write-Host "      reset --hard is safe here: your PC is source of truth and" -ForegroundColor DarkGray
Write-Host "      the server's tree came from a tar drop, not from git." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  [6/6] THE MIGRATION -- Supabase SQL editor, paste and run:" -ForegroundColor Yellow
Write-Host "      C:\Trezo\trezo-platform\db\migrations\0051_position_status_partial.sql" -ForegroundColor White
Write-Host "      Without it every profit step still banks at the broker" -ForegroundColor DarkGray
Write-Host "      and records nothing. This is the half that matters." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  ONCE THOSE ARE DONE, every future deploy is two steps:" -ForegroundColor Cyan
Write-Host "      1. git push          (from this PC)" -ForegroundColor White
Write-Host "      2. in Supabase SQL:  insert into ops_tasks (kind, note)" -ForegroundColor White
Write-Host "                           values ('git_pull_restart', 'what changed');" -ForegroundColor White
Write-Host "      The engine picks it up on its next watchdog tick, pulls," -ForegroundColor DarkGray
Write-Host "      restarts itself, and writes the outcome back to the row." -ForegroundColor DarkGray
Write-Host "      Works from your phone. No SSH." -ForegroundColor DarkGray
Write-Host ""
