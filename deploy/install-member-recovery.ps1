param([string]$MemberRoot = 'H:\JinshiDSH', [switch]$Disable)
$ErrorActionPreference = 'Stop'
$taskName = 'JinshiDSH-MemberRecovery'
if ($Disable) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    exit 0
}
$root = [IO.Path]::GetFullPath($MemberRoot)
if (-not (Test-Path -LiteralPath (Join-Path $root 'install_state.json'))) { throw 'Workbench is not installed' }
$guardDir = Join-Path $root 'recovery'
New-Item -ItemType Directory -Path $guardDir -Force | Out-Null
$script = Join-Path $guardDir 'member-process-recovery.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'member-process-recovery.ps1') -Destination $script -Force
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '" -MemberRoot "' + $root + '" -Enabled'
$action = New-ScheduledTaskAction -Execute $shell -Argument $arguments
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$login = New-ScheduledTaskTrigger -AtLogOn -User $user
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($login,$repeat) -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Output 'Member recovery enabled (current user task; 60-second interval).'
} catch [Microsoft.Management.Infrastructure.CimException] {
    # No privilege escalation: protect this session only; report persistence failure.
    Start-Process -FilePath $shell -ArgumentList ($arguments + ' -Watch') -WindowStyle Hidden
    Write-Warning 'Task registration denied. Session-only recovery started; rerun installer as administrator for login persistence.'
    exit 2
}
