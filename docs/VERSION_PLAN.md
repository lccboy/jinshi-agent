# 金十DSH 版本规划（v2 优化版）

> 优化说明（相对 v1）：
>
> - V0.1 拆为 **数据管线（V0.1a）+ 视图渲染（V0.1b）**，补齐"数据从哪来、怎么进 `DSH/data/`"这一缺失环节
> - V0.2 不再从零新建服务，改为**收编现有 `BK/api.py`**（已提供 `/api/sectors` 等接口）
> - V0.4 Agent **提前**，与 V0.2 并行开发——DSH 可直接读本地 JSON，不必等 API 服务完成
> - 新增**基建横切层**：git、数据目录规范、Windows 计划任务、安全约束（审批策略为 never 时的只读默认）
> - V0.3 信号引擎与 V0.4 Agent 共用同一份交集逻辑，互为服务化/自然语言两面

目标部署地址：

- Web 根目录：`C:\nginx\html\DSH`
- 访问路径：`http://服务器IP/DSH/`

## 当前基线（2026-08-16）

- `apps/web` 五个视图骨架已建，均为占位文案；`dist` 与 `apps/web` 同步
- KPL 数据新鲜：板块到 2026-08-14，涨停原因到 2026-08-15（`H:\projects\kpl\output`）
- 题材库已有 Flask 后端 `BK/api.py`（`/api/sectors`、`/api/stocks/<plate_id>`、`/api/sentiment`，带 CORS 与缓存）
- 策略结果在 `C:\Users\Administrator\WorkBuddy\<时间戳>\tdx_tri_result_*.json`
- 缺口：非 git 仓库、无 Windows 计划任务、无数据同步脚本、`limitup_multi` 的 `sources` 字段存在 PowerShell `@{...}` 序列化残留

## 版本依赖关系

```text
V0.1a（数据管线）→ V0.1b（视图渲染）→ V0.2（API 服务）→ V0.3（信号引擎）
                                    ↘ V0.4（Agent，与 V0.2 并行）
所有版本同步推进"基建横切层"；V0.5 收口。
```

## V0.1 静态工作台

### V0.1a 数据管线（阻塞项，最先做）

目标：把散落在 H 盘的数据标准化同步进 `apps/web/data/`。

> **可执行任务分解见** `docs/superpowers/plans/2026-08-16-v0.1a-data-pipeline.md`（superpowers 流程：任务/文件/测试/步骤/commit，核心逻辑 TDD）。

范围：

- 新增 `services/collector` 统一采集器（Python），替代零散脚本：
  - `master_collector.py` **主数据**：开盘啦 API 采集板块（`RealRankingInfo` 分页 + `SonPlate_Info`）、个股（`ZhiShuStockList_W8` 遍历 Type 0~19 合并）、题材/子概念（`Theme/InfoBKR`），按 `docs/DATA_MODEL.md` §3 写入 `data/normalized/`；每日开盘前 09:10 增量更新（`manifest.json` 断点续传，Token 过期自动刷新）
  - `intraday_collector.py` **盘中快照**（V0.3 起启用，节奏见 DATA_MODEL §5）
  - `quote_collector.py` **实时行情**：腾讯行情 qt.gtimg.cn 全市场批量，盘中 3s 快照（KPL 3s 做不了全市场，行情与涨停检测独立兜底）
  - `limit_detect.py` **涨停检测**：腾讯涨停价字段 + 规则推导（按板块/ST 阈值，见 DATA_MODEL §10），与 KPL 涨停池交叉验证，双源防缺失
  - `factor_collector.py` **板块因子**：东财板块资金流（`money_flow.json`，盘中 30s + 盘后归档）+ 选股宝领涨原因（`leading_reason.json`，盘后），经 `sector_map.json` 与 KPL 板块 join（见 DATA_MODEL §4.14/4.15）
  - `kline_sync.py` **日K同步**：盘后 15:10 从 TDX vipdoc 同步前复权日K到 `data/kline/`（策略历史条件底库，见 DATA_MODEL §12）
  - `archive_job.py` **15:20 归档**生成 facts（收编 `collect_reasons_multi.py` 的 4 源合并逻辑）
- 主数据以 API 为主源（口径统一），TDX/题材库降级为补充校验（`list_date`、交易日历）
- 数据目录规范：`data/{raw,normalized,facts,intraday,archive,runs}` + `manifest.json`，模型与字段见 `docs/DATA_MODEL.md`（主数据 + 按日事实 + 盘中实时 + 归档）
- 修复 `limitup_multi.json` 中 `sources` 字段的 PowerShell `@{...}` 残留，统一为纯 JSON 对象
- 只保留最近 N 个交易日（默认 30），避免 `dist` 无限膨胀
- `build.ps1` 串联调用归档/同步 → 拷贝到 `dist`

