# 前端 UI 优化：题材库/板块强度视图做真（v0.3.0）

> **面向 AI 代理的工作者：** 按 `docs/DEVELOPMENT_PROCESS.md` 执行；数据侧 TDD，前端 headless 验证。
> 依赖：后台数据全部落位（v0.2.3）——themes 248 / theme_stocks / sectors 264 / stocks 5146 / membership。

**目标：** 题材库视图 = 248 题材 → 概念标签 → 成分股展开；板块强度视图 = 264 板块 → 成分股展开（涨停徽章/题材标签）；两视图按代码互跳；主数据懒加载不进首屏。

**架构：**
- 数据侧：`archive_job` 新增 master lib 落盘到 `data/web/`——`themes.json`、`theme_stocks.json`、`sectors.json`、`stocks_slim.json`（{sid: {n 名称, s 板块, t 题材}}，体积裁剪 + gzip）
- 前端：`app.js` 懒加载这些文件（进题材/板块 tab 时拉，内存缓存）；成分股展开限 TOP200 防卡顿；涨停状态取当日 view.limitup 集合
- 互跳：成分股行的板块/题材标签点击 → 切换视图并高亮

**技术栈：** Python stdlib（数据侧）、vanilla JS + CSS（前端）、Edge headless 验证。

---

### 任务 1：archive 产出 master lib（TDD）

**文件：**
- 修改：`services/collector/archive_job.py`（`build_stocks_slim` + `write_master_lib`，archive_day 串联）
- 测试：`tests/test_web_aggregate.py`（新增）

- [x] **步骤 1：写失败测试**
```python
def test_build_stocks_slim():
    stocks = {"SZ300487": {"name": "蓝晓科技", "current": {"sectors": ["801001"], "themes": ["9"]}},
              "SH600000": {"name": "浦发银行", "current": {}}}
    slim = build_stocks_slim(stocks)
    assert slim["SZ300487"] == {"n": "蓝晓科技", "s": ["801001"], "t": ["9"]}
    assert slim["SH600000"] == {"n": "浦发银行", "s": [], "t": []}
def test_write_master_lib(tmp_path, ...):
    # normalized 有 themes/theme_stocks/sectors/stocks → web/ 出 4 个 .json + .gz
```
- [x] **步骤 2：确认失败 → 3：实现**：`build_stocks_slim` + `write_master_lib`（拷贝 3 字典 + 生成 slim，全部 gzip）
- [x] **步骤 4：确认通过**；**步骤 5：Commit** `feat: archive 产出 master lib（题材/板块/成分 slim + gzip）`

### 任务 2：前端视图做真（题材库 + 板块强度 + 互跳）

**文件：**
- 修改：`apps/web/assets/app.js`（懒加载器 + vTheme/vSector 重写 + 展开/搜索/互跳）
- 修改：`apps/web/assets/app.css`（题材列表/标签/展开行/搜索框）

- [x] **步骤 1：懒加载器**：`loadLib(name)` 读 `data/web/<name>.json`（themes/theme_stocks/sectors/stocks_slim），内存缓存，仅题材/板块 tab 触发
- [x] **步骤 2：vTheme**：搜索 + 题材列表（名称/成分数/热度/概念标签）→ 点击展开成分股（名称/板块标签/涨停徽章，TOP200）→ 板块标签点击跳板块视图高亮
- [x] **步骤 3：vSector**：板块排行（已有）→ 点击展开成分股（从 slim 反查 sector→stocks，题材标签/涨停徽章，TOP200）→ 题材标签点击跳题材视图高亮
- [x] **步骤 4：验证**：`node --check`；重新 archive + build；headless 验证题材库/板块视图展开渲染
- [ ] **步骤 5：Commit + tag** `feat: UI 题材库/板块强度视图做真 + 互跳` → `v0.3.0`
