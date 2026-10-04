# Read-only Windows inventory. No installs, network probes, env files or secrets.
# Run in Windows PowerShell 5.1; administrator rights improve feature visibility.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

function Read-Tool([string]$Name, [string]$Arguments) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { return @{ present = $false; status = 'missing' } }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = $command.Source
    $process.StartInfo.Arguments = $Arguments
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    if ($Name -eq 'docker.exe') {
        foreach ($key in @('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')) {
            [void]$process.StartInfo.EnvironmentVariables.Remove($key)
        }
    }
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(10000)) {
            try { $process.Kill() } catch { }
            return @{ present = $true; status = 'timeout' }
        }
        if ($process.ExitCode -ne 0) { return @{ present = $true; status = 'unavailable'; exit_code = $process.ExitCode } }
        # Raw output stays in memory; only whitelisted parsed facts are printed.
        return @{ present = $true; status = 'ok'; raw = $stdout.GetAwaiter().GetResult() }
    } catch { return @{ present = $true; status = 'unreadable' } }
    finally { $process.Dispose() }
}

function Read-Version([string]$Name) {
    $result = Read-Tool $Name '--version'
    $answer = @{ present = $result.present; status = $result.status }
    if ($result.status -eq 'ok') {
        $match = [regex]::Match([string]$result.raw, '\b\d+\.\d+(?:\.\d+){0,2}\b')
        if ($match.Success) { $answer.version = $match.Value } else { $answer.status = 'version_unrecognized' }
    }
    return $answer
}

function Read-Feature([string]$Name) {
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop
        return [string]$feature.State
    } catch { return 'unknown_or_unavailable' }
}

$report = [ordered]@{
    schema_version = 1
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    decision = 'REVIEW_REQUIRED'
    read_only = $true
    notes = @(
        'This inventory does not authorize installation or establish migration readiness.',
        'CPU indicators do not prove the cloud host supports nested virtualization.',
        'Docker Desktop is unsupported on Windows Server; Linux Docker must be independently verified.',
        'Supabase capacity must be additional to the existing Trezo workload.'
    )
}
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $machine = Get-CimInstance Win32_ComputerSystem
    $report.os = @{ name = $os.Caption; version = $os.Version; build = $os.BuildNumber; architecture = $os.OSArchitecture }
    $report.memory = @{
        installed_gib = [Math]::Round([double]$machine.TotalPhysicalMemory / 1GB, 2)
        available_gib = [Math]::Round([double]$os.FreePhysicalMemory / 1MB, 2)
    }
    $report.virtualization = @{
        hypervisor_present = $machine.HypervisorPresent
        processors = @(Get-CimInstance Win32_Processor | ForEach-Object {
            @{ logical_processors = $_.NumberOfLogicalProcessors; physical_cores = $_.NumberOfCores
               firmware_virtualization = $_.VirtualizationFirmwareEnabled
               second_level_address_translation = $_.SecondLevelAddressTranslationExtensions
               vm_monitor_extensions = $_.VMMonitorModeExtensions }
        })
        virtual_machine_platform = Read-Feature 'VirtualMachinePlatform'
        windows_subsystem_linux = Read-Feature 'Microsoft-Windows-Subsystem-Linux'
        nested_virtualization = 'NOT_PROVEN'
    }
} catch { $report.os_inventory_status = 'unreadable' }
try {
    $report.fixed_disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
        @{ drive = $_.DeviceID; capacity_gib = [Math]::Round([double]$_.Size / 1GB, 2)
           free_gib = [Math]::Round([double]$_.FreeSpace / 1GB, 2); filesystem = $_.FileSystem }
    })
} catch { $report.disk_inventory_status = 'unreadable' }
$report.services = @('TrezoAgents', 'TrezoApi', 'TrezoWeb', 'sshd', 'Tailscale', 'docker') | ForEach-Object {
    $service = Get-Service -Name $_ -ErrorAction SilentlyContinue
    @{ name = $_; status = $(if ($service) { [string]$service.Status } else { 'missing' }) }
}
$report.tasks = @('TrezoAutoPull', 'TrezoHealthWatchdog', 'TrezoWebWatchdog') | ForEach-Object {
    try {
        $task = Get-ScheduledTask -TaskName $_ -ErrorAction Stop
        @{ name = $_; state = [string]$task.State; enabled = [bool]$task.Settings.Enabled }
    } catch { @{ name = $_; state = 'missing_or_unreadable' } }
}
try {
    $report.ports = @(3000, 8000, 8001, 5432, 54321, 8080) | ForEach-Object {
        $port = $_
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -eq $port)
        @{ port = $port; listening = ($listeners.Count -gt 0)
           owner_pids = @($listeners.OwningProcess | Sort-Object -Unique) }
    }
} catch { $report.port_inventory_status = 'unreadable' }
$report.tools = @{ powershell = $PSVersionTable.PSVersion.ToString(); git = Read-Version 'git.exe'; python = Read-Version 'python.exe'; node = Read-Version 'node.exe'; docker = Read-Version 'docker.exe' }
# Pin a local Windows pipe; do not accidentally inspect a saved remote context.
$docker = Read-Tool 'docker.exe' '--host npipe:////./pipe/docker_engine info --format "{{.OSType}}|{{.ServerVersion}}|{{.NCPU}}|{{.MemTotal}}"'
$report.linux_docker = @{ status = $docker.status; confirmed = $false }
if ($docker.status -eq 'ok') {
    $match = [regex]::Match(([string]$docker.raw).Trim(), '^(linux|windows)\|(\d+\.\d+(?:\.\d+)?)[^|]*\|(\d+)\|(\d+)$')
    if ($match.Success) {
        $report.linux_docker = @{ status = 'observed'; confirmed = ($match.Groups[1].Value -eq 'linux')
            os_type = $match.Groups[1].Value; server_version = $match.Groups[2].Value
            logical_processors = [int]$match.Groups[3].Value
            memory_gib = [Math]::Round([double]$match.Groups[4].Value / 1GB, 2)
            location = 'Local Windows Docker named pipe; daemon reported OS only' }
    } else { $report.linux_docker.status = 'unrecognized_response' }
}
$report | ConvertTo-Json -Depth 8