数据来源：

- KPL：`H:\projects\kpl\output`
- 题材库：`H:\projects\金十AI题材库`
- 策略结果：`C:\Users\Administrator\WorkBuddy\2026-07-26-12-39-03`（V0.2 起改为统一输出目录）

验收标准：

- `apps/web/data/normalized/` 存在可用的板块/题材/涨停/策略 JSON，带 `data_date`、`source`、`fetched_at`
- 单一命令可完成"数据准备 → 构建"全流程

### V0.1b 视图渲染

目标：五个视图真实渲染数据，替换占位文案。

范围：

- 实时信号：今日涨停股列表（原因、连板高度、题材标签）
- 题材库：题材列表 + 细分概念 + 成分股
- 板块强度：板块排行（强度/涨跌%/主力净额/市值）+ 子板块
- 策略模型：TDX 模型命中、评分、买点
- 历史选股：日期切换查看历史数据
- **加载性能**：数据经 Web 视图层（`data/web/`，归档时生成）渲染——首屏只加载 `index.json` + 当日聚合，历史日期命中 immutable 缓存（0 网络请求），涨停原因详情懒加载；nginx `gzip_static` 预压缩（见 `docs/DATA_MODEL.md` §13）
- 股票名称/代码使用通达信 `treeid` 原生锚点；同花顺 `hexin://`，失败时降级网页链接

验收标准：

- 五个视图均有真实数据渲染，无 404
- 股票链接可联动通达信
- 可切换历史日期查看

## V0.2 统一数据服务（收编现有 api.py）

目标：把题材库现有 Flask 后端收编为统一市场数据服务，前端不再直接依赖零散 JSON。

范围：

- 将 `BK/api.py` 收编为 `services/market-data-service`，端口统一 8787
- 已有：`/api/sectors`、`/api/stocks/<plate_id>`、`/api/sentiment`
- 新增：`/api/themes`、`/api/limitups`、`/api/ladder`、`/api/market`、`/api/index`、`/api/abnormal`、`/api/strategies`、`/api/pools`、`/api/events`、`/api/instruments`、`/api/kline`、`/api/history`（与 `docs/DATA_MODEL.md` 的 facts 一一对应）
- 所有响应带 `data_date`、`source`、`fetched_at`；历史数据可查询
- 策略结果落盘规范化：统一输出到 `H:\projects\金十Agent\data\strategy\<日期>\`，停止依赖 WorkBuddy 时间戳目录
- 前端改为访问 API；保留 API 不可用时的 `data/` 文件降级
- API 读 Web 视图层（`data/web/`）并加内存缓存（lru），只返回页面所需字段；新增 `/api/intraday/latest` 轻量实时快照接口（~10-30KB）
- nginx 增加 `/DSH/api/` 反向代理到 `http://127.0.0.1:8787/api/`；静态层启用 `gzip_static` + 历史 `immutable` 缓存（见 `docs/DATA_MODEL.md` §13）

验收标准：

- 前端通过 API 加载题材、板块、涨停原因和策略命中
- 数据带元数据，历史可查询
- API 服务由 Windows 计划任务或服务托管，开机自启

## V0.3 实时信号交集

目标：当天涨停股与题材、板块、子板块、个股地位、涨停原因、策略模型的自动交集。

范围：

