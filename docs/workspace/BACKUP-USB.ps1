# BACKUP-USB -- mirror the Trezo workspace onto the USB stick.
# Copies C:\Trezo -> E:\Trezo, skipping machine-junk that has no
# business on a portable copy (.venv, node_modules, _to_delete).
# /MIR makes E: an exact mirror of what it copies -- run it after
# any work session and the stick walks out the door current.
#
# Run:  & C:\Trezo\BACKUP-USB.ps1
$src = "C:\Trezo"
$dst = "E:\Trezo"
if (-not (Test-Path "E:\")) {
  Write-Host "  No E: drive - plug the USB in first." -ForegroundColor Yellow
  return
}
$log = "C:\Trezo\usb-backup-log.txt"
robocopy $src $dst /MIR /R:1 /W:2 /NP /NFL /NDL `
  /XD "$src\_to_delete" "$src\trezo-platform\agents\.venv" `
      "$src\trezo-platform\web\node_modules" "$src\trezo-platform\web\.next" `
      "System Volume Information" `
  /XF "*.lock" `
  /LOG:$log
$code = $LASTEXITCODE
# Robocopy: 0-7 = success flavours, 8+ = real failures.
if ($code -lt 8) {
  Write-Host "  USB mirror complete (robocopy code $code). Log: $log" -ForegroundColor Cyan
} else {
  Write-Host "  USB mirror FAILED (robocopy code $code). Read $log" -ForegroundColor Red
}
