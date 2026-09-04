# 卸载命令：powershell -File .\install-member-workbench.ps1 -Uninstall
param(
    [string]$PackageRoot = $PSScriptRoot,
    [string]$MemberRoot = "H:\JinshiDSH",
    [string]$InstallRoot = "",
    [string]$DataRoot = "",
    [switch]$Rollback,
    [switch]$Uninstall,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$meta = Get-Content -LiteralPath (Join-Path $PackageRoot "member-workbench.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$MemberRoot = [IO.Path]::GetFullPath($MemberRoot)
if ([IO.Path]::GetPathRoot($MemberRoot) -eq $MemberRoot) { throw "会员工作台根目录不能直接使用磁盘根目录" }
if ([string]::IsNullOrWhiteSpace($InstallRoot)) { $InstallRoot = Join-Path $MemberRoot "app" }
if ([string]::IsNullOrWhiteSpace($DataRoot)) { $DataRoot = Join-Path $MemberRoot "data" }
$statePath = Join-Path $MemberRoot "install_state.json"
$bootstrapPath = Join-Path $MemberRoot "bootstrap.json"
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\JinshiDSH-Workbench.vbs"
$utf8 = New-Object Text.UTF8Encoding($false)
$allowedInstallBase = $MemberRoot
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
if (-not $resolvedInstallRoot.StartsWith($allowedInstallBase + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "程序安装目录必须位于会员工作台根目录下"
}
$InstallRoot = $resolvedInstallRoot
$versions = Join-Path $InstallRoot "versions"

function Stop-Workbench {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "JinshiDSH-Workbench.exe" -and $_.ExecutablePath -and
            $_.ExecutablePath.StartsWith($MemberRoot + '\', [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Wait-WorkbenchHealth([string]$Version) {
    for ($attempt=0; $attempt -lt 15; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8790/api/health' -TimeoutSec 2
            if ($health.ok -and $health.service -eq 'member-local' -and $health.version -eq $Version) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Installed service health/version verification failed; installation is incomplete.'
}

function Get-FileDigest([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)) }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Complete-Workbench([string]$Executable, [string]$SelectedDataRoot, [string]$Version) {
    $recoveryError = $null
    try {
        $recovery = & (Join-Path $PackageRoot 'install-member-recovery.ps1') -MemberRoot $MemberRoot -NoLaunch:$NoLaunch
        if (-not $recovery.persistent) {
            Write-Warning 'Recovery mode: session_only. Windows denied permanent startup. Re-run this installer as administrator to enable login recovery.'
        }
    } catch { $recoveryError = $_ }
    if (-not $NoLaunch) {
        Start-Process -FilePath $Executable -ArgumentList @('--serve','--data-root', ('"' + $SelectedDataRoot + '"'),
            '--bootstrap-path', ('"' + $bootstrapPath + '"')) -WindowStyle Hidden
        Wait-WorkbenchHealth $Version
    }
    if ($script:licenseHash -and (Get-FileDigest $script:licensePath) -ne $script:licenseHash) {
        throw 'License preservation verification failed'
    }
    if ($recoveryError) { throw $recoveryError }
    if ($NoLaunch) { Write-Host '[STAGED] Files and recovery configured; service health not verified (-NoLaunch).' }
    elseif ($recovery.persistent) { Write-Host "[OK] Workbench $Version healthy; permanent recovery configured; data preserved." }
    else { Write-Host "[PARTIAL] Workbench $Version healthy; data preserved; recovery=session_only (not permanent)." }
}

$recoveryMutex = New-Object Threading.Mutex($false, 'Local\JinshiDSH-MemberRecovery-8790')
$ownsRecovery = $false
try {
try { $ownsRecovery = $recoveryMutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $ownsRecovery = $true }
if (-not $ownsRecovery) { throw 'Recovery is busy; retry installation' }
if ($Uninstall) {
    & (Join-Path $PackageRoot 'install-member-recovery.ps1') -MemberRoot $MemberRoot -Uninstall
    Stop-Workbench
    Remove-Item -LiteralPath $startup -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] 程序已卸载；会员数据根目录保持不变。"
    exit 0
}

$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
} else { [pscustomobject]@{ current_version=""; previous_version="" } }
if (-not $PSBoundParameters.ContainsKey('DataRoot') -and $state.data_root) { $DataRoot = $state.data_root }
if (-not $PSBoundParameters.ContainsKey('InstallRoot') -and $state.install_root) {
    $InstallRoot = [IO.Path]::GetFullPath($state.install_root)
    if (-not $InstallRoot.StartsWith($MemberRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid saved install root' }
    $versions = Join-Path $InstallRoot 'versions'
}
$script:licensePath = Join-Path $DataRoot 'runtime\license.json'
$script:licenseHash = if (Test-Path -LiteralPath $script:licensePath) { Get-FileDigest $script:licensePath } else { $null }

if ($Rollback) {
    if (-not $state.previous_version) { throw "没有可回滚的上一版本" }
    $target = Join-Path $versions $state.previous_version
    $exe = Join-Path $target $meta.entry_exe
    if (-not (Test-Path -LiteralPath $exe)) { throw "上一版本程序不存在: $exe" }
    Stop-Workbench
    $oldCurrent = $state.current_version
    $state.current_version = $state.previous_version
    $state.previous_version = $oldCurrent
    [IO.File]::WriteAllText($statePath, ($state | ConvertTo-Json), $utf8)
    Complete-Workbench $exe $state.data_root $state.current_version
    exit 0
}

$resolvedData = [IO.Path]::GetFullPath($DataRoot)
if ([IO.Path]::GetPathRoot($resolvedData) -eq $resolvedData) { throw "数据根目录不能直接使用磁盘根目录" }
foreach ($name in "shared", "members", "runtime", "logs", "backup") {
    New-Item -ItemType Directory -Path (Join-Path $resolvedData $name) -Force | Out-Null
}
New-Item -ItemType Directory -Path (Split-Path -Parent $bootstrapPath) -Force | Out-Null
[IO.File]::WriteAllText($bootstrapPath,
    (@{schema_version=1;data_root=$resolvedData} | ConvertTo-Json), $utf8)

$source = Join-Path $PackageRoot "app\JinshiDSH-Workbench"
$target = Join-Path $versions $meta.version
if (-not (Test-Path -LiteralPath (Join-Path $source $meta.entry_exe))) { throw "安装载荷不完整" }
foreach ($required in @('install-member-recovery.ps1','member-process-recovery.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $required))) { throw "Missing recovery payload: $required" }
}
Stop-Workbench
New-Item -ItemType Directory -Path $versions -Force | Out-Null
if (-not (Test-Path -LiteralPath $target)) {
    Copy-Item -LiteralPath $source -Destination $target -Recurse
}
$exe = Join-Path $target $meta.entry_exe
$previous = if ($meta.version -eq $state.current_version) { $state.previous_version } else { $state.current_version }
$newState = @{ current_version=$meta.version; previous_version=$previous;
               install_root=$InstallRoot; data_root=$resolvedData; installed_at=(Get-Date).ToString("s") }
New-Item -ItemType Directory -Path (Split-Path -Parent $statePath) -Force | Out-Null
[IO.File]::WriteAllText($statePath, ($newState | ConvertTo-Json), $utf8)
Complete-Workbench $exe $resolvedData $meta.version
} finally {
    # recovery.disabled is managed by the recovery installer on disable/uninstall.
    if ($ownsRecovery) { $recoveryMutex.ReleaseMutex() }
    $recoveryMutex.Dispose()
}
