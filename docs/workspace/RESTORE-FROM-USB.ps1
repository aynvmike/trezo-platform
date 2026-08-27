# RESTORE-FROM-USB -- bring Trezo back onto this PC from the stick.
# Normal use: double-click RESTORE-FROM-USB.cmd at the ROOT of the USB
# stick. It runs this script from the stick's Trezo folder.
#
# The stick deliberately carries NO secrets (2026-08-27): every .env is
# stripped from the mirror, so a lost stick no longer means rotating
# every key. This script copies everything back, then recreates each
# missing .env as an empty-valued skeleton from the .template files the
# backup writes, and prints exactly which values to fill in. The values
# live in Mike's password manager.
param(
  [string]$Source = "",   # override: path to the stick's Trezo folder
  [switch]$Yes            # skip the overwrite confirmation
)

function Say($msg, $color = "Cyan") { Write-Host "  $msg" -ForegroundColor $color }

$src = $Source
if (-not $src) { $src = $PSScriptRoot }   # this script lives in <stick>:\Trezo
if (-not (Test-Path (Join-Path $src "BACKUP-USB.ps1"))) {
  Say "This does not look like the stick's Trezo folder: $src" "Red"
  Say "Run RESTORE-FROM-USB.cmd from the USB stick, or pass -Source E:\Trezo" "Red"
  exit 1
}
$dst = "C:\Trezo"

if ((Test-Path $dst) -and -not $Yes) {
  Say "C:\Trezo already exists on this PC." "Yellow"
  Say "Restoring will OVERWRITE its files with the stick's copies" "Yellow"
  Say "(nothing is deleted, but same-named files are replaced)." "Yellow"
  $answer = Read-Host "  Type YES to continue"
  if ($answer -ne "YES") { Say "Nothing was changed."; exit 0 }
}

Say "Copying $src -> $dst. SILENCE IS NORMAL - this can take 10+ quiet"
Say "minutes from a USB stick. Do NOT close this window."
robocopy $src $dst /E /IS /IT /R:1 /W:2 /NP /NFL /NDL | Out-Null
if ($LASTEXITCODE -ge 8) {
  Say "Copy FAILED (robocopy code $LASTEXITCODE)." "Red"
  exit 1
}
Say "Files restored (robocopy code $LASTEXITCODE)."

# Recreate missing .env files from the sanitized templates the backup
# left on the stick (key names only, no values).
$made = @()
Get-ChildItem $dst -Recurse -Force -File -Filter "*.template" -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\(\.venv|node_modules|_to_delete|\.next)\\' } |
  ForEach-Object {
    $real = $_.FullName.Substring(0, $_.FullName.Length - ".template".Length)
    if (-not (Test-Path $real)) {
      Copy-Item $_.FullName $real
      $made += $real
    }
  }

if ($made.Count -gt 0) {
  Say ""
  Say "The stick carries NO keys (by design). These files were created" "Yellow"
  Say "with EMPTY values - fill them in from the password manager:" "Yellow"
  foreach ($f in $made) {
    Say ""
    Say "  $f" "Yellow"
    Get-Content $f | Where-Object { $_ -match '^[A-Za-z_]' } |
      ForEach-Object { Say "      $_" "DarkYellow" }
  }
} else {
  Say "All .env files already present - nothing to fill in."
}

Say ""
Say "Next steps (full detail in C:\Trezo\REBUILD-FROM-USB.md):"
Say "  1. Fill in the .env values listed above (password manager)."
Say "  2. cd C:\Trezo\trezo-platform\agents"
Say "     python -m venv .venv"
Say "     .venv\Scripts\pip install -r requirements.txt"
Say "  3. cd C:\Trezo\trezo-platform\web"
Say "     npm install"
Say "  4. git fetch origin, then: git pull --ff-only origin main"
Say "  5. & C:\Trezo\AUTO-PUSH.ps1 -Register"
Say ""
Say "Restore complete."
