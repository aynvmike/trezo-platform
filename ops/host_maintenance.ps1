# Manual database-independent maintenance. No arbitrary commands or scheduler setup.
# Status is read-only. Deploy requires an administrator and an exact reviewed SHA.
# powershell -NoProfile -ExecutionPolicy Bypass -File ops\host_maintenance.ps1 -Operation Status
# powershell -NoProfile -ExecutionPolicy Bypass -File ops\host_maintenance.ps1 -Operation Deploy -ExpectedCommit <40-hex-sha>
[CmdletBinding()]
param(
    [ValidateSet('Status', 'Deploy')][string]$Operation = 'Status',
    [string]$ExpectedCommit = ''
)
$ErrorActionPreference = 'Stop'
$Repo = 'C:\Trezo\trezo-platform'
$Maintenance = 'C:\Trezo\maintenance'
$Nssm = 'C:\ProgramData\chocolatey\bin\nssm.exe'
$Python = Join-Path $Repo 'agents\.venv\Scripts\python.exe'
$ServiceName = 'TrezoAgents'
$script:LogEnabled = $false
$script:Step = 'initialization'

function Note([string]$Message) {
    # Only fixed messages, statuses, SHA values and counts reach this log.
    $line = '{0} {1}' -f [DateTime]::UtcNow.ToString('o'), $Message
    Write-Host $line
    if ($script:LogEnabled) {
        try {
            $path = Join-Path $Maintenance 'maintenance.log'
            if ((Test-Path $path) -and (Get-Item $path).Length -gt 256KB) {
                Move-Item $path ($path + '.1') -Force
            }
            Add-Content -LiteralPath $path -Value $line -Encoding UTF8
        } catch { Write-Host 'LOCAL_LOG_UNAVAILABLE; console status remains authoritative.' }
    }
}

function Native-Argument([string]$Value) {
    # Windows CommandLineToArgvW quoting; no shell interpretation.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Run([string]$Exe, [string[]]$Arguments, [string]$Directory = $Repo, [int]$Timeout = 120) {
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = $Exe
    $process.StartInfo.Arguments = (($Arguments | ForEach-Object { Native-Argument $_ }) -join ' ')
    $process.StartInfo.WorkingDirectory = $Directory
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    # Prevent unattended credential prompts and raw credential-bearing diagnostics.
    $process.StartInfo.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($Timeout * 1000)) {
            # Kill only the timed-out command's own tree, never the engine.
            $null = & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F 2>&1
            throw 'Command timed out; raw output suppressed.'
        }
        return @{ code = $process.ExitCode; output = $stdout.GetAwaiter().GetResult(); errors = $stderr.GetAwaiter().GetResult() }
    } finally { $process.Dispose() }
}

function Git([string[]]$Arguments, [int]$Timeout = 120) {
    return Run 'git.exe' (@('-c', ('core.hooksPath=' + (Join-Path $Maintenance 'no-hooks')), '-C', $Repo) + $Arguments) $Repo $Timeout
}

function Need-Git([string[]]$Arguments, [int]$Timeout = 120) {
    $result = Git $Arguments $Timeout
    if ($result.code -ne 0) { throw 'Git operation failed; raw output suppressed.' }
    return $result.output.Trim()
}

function Head { return Need-Git @('rev-parse', '--verify', 'HEAD') }

function Assert-Clean {
    $state = Need-Git @('status', '--porcelain', '--untracked-files=no')
    if ($state) { throw 'Tracked working tree or index is dirty; no deployment.' }
    if ((Need-Git @('symbolic-ref', '--short', 'HEAD')) -ne 'main') { throw 'Live checkout is not on main.' }
}

function Assert-NoRelayRestart {
    # The engine relay does not share this script's mutex. Its independent
    # Task Scheduler restart can survive the engine process that queued it.
    foreach ($task in @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -like 'TrezoRelayRestart*' })) {
        if ($task.State -eq 'Running') { throw 'An existing relay restart is running.' }
        if ($task.Settings.Enabled) {
            $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction Stop
            if ($info.NextRunTime -gt (Get-Date)) { throw 'An existing relay restart is pending.' }
        }
    }
}

function Assert-OwnedCheckout([string[]]$AllowedCommits) {
    Assert-Clean
    if ((Head) -notin $AllowedCommits) { throw 'Checkout ownership lost to another actor.' }
    Assert-NoRelayRestart
}

