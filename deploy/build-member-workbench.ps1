param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, ".."))
$meta = Get-Content -LiteralPath (Join-Path $PSScriptRoot "member-workbench.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $root "dist-member-workbench"
}
$output = [IO.Path]::GetFullPath($OutputDir)
$work = Join-Path $output "build"
$package = Join-Path $output ("JinshiDSH-Workbench-" + $meta.version)
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Recurse -Force }
New-Item -ItemType Directory -Path $work -Force | Out-Null
New-Item -ItemType Directory -Path $package -Force | Out-Null
$webStage = Join-Path $work "apps\web"
New-Item -ItemType Directory -Path $webStage -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "apps\web\index.html") -Destination $webStage
Copy-Item -LiteralPath (Join-Path $root "apps\web\member-guide.html") -Destination $webStage
Copy-Item -LiteralPath (Join-Path $root "apps\web\assets") -Destination $webStage -Recurse

$python = Join-Path $root ".venv-auction\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "会员构建环境不存在，请先创建 .venv-auction 并安装 deploy/requirements-member-build.txt"
}
& $python -c "import PyInstaller, eltdx"
if ($LASTEXITCODE -ne 0) { throw "会员构建依赖不完整，请安装 deploy/requirements-member-build.txt" }
& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "JinshiDSH-Workbench" `
    --distpath (Join-Path $package "app") --workpath (Join-Path $work "pyi") `
    --specpath $work `
    --paths $root `
    --hidden-import services.local_sync --hidden-import services.local_license `
    --hidden-import services.auction_control `
    --hidden-import services.collector.auction_depth_shadow `
    --hidden-import services.collector.auction_source `
    --hidden-import services.collector.auction_schema `
    --hidden-import services.collector.auction_storage `
    --hidden-import services.collector.auction_materialize `
    --collect-all eltdx `
    --hidden-import services.collector.realtime_engine --hidden-import services.collector.archive_job `
    --exclude-module pandas --exclude-module torch --exclude-module scipy `
    --exclude-module matplotlib --exclude-module pytest --exclude-module numpy `
    --exclude-module PIL --exclude-module lxml --exclude-module IPython `
    --add-data ($webStage + ";apps\web") `
    --add-data ((Join-Path $root "config\strategy.json") + ";config") `
    (Join-Path $root "services\member_local_service.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller member workbench build failed" }

$installerSource = Join-Path $PSScriptRoot "install-member-workbench.ps1"
$installerTarget = Join-Path $package "install-member-workbench.ps1"
# Windows PowerShell 5.1 会把无 BOM 的 UTF-8 脚本当作 ANSI，中文字节可能破坏引号并导致语法错误。
for ($attempt = 1; $attempt -le 10; $attempt++) {
    Copy-Item -LiteralPath $installerSource -Destination $installerTarget -Force
    if (Test-Path -LiteralPath $installerTarget) { break }
    Start-Sleep -Milliseconds 500
}
if (-not (Test-Path -LiteralPath $installerTarget)) { throw "安装脚本复制失败: $installerTarget" }
$installerBytes = [IO.File]::ReadAllBytes($installerTarget)
if ($installerBytes.Length -lt 1000 -or $installerBytes[0] -ne 0xEF -or
        $installerBytes[1] -ne 0xBB -or $installerBytes[2] -ne 0xBF) {
    throw "安装脚本不完整或不是 UTF-8 BOM 编码"
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "member-workbench.json") -Destination $package
$guideSource = Join-Path $root "docs\MEMBER_WORKBENCH_GUIDE.md"
$guideTarget = Join-Path $package "MEMBER-GUIDE.txt"
[IO.File]::Copy($guideSource, $guideTarget, $true)
$hashes = @{}
Get-ChildItem -LiteralPath $package -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($package.Length + 1).Replace("\", "/")
    $hashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$utf8 = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $package "manifest.sha256.json"),
    ($hashes | ConvertTo-Json -Depth 4), $utf8)
$zip = $package + ".zip"
Compress-Archive -Path (Join-Path $package "*") -DestinationPath $zip -Force
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
$hashPath = Join-Path $output ("JinshiDSH-Workbench-" + $meta.version + ".sha256.txt")
[IO.File]::WriteAllText($hashPath, ($zipHash + "  " + [IO.Path]::GetFileName($zip) + "`r`n"), $utf8)
Write-Host "[OK] member workbench package: $zip"
