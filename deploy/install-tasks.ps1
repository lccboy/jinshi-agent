param(
    [switch]$Uninstall,
    [string]$Python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runner = "-m services.collector.daily_runner"
$tasks = @(
    @{ Name = "JinshiDSH-Premarket"; Time = "09:00"; Phase = "premarket"; Limit = (New-TimeSpan -Hours 1) },
    @{ Name = "JinshiDSH-Intraday"; Time = "09:14"; Phase = "intraday"; Limit = (New-TimeSpan -Hours 8) },
    @{ Name = "JinshiDSH-Postmarket"; Time = "15:10"; Phase = "postmarket"; Limit = (New-TimeSpan -Hours 3) },
    @{ Name = "JinshiDSH-Archive"; Time = "15:30"; Phase = "archive"; Limit = (New-TimeSpan -Hours 2) }
)

if ($Uninstall) {
    foreach ($task in $tasks) {
        Unregister-ScheduledTask -TaskName $task.Name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "[REMOVED] $($task.Name)"
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
foreach ($task in $tasks) {
    $arguments = "$runner --phase $($task.Phase) --runtime config/runtime.json"
    $action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $task.Time
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit $task.Limit
    Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Settings $settings `
        -Description "Jinshi DSH V0.3 daily phase: $($task.Phase)" -Force | Out-Null
    Write-Host "[INSTALLED] $($task.Name) weekdays $($task.Time) phase=$($task.Phase)"
}

Write-Host "[OK] Jinshi DSH daily tasks installed. Run deploy\status.ps1 to inspect."