function Engine-State {
    $service = Get-CimInstance Win32_Service -Filter "Name='TrezoAgents'" -ErrorAction Stop
    if (-not $service) { throw 'TrezoAgents service missing.' }
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
    $descendants = New-Object 'System.Collections.Generic.HashSet[int]'
    if ([int]$service.ProcessId -gt 0) { [void]$descendants.Add([int]$service.ProcessId) }
    do {
        $changed = $false
        foreach ($item in $processes) {
            if ($descendants.Contains([int]$item.ParentProcessId) -and $descendants.Add([int]$item.ProcessId)) { $changed = $true }
        }
    } while ($changed)
    $engines = @($processes | Where-Object { $_.CommandLine -match '(?i)uvicorn.*app\.main' })
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -eq 8001)
    $foreign = @($engines | Where-Object { -not $descendants.Contains([int]$_.ProcessId) })
    $foreignPorts = @($listeners | Where-Object { -not $descendants.Contains([int]$_.OwningProcess) })
    return @{ service = [string]$service.State; service_pid = [int]$service.ProcessId
        engine_pids = @($engines.ProcessId); listener_pids = @($listeners.OwningProcess | Sort-Object -Unique)
        foreign_count = ($foreign.Count + $foreignPorts.Count); descendants = $descendants }
}

function Assert-ServiceConfig {
    if (-not (Test-Path -LiteralPath $Nssm) -or -not (Test-Path -LiteralPath $Python)) { throw 'Required NSSM or existing Python environment missing.' }
    $service = Get-CimInstance Win32_Service -Filter "Name='TrezoAgents'"
    if (-not $service -or $service.PathName -notmatch '(?i)nssm\.exe') { throw 'TrezoAgents is not a verified NSSM service.' }
    $config = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\TrezoAgents\Parameters'
    if ([IO.Path]::GetFullPath([string]$config.Application) -ne [IO.Path]::GetFullPath($Python)) { throw 'Unexpected service executable.' }
    if ([IO.Path]::GetFullPath([string]$config.AppDirectory) -ne [IO.Path]::GetFullPath((Join-Path $Repo 'agents'))) { throw 'Unexpected service working directory.' }
    $parameters = [string]$config.AppParameters
    if ($parameters -notmatch 'uvicorn\s+app\.main:app' -or $parameters -match '--reload|--workers(?:=|\s+)(?!1\b)\d+' -or $parameters -notmatch '--port(?:=|\s+)8001\b' -or $parameters -notmatch '--host(?:=|\s+)127\.0\.0\.1\b') {
        throw 'Service must run a single non-reloading app.main on loopback port8001.'
    }
    if ([string]$config.AppKillProcessTree -ne '1') { throw 'NSSM process-tree stop must be enabled.' }
}

function Wait-Stopped {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    do {
        $state = Engine-State
        if ($state.foreign_count -gt 0) { throw 'Unowned engine/listener found; refusing to start any engine.' }
        if ($state.service -eq 'Stopped' -and $state.engine_pids.Count -eq 0 -and $state.listener_pids.Count -eq 0) { return }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Engine did not stop completely; no replacement will be started.'
}

function Stop-Engine {
    $state = Engine-State
    if ($state.foreign_count -gt 0) { throw 'Unowned engine/listener found; refusing service change.' }
    if ($state.service -ne 'Stopped') {
        $result = Run $Nssm @('stop', $ServiceName) $Repo 90
        if ($result.code -ne 0) { throw 'NSSM stop failed.' }
    }
    Wait-Stopped
}

function Wait-Boot([string]$Commit, [DateTimeOffset]$After) {
    $deadline = [DateTime]::UtcNow.AddSeconds(180)
    do {
        $state = Engine-State
        if ($state.foreign_count -gt 0) { throw 'Unowned engine/listener appeared.' }
        $verified = $false
        $files = @(Get-ChildItem -LiteralPath (Join-Path $Repo 'logs') -Filter 'activity-*.jsonl' -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 2)
        foreach ($file in $files) {
            foreach ($line in @(Get-Content -LiteralPath $file.FullName -Tail 1500 -ErrorAction SilentlyContinue)) {
                try {
                    $event = $line | ConvertFrom-Json
                    if ($event.event -ne 'engine_boot' -or [DateTimeOffset]::Parse($event.ts) -lt $After) { continue }
                    $match = [regex]::Match([string]$event.reason, 'pid=(\d+) commit=([0-9a-f]{7,40}) agents=(\d+)')
                    if ($match.Success -and $Commit.StartsWith($match.Groups[2].Value) -and [int]$match.Groups[3].Value -ge 30 -and $state.descendants.Contains([int]$match.Groups[1].Value)) { $verified = $true }
                } catch { }
            }
        }
        if ($verified -and $state.service -eq 'Running' -and $state.listener_pids.Count -eq 1) {
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 5
                if ($health.status -eq 'ok' -and $health.service -eq 'trezo-agents') { return }
            } catch { }
        }
        Start-Sleep -Seconds 3
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Fresh local boot beacon and health were not verified.'
}

function Start-Engine([string]$Commit) {
    Wait-Stopped
    $started = [DateTimeOffset]::UtcNow
    # NSSM can return SERVICE_START_PENDING while booting; prove the boot below.
    $null = Run $Nssm @('start', $ServiceName) $Repo 90
    Wait-Boot $Commit $started
}

if ($Operation -eq 'Status') {
    try {
        $state = Engine-State
        $report = @{ timestamp_utc = [DateTime]::UtcNow.ToString('o'); checkout_commit = Head
            service = $state.service; engine_pids = $state.engine_pids; listener_pids = $state.listener_pids
            foreign_engine_or_listener_count = $state.foreign_count
            runtime_commit_verified = $false; note = 'Checkout SHA is not proof of running code; deploy verifies a fresh local boot beacon.' }
        $report | ConvertTo-Json -Depth 5
        exit 0
    } catch { Write-Output '{"status":"INCOMPLETE","note":"Host status could not be verified; no changes made."}'; exit 2 }
}

if ($ExpectedCommit -notmatch '^[0-9a-fA-F]{40}$') { Write-Error 'Deploy requires ExpectedCommit as a full40-character reviewed SHA.'; exit 2 }
$ExpectedCommit = $ExpectedCommit.ToLowerInvariant()
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Error 'Deploy requires an administrator PowerShell session.'; exit 2 }

