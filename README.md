# 金十DSH · 股票分析工作台

A 股盘中实时预警 + 策略模型选股 + 数据管线一体的个人工作台。

## 能力概览

- **数据管线**（`services/collector/`）：主数据（开盘啦 API）· 日K（TDX vipdoc 前复权）· 腾讯实时行情 · 东财资金流 · 选股宝领涨原因 · 每日 15:20 归档
- **策略模型**（`config/strategy.json` 可编辑）：17 个通达信技术模型 + 四维共振叠加（模型×强度×资金×原因）
- **盘中预警**：事件驱动分层预警池（涨停/连板/预警/候选/自选），模型命中置顶，通达信双向联动
- **Web 工作台**：静态 SPA + Web 视图层（字段裁剪 + gzip + immutable 缓存），历史日期秒开

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | 数据模型（主数据/按日事实/盘中实时/日K/Web 视图层） |
| [`docs/STRATEGY_MODEL.md`](docs/STRATEGY_MODEL.md) | 策略定义（17 模型 + 买点评分 + 叠加确认层 + 通达信公式转化） |
| [`docs/VERSION_PLAN.md`](docs/VERSION_PLAN.md) | 版本规划（V0.1a → V0.5） |
| [`docs/DEVELOPMENT_PROCESS.md`](docs/DEVELOPMENT_PROCESS.md) | 开发流程规范（superpowers：计划→TDD→验证→审查） |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | 实现计划（任务/文件/测试/步骤） |

## 快速开始

```powershell
# 测试（TDD 红绿循环）
pytest tests/ -v

# 主数据采集（KPL API，全量约 10-20 分钟）
python services/collector/master_collector.py --full --verify

# 单日归档 + Web 视图层生成
python services/collector/archive_job.py --date 2026-08-14 --verify

# 构建 + 部署
powershell -ExecutionPolicy Bypass -File .\deploy\build.ps1
```

## 项目红线（见 AGENTS.md）

- 数据产出必须符合 `docs/DATA_MODEL.md`；⑧金量买入公式口径不可改（`services/collector/models/golden_vol.py`）
- 先计划后代码；核心逻辑 TDD

> 仅供研究参考，不构成投资建议。
