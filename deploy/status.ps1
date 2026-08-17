$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "=== Windows scheduled tasks ==="
Get-ScheduledTask -TaskName "JinshiDSH-*" -ErrorAction SilentlyContinue | ForEach-Object {
    $info = Get-ScheduledTaskInfo -TaskName $_.TaskName
    [pscustomobject]@{
        Task = $_.TaskName
        State = $_.State
        LastRun = $info.LastRunTime
        LastResult = $info.LastTaskResult
        NextRun = $info.NextRunTime
    }
} | Format-Table -AutoSize

Write-Host "=== Latest daily run ==="
$schedulerPath = Join-Path $root "data\runs\scheduler_state.json"
if (Test-Path -LiteralPath $schedulerPath) {
    $scheduler = [System.IO.File]::ReadAllText($schedulerPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    Write-Host "scheduler pid=$($scheduler.pid) heartbeat=$($scheduler.updated_at)"
} else {
    Write-Host "scheduler heartbeat not found"
}
$runsPath = Join-Path $root "data\runs\daily_runs.json"
if (Test-Path -LiteralPath $runsPath) {
    $runs = [System.IO.File]::ReadAllText($runsPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    $latest = $runs.runs.PSObject.Properties.Name | Sort-Object -Descending | Select-Object -First 1
    Write-Host "date=$latest"
    $runs.runs.$latest.PSObject.Properties | ForEach-Object {
        Write-Host ("  {0,-12} {1}" -f $_.Name, $_.Value.status)
    }
} else {
    Write-Host "daily_runs.json not found"
}

Write-Host "=== Latest quality report ==="
$quality = Get-ChildItem -LiteralPath (Join-Path $root "data\runs") -Filter "quality_*.json" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($quality) {
    $report = [System.IO.File]::ReadAllText($quality.FullName, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    Write-Host "$($report.data_date) status=$($report.status)"
    $report.checks | ForEach-Object { Write-Host ("  {0,-28} {1}" -f $_.name, $_.status) }
} else {
    Write-Host "quality report not found"
}

Write-Host "=== Service health ==="
foreach ($url in "http://127.0.0.1:8787/api/health", "http://127.0.0.1:8088/DSH/") {
    $code = try { (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 0 }
    Write-Host "$url -> HTTP $code"
}

Write-Host "=== Latest backup ==="
$backup = Get-ChildItem -LiteralPath (Join-Path $root "backups") -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($backup) {
    $manifest = [System.IO.File]::ReadAllText((Join-Path $backup.FullName "manifest.json"), [System.Text.Encoding]::UTF8) | ConvertFrom-Json
    Write-Host "$($backup.Name) created=$($manifest.created_at) files=$($manifest.files.Count)"
} else {
    Write-Host "backup not found"
}
