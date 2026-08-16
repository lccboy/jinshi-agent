param(
    [string]$SourceDir = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if (-not $SourceDir) { $SourceDir = Join-Path $root "apps\web" }
if (-not $OutputDir) { $OutputDir = Join-Path $root "dist" }

if (-not (Test-Path -LiteralPath $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

if (Test-Path -LiteralPath $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $OutputDir | Out-Null
Copy-Item -Path (Join-Path $SourceDir '*') -Destination $OutputDir -Recurse -Force

# V0.1b：Web 视图层（data/web/）一并打包，nginx 静态直出
$root = Split-Path -Parent $PSScriptRoot
$webData = Join-Path $root "data\web"
if (Test-Path -LiteralPath $webData) {
    Copy-Item -Path $webData -Destination (Join-Path $OutputDir "data") -Recurse -Force
    Write-Host "  included data/web (web view layer)"
}

Write-Host "Built static web package:"
Write-Host "  source: $SourceDir"
Write-Host "  output: $OutputDir"
