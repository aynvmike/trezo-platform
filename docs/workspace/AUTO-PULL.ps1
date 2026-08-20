# AUTO-PULL -- SERVER-SIDE self-updater. Runs OUTSIDE the engine, so its
# restart cannot be killed by the thing it restarts.
#
# Every 10 minutes: fetch. If the server is behind GitHub AND the newest
# commit's subject contains [ship], deploy it the same way the relay
# does: fast-forward pull, run the full guard suite, restart ONLY if
# green, roll back if not. A commit without [ship] just gets logged --
# deploys stay intentional; nothing restarts the engine by accident.
#
# One-time setup on the server:   & C:\Trezo\trezo-platform\docs\workspace\AUTO-PULL.ps1 -Register
# (copies itself to C:\Trezo\AUTO-PULL.ps1 and schedules that copy)
param([switch]$Register)

$repo = "C:\Trezo\trezo-platform"
$nssm = "C:\ProgramData\chocolatey\bin\nssm.exe"
$log  = "C:\Trezo\auto-pull-output.txt"

if ($Register) {
  Copy-Item $PSCommandPath "C:\Trezo\AUTO-PULL.ps1" -Force
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Trezo\AUTO-PULL.ps1"
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
             -RepetitionInterval (New-TimeSpan -Minutes 10)
  try {
    Register-ScheduledTask -TaskName "TrezoAutoPull" -Action $action `
      -Trigger $trigger -RunLevel Highest `
      -Description "Deploy [ship]-tagged Trezo commits from GitHub every 10 min" `
      -Force -ErrorAction Stop | Out-Null
    Write-Host "  TrezoAutoPull registered - checks GitHub every 10 minutes." -ForegroundColor Cyan
  } catch {
    Write-Host "  REGISTRATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  This needs an ADMINISTRATOR PowerShell, on the SERVER." -ForegroundColor Red
  }
  return
}

function Log($m) { "$(Get-Date -Format s)  $m" | Out-File $log -Append -Encoding utf8 }

cd $repo
git fetch origin 2>&1 | Out-Null
$behind = [int](git rev-list --count HEAD..origin/main 2>$null)
if ($behind -eq 0) { return }   # up to date; say nothing, log nothing

$subject = (git log -1 --format=%s origin/main 2>$null)
if ($subject -notmatch '\[ship\]') {
  Log "behind $behind commit(s); newest is '$subject' - not [ship]-tagged, waiting for the relay or the tag"
  return
}

$before = (git rev-parse HEAD).Trim()
Log "deploying: behind $behind, newest '$subject'"
$pull = (git pull --ff-only origin main 2>&1 | Out-String)
Log $pull
if ($LASTEXITCODE -ne 0) { Log "PULL FAILED - not restarting"; return }

cd "$repo\agents"
$py = "$repo\agents\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$guards = (& $py -m tests.run_all 2>&1 | Out-String)
Log ($guards | Select-String -Pattern "green|FAILED|failures" | Out-String)
if ($guards -notmatch "all green across") {
  cd $repo
  git reset --hard $before 2>&1 | Out-Null
  Log "GUARDS FAILED - rolled back to $($before.Substring(0,8)), engine NOT restarted"
  return
}

Log "guards green - restarting TrezoAgents"
& $nssm restart TrezoAgents 2>&1 | Out-File $log -Append -Encoding utf8
Log "restart issued"
