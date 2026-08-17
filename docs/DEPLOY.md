# 金十DSH Windows Nginx 部署说明

目标服务器目录：`C:\nginx\html\DSH`（本机部署时 nginx 监听 **8088**，内网访问 `http://<IP>:8088/DSH/`）

> 端口说明：80 为特权端口，在沙箱/部分防火墙环境无法监听；本机部署统一用 8088。
> 若环境允许，把 `deploy/nginx-dsh.conf` 中 `listen 8088` 改为 `listen 80` 即可。

## 快速部署（本机）

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-local.ps1
```

若 Windows 任务计划注册被策略拒绝，可安装无需管理员权限的用户态调度（当前用户登录自启）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-user-daemon.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\status.ps1
```

调度心跳位于 `data/runs/scheduler_state.json`，阶段日志位于 `data/runs/logs/daily_runner.log`。盘前主数据固定读取上一交易日 KPL 历史截面，空响应或低于既有活跃股票数 80% 时拒绝写盘。

一键完成：构建 dist → 复制到 `C:\nginx\html\DSH` → 安装 nginx 配置（旧配置自动备份）→ 启动 API 服务(8787) + nginx(8088) → 打印验收结果。

## 部署拓扑

第一版采用静态 Web 部署：

```text
本地开发机
  apps/web
  docs
  deploy

Windows 服务器
  C:\nginx\html\DSH
    index.html
    assets/
    data/
```

后续版本增加后端后：

```text
nginx
  /DSH/          -> C:\nginx\html\DSH
  /DSH/api/      -> http://127.0.0.1:8787/api/
```

## 环境变量

部署脚本不保存密码，通过环境变量传入：

```powershell
$env:DSH_SSH_HOST="114.132.236.131"
$env:DSH_SSH_PORT="22"
$env:DSH_SSH_USER="Administrator"
$env:DSH_SSH_PASSWORD="请替换"
$env:DSH_LOCAL_DIST="H:\projects\金十Agent\apps\web"
$env:DSH_REMOTE_DIR="/C:/nginx/html/DSH"
```

也可以使用密钥：

```powershell
$env:DSH_SSH_KEY="C:\Users\Administrator\.ssh\id_rsa"
```

## 本地构建

当前 V0.1 是静态站，无需 npm 依赖。构建脚本会复制 `apps/web` 到 `dist`。

```powershell
cd H:\projects\金十Agent
.
```

实际命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\build.ps1
```

## SSH 上传

使用本地 Python 3.10 和 paramiko：

```powershell
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
& $py .\deploy\deploy.py
```

脚本会：

1. 检查 `DSH_LOCAL_DIST`
2. 连接 SSH
3. 备份服务器上旧的 `C:\nginx\html\DSH`
4. 创建远程目录
5. 上传静态文件

## 回滚

服务器备份目录名类似：

```text
C:\nginx\html\DSH.backup.20260816-101500
```

手工回滚：

```powershell
ssh Administrator@服务器IP
cd C:\nginx\html
Remove-Item -LiteralPath .\DSH -Recurse -Force
Rename-Item -LiteralPath .\DSH.backup.时间 .\DSH
```

本机部署会在 `C:\nginx\backups\DSH.<时间>` 自动保留现网版本。明确选择备份后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\rollback-local.ps1 -Backup DSH.20260817-093500
```

V0.5 数据备份、校验和隔离恢复：

```powershell
python -m services.collector.production_ops backup --root . --out backups --keep 14
python -m services.collector.production_ops verify-backup backups\<时间>
python -m services.collector.production_ops restore backups\<时间> --target D:\restore-drill
python -m services.collector.production_ops scan-secrets --root .
```

日备份覆盖不可再生主数据、事实、归档、Web 发布层、运行清单和配置。`data/kline` 为约 2.3GB 的可重建派生缓存，默认不重复备份，灾备时从配置的 TDX vipdoc 重新同步。

