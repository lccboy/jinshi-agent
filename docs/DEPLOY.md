# 金十DSH Windows Nginx 部署说明

目标服务器目录：`C:\nginx\html\DSH`

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

## nginx 配置

在 `nginx.conf` 的 server 块中加入：

```nginx
gzip_static on;
gzip_types application/json application/javascript text/css;

location /DSH/ {
    alias C:/nginx/html/DSH/;
    index index.html;
    try_files $uri $uri/ /DSH/index.html;
}

# Web 视图层：历史日文件不可变 → 永久缓存（切换历史日期 0 网络请求）
location ~* ^/DSH/data/web/day_\d{8}\.json(\.gz)?$ {
    alias C:/nginx/html/DSH/data/web/;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location = /DSH/data/web/index.json {
    add_header Cache-Control "public, max-age=300";
}
location = /DSH/data/web/day_latest.json {
    add_header Cache-Control "no-cache";
}
```

新增 API 后追加：

```nginx
location /DSH/api/ {
    proxy_pass http://127.0.0.1:8787/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

修改后重启 nginx。

## 验证

浏览器访问：

```text
http://服务器IP/DSH/
```

检查内容：

- 页面标题是金十DSH
- 没有静态资源 404
- 股票代码链接使用 `http://www.treeid/code_XXXXXX`
- 后续 API 路径可访问 `/DSH/api/health`

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
