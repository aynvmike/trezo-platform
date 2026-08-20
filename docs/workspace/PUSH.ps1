# Push the Trezo fix to GitHub and record exactly what happened.
# Run:  & C:\Trezo\PUSH.ps1
$log = "C:\Trezo\push-output.txt"
"=== $(Get-Date -Format s) ===" | Out-File $log -Encoding utf8
cd C:\Trezo\trezo-platform
"--- remote ---"            | Out-File $log -Append -Encoding utf8
(git remote -v)             | Out-File $log -Append -Encoding utf8
"--- local HEAD ---"        | Out-File $log -Append -Encoding utf8
(git log --oneline -2)      | Out-File $log -Append -Encoding utf8
"--- push ---"              | Out-File $log -Append -Encoding utf8
(git push -u origin main 2>&1) | Out-File $log -Append -Encoding utf8
"--- after ---"             | Out-File $log -Append -Encoding utf8
(git branch -vv)            | Out-File $log -Append -Encoding utf8
Write-Host ""
Get-Content $log | Select-Object -Last 25
Write-Host ""
Write-Host "  Saved to $log -- tell Nova it's done and she'll read it." -ForegroundColor Cyan
