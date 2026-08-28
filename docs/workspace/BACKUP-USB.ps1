# BACKUP-USB -- mirror the Trezo workspace onto the USB stick.
# Copies C:\Trezo -> <stick>:\Trezo, skipping machine-junk that has no
# business on a portable copy (.venv, node_modules, _to_delete).
# /MIR makes the stick an exact mirror of what it copies.
#
# The stick is FOUND, not assumed: the drive letter changes between the
# desktop and the laptop, so this looks at every removable drive for a
# TREZO-USB.json marker at its root (written on the first successful
# mirror, or by double-clicking CLAIM-TREZO-USB.cmd on the stick), a
# volume label of TREZO, or, failing both, an existing
# Trezo\REBUILD-FROM-USB.md.
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
  if ($Drive) {
    $d = ($Drive.TrimEnd(':', '\') + ":")
    # GUARD (2026-08-28 audit): -Drive C would make $dst = C:\Trezo, and
    # the post-mirror secret purge would then delete the LIVE .env files.
    # A typo must never be able to do that.
    if ($d -ieq (Split-Path $src -Qualifier)) {
      Say "-Drive $d is the SOURCE drive - refusing to mirror $src onto itself." "Red"
      exit 1
    }
    if (-not (Test-Path "$d\")) {
      Say "-Drive $d does not exist - plug the stick in or drop the flag." "Red"
      exit 1
    }
    return $d
  }
  $removable = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2" -ErrorAction SilentlyContinue
  foreach ($d in $removable) {
    if (Test-Path (Join-Path $d.DeviceID "TREZO-USB.json")) { return $d.DeviceID }
  }
  foreach ($d in $removable) {
    if ($d.VolumeName -eq "TREZO") { return $d.DeviceID }
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
# SECRETS STAY OFF THE STICK (2026-08-27). The mirror used to carry
# every .env — live broker keys on an unencrypted USB, refreshed every
# pass. /XF hides .env* from the copy, and because /MIR does NOT purge
# destination files that /XF excludes, any .env* a previous pass already
# put on the stick is deleted explicitly below.
robocopy $src $dst /MIR /R:1 /W:2 /NP /NFL /NDL `
  /XD "$src\_to_delete" "$src\trezo-platform\agents\.venv" `
      "$src\trezo-platform\web\node_modules" "$src\trezo-platform\web\.next" `
      "System Volume Information" `
  /XF "*.lock" ".env" ".env.*" "*.env" `
  /LOG:$log
$code = $LASTEXITCODE
# GUARD (2026-08-28 audit): the purge deletes .env* files. It must only
# ever run against a DESTINATION that is not the source tree, and only
# after a mirror that actually succeeded (robocopy 8+ = failure; who
# knows what $dst holds then). Belt and braces with the -Drive refusal.
if (($dst -ne $src) -and ($code -lt 8) -and (Test-Path $dst)) {
  Get-ChildItem $dst -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -eq ".env" -or $_.Name -like ".env.*" -or $_.Name -like "*.env") -and
                   $_.Name -notlike "*.template" } |
    ForEach-Object {
      Say "Removing secret file from stick: $($_.FullName)" "Yellow"
      Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# Write sanitized .env TEMPLATES to the stick (2026-08-27): key names
# only, no values, so RESTORE-FROM-USB knows exactly which keys a
# rebuild must refill without the stick ever carrying a secret. Skips
# .bak copies and examples - stale key sets would only confuse a
# restore. Same guard as the purge: never when $dst is the source tree.
if (($dst -ne $src) -and ($code -lt 8) -and (Test-Path $dst)) {
  Get-ChildItem $src -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object {
      ($_.Name -eq ".env" -or $_.Name -like ".env.*" -or $_.Name -like "*.env") -and
      $_.Name -notlike "*.bak*" -and $_.Name -notlike "*.template" -and
      $_.Name -notlike "*example*" -and
      $_.FullName -notmatch '\\(\.venv|node_modules|_to_delete|\.next)\\'
    } |
    ForEach-Object {
      $rel  = $_.FullName.Substring($src.Length).TrimStart('\')
      $tpl  = Join-Path $dst ($rel + ".template")
      $tdir = Split-Path $tpl -Parent
      if (-not (Test-Path $tdir)) { New-Item -ItemType Directory -Path $tdir -Force | Out-Null }
      $keys = Get-Content $_.FullName -ErrorAction SilentlyContinue |
        ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') { "$($matches[1])=" } }
      @("# Sanitized template written by BACKUP-USB.ps1 - key names only, no values.",
        "# On restore, RESTORE-FROM-USB recreates the real file from this skeleton;",
        "# fill the values from the password manager.") + $keys |
        Set-Content $tpl -Encoding utf8
    }
}
# Robocopy: 0-7 = success flavours, 8+ = real failures.
if ($code -lt 8) {
  # Keep the one-click claim file on the stick so any machine can re-claim it.
  Copy-Item "C:\Trezo\CLAIM-TREZO-USB.cmd" "$root\CLAIM-TREZO-USB.cmd" -Force -ErrorAction SilentlyContinue
  # And the one-click restore at the stick ROOT, so starting back up
  # from this stick is a double-click (2026-08-27, Mike's ask).
  Copy-Item "C:\Trezo\RESTORE-FROM-USB.cmd" "$root\RESTORE-FROM-USB.cmd" -Force -ErrorAction SilentlyContinue
  @{ head = $head; mirrored_at = (Get-Date -Format s); from = $env:COMPUTERNAME; robocopy = $code } |
    ConvertTo-Json | Out-File $marker -Encoding utf8
  Say "USB mirror complete on $root (robocopy code $code, head $head). Log: $log"
  exit 0
} else {
  Say "USB mirror FAILED on $root (robocopy code $code). Read $log" "Red"
  exit 1
}
