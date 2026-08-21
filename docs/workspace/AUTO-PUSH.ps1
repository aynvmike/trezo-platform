# AUTO-PUSH -- keep GitHub current without anyone at the keyboard.
# Every run: fast-forward from GitHub, then push anything Nova has
# committed locally. Safe by construction: --ff-only never touches
# uncommitted work, and push only ships commits that already exist.
#
# Since 2026-08-21 it also keeps the USB stick current: if a Trezo USB
# is plugged in (any drive letter), BACKUP-USB.ps1 mirrors C:\Trezo onto
# it after the sync -- only when the repo moved or the last mirror is
# over an hour old, so the stick isn't thrashed every ten minutes.
#
# Run once by hand:      & C:\Trezo\AUTO-PUSH.ps1
# Run every 10 minutes:  & C:\Trezo\AUTO-PUSH.ps1 -Register
param([switch]$Register)

if ($Register) {
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Trezo\AUTO-PUSH.ps1"
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
             -RepetitionInterval (New-TimeSpan -Minutes 10)
  try {
    Register-ScheduledTask -TaskName "TrezoAutoPush" -Action $action `
      -Trigger $trigger -Description "Push Trezo commits to GitHub every 10 min; mirror to USB when present" `
      -Force -ErrorAction Stop | Out-Null
    Write-Host "  TrezoAutoPush registered - every 10 minutes while you're logged in." -ForegroundColor Cyan
  } catch {
    Write-Host "  REGISTRATION FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Re-run from an ADMINISTRATOR PowerShell." -ForegroundColor Red
  }
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

# USB mirror, only if a Trezo stick is plugged in. Never fails the sync.
try {
  $usbOut = (& C:\Trezo\BACKUP-USB.ps1 -Quiet -OnlyIfStale 2>&1 | Out-String)
  $mk = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2" -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.DeviceID "TREZO-USB.json") } | Select-Object -First 1
  if ($mk) {
    $info = Get-Content (Join-Path $mk.DeviceID "TREZO-USB.json") -Raw | ConvertFrom-Json
    "usb: $($mk.DeviceID) at $($info.head), mirrored $($info.mirrored_at) (robocopy $($info.robocopy))" |
      Out-File $log -Append -Encoding utf8
  } else {
    "usb: no Trezo stick present" | Out-File $log -Append -Encoding utf8
  }
  if ($usbOut.Trim()) { $usbOut | Out-File $log -Append -Encoding utf8 }
} catch {
  "usb: mirror step errored - $($_.Exception.Message)" | Out-File $log -Append -Encoding utf8
}
