param([string]$MemberRoot = 'H:\JinshiDSH', [switch]$Enabled, [switch]$Watch)
$ErrorActionPreference = 'Stop'
if (-not $Enabled) { exit 0 }
$root = [IO.Path]::GetFullPath($MemberRoot)
$disabled = Join-Path $root 'recovery\recovery.disabled'
if (Test-Path -LiteralPath $disabled) { exit 0 }
if ($Watch) {
    $watchMutex = New-Object Threading.Mutex($false, 'Local\JinshiDSH-MemberRecovery-Watch')
    $ownsWatch = $false
    try {
        try { $ownsWatch = $watchMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsWatch = $true }
        if (-not $ownsWatch) { exit 0 }
        while ($true) {
            if (Test-Path -LiteralPath $disabled) { break }
            & (Join-Path $PSHOME 'powershell.exe') -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -MemberRoot $MemberRoot -Enabled
            Start-Sleep -Seconds 60
        }
    } finally {
        if ($ownsWatch) { $watchMutex.ReleaseMutex() }
        $watchMutex.Dispose()
    }
    exit 0
}
$root = [IO.Path]::GetFullPath($MemberRoot)
if ($root -eq [IO.Path]::GetPathRoot($root)) { throw 'Invalid member root' }
$mutex = New-Object Threading.Mutex($false, 'Local\JinshiDSH-MemberRecovery-8790')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { exit 0 }
    if (Test-Path -LiteralPath $disabled) { exit 0 }
    $install = Get-Content -LiteralPath (Join-Path $root 'install_state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $exe = [IO.Path]::GetFullPath((Join-Path $install.install_root ('versions\' + $install.current_version + '\JinshiDSH-Workbench.exe')))
    if (-not $exe.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Executable outside member root' }
    if (-not (Test-Path -LiteralPath $exe)) { throw 'Installed executable missing' }
    # Never restart or kill an existing process, including an occupied foreign port.
    if (Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue) { exit 0 }
    $running = Get-CimInstance Win32_Process -Filter "Name='JinshiDSH-Workbench.exe'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) }
    if ($running) { exit 0 }
    $runtime = Join-Path $install.data_root 'runtime'
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    $statePath = Join-Path $runtime 'member_recovery.json'
    $logPath = Join-Path $runtime 'member_recovery.log'
    $now = Get-Date
    $state = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } else { @{ attempts=@() } }
    $attempts = @($state.attempts | Where-Object { [datetime]$_ -gt $now.AddMinutes(-15) })
    if ($attempts.Count -ge 3) { exit 0 }
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -ge 1048576) {
        Move-Item -LiteralPath $logPath -Destination ($logPath + '.1') -Force
    }
    $attempts += $now.ToString('o')
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($statePath, (@{attempts=$attempts} | ConvertTo-Json), $utf8)
    [IO.File]::AppendAllText($logPath, ($now.ToString('o') + ' process_absent restart_requested' + [Environment]::NewLine), $utf8)
    $process = Start-Process -FilePath $exe -ArgumentList @('--serve', '--data-root', ('"' + $install.data_root + '"'),
        '--bootstrap-path', ('"' + (Join-Path $root 'bootstrap.json') + '"')) -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 3
    $process.Refresh()
    $status = if ($process.HasExited) { 'early_exit code=' + $process.ExitCode } else { 'process_started pid=' + $process.Id }
    [IO.File]::AppendAllText($logPath, ((Get-Date).ToString('o') + ' ' + $status + [Environment]::NewLine), $utf8)
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
