# Exercise the real maintenance lifecycle with all host/network effects mocked.
# Compatible with Windows PowerShell 5.1 and PowerShell 7. No production writes.
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$source = Get-Content -LiteralPath (Join-Path $repository 'ops/host_maintenance.ps1') -Raw
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Maintenance script did not parse.' }

# Evaluate definitions only; never evaluate the production parameter handling,
# Windows identity check, mutex creation or fixed host paths.
foreach ($definition in $ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.FunctionDefinitionAst] }) {
    . ([ScriptBlock]::Create($definition.Extent.Text))
}
$main = @($ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.TryStatementAst] })
if ($main.Count -ne 1) { throw 'Expected exactly one top-level maintenance lifecycle.' }
$lifecycle = [ScriptBlock]::Create($main[0].Extent.Text)

function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ($Actual -ne $Expected) { throw ("Assertion failed: {0}; expected {1}, got {2}" -f $Label, $Expected, $Actual) }
}

# Every external effect reached by the lifecycle is replaced here. Functions
# under test remain real: Assert-Clean, Assert-OwnedCheckout and relay checks.
function Note([string]$Message) { $script:Messages += $Message }
function Assert-ServiceConfig { }
function Engine-State {
    return @{
        foreign_count = 0
        service = $script:InitialService
        engine_pids = $(if ($script:InitialService -eq 'Running') { @(100) } else { @() })
        listener_pids = $(if ($script:InitialService -eq 'Running') { @(100) } else { @() })
    }
}

function Watchdog-Task {
    return [pscustomobject]@{
        TaskName = 'TrezoHealthWatchdog'
        TaskPath = '\'
        State = 'Ready'
        Settings = [pscustomobject]@{ Enabled = $script:WatchdogEnabled }
        Actions = @()
    }
}

function Get-ScheduledTask([string]$TaskName, [string]$TaskPath) {
    if ($TaskName) { return Watchdog-Task }
    $tasks = @()
    if ($script:HasWatchdog) { $tasks += Watchdog-Task }
    if ($script:Stops -gt 0 -and $script:Scenario -eq 'relay_race') {
        $tasks += [pscustomobject]@{
            TaskName = 'TrezoRelayRestart_123456'
            TaskPath = '\'
            State = 'Ready'
            Settings = [pscustomobject]@{ Enabled = $true }
            Actions = @()
        }
    }
    return $tasks
}

function Get-ScheduledTaskInfo([string]$TaskName, [string]$TaskPath) {
    return @{ NextRunTime = (Get-Date).AddMinutes(1) }
}
function Disable-ScheduledTask([string]$TaskName, [string]$TaskPath) {
    Assert-Equal $TaskName 'TrezoHealthWatchdog' 'only known existing watchdog is paused'
    $script:WatchdogEnabled = $false
    $script:TaskDisables++
}
function Enable-ScheduledTask([string]$TaskName, [string]$TaskPath) {
    Assert-Equal $TaskName 'TrezoHealthWatchdog' 'only previously paused task is restored'
    $script:WatchdogEnabled = $true
    $script:TaskEnables++
}
function New-Item { }
function Test-Path { return $false }
function Join-Path([string]$Path, [string]$ChildPath) { return "$Path/$ChildPath" }

function Need-Git([string[]]$Arguments, [int]$Timeout = 120) {
    switch ($Arguments[0]) {
        'status' {
            if ($script:Stops -gt 0 -and $script:Scenario -eq 'dirty_race') { return ' M tracked.py' }
            return ''
        }
        'symbolic-ref' { return 'main' }
        'rev-parse' {
            if ($Arguments[-1] -eq 'refs/remotes/origin/main') { return $ExpectedCommit }
            return $script:MockHead
        }
        'remote' { return 'https://github.com/aynvmike/trezo-platform.git' }
        'merge' {
            $script:Merges++
            $script:MockHead = $ExpectedCommit
            return ''
        }
        'reset' {
            $script:Resets++
            $script:MockHead = $before
            return ''
        }
        default { return '' }
    }
}
function Git([string[]]$Arguments, [int]$Timeout = 120) { return @{ code = 0; output = '' } }
function Run([string]$Exe, [string[]]$Arguments, [string]$Directory, [int]$Timeout) {
    if ($script:Scenario -eq 'guard_failure') { return @{ code = 1; output = 'guards failed' } }
    return @{ code = 0; output = 'all green across 84 suites' }
}
function Stop-Engine {
    $script:Stops++
    if ($script:Scenario -eq 'head_race' -and $script:Stops -eq 1) { $script:MockHead = ('c' * 40) }
}
function Start-Engine([string]$Commit) {
    $script:Starts++
    if ($Commit -eq $ExpectedCommit -and $script:Scenario -in @('boot_failure', 'rollback_head_race')) {
        if ($script:Scenario -eq 'rollback_head_race') { $script:MockHead = ('c' * 40) }
        throw 'Simulated new-engine boot failure.'
    }
}
function Wait-Stopped { }

