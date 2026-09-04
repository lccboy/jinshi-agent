param([string]$MemberRoot = 'H:\JinshiDSH', [switch]$Disable, [switch]$Uninstall, [switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$taskName = 'JinshiDSH-MemberRecovery'
$root = [IO.Path]::GetFullPath($MemberRoot)
if ($root -eq [IO.Path]::GetPathRoot($root)) { throw 'Invalid member root' }
$guardDir = Join-Path $root 'recovery'
New-Item -ItemType Directory -Path $guardDir -Force | Out-Null
$disabled = Join-Path $guardDir 'recovery.disabled'
$script = Join-Path $guardDir 'member-process-recovery.ps1'
# Replace only our exact old watch process, never an unrelated PowerShell session.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains('"' + $script + '"') -and $_.CommandLine -match '\s-Watch(?:\s|$)'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'JinshiDSH-Workbench.vbs'
$oldStartup = Join-Path ([Environment]::GetFolderPath('Startup')) 'JinshiDSH-MemberRecovery.vbs'
if ($Disable -or $Uninstall) {
    [IO.File]::WriteAllText($disabled, 'disabled')
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        if ($Uninstall) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
        else { Disable-ScheduledTask -TaskName $taskName | Out-Null }
    }
    if ($Uninstall) {
        foreach ($entry in @($startup,$oldStartup)) {
            if (Test-Path -LiteralPath $entry) { Remove-Item -LiteralPath $entry -Force }
        }
    }
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'install_state.json'))) { throw 'Workbench is not installed' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'member-process-recovery.ps1') -Destination $script -Force
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '" -MemberRoot "' + $root + '" -Enabled'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
try {
    $action = New-ScheduledTaskAction -Execute $shell -Argument $arguments -ErrorAction Stop
    $login = New-ScheduledTaskTrigger -AtLogOn -User $user -ErrorAction Stop
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -ErrorAction Stop
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited -ErrorAction Stop
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ErrorAction Stop
    $registered = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($login,$repeat) -Principal $principal -Settings $settings -Force -ErrorAction Stop
    if (-not $registered) { throw 'Task registration returned no result' }
    $mode = 'scheduled_task'
} catch {
    # Supported per-user fallback, never elevate or modify a protected registry key.
    try {
        $command = '"' + $shell + '" ' + $arguments + ' -Watch'
        $vbs = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" + 'shell.Run "' + $command.Replace('"','""') + '", 0, False'
        [IO.File]::WriteAllText($startup, $vbs, [Text.Encoding]::Unicode)
        $mode = 'user_startup'
    } catch {
        $mode = 'session_only'
    }
}
$cleanupPending = $false
foreach ($entry in @($oldStartup,$startup)) {
    if ($entry -eq $startup -and $mode -ne 'scheduled_task') { continue }
    if (Test-Path -LiteralPath $entry) {
        try { Remove-Item -LiteralPath $entry -Force -ErrorAction Stop }
        catch { $cleanupPending = $true; Write-Warning 'cleanup_pending: legacy startup retained because Windows denied removal.' }
    }
}
if (Test-Path -LiteralPath $disabled) { Remove-Item -LiteralPath $disabled -Force -ErrorAction Stop }
if (-not $NoLaunch) {
    if ($mode -eq 'scheduled_task') {
        try { Start-ScheduledTask -TaskName $taskName -ErrorAction Stop }
        catch { $mode = 'session_only' }
    }
    if ($mode -ne 'scheduled_task') { Start-Process -FilePath $shell -ArgumentList ($arguments + ' -Watch') -WindowStyle Hidden -ErrorAction Stop }
}
$reportedMode = if ($cleanupPending) { $mode + '_cleanup_pending' } else { $mode }
[pscustomobject]@{persistent=($mode -ne 'session_only' -and -not $cleanupPending); mode=$reportedMode}
