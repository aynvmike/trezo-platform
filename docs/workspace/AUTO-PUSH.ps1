# AUTO-PUSH -- keep GitHub current without anyone at the keyboard.
# Every run: fast-forward from GitHub, then push anything Nova has
# committed locally. Safe by construction: --ff-only never touches
# uncommitted work, and push only ships commits that already exist.
#
# Run once by hand:      & C:\Trezo\AUTO-PUSH.ps1
# Run every 10 minutes:  & C:\Trezo\AUTO-PUSH.ps1 -Register
param([switch]$Register)

if ($Register) {
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Trezo\AUTO-PUSH.ps1"
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
             -RepetitionInterval (New-TimeSpan -Minutes 10)
  Register-ScheduledTask -TaskName "TrezoAutoPush" -Action $action `
    -Trigger $trigger -Description "Push Trezo commits to GitHub every 10 min" -Force
  Write-Host "  TrezoAutoPush registered - every 10 minutes while you're logged in." -ForegroundColor Cyan
  return
}

$log = "C:\Trezo\auto-push-output.txt"
"=== $(Get-Date -Format s) ===" | Out-File $log -Encoding utf8
cd C:\Trezo\trezo-platform

# Clear any lock the device bridge left behind (rename, never delete).
if (Test-Path .git\index.lock) {
  Move-Item .git\index.lock (".git\stale.ilock." + (Get-Random)) -ErrorAction SilentlyContinue
}

(git pull --ff-only origin main 2>&1) | Out-File $log -Append -Encoding utf8
$ahead = git rev-list --count origin/main..HEAD 2>$null
if ([int]$ahead -gt 0) {
  "pushing $ahead commit(s)..." | Out-File $log -Append -Encoding utf8
  (git push origin main 2>&1)  | Out-File $log -Append -Encoding utf8
} else {
  "nothing to push" | Out-File $log -Append -Encoding utf8
}
(git log --oneline -1 2>&1) | Out-File $log -Append -Encoding utf8
