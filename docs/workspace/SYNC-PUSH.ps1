# Reconcile with whatever GitHub created, then push.
# Run:  & C:\Trezo\SYNC-PUSH.ps1
$log = "C:\Trezo\push-output.txt"
"=== SYNC $(Get-Date -Format s) ===" | Out-File $log -Encoding utf8
cd C:\Trezo\trezo-platform

"--- what is on the remote ---" | Out-File $log -Append -Encoding utf8
(git fetch origin 2>&1)         | Out-File $log -Append -Encoding utf8
(git log --oneline origin/main 2>&1) | Out-File $log -Append -Encoding utf8
"--- files on the remote ---"   | Out-File $log -Append -Encoding utf8
$remoteFiles = @(git ls-tree -r --name-only origin/main 2>$null)
($remoteFiles -join "`n")       | Out-File $log -Append -Encoding utf8

# Only overwrite the remote if it holds nothing but GitHub's own scaffolding.
# Anything else and we stop: a force-push is not something to do blind.
$scaffold = @('README.md','readme.md','.gitignore','LICENSE','LICENSE.md')
$unexpected = $remoteFiles | Where-Object { $_ -and ($scaffold -notcontains $_) }

if ($unexpected) {
  "--- STOPPED ---"             | Out-File $log -Append -Encoding utf8
  "The remote holds files that are not GitHub scaffolding:" | Out-File $log -Append -Encoding utf8
  ($unexpected -join "`n")      | Out-File $log -Append -Encoding utf8
  "Not force-pushing. Nova should look first." | Out-File $log -Append -Encoding utf8
  Write-Host "  STOPPED - the remote has real content. Tell Nova." -ForegroundColor Yellow
} else {
  "--- remote holds only scaffolding; replacing it with your history ---" |
    Out-File $log -Append -Encoding utf8
  (git push -u --force origin main 2>&1) | Out-File $log -Append -Encoding utf8
  "--- after ---"               | Out-File $log -Append -Encoding utf8
  (git branch -vv 2>&1)         | Out-File $log -Append -Encoding utf8
  (git log --oneline -1 origin/main 2>&1) | Out-File $log -Append -Encoding utf8
  Write-Host "  Push attempted." -ForegroundColor Cyan
}
Write-Host ""
Get-Content $log | Select-Object -Last 20
Write-Host ""
Write-Host "  Saved to $log -- tell Nova." -ForegroundColor Cyan
