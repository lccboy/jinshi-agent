param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$name = "JinshiDSH-Scheduler"
$startScript = Join-Path $PSScriptRoot "start-user-daemon.ps1"
$command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $startScript

if ($Uninstall) {
    Remove-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue
    Write-Host "[REMOVED] $name"
    exit 0
}

Set-ItemProperty -Path $runKey -Name $name -Value $command
$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -like "*services.collector.scheduler_daemon*"
}
if (-not $existing) {
    Start-Process -FilePath $python -ArgumentList "-m services.collector.scheduler_daemon --runtime config/runtime.json" `
        -WorkingDirectory $root -WindowStyle Hidden
}
Write-Host "[OK] 用户态调度已安装并启动（登录时自动运行）"