$mutex = New-Object System.Threading.Mutex($false, 'Global\TrezoHostMaintenance')
$locked = $false
$stage = $null
$before = $null
$changedLive = $false
$stoppedLive = $false
$wasRunning = $false
$pausedTasks = @()
$exitCode = 1
$safeToRestoreTasks = $true
$ownershipLost = $false
try {
    $script:Step = 'maintenance_lock'
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'Another manual maintenance operation holds the lock.' }
    $script:Step = 'checkout_and_service_preconditions'
    Assert-Clean
    Assert-ServiceConfig
    $initial = Engine-State
    if ($initial.foreign_count -gt 0 -or $initial.service -notin @('Running', 'Stopped')) { throw 'Engine ownership or stable service state could not be verified.' }
    if ($initial.service -eq 'Running' -and ($initial.engine_pids.Count -eq 0 -or $initial.listener_pids.Count -ne 1)) { throw 'Existing engine is unhealthy; investigate before deploying.' }
    if ($initial.service -eq 'Stopped' -and ($initial.engine_pids.Count -gt 0 -or $initial.listener_pids.Count -gt 0)) { throw 'Stopped service has surviving engine/listener.' }
    $wasRunning = $initial.service -eq 'Running'
    $before = Head
    $remote = Need-Git @('remote', 'get-url', 'origin')
    if ($remote -notmatch '^https://github\.com/aynvmike/trezo-platform(?:\.git)?/?$' -and $remote -notmatch '^git@github\.com:aynvmike/trezo-platform(?:\.git)?$') { throw 'Origin is not the approved credential-free Trezo repository URL.' }
    $null = New-Item -ItemType Directory -Path $Maintenance -Force
    $script:LogEnabled = $true
    Note "Requested deploy $ExpectedCommit; existing $before."
    $script:Step = 'scheduled_task_coordination'
    # Suppress only existing engine maintenance tasks, preserving enabled state.
    # A running task or pending relay restart requires the operator to let it finish.
    Assert-NoRelayRestart
    foreach ($task in @(Get-ScheduledTask -ErrorAction Stop)) {
        $relevant = $task.TaskName -in @('TrezoAutoPull', 'TrezoHealthWatchdog')
        foreach ($action in $task.Actions) { if ([string]$action.Arguments -match '(?i)(health-watchdog|AUTO-PULL)\.ps1') { $relevant = $true } }
        if ($relevant -and $task.Settings.Enabled) {
            if (-not $wasRunning) { throw 'An enabled automatic starter prevents preserving the stopped service; operator review required.' }
            if ($task.State -eq 'Running') { throw 'An existing updater/watchdog is running; retry after it finishes.' }
            $pausedTasks += @{ name = $task.TaskName; path = $task.TaskPath }
            $null = Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
            $observedTask = Get-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
            if ($observedTask.Settings.Enabled -or $observedTask.State -eq 'Running') { throw 'Updater/watchdog could not be quiesced.' }
        }
    }
    $script:Step = 'fetch_and_verify_reviewed_commit'
    $null = Need-Git @('fetch', '--no-tags', 'origin', 'refs/heads/main:refs/remotes/origin/main') 300
    if ((Need-Git @('rev-parse', '--verify', 'refs/remotes/origin/main')) -ne $ExpectedCommit) { throw 'ExpectedCommit is not fetched origin/main; refusing moving or incorrect target.' }
    if ((Git @('merge-base', '--is-ancestor', $before, $ExpectedCommit)).code -ne 0) { throw 'Target is not a fast-forward descendant; no deployment.' }
    $stage = Join-Path $Maintenance ('stage-' + [Guid]::NewGuid().ToString('N'))
    $script:Step = 'staged_checkout_and_guards'
    $null = Need-Git @('worktree', 'add', '--detach', $stage, $ExpectedCommit)
    $guards = Run $Python @('-m', 'tests.run_all') (Join-Path $stage 'agents') 900
    if ($guards.code -ne 0 -or $guards.output -notmatch 'all green across (\d+) suites') { throw 'Staged guard suites failed; live checkout was not changed.' }
    Note 'Staged guard suites passed.'
    $script:Step = 'recheck_live_checkout'
    Assert-Clean
    if ((Head) -ne $before) { throw 'Live HEAD changed during staging; refusing concurrent deployment.' }
    if ($before -eq $ExpectedCommit) {
        Note 'Checkout already matches; no restart or runtime claim made.'
        $exitCode = 0
    } else {
        $script:Step = 'stop_owned_service'
        Assert-NoRelayRestart
        $stoppedLive = $true # Stop may partly succeed before an error; recovery must own it.
        Stop-Engine
        # Staging left the previous engine running. Its Supabase relay could
        # have deployed or scheduled a restart while the guards were running.
        # Once stopped, re-establish ownership BEFORE any tracked-file change.
        # An ownership failure is not ours to undo: never reset another deploy.
        $script:Step = 'post_stop_ownership_verification'
        $ownershipLost = $true
        Assert-OwnedCheckout @($before)
        $ownershipLost = $false
        $changedLive = $true # A failing merge may still touch the index; rollback owns it.
        $script:Step = 'fast_forward_live_checkout'
        $null = Need-Git @('merge', '--ff-only', $ExpectedCommit)
        if ((Head) -ne $ExpectedCommit) { throw 'Live checkout verification failed.' }
        $script:Step = 'verify_new_service_boot'
        if ($wasRunning) { Start-Engine $ExpectedCommit; Note "DEPLOY_VERIFIED $ExpectedCommit; fresh boot and local health verified." }
        else { Wait-Stopped; Note "CHECKOUT_UPDATED $ExpectedCommit; service was stopped and remains stopped." }
        $exitCode = 0
    }
} catch {
    # Never print native output, registry values, exception text or credentials.
    Note ("DEPLOY_FAILED at step=" + $script:Step + '; raw diagnostic output suppressed to protect secrets.')
    if ($ownershipLost) {
        $safeToRestoreTasks = $false
        Note 'OWNERSHIP_LOST; no rollback or restart issued. Paused tasks remain disabled. Another relay restart may still be pending; operator review required.'
    } elseif ($stoppedLive -or $changedLive) {
        try {
            Stop-Engine
            # Refuse to erase a concurrent actor's new HEAD or dirty worktree,
            # or race its pending restart, even during failure recovery.
            $allowed = @($before)
            if ($changedLive) { $allowed += $ExpectedCommit }
            Assert-OwnedCheckout $allowed
            if ($changedLive) { $null = Need-Git @('reset', '--hard', $before) }
            if ($wasRunning) { Start-Engine $before; Note "ROLLBACK_VERIFIED $before; previous service restored." }
            else { Wait-Stopped; Note 'Rollback left previously stopped service stopped.' }
        } catch {
            $safeToRestoreTasks = $false
            Note 'ROLLBACK_INCOMPLETE; do not start another engine. Paused tasks remain disabled for manual recovery.'
        }
    }
} finally {
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        try { $null = Need-Git @('worktree', 'remove', '--force', $stage); Note 'Staging worktree removed.' }
        catch { Note 'Staging cleanup incomplete; operator should inspect maintenance staging directories.' }
    }
    if ($safeToRestoreTasks) {
        foreach ($task in $pausedTasks) {
            try { $null = Enable-ScheduledTask -TaskName $task.name -TaskPath $task.path }
            catch { $exitCode = 1; Note 'Previously enabled task could not be restored; operator attention required.' }
        }
    }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $exitCode
