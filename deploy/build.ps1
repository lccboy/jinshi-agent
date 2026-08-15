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

Write-Host "Built static web package:"
Write-Host "  source: $SourceDir"
Write-Host "  output: $OutputDir"
