# 金十DSH 本机部署脚本（Windows）
# 用法：powershell -ExecutionPolicy Bypass -File .\deploy\deploy-local.ps1
# 步骤：构建 dist → 复制到 C:\nginx\html\DSH → 安装 nginx 配置 → 启动 API 服务 → 启动 nginx
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
$nginxDir = "C:\nginx"

# 1) 构建静态包
Write-Host "[1/4] 构建 dist ..."
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1")

# 2) 复制到 nginx html/DSH
Write-Host "[2/4] 部署到 $nginxDir\html\DSH ..."
$dst = Join-Path $nginxDir "html\DSH"
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Copy-Item (Join-Path $root "dist") $dst -Recurse -Force

# 3) nginx 配置（已存在则备份）
Write-Host "[3/4] 安装 nginx 配置 ..."
$conf = Join-Path $nginxDir "conf\nginx.conf"
if (Test-Path $conf) {
    Copy-Item $conf "$conf.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')" -Force
}
Copy-Item (Join-Path $PSScriptRoot "nginx-dsh.conf") $conf -Force

# 4) 启动服务（API 已跑则跳过；nginx 已跑则 reload）
Write-Host "[4/4] 启动服务 ..."
$apiHealth = try { (Invoke-WebRequest -Uri "http://127.0.0.1:8787/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode } catch { 0 }
if ($apiHealth -ne 200) {
    Start-Process -FilePath $py -ArgumentList "services\market_data_service.py --port 8787 --data data" -WorkingDirectory $root -WindowStyle Hidden
    Write-Host "  API 服务已启动 (8787)"
} else {
    Write-Host "  API 服务已在运行 (8787)"
}

$nginxRunning = Get-Process -Name nginx -ErrorAction SilentlyContinue
if ($nginxRunning) {
    & (Join-Path $nginxDir "nginx.exe") -s reload
    Write-Host "  nginx 已 reload"
} else {
    Start-Process -FilePath (Join-Path $nginxDir "nginx.exe") -WorkingDirectory $nginxDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Write-Host "  nginx 已启动 (8088)"
}

Write-Host ""
Write-Host "=== 验收 ==="
foreach ($u in "http://127.0.0.1:8088/DSH/", "http://127.0.0.1:8088/DSH/api/health") {
    $code = try { (Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }
    Write-Host "  $u -> HTTP $code"
}
