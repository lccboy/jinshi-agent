param([string]$Backup)

$ErrorActionPreference = "Stop"
$nginxDir = "C:\nginx"
$backupRoot = Join-Path $nginxDir "backups"
$dst = Join-Path $nginxDir "html\DSH"

if (-not $Backup) {
    Get-ChildItem -LiteralPath $backupRoot -Directory -Filter "DSH.*" | Sort-Object Name -Descending |
        Select-Object Name, LastWriteTime | Format-Table -AutoSize
    throw "Specify an exact backup directory name with -Backup"
}
$source = Join-Path $backupRoot $Backup
$resolvedRoot = [System.IO.Path]::GetFullPath($backupRoot).TrimEnd('\') + '\'
$resolvedSource = [System.IO.Path]::GetFullPath($source)
if (-not $resolvedSource.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup path escapes backup root"
}
if (-not (Test-Path -LiteralPath (Join-Path $resolvedSource "index.html"))) {
    throw "Invalid backup: $resolvedSource"
}
$safety = Join-Path $backupRoot ("DSH.before-rollback." + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item $dst $safety -Recurse -Force
Remove-Item $dst -Recurse -Force
Copy-Item $resolvedSource $dst -Recurse -Force
& (Join-Path $nginxDir "nginx.exe") -p $nginxDir -c "conf/nginx.conf" -s reload
if ($LASTEXITCODE -ne 0) { throw "nginx reload failed (exit $LASTEXITCODE)" }
$code = try { (Invoke-WebRequest -Uri "http://127.0.0.1:8088/DSH/" -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }
if ($code -ne 200) { throw "Rollback health check failed: HTTP $code; safety copy: $safety" }
Write-Host "[OK] Rolled back to $Backup; previous release saved at $safety"