- `services/signal-engine`：盘中用 KPL 实时数据，模型使用最近一次收盘结果
- 信号输出改为**事件驱动**：`limitup`/`ladder_up`/`signal_hit`/`broken`/`leader_change`/`sector_boom`/`volume_surge`/`index_resonance` 八类事件写入 `facts/<日期>/events.json`（见 DATA_MODEL §4.12）
- **分层预警池**：涨停池/连板池/预警池/候选池/自选池，成员带进入时间、评分、状态机（观察→预警→确认/移除），写入 `facts/<日期>/pool.json`（见 DATA_MODEL §4.13）；**自研模型命中票置顶**（`model_hit` + `priority: high`）
- **策略引擎（可编辑）**：`services/collector/strategy_engine.py` 加载 `config/strategy.json`——17 个模型（见 `docs/STRATEGY_MODEL.md`）启停/阈值/权重全部外置可编辑，改配置即重跑；盘后全量扫描写 `strategy.json`，盘中"昨日定格指标 + 腾讯实时"触发模型命中 → `events(signal_hit, source=tdx_model)`
- **四维共振叠加**：模型命中（基础层）∧ 板块强度≥4000（`sectors.json`）∧ 资金流入（`money_flow.json`）∧ 领涨原因（`leading_reason.json`）→ 3星/4星分级，4 星置顶（`confirm` + `stars`，见 `docs/STRATEGY_MODEL.md` §8）；精选板块升级为"强度+资金+原因"三条件
- 评分 = 硬条件（涨停/晋级/交集命中过线）+ 软评分（连板高度×题材热度×板块强度×模型命中×原因置信度），带 `score_breakdown` 分解可解释
- **通达信联动**：单票 `treeid://` 锚点；预警池/候选池批量导出通达信自定义板块文件（`.blk`，`代码|名称|市场`），服务器开盘前写入 TDX `T0002\blocknew\`，前端可下载手动导入（见 DATA_MODEL §11）
- **历史可查与回测闭环**：`/api/pools?date=`、`/api/pools?stock=`、`/api/events?type=`；预警池 + 后续 N 日收益 → 命中率/质量回测 → 迭代评分权重（见 DATA_MODEL §11.3）
- 盘中实时采集（节奏见 `docs/DATA_MODEL.md` §5）：竞价 09:15–09:30 每 3s、开盘 09:30–10:30 每 3s、10:31–15:00 每 30s，快照追加写入 `data/intraday/<日期>/`（行情段走腾讯全市场，结构化段走 KPL，分层见 §10）
- 涨停检测独立于 KPL：腾讯涨停价 + 板块/ST 阈值规则，与 KPL 涨停池交叉验证防缺失（见 `docs/DATA_MODEL.md` §10）
- 每日 15:20 归档：生成当日 facts（行情/涨停/归属+地位/策略），intraday 目录移入 `data/archive/`
- 交集 = `limitup` ⋈ `strategy` ⋈ 当日 `membership`（join 键 `stock_id`）
- Windows 计划任务托管采集与扫描（交易日 09:14 启动，15:05 停止，15:20 归档）
- 前端自动刷新候选股列表
- 交集逻辑抽为独立模块，与 V0.4 Agent 共用

验收标准：

- 能执行"扫描当天实时信号交集"
- 候选股展示题材、板块、子板块、地位、原因、模型命中和总分
- 预警池（alert）可导出通达信自定义板块并单票联动，历史任一天各池成员可查
- 事件流带时间戳可回放，历史快照可查看

## V0.4 金十DSH Agent（与 V0.2 并行）

目标：接入 DeepSeek Harness，使股票工作台具备自然语言分析和多代理研究能力。依赖 V0.1a 数据管线，不依赖 V0.2 API。

范围：

- 创建 `stock-signal` Agent Preset
- 工具**默认只读**（查询/扫描/历史），写操作（归档、自选股）走白名单——当前审批策略为 never，Agent 自动执行工具时不能有破坏性默认权限
- 注册通达信/同花顺联动工具
- 注册股票专用 Conversation Node 和 UI 卡片
- 使用子代理并行分析候选股
- 使用 Storage 保存自选股、研究笔记和历史选股

部署选择：

- DSH 后端运行在本机或服务器本地端口，绑定内网
- nginx 将 `/DSH/api/` 代理到 DSH 或股票数据服务
- 静态 Web 前端仍然部署到 `C:\nginx\html\DSH`

验收标准：

- 用户可以在 DSH 对话中查询当天信号
- 返回的股票卡片可点击通达信和同花顺
- 候选股能被并行研究和归档

## V0.5 生产化

范围：

- nginx 增加访问认证或反向代理层认证；API 与 DSH 仅内网可达
- 数据库/数据备份和日志轮转（Windows 计划任务）
- 服务自动重启（NSSM 或计划任务）
- 部署回滚脚本（backup 目录 + git 标签双通道）
- 数据源密钥迁移到凭据管理，不写入前端与 git

验收标准：

- 版本可回滚（git tag 或 backup 目录）
- 数据可恢复
- 敏感信息不写入前端文件与仓库

## 基建横切层（所有版本同步推进）

| 项 | 内容 | 起始版本 |
|---|---|---|
| 开发流程 | 按 `docs/DEVELOPMENT_PROCESS.md`（superpowers）：头脑风暴→规格→计划→TDD→验证→审查；实现计划存 `docs/superpowers/plans/`；项目红线见 `AGENTS.md` | V0.1a |
| 版本控制 | `git init` + 首次提交；中文提交规范；`main` + `feat/<version>-<feature>` 分支；每版本打 tag | V0.1a |
| 数据规范 | 目录与字段按 `docs/DATA_MODEL.md`；`data/{raw,normalized,facts,intraday,archive,kline,web,runs}` | V0.1a |
| 调度 | Windows 计划任务：采集 09:14 启动 / 15:05 停止（交易日）、归档 15:20、备份（V0.5） | V0.1a |
| 安全 | 工具默认只读、API/DSH 内网绑定、密钥凭据管理 | V0.1a |
| 部署 | `build.ps1` 串联归档/同步；`deploy.py` 上传 + 回滚（backup 目录 + git tag 双通道） | V0.1a |
