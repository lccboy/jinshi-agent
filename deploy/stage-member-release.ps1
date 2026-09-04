param([Parameter(Mandatory=$true)][string]$WorkbenchOutput,
      [Parameter(Mandatory=$true)][string]$OutputDir)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$meta = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'member-workbench.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $target) { throw 'Use a new release directory' }
$downloads = Join-Path $target 'downloads'
$assets = Join-Path $target 'assets'
New-Item -ItemType Directory -Path $downloads,$assets -Force | Out-Null
foreach ($name in @('index.html','member-guide.html')) {
    Copy-Item -LiteralPath (Join-Path $repo ('apps\web\' + $name)) -Destination $target
}
foreach ($name in @('app.js','app.css')) {
    Copy-Item -LiteralPath (Join-Path $repo ('apps\web\assets\' + $name)) -Destination $assets
}
$base = 'JinshiDSH-Workbench-' + $meta.version
foreach ($suffix in @('.zip','.sha256.txt')) {
    Copy-Item -LiteralPath (Join-Path $WorkbenchOutput ($base + $suffix)) -Destination $downloads
}
Copy-Item -LiteralPath (Join-Path $repo 'docs\MEMBER_WORKBENCH_GUIDE.md') -Destination (Join-Path $downloads 'MEMBER-GUIDE.txt')
$stream = [IO.File]::OpenRead((Join-Path $downloads ($base + '.zip')))
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }
finally { $stream.Dispose(); $sha.Dispose() }
$manifest = @{schema_version='member-workbench-update-v1'; version=$meta.version; sha256=$hash;
    zip_url=('http://114.132.236.131/dsh/downloads/' + $base + '.zip');
    sha256_url=('http://114.132.236.131/dsh/downloads/' + $base + '.sha256.txt');
    notes='Integrated process recovery, upgrade coordination and verified installation.'}
[IO.File]::WriteAllText((Join-Path $downloads 'member-workbench-latest.json'),
    ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
Write-Output ('Member release staged: ' + $target)