## nginx 配置

配置模板：`deploy/nginx-dsh.conf`（复制到 `C:\nginx\conf\nginx.conf`，`deploy-local.ps1` 自动安装并备份旧配置）。

核心 server 块：

```nginx
gzip_static on;
gzip_types application/json application/javascript text/css;

location /DSH/ {
    alias C:/nginx/html/DSH/;
    index index.html;
    try_files $uri $uri/ /DSH/index.html;
}

# Web 视图层：历史日文件不可变 → 永久缓存（切换历史日期 0 网络请求）
location ~* "^/DSH/data/web/day_[0-9]{8}\.json(\.gz)?$" {
    alias C:/nginx/html/DSH/data/web/;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location = /DSH/data/web/index.json {
    alias C:/nginx/html/DSH/data/web/index.json;
    add_header Cache-Control "public, max-age=300";
}
location = /DSH/data/web/day_latest.json {
    alias C:/nginx/html/DSH/data/web/day_latest.json;
    add_header Cache-Control "no-cache";
}

# API 反代（V0.2+）
location /DSH/api/ {
    proxy_pass http://127.0.0.1:8787/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

> 注意：nginx 正则 location 中的 `{`/`}` 需用双引号包裹整个正则，否则配置解析器会误判为块开始（`unknown directive`）。

## 验证

浏览器访问：

```text
http://服务器IP:8088/DSH/
```

检查内容：

- 页面标题是金十DSH
- 没有静态资源 404
- 股票代码链接使用 `http://www.treeid/code_XXXXXX`
- API 路径可访问 `/DSH/api/health`、`/DSH/api/agent/summary`（Agent 聚合摘要）

## V0.3 每日任务

以管理员 PowerShell 注册四阶段任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\install-tasks.ps1
```

默认工作日执行：09:00 `premarket`、09:14 `intraday`、15:10 `postmarket`、15:30 `archive`。归档先冻结开盘啦全量板块/子板块/成分股与涨停原因，再同时生成题材库、板块强度日视图。每阶段由 `daily_runner.py` 幂等记录；成功阶段不会重复执行，失败阶段每 5 分钟重试、最多三次。

检查计划任务、最近运行、质量门禁和服务健康：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\status.ps1
```

补跑指定阶段：

```powershell
python -m services.collector.daily_runner --date 2026-08-17 --phase postmarket --force
python -m services.collector.daily_runner --date 2026-08-17 --phase archive --force
```

卸载任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\install-tasks.ps1 -Uninstall
```

## V0.2 统一数据服务（market-data-service）

服务是**服务器本地进程**（仅监听 127.0.0.1，nginx 反代对外），纯 stdlib 零依赖。

### 本地启动（开发/验证）

```powershell
python services\market_data_service.py --port 8787 --data data
# 验证
curl http://127.0.0.1:8787/api/health
curl "http://127.0.0.1:8787/api/history?stock=SZ300487"
```

### 服务器部署（NSSM 注册开机自启）

```powershell
# 先装 NSSM（https://nssm.cc），再：
nssm install DSH-API "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe" "H:\金十Agent\services\market_data_service.py --port 8787 --data H:\金十Agent\data"
nssm set DSH-API AppDirectory "H:\金十Agent"
nssm set DSH-API AppStdout "H:\金十Agent\logs\api.log"
nssm set DSH-API AppStderr "H:\金十Agent\logs\api.err"
nssm start DSH-API
```

nginx 反代（已在上文 `location /DSH/api/`）后，对外访问 `/DSH/api/health` 验证。

### 数据送达服务器

采集在本地完成（TDX/KPL 数据源在本地），把 `data/web`、`data/facts`、`data/kline`、`data/normalized` 同步到服务器对应目录（可用 `deploy.py` 扩展或 robocopy）。前端静态优先（nginx 直出视图层），API 补动态（历史时间线/实时快照/Agent 入口）。
