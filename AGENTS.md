# AGENTS.md — 金十Agent 项目指令

> 本文件对所有在本仓库工作的 AI 代理 / 开发者生效，优先级高于默认行为。
> 配套规范：`docs/DEVELOPMENT_PROCESS.md`（流程）、`docs/DATA_MODEL.md`（数据）、`docs/STRATEGY_MODEL.md`（策略）、`docs/VERSION_PLAN.md`（路线）。

## 硬性约束（红线）

1. **数据模型**：一切数据产出必须符合 `docs/DATA_MODEL.md`——目录结构（§2）、字段命名（§4）、关键规则（§7）。不得自创并行数据格式。
2. **⑧金量买入公式口径不可改**：`services/collector/models/golden_vol.py` 与 `docs/STRATEGY_MODEL.md` §9 中的通达信公式转化（`AA/BUYA/TJ`）是用户指定口径，**不降级、不近似、不加容差**。
3. **主数据以开盘啦 API 为主源**（DATA_MODEL §3.4）；TDX/题材库仅作补充与校验。
4. **涨停原因 4 源合并**：`primary` 优先级 `kpl > jygs > ths > xgb`，`sources` 必须保留各源原文（§4.2）。
5. **只增不改**：facts 与 intraday 只追加；主数据与字典才允许更新。
6. **stock_id 统一**：市场前缀 + 6 位代码（SH/SZ/BJ），全系统唯一 join 键。
7. **先计划后代码**：多步骤任务必须先写实现计划（`docs/superpowers/plans/`），禁止直接开写。
8. **TDD**：核心逻辑（normalize/limit_detect/strategy_engine/kline_sync/web 聚合）先写失败测试。

## 项目结构

```text
apps/web/                 # 静态前端（V0.1）
services/collector/       # 统一采集器（V0.1a 起）
  master_collector.py     #   主数据（KPL API）
  kline_sync.py           #   日K同步（TDX vipdoc）
  quote_collector.py      #   腾讯实时行情
  limit_detect.py         #   涨停检测
  factor_collector.py     #   东财资金流 + 选股宝领涨原因
  archive_job.py          #   15:20 归档 + web 视图层
  models/golden_vol.py    #   ⑧金量买入（公式转化，口径不可改）
  normalize.py            #   清洗纯函数
tests/                    # TDD 测试（fixtures/ 放真实样本裁剪）
deploy/                   # build.ps1 + deploy.py
docs/                     # 规格/计划/验收/数据模型/策略
data/                     # 数据（raw/normalized/facts/intraday/archive/kline/web/runs）
config/strategy.json      # 策略配置（可编辑，不硬编码）
```

## 开发工作流（每任务）

1. 读相关规范（数据模型/策略/流程）
2. 写失败测试 → 确认红灯
3. 最少实现 → 绿灯
4. `collector --verify` 数据校验
5. 真实样本跑通
6. commit（中文规范，见 DEVELOPMENT_PROCESS §6）

## 常用命令

```powershell
# 测试
pytest tests/ -v
# 采集验证（单日）
python services/collector/archive_job.py --date 2026-08-14 --verify
# 构建 + 部署
powershell -ExecutionPolicy Bypass -File .\deploy\build.ps1
& "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe" .\deploy\deploy.py
```

## 参考仓库（已克隆，勿提交）

- `H:\projects\_ref_repos\kaipanla-data-parser`（开盘啦接口）
- `H:\projects\_ref_repos\kaipanla-crawler`（开盘啦爬虫）
- `H:\projects\_ref_repos\superpowers-zh`（开发流程方法论）
