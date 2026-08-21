# BACKUP-USB -- mirror the Trezo workspace onto the USB stick.
# Copies C:\Trezo -> <stick>:\Trezo, skipping machine-junk that has no
# business on a portable copy (.venv, node_modules, _to_delete).
# /MIR makes the stick an exact mirror of what it copies.
#
# The stick is FOUND, not assumed: the drive letter changes between the
# desktop and the laptop, so this looks at every removable drive for a
# TREZO-USB.json marker at its root (written on the first successful
# mirror) or, failing that, an existing Trezo\REBUILD-FROM-USB.md.
#
# Run by hand:       & C:\Trezo\BACKUP-USB.ps1
# Force a letter:    & C:\Trezo\BACKUP-USB.ps1 -Drive F
# From AUTO-PUSH:    & C:\Trezo\BACKUP-USB.ps1 -Quiet -OnlyIfStale
#   (-OnlyIfStale skips the pass when the repo HEAD hasn't moved since
#    the last mirror AND that mirror is under an hour old.)
param(
  [string]$Drive = "",
  [switch]$Quiet,
  [switch]$OnlyIfStale
)

function Say($msg, $color = "Cyan") { if (-not $Quiet) { Write-Host "  $msg" -ForegroundColor $color } }

function Find-TrezoUsb {
  if ($Drive) { return ($Drive.TrimEnd(':', '\') + ":") }
  $removable = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2" -ErrorAction SilentlyContinue
  foreach ($d in $removable) {
    if (Test-Path (Join-Path $d.DeviceID "TREZO-USB.json")) { return $d.DeviceID }
  }
  foreach ($d in $removable) {
    if (Test-Path (Join-Path $d.DeviceID "Trezo\REBUILD-FROM-USB.md")) { return $d.DeviceID }
  }
  return $null
}

$src  = "C:\Trezo"
$root = Find-TrezoUsb
if (-not $root -or -not (Test-Path "$root\")) {
  Say "No Trezo USB stick found - plug it in first (any drive letter works)." "Yellow"
  exit 0
}
$dst    = "$root\Trezo"
$marker = "$root\TREZO-USB.json"
$log    = "C:\Trezo\usb-backup-log.txt"

$head = (git -C "C:\Trezo\trezo-platform" rev-parse --short HEAD 2>$null)
if ($OnlyIfStale -and (Test-Path $marker)) {
  try {
    $last = Get-Content $marker -Raw | ConvertFrom-Json
    $age  = (Get-Date) - [datetime]$last.mirrored_at
    if ($last.head -eq $head -and $age.TotalMinutes -lt 60) {
      Say "USB ($root) already current at $head, mirrored $([int]$age.TotalMinutes)m ago - skipping."
      exit 0
    }
  } catch { }
}

Say "Mirroring C:\Trezo -> $dst. SILENCE IS NORMAL - a full pass can take"
Say "10+ quiet minutes on a USB stick. Do NOT close this window; wait for 'complete'."
robocopy $src $dst /MIR /R:1 /W:2 /NP /NFL /NDL `
  /XD "$src\_to_delete" "$src\trezo-platform\agents\.venv" `
      "$src\trezo-platform\web\node_modules" "$src\trezo-platform\web\.next" `
      "System Volume Information" `
  /XF "*.lock" `
  /LOG:$log
$code = $LASTEXITCODE
# Robocopy: 0-7 = success flavours, 8+ = real failures.
if ($code -lt 8) {
  @{ head = $head; mirrored_at = (Get-Date -Format s); from = $env:COMPUTERNAME; robocopy = $code } |
    ConvertTo-Json | Out-File $marker -Encoding utf8
  Say "USB mirror complete on $root (robocopy code $code, head $head). Log: $log"
  exit 0
} else {
  Say "USB mirror FAILED on $root (robocopy code $code). Read $log" "Red"
  exit 1
}
