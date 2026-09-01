param(
    [string]$Executable = "",
    [int]$Port = 8792
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Executable)) {
    $Executable = [IO.Path]::GetFullPath([IO.Path]::Combine(
        $PSScriptRoot, "..", "dist-member-workbench", "JinshiDSH-Workbench-1.0.29",
        "app", "JinshiDSH-Workbench", "JinshiDSH-Workbench.exe"))
}
if (-not (Test-Path -LiteralPath $Executable)) { throw "workbench executable not found" }

function Test-EltdxNativeRuntime([string]$WorkbenchExecutable) {
    $internal = Join-Path (Split-Path -Parent $WorkbenchExecutable) "_internal"
    $native = Get-ChildItem -LiteralPath $internal -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName.Replace("\", "/") -match "eltdx/_native.*\.pyd$" } |
        Select-Object -First 1
    if (-not $native) { throw "eltdx/_native extension missing from frozen workbench" }
    return $native.FullName
}

$eltdxNative = Test-EltdxNativeRuntime $Executable
$testRoot = Join-Path $env:TEMP "JinshiDSH-Frozen-Smoke"
$process = Start-Process -FilePath $Executable -ArgumentList @(
    "--serve", "--host", "127.0.0.1", "--port", [string]$Port,
    "--data-root", $testRoot, "--server-api", "http://114.132.236.131/dsh/api"
) -WindowStyle Hidden -PassThru
try {
    $health = $null
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod ("http://127.0.0.1:" + $Port + "/api/system/health") -TimeoutSec 2
            break
        } catch {}
    }
    if (-not $health.ok) { throw "frozen workbench did not become healthy" }
    $homeResponse = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:" + $Port + "/")
    $asset = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:" + $Port + "/assets/app.js")
    [pscustomobject]@{
        process_id = $process.Id
        health = $health.ok
        service = $health.service
        tabs = ([regex]::Matches($homeResponse.Content, "data-view=").Count)
        asset_status = $asset.StatusCode
        eltdx_native = $eltdxNative
        data_root = $health.data_root
    } | ConvertTo-Json -Compress
} finally {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