$cases = @('success', 'head_race', 'dirty_race', 'relay_race', 'boot_failure', 'rollback_head_race', 'stopped', 'guard_failure')
foreach ($case in $cases) {
    $script:Scenario = $case
    $script:Stops = 0
    $script:Starts = 0
    $script:Resets = 0
    $script:Merges = 0
    $script:Messages = @()
    $script:MockHead = ('a' * 40)
    $script:InitialService = $(if ($case -eq 'stopped') { 'Stopped' } else { 'Running' })
    $script:HasWatchdog = $case -ne 'stopped'
    $script:WatchdogEnabled = $script:HasWatchdog
    $script:TaskDisables = 0
    $script:TaskEnables = 0

    # Harmless synthetic values; production paths and credentials are never used.
    $Repo = 'mock-repository'
    $Maintenance = 'mock-maintenance'
    $Python = 'mock-python'
    $ExpectedCommit = ('b' * 40)
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
    $mutex = New-Object PSObject
    $mutex | Add-Member ScriptMethod WaitOne { param($ignored) return $true }
    $mutex | Add-Member ScriptMethod ReleaseMutex { }
    $mutex | Add-Member ScriptMethod Dispose { }

    . $lifecycle

    switch ($case) {
        'success' {
            Assert-Equal $exitCode 0 'successful deploy status'
            Assert-Equal $script:Merges 1 'one fast-forward'
            Assert-Equal $script:Starts 1 'one engine start'
            Assert-Equal $script:Resets 0 'no rollback on success'
        }
        'stopped' {
            Assert-Equal $exitCode 0 'stopped-service deploy status'
            Assert-Equal $script:Merges 1 'stopped checkout updated'
            Assert-Equal $script:Starts 0 'previously stopped engine never started'
            Assert-Equal $script:TaskEnables 0 'no task enabled for stopped service'
        }
        'guard_failure' {
            Assert-Equal $exitCode 1 'failed guards reported'
            Assert-Equal $script:Stops 0 'failed staged guards never stop live service'
            Assert-Equal $script:Merges 0 'failed staged guards never change live files'
            Assert-Equal $script:Starts 0 'failed staged guards never start service'
            Assert-Equal $script:Resets 0 'failed staged guards need no rollback'
        }
        'boot_failure' {
            Assert-Equal $exitCode 1 'failed new boot remains a failed deployment'
            Assert-Equal $script:Starts 2 'new boot attempted then old service restored'
            Assert-Equal $script:Resets 1 'owned checkout rolled back'
            Assert-Equal $script:MockHead ('a' * 40) 'old commit restored'
        }
        'rollback_head_race' {
            Assert-Equal $exitCode 1 'rollback ownership loss reported'
            Assert-Equal $script:Starts 1 'unowned checkout is not started during rollback'
            Assert-Equal $script:Resets 0 'another actor commit is never reset'
            Assert-Equal $safeToRestoreTasks $false 'automatic tasks remain paused'
        }
        default {
            Assert-Equal $exitCode 1 'concurrent ownership failure reported'
            Assert-Equal $script:Starts 0 'no restart after ownership loss'
            Assert-Equal $script:Resets 0 'no reset after ownership loss'
            Assert-Equal $script:Merges 0 'no merge after ownership loss'
            Assert-Equal $safeToRestoreTasks $false 'automatic tasks remain paused'
        }
    }
    if ($script:HasWatchdog) {
        Assert-Equal $script:TaskDisables 1 'existing watchdog paused once'
        if ($safeToRestoreTasks) {
            Assert-Equal $script:TaskEnables 1 'previous enabled state restored once'
            Assert-Equal $script:WatchdogEnabled $true 'watchdog enabled after safe completion'
        } else {
            Assert-Equal $script:TaskEnables 0 'unsafe recovery never re-enables watchdog'
            Assert-Equal $script:WatchdogEnabled $false 'watchdog stays paused for manual review'
        }
    }
    Write-Output ("PASS " + $case)
}
Write-Output ("All {0} mocked maintenance lifecycle scenarios passed." -f $cases.Count)
