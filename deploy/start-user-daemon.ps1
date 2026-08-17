$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
Start-Process -FilePath $python -ArgumentList "-m services.collector.scheduler_daemon --runtime config/runtime.json" `
    -WorkingDirectory $root -WindowStyle Hidden

