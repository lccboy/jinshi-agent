# 主基础数据落位（题材字典 + 板块字典）实现计划

> **面向 AI 代理的工作者：** 按 `docs/DEVELOPMENT_PROCESS.md` 逐任务实现；纯函数 TDD。
> 背景：`data/normalized/` 目前只有 `stocks.json` + `sector_map.json`；按 `docs/DATA_MODEL.md` §3，
> 主基础数据 = `stocks.json`（✅） + `themes.json`（❌）+ `sectors.json`（❌），本次补齐。

**目标：** 产出 `data/normalized/themes.json`（题材字典+概念树+热度+成分数）、`data/normalized/sectors.json`
（板块/子板块字典，parent_id/level/type）、`data/normalized/theme_stocks.json`（题材→成分股索引，UI 展开用），
并回写 `stocks.json` 的 `current.themes`。

**架构：**
- `sectors.json`：`master_collector` 新增 `--kpl-daily`（读 kpl_<date>.json 的 sectors+sub → 字典，离线真实数据）
- `themes.json`：新增 `theme_collector.py`（读题材库 `all_themes_slim.json` → 字典 + 成分索引 + 回写 stocks）
- 题材库源路径可配置（`--source`），默认最新备份 `H:\projects\金十AI题材库\.deploy_backups\pre_l2_sweep_20260813\all_themes_slim.json`

**技术栈：** Python 3.10 stdlib、pytest、真实题材库/KPL 数据。

---

### 任务 1：sectors.json 板块字典（master_collector 扩展，TDD）

**文件：**
- 修改：`services/collector/master_collector.py`（`build_sectors_from_daily` + CLI `--kpl-daily`）
- 测试：`tests/test_master_collector.py`（新增用例）

- [x] **步骤 1：写失败测试**
```python
def test_build_sectors_from_daily():
    daily = {"sectors": [{"id": "801001", "name": "芯片"}],
             "sub": {"801001": [{"id": "801722", "name": "存储"}]}}
    secs = build_sectors_from_daily(daily)
    assert secs["801001"]["level"] == 1 and secs["801001"]["parent_id"] is None
    assert secs["801722"]["level"] == 2 and secs["801722"]["parent_id"] == "801001"
    assert secs["801001"]["type"] == "concept"
```
- [x] **步骤 2：确认失败 → 3：实现**：`build_sectors_from_daily`（sectors→level1，sub→level2，type 按前缀）+ CLI `--kpl-daily <文件> --out data` → 写 `normalized/sectors.json`
- [x] **步骤 4：确认通过**；**步骤 5：Commit** `feat: master_collector 产出 sectors.json 板块字典`

### 任务 2：theme_collector.py（题材字典，TDD）

**文件：**
- 创建：`services/collector/theme_collector.py`
- 测试：`tests/test_theme_collector.py`
- 修改：`docs/DATA_MODEL.md`（§2/§3.2 补 theme_stocks.json 说明）

- [x] **步骤 1：写失败测试**（内联小样本断言解析）
```python
def test_parse_theme_dump():
    dump = {"9": {"n": "光刻机概念", "l": 1, "t": [{"n1": "电子特气", "l2": [{"n2": "二氯二氢硅"}]}],
                  "s": [{"c": "600895", "n": "张江高科", "h": 386}]}}
    themes, ts, names = parse_theme_dump(dump)
    assert themes["9"]["name"] == "光刻机概念"
    assert "电子特气" in themes["9"]["sub_concepts"] and "二氯二氢硅" in themes["9"]["sub_concepts"]
    assert ts["9"] == ["SH600895"]
    assert names["SH600895"] == "张江高科"
```
- [x] **步骤 2：确认失败 → 3：实现**：`parse_theme_dump`（概念树展平 → sub_concepts、成分 s[].c → stock_id、热度=均值）+ `merge_themes_into_master`（补缺失个股 + current.themes 去重回写）+ CLI `--source --out`
- [x] **步骤 4：确认通过**；**步骤 5：Commit** `feat: theme_collector 题材字典（themes + 成分索引 + 回写 stocks）`

### 任务 3：真实数据落位 + 验证

- [x] **步骤 1**：`master_collector --kpl-daily kpl_2026-08-14.json` → sectors.json（计数：板块/子板块/type 分布）
- [x] **步骤 2**：`theme_collector` 跑题材库全量 → themes.json/theme_stocks.json/回写 stocks.json（计数：题材数/成分股数/新增个股）
- [x] **步骤 3**：数据一致性校验：stocks.json 的 current.themes 与 theme_stocks.json 互逆；sector_map 与 sectors.json 对齐
- [x] **步骤 4**：headless 验证题材库视图可用性（数据就绪，UI 展开下一步）；Commit + tag `v0.2.2`
