# 金十DSH 会员本地一体化工作台安装与使用指南

> 适用版本：1.0.22。会员本地数据默认放在 `H:\JinshiDSH\data`，不会上传 vipdoc、gbbq、K 线或私有策略结果。

## 1. 去哪里下载

- 公网下载地址：`http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.22.zip`
- 管理员本机发布包：`H:\projects\金十Agent\dist-member-workbench\JinshiDSH-Workbench-1.0.22.zip`
- SHA-256 校验文件：`http://114.132.236.131/dsh/downloads/JinshiDSH-Workbench-1.0.22.sha256.txt`

下载后先解压到临时目录，例如 `H:\JinshiDSH-Installer`。不要直接解压到正式数据目录 `H:\JinshiDSH\data`。

## 2. 安装

1. 在解压目录空白处按住 Shift 点右键，选择“在此处打开 PowerShell”。
2. 运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-member-workbench.ps1
```

3. 安装完成后访问 `http://127.0.0.1:8790/`。

默认目录：

- 程序：`H:\JinshiDSH\app`
- 公共数据缓存：`H:\JinshiDSH\data\shared`
- 会员 K 线和私有结果：`H:\JinshiDSH\data\members`
- 运行状态和日志：`H:\JinshiDSH\data\runtime`、`logs`

没有 H 盘时可指定其他根目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-member-workbench.ps1 -MemberRoot "D:\JinshiDSH"
```

## 3. 首次使用：云会员授权

1. 打开 `http://127.0.0.1:8790/`。
2. 点右上角“会员中心”。
3. 新会员可在“会员授权”填写姓名和手机号，领取并自动激活 5 天试用；每个手机号和每台设备只能领取一次。
4. 已有正式激活码的会员直接输入激活码，点激活或重新校验。
5. 页面显示会员编号、套餐、到期时间和授权有效后，再配置本地 K 线。

云端仅校验会员权限，不接收本机通达信路径和行情数据。

## 4. 配置 vipdoc 和复权数据

1. 在本地工作台会员中心打开“通达信数据”。
2. 填写“通达信 vipdoc 路径”，例如 `D:\new_tdx\vipdoc`。
3. 填写“通达信根目录”，例如 `D:\new_tdx`。
4. 程序会自动寻找 `T0002\hq_cache\gbbq` 或 `gbbq.dat`。
5. 先点“保存并检查”，确认有效后点“生成会员 K 线”。

vipdoc 有效的最低条件：

- `vipdoc\sh\lday` 存在；
- `vipdoc\sz\lday` 存在；
- 通达信已下载日线数据；
- 如需精确前复权，根目录下应有 gbbq 权息文件。

首次生成要扫描全市场，请等待页面显示“K 线已生成”。

## 5. 怎样确认已经开始监控

在会员中心“工作台总览”查看运行状态，正常时应看到：

- 状态：监控中；
- 数据日期为当前交易日；
- 最近同步时间持续更新；
- 公共行情只数大于 0；
- 策略基线只数大于 0；
- 会员授权有效，本地计算状态为成功。

如状态为“需要授权”、“同步过期”或“等待计算”，先按页面提示处理，不要把历史归档当作当天实时数据。

## 6. 七个 TAB 怎么用

工作台包含七个 TAB：

1. 实时信号：市场驾驶舱、可买预警、事件流和板块资金流。
2. 竞价雷达：公共竞价事实与会员本地日线/分钟基线。
3. 题材库：题材概念、成分股和盘中题材直播。
4. 板块强度：板块排名、强度和历史趋势。
5. 领涨原因：涨停原因与多源合并结果。
6. 策略模型：模型池、买点、止损和 RR 筛选。
7. 历史选股：按交易日查看已归档选股。

顶部日期为“当天·实时”时才是实时视图；选择具体日期后显示历史归档。

## 7. 日常使用

1. Windows 登录后工作台自动启动；也可直接访问 `http://127.0.0.1:8790/`。
2. 盘中公共行情和题材数据自动从服务器同步。
3. 通达信盘后下载完整日线后，进入本地助手点一次“保存配置并生成会员 K 线”，补入最新交易日。
4. 生成完成后检查“监控运行状态”和当天策略基线。

## 8. 升级、回滚和卸载

升级：下载新 ZIP，解压后再运行同一安装命令。安装器会切换程序版本，不删除 `data`。

回滚：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-member-workbench.ps1 -Rollback
```

卸载程序并保留会员数据：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-member-workbench.ps1 -Uninstall
```

## 9. 常见问题

### 1.0.39：后台恢复已经整合到主安装器

ZIP 包内包含两个守护脚本，但会员只运行 `install-member-workbench.ps1`。
安装器会配置计划任务；无任务权限时尝试当前用户登录启动项。1.0.40起，两者均失败时
降级为本次登录期间守护并明确显示session_only，不再阻断健康主程序安装。要启用永久
守护，请以管理员身份重新运行同一个主安装器，不需要另装脚本。只有版本健康检查
通过、永久守护配置成功、已有授权文件校验不变时才报告全部安装成功；临时守护显示PARTIAL。

守护每60秒检查一次，15分钟最多尝试启动3次；不会重启仍存在的后台进程，也不会
增加行情请求或策略计算频率。升级和回滚持有互斥锁，守护不会中途拉起旧版；同版
重复安装保留上一版本。卸载移除自启动入口并禁用守护，不删除会员数据。
`-NoLaunch` 只配置文件与守护，不代表服务健康验收通过。
守护诊断在数据根目录 `runtime/member_recovery.log`，最多1MB加一个轮转备份。

- 网址打不开：检查任务管理器中是否有 `JinshiDSH-Workbench.exe`，或重新运行安装命令。
- 加载失败 HTTP 404：确认工作台版本不低于 1.0.22，按 `Ctrl+F5`，再检查服务器是否可访问。
- 保存失败：必须从 `127.0.0.1:8790` 本地工作台进入，不要在公网页直接保存本地路径。
- vipdoc 无效：核对 `sh\lday` 和 `sz\lday`，并先在通达信下载日线。
- 权息文件未找到：通达信根目录应指向包含 `T0002` 的目录。
- 状态不是“监控中”：依次检查云授权、最近同步、K 线生成和最近计算错误。

## 10. 数据安全边界

- 服务器下发：公共行情、题材、板块、领涨原因和公共历史归档。
- 会员电脑保存：vipdoc 配置、gbbq、前复权 K 线、私有策略结果和自选。
- 系统不应把会员本地路径、原始 K 线或私有策略上传公共服务器。
