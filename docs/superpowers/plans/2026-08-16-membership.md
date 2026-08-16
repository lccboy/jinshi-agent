# 按日归属 membership（DATA_MODEL §4.5）实现计划

> **面向 AI 代理的工作者：** 纯函数 TDD；依赖主基础数据（stocks/themes/sectors 已落位 v0.2.2）。

**目标：** 产出 `data/facts/<date>/membership.json`——"当天该股属于哪些板块/子板块/题材、地位（龙头/中军/跟风）、板块内排名"，供前端题材库/板块视图按代码互跳与 V0.3 交集。

**架构：** `membership_collector.py`：
- 板块归属+排名：`stocks.json.current.sectors` × `kpl_<date>_stocks.json` 板块内顺序（强度序）→ rank
- 地位：rank 分位 → 龙头(前5%)/中军(前20%)/跟风
- 题材归属：`stocks.json.current.themes` × `themes.json` → theme 条目（position=None）
- 子板块识别：`sectors.json.parent_id` 非空 → type=subsector

**技术栈：** Python 3.10 stdlib、pytest、真实 KPL 数据。

---

### 任务 1：membership 生成（TDD）

**文件：**
- 创建：`services/collector/membership_collector.py`
- 测试：`tests/test_membership_collector.py`

- [x] **步骤 1：写失败测试**
```python
def test_position_by_rank():
    assert position_by_rank(1, 50) == "龙头"
    assert position_by_rank(6, 50) == "中军"    # 12%
    assert position_by_rank(30, 50) == "跟风"
def test_build_membership():
    ...sectors（801001 level1 + 801722 level2）+ themes + plate_orders（含顺序）→
    断言 sector/subsector/theme 条目、rank、position、type
```
- [x] **步骤 2：确认失败 → 3：实现**：`position_by_rank` + `build_membership` + `load_plate_orders`（保持 KPL 板块内源顺序）+ CLI `--date --kpl-stocks --normalized --out`
- [x] **步骤 4：确认通过**；**步骤 5：Commit** `feat: membership_collector 按日归属（板块/子板块/题材 + 地位 + 排名）`

### 任务 2：真实数据 + 归档联动

- [x] **步骤 1**：2026-08-14 真实跑 → membership.json（计数：覆盖个股数、板块条目、题材条目）
- [x] **步骤 2**：重跑 archive（view.pools.confirm/stars 现用真实 membership）→ headless 验证 strategy/history 视图正常
- [x] **步骤 3**：Commit + tag `v0.2.3`
