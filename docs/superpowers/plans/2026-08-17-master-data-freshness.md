# 主数据新鲜度与安全增量修复计划

## 目标

修复三类已确认问题：题材采集固定读取旧备份且伪造新鲜度；KPL 增量更新覆盖题材等补充字段；板块覆盖不足及 `industry/list_date` 缺失没有进入验证报告。

## 任务 1：题材源发现与新鲜度元数据（TDD）

修改 `services/collector/theme_collector.py`，测试 `tests/test_theme_collector.py`。

1. [x] 先写失败测试：默认候选源优先选择题材库当前产物，不选择 `.deploy_backups`；解析结果分别记录 `source_updated_at` 与 `collected_at`；manifest 保存路径、哈希、计数和 stale 状态。
2. [x] 实现源文件发现、文件时间/哈希元数据和 manifest 更新。
3. [x] 保留 `updated_at` 兼容字段，但其值取源数据日期，不再取程序运行日期。
4. [x] 运行题材采集器，以当前源重建 normalized 题材数据。

## 任务 2：主数据字段级合并（TDD）

修改 `services/collector/master_collector.py` 与 `services/collector/theme_collector.py`，测试 `tests/test_master_collector.py`、`tests/test_theme_collector.py`。

1. [x] 先写失败测试：KPL 增量更新保留 `current.themes`、`list_date`、来源元数据；更名写入 `name_history`；源端缺失股票不删除并标记本次未见。
2. [x] 实现 KPL 字段所有权合并，不再用新记录覆盖整条记录。
3. [x] 题材刷新先重建全部股票的 `current.themes`，再按最新反向索引写入，确保退出题材的旧归属被清除。
4. [x] 增加 removed/source_missing 变化报告。

## 任务 3：板块覆盖、行业和上市日期质量门禁（TDD）

修改 `services/collector/master_collector.py`，测试 `tests/test_master_collector.py`。

1. [x] 先写失败测试：板块 API 使用正确 offset 分页并去重；行业从行业板块归属推导；验证报告包含板块类型数、无板块数、无行业数、无上市日期数与覆盖率。
2. [x] 修复分页 `Index=0,30,...`，并把板块元数据传入股票构建流程。
3. [x] `list_date` 保持可选，不伪造；验证报告明确缺失数量。
4. [x] 跑全量测试并用 2026-08-14 最新本地 KPL 文件重放；当前环境无 KPL 凭据，在线刷新待凭据可用后执行。

## 验收

- 全量测试通过。
- 题材默认读取 `H:\projects\金十AI题材库\all_themes_slim.json`，manifest 显示真实源时间而非运行日期。
- KPL 增量不会清空题材和补充字段；题材刷新会清除退出题材的旧引用。
- 主数据校验报告可明确暴露板块、行业和上市日期覆盖缺口。
