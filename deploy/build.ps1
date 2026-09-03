param(
    [string]$SourceDir = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $resolvedSourceDir = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, "..", "apps", "web"))
} else { $resolvedSourceDir = $SourceDir }
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $resolvedOutputDir = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, "..", "dist"))
} else { $resolvedOutputDir = $OutputDir }

if (-not (Test-Path -LiteralPath $resolvedSourceDir)) {
    throw "Source directory not found: $resolvedSourceDir"
}

if (Test-Path -LiteralPath $resolvedOutputDir) {
    Remove-Item -LiteralPath $resolvedOutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $resolvedOutputDir | Out-Null
Copy-Item -Path (Join-Path $resolvedSourceDir '*') -Destination $resolvedOutputDir -Recurse -Force

# 会员下载区只发布新版一体化工作台，不再携带旧版 295MB Helper EXE。
$downloads = Join-Path $resolvedOutputDir "downloads"
New-Item -ItemType Directory -Path $downloads -Force | Out-Null
Remove-Item -LiteralPath (Join-Path $downloads "JinshiDSH-MemberHelper.exe") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $downloads "JinshiDSH-MemberHelper.exe.sha256.txt") -Force -ErrorAction SilentlyContinue
$workbenchOutput = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, "..", "dist-member-workbench"))
foreach ($name in "JinshiDSH-Workbench-1.0.37.zip", "JinshiDSH-Workbench-1.0.37.sha256.txt") {
    $source = Join-Path $workbenchOutput $name
    if (-not (Test-Path -LiteralPath $source)) { throw "请先构建会员工作台: $source" }
    Copy-Item -LiteralPath $source -Destination $downloads -Force
}
Copy-Item -LiteralPath ([IO.Path]::Combine($PSScriptRoot, "..", "docs", "MEMBER_WORKBENCH_GUIDE.md")) `
    -Destination (Join-Path $downloads "MEMBER-GUIDE.txt") -Force
$zipHash = (Get-FileHash -LiteralPath (Join-Path $downloads "JinshiDSH-Workbench-1.0.37.zip") -Algorithm SHA256).Hash
$latest = [ordered]@{
    schema_version = "member-workbench-update-v1"
    version = "1.0.37"
    zip_url = "http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.37.zip"
    sha256_url = "http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.37.sha256.txt"
    sha256 = $zipHash
    notes = "新版会员中心、通达信本地配置、5 天试用注册、TAB 页面与功能更新检查"
}
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $downloads "member-workbench-latest.json"),
    ($latest | ConvertTo-Json -Depth 4), $utf8NoBom)

# 业务数据完整打包；runs 为运行日志与诊断信息，不属于部署数据。
Write-Host "  script root after web copy: [$PSScriptRoot]"
$pkg = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, "..", "dist", "data"))
$dataLayers = @("raw", "normalized", "facts", "intraday", "archive", "kline", "web")
Write-Host "  data package root: $pkg"
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
foreach ($layer in $dataLayers) {
    $sourceLayer = [IO.Path]::GetFullPath([IO.Path]::Combine($PSScriptRoot, "..", "data", $layer))
    if (-not (Test-Path -LiteralPath $sourceLayer)) { continue }
    $targetLayer = Join-Path $pkg $layer
    Copy-Item -LiteralPath $sourceLayer -Destination $targetLayer -Recurse -Force
    $measure = Get-ChildItem -LiteralPath $targetLayer -File -Recurse -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    $sizeMB = [math]::Round(($measure.Sum / 1MB), 2)
    Write-Host "  included data/$layer ($($measure.Count) files, $sizeMB MB)"
}

# 生产 API 与公共采集器随站点部署；服务器从 DSH 根目录直接启动。
$runtimeRoot = [IO.Path]::GetDirectoryName($PSScriptRoot)
Copy-Item -LiteralPath ([IO.Path]::Combine($runtimeRoot, "services")) -Destination ([IO.Path]::Combine($resolvedOutputDir, "services")) -Recurse -Force
Copy-Item -LiteralPath ([IO.Path]::Combine($runtimeRoot, "config")) -Destination ([IO.Path]::Combine($resolvedOutputDir, "config")) -Recurse -Force

Write-Host "Built static web package:"
Write-Host "  source: $resolvedSourceDir"
Write-Host "  output: $resolvedOutputDir"
