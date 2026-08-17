# 金十DSH 数据模型（最终稿 v1.0）

> 状态：**最终稿（2026-08-16）**。主数据 + 按日事实 + 盘中实时 + 归档的四层模型已定稿。
> 版本规划中 V0.1a 数据管线按此模型产出数据；V0.2 API、V0.3 信号引擎、V0.4 Agent 都只面向这一套模型。
> 字段口径参考开盘啦社区接口研究（`kaipanla-data-parser`、`kaipanla-crawler`），见 §9。

## 1. 分层总览

| 层 | 位置 | 内容 | 变更方式 |
|---|---|---|---|
| 主数据 | `data/normalized/stocks.json` | 个股身份：代码/名称/市场/板块/treeid/hexin | 增量合并，只更新 |
| 字典 | `data/normalized/themes.json`、`sectors.json` | 题材定义（含子概念）、板块/子板块定义（含层级） | 只更新 |
| **日K底库** | `data/kline/` | 本地通达信日线（前复权），策略与回测的时间序列底库 | 每日盘后同步，只追加 |
| 按日事实 | `data/facts/<日期>/` | 行情、涨停原因、连板梯队、市场统计、指数、情绪、归属+地位、策略命中、**资金流、领涨原因**、事件流、预警池 | **只增不改**，按日追加 |
| 盘中实时 | `data/intraday/<日期>/` | 板块强度/题材排序/指数/连板/异动/个股实时快照 | 只增，15:20 归档 |
| 归档 | `data/archive/<日期>/` | intraday 原始快照归档 | 只增 |
| 运行清单 | `data/runs/strategy_runs.json` | 策略每次运行的版本/参数/universe | 只增 |

**核心原则**：身份与字典放主数据；一切随时间变化的值——价格、量比、涨停原因、**连板**、**地位**、题材归属、策略命中、**板块强度与爆发原因**——全部放按日事实。主数据里只保留"当前"归属用于展示，历史查询一律走 facts。

## 2. 目录结构

```text
data/
├── manifest.json           # 各源/各类最后更新时间（主数据增量采集断点）
├── kline/                  # 本地日K（TDX vipdoc 同步，前复权，每日盘后 15:10 追加当日）
│   ├── sh600000.json       #   按 stock_id 分文件（或按交易所子目录）
│   └── manifest.json       #   各股票最后同步日期
├── normalized/
│   ├── stocks.json          # 个股主数据（开盘啦 API 采集，TDX/题材库补充校验）
│   ├── themes.json          # 题材字典（含子概念、热度、成分数）
│   ├── theme_stocks.json    # 题材→成分股索引（{theme_id: [stock_id]}，题材库 UI 展开用）
│   └── sectors.json         # 板块/子板块字典（parent_id 表达层级，标注概念/行业类型）
├── facts/
│   └── 2026-08-14/
│       ├── meta.json        # data_date、来源、fetched_at、行情状态、复权口径
│       ├── quotes.json      # 个股行情数值（63 字段子集，按 stock_id）
│       ├── limitup.json     # 涨停原因 4 源合并、连板、概念、涨停时间（按 stock_id）
│       ├── ladder.json      # 连板梯队：连板分布、反包板、打开高度、板块连板
│       ├── sectors.json     # 板块当日汇总：强度/涨停数/封单/家数/量比/机构增仓/爆发原因
│       ├── membership.json  # 当日题材/板块/子板块归属 + 地位 + 排名（按 stock_id）
│       ├── market.json      # 市场统计：涨跌家数/涨跌比/连板率/大幅回撤/百日新高
│       ├── index.json       # 大盘指数：上证/深成/创业板/沪深300 OHLC
│       ├── sentiment.json   # 多头空头风向标
│       ├── abnormal.json    # 异动个股（盘中/收盘）
│       ├── money_flow.json  # 板块资金流（东财：主力/超大/大/中/小单净流入+占比）
│       ├── leading_reason.json # 板块领涨原因（选股宝：description+涨停数）
│       ├── events.json      # 事件流：涨停/晋级/命中/炸板/龙头易主/板块爆发/量比/指数共振
│       ├── pool.json        # 分层预警池：涨停/连板/预警/候选/自选 + 状态机
│       └── strategy.json    # 策略命中、评分、买点（按 stock_id，引用 run_id）
├── intraday/
│   └── 2026-08-14/
│       ├── snapshots.ndjson # 每行一个采集快照（指数+板块+题材+连板+异动+个股，见 §5）
│       └── meta.json        # 当日采集节奏、起止状态
├── archive/
│   └── 2026-08-14/          # 归档后的 intraday 原始快照
├── web/                     # Web 视图层（归档时生成，页面唯一数据源，见 §13）
│   ├── index.json           #   日期清单 + 每日摘要（首屏）
│   ├── day_20260814.json    #   当日聚合视图（字段裁剪+预排序+gzip 预压缩）
│   └── day_20260814.detail.json  # 详情懒加载（涨停原因原文等）
└── runs/
    └── strategy_runs.json   # 策略运行清单（run_id → 版本/参数/universe）
```

## 3. 主数据与字典

**主数据以开盘啦 API 为主源**（口径统一、无需三源拼合），TDX/题材库降级为补充与校验。采集细节见 §3.4。

### 3.1 `stocks.json` 个股主数据

由开盘啦 API 采集生成：遍历板块成分（`ZhiShuStockList_W8`，Type 0~19 合并去重）得到全市场 code/name/所属板块标签；`market`/`board`/`is_st` 由代码与名称推导；`treeid`/`hexin` 由 code 推导；`industry` 取行业板块归属。TDX 仅补充 `list_date` 与校验。

```json
{
  "SZ300487": {
    "stock_id": "SZ300487",
    "code": "300487",
    "name": "蓝晓科技",
    "market": "SZ",
    "board": "创业板",
    "list_date": "2019-07-05",
    "industry": "医药生物",
    "treeid": "300487",
    "hexin": "300487",
    "is_st": false,
    "current": {
      "themes": ["T01", "T02"],
      "sectors": ["801001"],
      "updated_at": "2026-08-16"
    },
    "updated_at": "2026-08-16"
  }
}
```

- `stock_id`：**市场前缀 + 6 位代码**（`SH`/`SZ`/`BJ`），全系统唯一 join 键；market 由代码前缀推导（60/68→SH，00/30→SZ，8/4/92→BJ）
- `current`：当前归属，仅作展示快照；历史归属查当日 `membership.json`
- 更名/退市等低频变化直接覆盖，必要时记 `name_history`；`list_date` 为可选字段（API 63 字段不含，需 akshare/TDX 补充）

### 3.2 `themes.json` 题材字典

题材是动态概念，由开盘啦 API 采集：概念板块列表 + `Theme/InfoBKR`（子概念）+ `Index/NewGetList`（热门板块）；涨停原因 concepts 与题材库作交叉校验。题材 ID 需稳定：

```json
{
  "T01": {
    "theme_id": "T01", "name": "液冷", "source": "kpl",
    "sub_concepts": ["冷板式", "浸没式"], "hot": 123, "stock_count": 45, "updated_at": "2026-08-16"
  }
}
```

- 成分股与题材的完整映射在 `data/normalized/theme_stocks.json`（`{theme_id: [stock_id]}`），题材库 UI 直接展开；个股侧回写 `stocks.json` 的 `current.themes`
- `hot` 取成分股热度均值，`stock_count` 为成分股数；题材库接入见 `services/collector/theme_collector.py`

### 3.3 `sectors.json` 板块/子板块字典

**注意开盘啦板块分两类，字段映射不同**：概念板块（267 个，ID 以 8010–8018 开头）与行业板块（58 个，ID 以 8019/803/880 开头）。字典由 `RealRankingInfo` 动态分页 + `SonPlate_Info`（子板块）采集，统一记录类型：

```json
{
  "801001": { "sector_id": "801001", "name": "芯片", "parent_id": null, "level": 1, "type": "concept", "source": "kpl",
              "em_code": "BK1036", "xgb_id": "1234" },
  "801722": { "sector_id": "801722", "name": "存储", "parent_id": "801001", "level": 2, "type": "concept", "source": "kpl" }
}
```

- `type`：`concept`（概念板块）/ `industry`（行业板块）——**解析板块行情时按 type 用不同字段映射（见 §9）**
- `em_code`（东财板块代码，资金流来源）、`xgb_id`（选股宝板块 ID，领涨原因来源）：**跨源 join 键**，由名称匹配自动建立，映射表存 `data/normalized/sector_map.json`；KPL 801xxx 与东财 BKxxxx、选股宝 plate_id 是**三套不同 ID**，不能混用

### 3.4 主数据采集与增量更新

主数据各属性按来源分组更新，采集器不得重建整条股票记录：KPL 负责身份、ST、板块和行业；题材采集负责 `current.themes`；TDX/交易所负责 `list_date`。题材全量刷新时先清空旧题材归属再按最新索引重建，避免退出题材后残留。

`updated_at` 表示该属性组对应的源数据日期，不得用程序运行日期伪装新鲜度。运行清单同时记录：

- `source_updated_at`：源文件或接口数据实际时间；
- `collected_at`：本系统采集/处理时间；
- `source_hash`：文件源内容 SHA-256；
- `freshness`：`fresh` / `stale`。

| 主数据 | API 采集 | 补充 / 推导 |
|---|---|---|
| `sectors.json` | `RealRankingInfo` 动态分页（概念 267 + 行业 58）+ `SonPlate_Info`（子板块） | `type` 由板块 ID 前缀推导 |
| `themes.json` | 概念板块列表 + `Theme/InfoBKR`（子概念）+ `Index/NewGetList`（热门板块） | — |
| `stocks.json` | `ZhiShuStockList_W8` 遍历板块成分、Type 0~19 合并去重（code/name/所属板块标签） | market/board 由代码前缀推导；is_st 由名称前缀推导；treeid/hexin 由 code 推导；industry 取行业板块归属；`list_date` 用 akshare/TDX 补充（可选） |

采集器：`services/collector/master_collector.py`

- **每日开盘前 09:10 增量更新**：按 `manifest.json` 对比上次采集，只处理新增/变化（新上市、更名、ST、板块调整），写入 `data/normalized/`
- **周末 / 手动全量**：`master_collector.py --full`，全市场约 5300 只，并行 10 线程约 10–20 分钟
- Token 过期自动抓包刷新（沿用现有脚本逻辑）

`manifest.json`：

```json
{
  "stocks":  { "last_full": "2026-08-14", "last_incr": "2026-08-15" },
  "sectors": { "last_full": "2026-08-14" },
  "themes":  {
    "source": "theme_repo",
    "source_updated_at": "2026-08-14T11:40:52+08:00",
    "collected_at": "2026-08-14T15:20:00+08:00",
    "source_hash": "<sha256>",
    "freshness": "fresh",
    "count": 248
  }
}
```

## 4. 按日事实（`facts/<日期>/`）

只增不改，每日收盘归档后生成（或当日盘中增量写）。全部以 `stock_id` 为键（市场级事实除外）。

### 4.1 `quotes.json` 个股行情数值

字段来自开盘啦 `ZhiShuStockList_W8`（63 字段，需遍历 Type 0~19 合并）+ KPL 现网数据；盘中实时行情由腾讯补齐（`quote_source: tencent`，见 §10）：

```json
{
  "SZ300487": {
    "price": 67.25, "change": 1.01,
    "speed": 0.12,                     // 涨速
    "turnover": 0.37,                  // 实际换手率%
    "volume": 76836754,
    "volRatio": 1.01987,               // 量比
    "amplitude": 3.2,                  // 振幅
    "range_change": 5.1,               // 区间涨幅
    "mainBuy": 21093813, "mainSell": -15929506, "mainNet": 5164307,
    "big_order_net": 1234567,          // 300万以上大单净额
    "sell_flow_ratio": 0.31,           // 卖流占比
    "net_flow_ratio": 0.12,            // 净流占比（KPL 现网为 netFlowRatio）
    "close_seal_amount": 0,            // 收盘封单（涨停股>0）
    "max_seal_amount": 0,              // 最大封单
    "lead_count": 3,                   // 领涨次数
    "institution_increase": 123456,    // 机构增仓
    "circMarketCap": 34122276088, "totalMarketCap": 20643461595,
    "pb": 3.2,                         // 市净率
    "pe_dynamic": 30.26, "pe_ttm": 28.1, "pe_static": 32.4,
    "popularity": 880,                 // 人气值
    "popularity_rank_change": 12,      // 人气排名变化
    "close_source": "kpl", "adjusted": "qfq", "quote_source": "tencent"
  }
}
```

- `close_source` 记录口径来源（kpl/tdx），`adjusted` 记录复权口径（qfq 前复权/hfq 后复权）——策略买点计算与行情必须同口径
- `quote_source`：盘中实时行情来自腾讯行情（`tencent`）/ KPL（`kpl`）；收盘归档以 TDX 为准，同字段可并存多源用于交叉验证（见 §10）
- KPL 现网 `pe1`/`pe2` 映射到 `pe_dynamic`/`pe_ttm`，缺失字段允许缺省

### 4.2 `limitup.json` 涨停原因、连板、概念（多源合并）

涨停原因有 **4 个数据源**：

| 源 | 名称 | 获取时机 |
|---|---|---|
| `kpl` | 开盘啦 | 盘中实时（唯一盘中源） |
| `jygs` | 韭研公社 | 盘后补充（需 Cookie） |
| `ths` | 同花顺 | 盘后补充（需 Cookie） |
| `xgb` | 选股吧 | 盘后补充（公开接口） |

盘后由 `collect_reasons_multi.py` 合并：`primary` 按优先级 `kpl > jygs > ths > xgb` 裁决，`sources` 保留各源原文，`sourceCount` 记录实际命中的源数（≤4）。主源缺失时自动降级到下一个有值的源。

```json
{
  "SZ300487": {
    "reason": "存储",
    "detail": "…主源原文…",
    "boards": "首板",
    "concepts": ["存储", "盐湖提锂"],
    "first_time": "09:35",
    "seal_amount": 12345678,
    "detected_by": "both",
    "primary": "kpl",
    "sourceCount": 4,
    "sources": {
      "kpl":  { "reason": "存储", "detail": "…", "concepts": "存储、盐湖提锂", "boards": "首板", "name": "蓝晓科技", "source": "kpl" },
      "jygs": { "reason": "存储", "detail": "…", "boards": "首板", "name": "蓝晓科技", "source": "jygs" },
      "ths":  { "reason": "存储", "detail": "…", "boards": "首板", "name": "蓝晓科技", "source": "ths" },
      "xgb":  { "reason": "存储", "detail": "…", "boards": "首板", "name": "蓝晓科技", "source": "xgb" }
    }
  }
}
```

- `boards` = **连板**（首板/2连板/3天2板…），每日不同 → 属于事实
- `primary`/`sourceCount`/`sources` 三个字段**必须保留**——前端展示"主因 + N 源"标签，Agent 分析时可对比多源表述
- 盘中快照阶段只有 `kpl` 单源（`primary=kpl`、`sourceCount=1`）；15:20 归档时由盘后 enrichment 覆盖为 4 源版本
- `concepts` 拆成数组便于与题材字典对齐；涨停原因原文保留在 `detail`
- `first_time` 涨停时间、`seal_amount` 封单额来自 `get_sector_ranking` 个股明细
- `detected_by`：涨停由谁确认（`kpl`/`tencent`/`both`）——腾讯实时检测独立于 KPL，KPL 缺失时兜底，双源交叉验证（见 §10）

### 4.3 `ladder.json` 连板梯队（新增）

全市场 + 板块连板梯队、反包板、打开高度、连板统计（`get_market_limit_up_ladder` / `get_sector_limit_up_ladder` / `get_consecutive_limit_up`）：

```json
{
  "data_date": "2026-08-14",
  "statistics": {
    "total_limit_up": 52, "first_board": 38, "max_consecutive": 6,
    "ladder_distribution": { "1": 38, "2": 8, "3": 3, "6": 1 },
    "ladder_rate": 26.9
  },
  "stocks": {
    "SH600785": { "consecutive_days": 4, "boards": "4连板", "tips": "", "is_first_board": 0, "is_broken": false, "is_height_mark": false }
  },
  "broken_stocks": ["SZ002636"],
  "height_marks": ["SH600111"],
  "sectors": {
    "801346": { "limit_up_count": 5, "stocks": ["SH600785"], "broken_stocks": [] }
  }
}
```

- 连板率 =（总涨停 − 首板）/ 总涨停 × 100%
- 反包板（`is_broken`）与打开高度（`is_height_mark`）不计入连板梯队，但**必须保留**——它们决定"地位"重算

### 4.4 `sectors.json` 板块当日汇总（新增）

板块强度/涨停数/封单/家数/量比/机构增仓/爆发原因（`GetPlate_Info_QJ` + `GetPanKou` + `GetBaseFaceListZDEvnArtNew` + Socket `PlateTypeQuotasListResp`）：

```json
{
  "data_date": "2026-08-14",
  "sectors": {
    "801001": {
      "name": "芯片", "type": "concept", "level": 1,
      "strength": 23819, "change": 3.98, "volume": 12930.95,
      "mainNet": 207.52, "marketCap": 265122.13,
      "turnover": 3.99,               // GetPanKou 板块换手率
      "vol_ratio": 1.2,               // 板块量比（仅 Socket 推送）
      "institution_increase": 123,    // 机构增仓（仅 Socket 推送）
      "limit_up_count": 5,            // 涨停数
      "seal_amount": 2123483126,      // 涨停封单（元）
      "big_seal_amount": 1347672506,  // 大单封单（元）
      "up_count": 872, "down_count": 295,
      "boom_reason": "…",             // 当日爆发原因
      "rank": 1,
      "sub_sectors": ["801722"]
    }
  }
}
```

- `strength/change/volume/mainNet/marketCap` 即现网 KPL 每日 `kpl_<date>.json` 内容
- `vol_ratio`/`institution_increase` 仅 Socket 推送（HTTP 无此字段），缺失时允许缺省并降级（见 §7 规则 9）
- `boom_reason` 为板块当日爆发原因，历史爆发原因走 `GetDayBaseFaceListZDEvnArt`

### 4.5 `membership.json` 当日归属 + 地位 + 排名

**关键点**：题材归属、板块/子板块归属、以及个股在板块内的**地位（龙头/中军/跟风）和排名，每天都可能变**（题材退潮、新题材诞生、龙头易主），必须按日存：

```json
{
  "SZ300487": [
    { "type": "sector", "id": "801001", "name": "芯片", "position": "龙头", "rank": 1 },
    { "type": "theme", "id": "T01", "name": "存储", "position": null, "rank": 5 }
  ]
}
```

- `type`：sector（板块/子板块，按 `sectors.json` 的 parent_id 区分层级）/ theme
- `position`：个股在板块内的地位（龙头/中军/跟风），每日重算——输入含连板高度（`ladder`）、人气（`quotes.popularity`）、封单（`quotes.close_seal_amount`）
- `rank`：板块内强度排名
- 该文件是 V0.3 交集引擎"当天该股属于哪些题材/板块/子板块、什么地位"的唯一来源

### 4.6 `market.json` 市场统计（新增）

`get_daily_data` + `get_new_high_data` + `get_sharp_withdrawal`：

```json
{
  "data_date": "2026-08-14",
  "limit_up": 52, "actual_limit_up": 50,
  "limit_down": 12, "actual_limit_down": 10,
  "up_count": 2500, "down_count": 1800, "flat_count": 300,
  "up_down_ratio": 1.39, "prev_up_down_ratio": 1.25,
  "first_board_count": 38, "ladder_2": 8, "ladder_3": 3, "ladder_4_plus": 3,
  "ladder_rate": 26.9,
  "sharp_withdrawal_count": 15,
  "new_high_count": 120
}
```

- 大幅回撤家数（`sharp_withdrawal_count`）与对应股票列表（`get_sharp_withdrawal`）盘后补充
- 百日新高（`new_high_count`）为当日新增数量

### 4.7 `index.json` 大盘指数（新增）

`get_market_index` / `get_index_intraday` 收盘值：

```json
{
  "data_date": "2026-08-14",
  "indexes": {
    "SH000001": { "name": "上证指数", "open": 3200.5, "close": 3220.1, "high": 3225.0, "low": 3195.2, "preclose": 3190.3, "change_pct": 0.93, "turnover": 4123456789 },
    "SZ399001": { "name": "深证成指" },
    "SZ399006": { "name": "创业板指" },
    "SH000300": { "name": "沪深300" }
  }
}
```

### 4.8 `sentiment.json` 情绪风向标（新增）

`get_sentiment_indicator`（多头空头风向标，默认板块 801225）：

```json
{
  "data_date": "2026-08-14",
  "plate_id": "801225",
  "bullish_codes": ["SZ002112", "SH603667", "SH600550"],
  "bearish_codes": ["SZ000681", "SZ002465", "SZ001255"]
}
```

### 4.9 `abnormal.json` 异动个股（新增）

`get_abnormal_stocks`（区分盘中异动/收盘异动）：

```json
{
  "data_date": "2026-08-14",
  "items": [
    { "stock_id": "SZ300487", "type": "盘中异动", "time": "09:31", "reason": "…" }
  ]
}
```

### 4.10 `strategy.json` 策略命中

```json
{
  "SZ300487": {
    "run_id": "20260816_1445",
    "models": { "reversal": 87.3, "breakout": 0 },
    "score": 87.3,
    "buy_point": 66.5,
    "target": 72.0
  }
}
```

`run_id` 引用 `data/runs/strategy_runs.json`：

```json
{
  "20260816_1445": {
    "date": "2026-08-16",
    "models": ["reversal", "breakout", "weekly", "dwm", "lowstart", "volbrk"],
    "universe": 5292,
    "params": { "…": "…" },
    "created_at": "2026-08-16 14:45:00"
  }
}
```

模型每次运行的版本/参数/universe 都不同，没有 run_id 历史命中无法解释。策略定义与参数外置为 `config/strategy.json`（可编辑，见 `docs/STRATEGY_MODEL.md` §6），`run_id` 同时记录策略配置版本，配置变更后旧 run 仍可溯源对比。

### 4.11 `meta.json` 当日元数据

```json
{
  "data_date": "2026-08-14",
  "sources": ["kpl", "tdx", "题材库", "jygs", "ths", "xgb"],
  "market_status": "close",
  "adjusted": "qfq",
  "fetched_at": "2026-08-14 15:20:01",
  "archived_at": "2026-08-14 15:20:30"
}
```

### 4.12 `events.json` 事件流（新增）

信号引擎输出的事件化记录，是预警池的触发源。每类事件带时间戳与快照引用（可回放当日盘面）：

```json
{
  "data_date": "2026-08-14",
  "events": [
    { "ts": "2026-08-14T09:35:03", "type": "limitup",    "stock_id": "SZ300487", "score": 92,  "detail": "存储板块涨停",       "snapshot_ref": "09:35:03" },
    { "ts": "2026-08-14T10:47:00", "type": "broken",     "stock_id": "SZ002636", "score": 0,   "detail": "炸板",               "snapshot_ref": "10:47:00" },
    { "ts": "2026-08-14T11:05:00", "type": "signal_hit", "stock_id": "SZ300487", "score": 87.3, "detail": "模型 reversal 命中", "snapshot_ref": "11:05:00" }
  ]
}
```

事件类型与触发条件：

| type | 触发条件 | 数据来源 |
|---|---|---|
| `limitup` | 涨停检测确认（腾讯/KPL 双源） | quote + limitup |
| `ladder_up` | 连板晋级（1→2…） | ladder 实时 |
| `signal_hit` | 交集评分 ≥ 阈值 | 信号引擎 |
| `broken` | 涨停后跌破涨停价（炸板） | quote 连续快照 |
| `leader_change` | 板块内地位变化 | membership 重算 |
| `sector_boom` | 板块涨停家数激增 | sectors 实时 |
| `volume_surge` | 量比 ≥ 阈值 | quote |
| `index_resonance` | 指数与板块同步拉升 | index 实时 |

### 4.13 `pool.json` 分层预警池（新增）

事件驱动维护，每池成员带状态机（观察→预警→确认/移除），尾盘定格、次日重置（连板除外）：

```json
{
  "data_date": "2026-08-14",
  "pools": {
    "limitup":  { "SZ300487": { "entry_time": "09:35", "score": 92, "status": "active", "detected_by": "both" } },
    "ladder":   { "SH600785": { "entry_time": "09:30", "consecutive_days": 4, "status": "active" } },
    "alert":    { "SZ300487": { "entry_time": "09:35:03", "score": 87.3, "status": "active",
                                 "model_hit": ["②横盘突破", "⑧金量买入"],
                                 "confirm": { "sector_strength": true, "money_flow": true, "leading_reason": true },
                                 "stars": 4,
                                 "priority": "high",
                                 "score_breakdown": { "ladder": 30, "theme_heat": 20, "sector_strength": 15, "model_hit": 15, "reason_conf": 7.3 },
                                 "reasons": ["存储涨停", "板块第1", "模型 reversal 命中"] } },
    "candidate": { "SZ300487": { "score": 65, "rank": 12, "status": "candidate" } },
    "watchlist": { "SZ300487": { "note": "手动添加", "status": "active" } }
  },
  "removed": {
    "SZ002636": { "entry_time": "10:02", "exit_time": "10:47", "exit_reason": "炸板", "status": "removed" }
  }
}
```

- 五池语义：`limitup` 实时涨停、`ladder` 连板梯队、`alert` **交集信号预警（核心）**、`candidate` 收盘评分排序、`watchlist` 人工自选
- `model_hit`：命中的自研模型（②横盘突破…），**预警展示置顶**（`priority: high`）——"重点突出我的模型策略选出来的票"；`score_breakdown` 保留评分分解 → 可解释、可回测（见 §11.3、`docs/STRATEGY_MODEL.md`）
- `confirm`：叠加确认层结果（`sector_strength`/`money_flow`/`leading_reason` 三布尔）——4 星共振（模型∧强度∧资金∧原因）置顶，见 `docs/STRATEGY_MODEL.md` §8
- `removed` 记录退出（炸板/破位/人工移除），历史状态可完整还原

### 4.14 `money_flow.json` 板块资金流（新增）

东财板块资金流（`push2delay.eastmoney.com` clist API，f62 主力净流入口径），与 KPL 板块按 `sectors.json` 的 `em_code`/名称 join：

```json
{
  "data_date": "2026-08-14",
  "sectors": {
    "801001": {
      "name": "芯片", "em_code": "BK1036",
      "main": 8437255508, "main_pct": 3.2,        // 主力净流入(元)/占比%
      "super": 5123456789, "super_pct": 1.9,       // 超大单
      "big": 3313798719, "big_pct": 1.3,           // 大单
      "mid": -123456789, "small": -876543210,      // 中单/小单
      "rank_in": 3, "main_pct_rank": 5,            // 主力净流入排名（含占比排名）
      "intraday_trend": [                          // 分钟资金流（盘中归档，可省）
        { "t": "09:35", "main": 12345678, "super": 9012345 }
      ]
    }
  }
}
```

- 排名字段 `rank_in`/`main_pct_rank` 供叠加层"资金流入排名前 N"判定
- 分钟资金流（`fflow/kline`）盘中存 `intraday`，归档时可保留近 30 分钟或省略

### 4.15 `leading_reason.json` 板块领涨原因（新增）

选股宝 surge_stock（flash-api.xuangubao.cn），板块级"为什么涨"，与个股级 4 源原因（§4.2）互补：

```json
{
  "data_date": "2026-08-14",
  "plates": {
    "1234": {
      "xgb_id": "1234", "name": "存储",
      "reason": "…板块领涨原因原文…",
      "limit_up_count": 5,
      "stocks": ["SZ300487", "SH600785"]
    }
  }
}
```

- 按涨停数排序 = 右栏"领涨原因"列表；点击板块展开成分股
- 与 `sectors.json` 的 `xgb_id` join；`reason` 非空 且 涨停数 ≥ 阈值 → 叠加层 R 维度确认

## 5. 盘中实时采集（`data/intraday/<日期>/`）

### 5.1 采集节奏

| 时段 | 节奏 | 采集内容 |
|---|---|---|
| 09:15:00–09:30:00（竞价） | **每 3 秒** | 板块强度、题材排序、指数、连板梯队、竞价异动/涨停池个股 |
| 09:30:00–10:30:00（开盘） | **每 3 秒** | 同上 + 涨停池/强势板块成分/自选候选个股 |
| 10:31:00–15:00:00 | **每 30 秒** | 板块强度、题材排序、指数、连板梯队、个股（建议全量） |
| 15:20:00 | **归档** | 生成当日 facts，intraday 目录移入 archive |

### 5.2 快照格式（snapshots.ndjson，每行一个快照）

```json
{"ts": "2026-08-14 09:31:03", "phase": "open",
 "indexes":  {"SH000001": {"price": 3205.2, "change_pct": 0.47, "turnover": 123456}},
 "sectors":  [{"id": "801001", "name": "芯片", "strength": 23819, "change": 3.98, "mainNet": 207.52, "limit_up_count": 2}],
 "themes":   [{"id": "T01", "name": "液冷", "rank": 1}],
 "ladder":   {"total_limit_up": 12, "max_consecutive": 4},
 "abnormal": [{"code": "SZ300487", "type": "盘中异动", "reason": "…"}],
 "stocks":   {"SZ300487": {"price": 66.9, "change": 0.51, "volRatio": 0.98, "boards": ""}}}
```

- 追加写入，不修改历史行；只增不改
- `phase`：auction（竞价）/ open（开盘）/ tail（尾盘）
- 实时接口映射：`get_market_limit_up_ladder`→ladder、`get_abnormal_stocks`→abnormal、`get_index_intraday`→indexes、`get_sector_ranking`/`get_consecutive_limit_up`→sectors+stocks
- 行情段（`stocks`）3s 节奏来自**腾讯行情全市场批量**（qt.gtimg.cn，单请求数百只，分 10~20 批）；KPL 只提供板块/题材/连板/涨停池结构化字段（分层见 §10）

### 5.3 采集器行为与数据量说明

- 交易日 09:14 由 Windows 计划任务启动，15:05 停止高频采集，15:20 执行归档
- **KPL 段 3s 节奏无法覆盖全市场**（全量一轮约 19 秒）：KPL 3s 阶段只采子集——涨停池、强势板块成分、自选/候选池（建议 ≤500 只）；30s 阶段 KPL 可全量。**腾讯段 3s 即全市场**（见 §5.2、§10）
- 全天快照数 ≈ 300（3s×75min）+ 540（30s×4.5h）≈ **840 行/日**；`snapshots.ndjson` 单日约几十 MB，可接受；如需压缩后续可启用 gzip
- 盘中涨停原因只有 `kpl` 单源（`primary=kpl`、`sourceCount=1`）；盘后由 `collect_reasons_multi.py` 补充 `jygs`/`ths`/`xgb` 三源，15:20 归档时写入 facts 的 `limitup.json`（见 §4.2）

## 6. 归档流程（每日 15:20）

1. 停止采集，读取当日最后快照
2. 生成当日事实：`quotes.json`（收盘值，优先 TDX 收盘，缺失补 KPL 末值）、`limitup.json`（盘后多源合并：`primary` 裁决 + `sources` 保留 4 源原文）、`ladder.json`、`sectors.json`（含爆发原因）、`market.json`、`index.json`、`sentiment.json`、`abnormal.json`、`money_flow.json`、`leading_reason.json`、`membership.json`（重算地位/排名/归属）、`strategy.json`（若当日有模型运行）
3. 写 `meta.json`（`market_status: close`）
4. **生成 Web 视图层** `data/web/day_<date>.json`（字段裁剪 + 预排序 + gzip 预压缩，见 §13）
5. `data/intraday/<日期>/` 移入 `data/archive/<日期>/`
6. 次日 09:14 新建新的 intraday 目录

## 7. 关键设计规则

1. **stock_id 统一**：市场前缀 + 6 位代码（SH/SZ/BJ），全系统唯一 join 键；treeid/hexin 是主数据属性，不是键
2. **只增不改**：facts 与 intraday 只追加；主数据与字典才允许更新
3. **地位、连板、归属按日**：`position`、`boards`、`ladder`、`membership` 每天重算，历史查询只查当日 facts
4. **run_id 关联模型版本**：策略命中必须能溯源到运行参数
5. **复权口径显式记录**：`adjusted` 字段写入 meta 与 quotes，买卖点与行情同口径
6. **涨停原因多源合并（4 源）**：`kpl` 开盘啦（盘中）/ `jygs` 韭研公社 / `ths` 同花顺 / `xgb` 选股吧（盘后补充）。合并规则——`sources` 保留各源原文与 `source` 标识，`primary` 按优先级 `kpl > jygs > ths > xgb` 裁决，`sourceCount` 记录实际命中源数，主源缺失自动降级
7. **来源可追溯**：一般事实带 `source`/`close_source`，涨停原因带 `primary`/`sourceCount`/`sources`；多来源冲突时以优先级覆盖并保留原文备查
8. **板块按类型解析**：概念板块与行业板块的 `GetPlate_Info_QJ` 字段映射不同（见 §9），normalized 层必须按 `sectors.json` 的 `type` 走不同解析器
9. **Socket-only 字段降级**：板块量比、机构增仓只有 Socket 推送（HTTP 拿不到）；未启用 Socket 订阅时允许缺省，不阻塞其他字段
10. **主数据 API 采集为主源**：stocks/sectors/themes 一律由开盘啦 API 采集（口径统一），TDX/题材库仅作补充（`list_date`、交易日历）与交叉校验；主数据每日开盘前增量更新，manifest 断点续传

## 8. 关联关系图

```text
stocks.json (1) ──< facts/<d>/quotes.json
stocks.json (1) ──< facts/<d>/limitup.json
stocks.json (1) ──< facts/<d>/ladder.json
stocks.json (1) ──< facts/<d>/membership.json >── (1) themes.json / sectors.json
stocks.json (1) ──< facts/<d>/strategy.json >── (1) runs/strategy_runs.json
kline/ (1) ──< facts/<d>/strategy.json          （策略历史条件来自日K）
kline/ (1) ──< facts/<d>/quotes.json            （收盘行情与日K末根一致）
facts/<d>/* ──< intraday/<d>/snapshots.ndjson（盘中过程，facts 是收盘结果）
facts/<d>/market.json · index.json · sentiment.json · abnormal.json · money_flow.json · leading_reason.json 为市场级独立事实
```

V0.3 交集 = `limitup` ⋈ `ladder` ⋈ `strategy` ⋈ 当日 `membership`，join 键全为 `stock_id`；命中结果写 `events.json` → 维护 `pool.json` 预警池（通达信联动见 §11）；板块强弱看 `facts/<d>/sectors.json`，市场情绪看 `market.json` + `sentiment.json`；叠加确认（四维共振）看 `money_flow.json`（资金）+ `leading_reason.json`（原因）+ `sectors.json`（强度）+ `strategy.json`（模型）。

## 9. 数据源接口要点（开盘啦，社区仓库经验）

来源：`github.com/Rainynitesky/kaipanla-data-parser`、`github.com/jinhao2003/kaipanla-crawler`。

1. **域名分工**：`apphwshhq.longhuvip.com`（行情：板块/指数/盘口，涨停复盘与实时播报）、`applhb.longhuvip.com`（题材详情：概念层级 + 成分股）、`apphis.longhuvip.com`（历史数据/历史涨停复盘，**ZhiShuStockList_W8 必须用它**）、`apparticle.longhuvip.com`（资讯）、`getsockip.longhuvip.com`（**服务发现**：Socket 服务器 IP 列表）
2. **认证**：必须 Dalvik UA，通用参数 `PhoneOSNew=1&apiv=w44&UserID&Token`；Token 会过期，需抓包刷新
3. **板块两类映射不同**：概念板块（267，8010–8018）`GetPlate_Info_QJ` 字段布局与行业板块（58，8019/803/880）不同
4. **涨跌幅不在 GetPlate_Info_QJ**：在 `Index/GetInfo → BaceFaceList`；非交易时间该列表为空，需传 `Date=交易日期`
5. **GetPanKou 控制器是 ZhiShuL2Data**（参数用 StockID 而非 PlateID），不是 ZhiShuRanking
6. **BKFenShiZhiBo 控制器是 ConceptionPoint**（板块分时直播事件）
7. **ZhiShuStockList_W8 三个坑**：域名必须 apphis；响应 key 是小写 `list`；每 Type 只返回 Top9，**需遍历 Type 0~19 合并去重**才是完整个股列表（63 字段）
8. **板块量比（volRatio）与机构增仓（institutionIncrease）只在 Socket 推送**（`PlateTypeQuotasListResp`），HTTP API 找不到 → 需 Socket 订阅或降级缺省
9. **子板块个股数据 App 走 Socket 不走 HTTP**——盘中 3s 采集子板块成分可能受限，需实测降级方案
10. **连板梯队语义**：首板=当日首次涨停；N 连板=连续 N 天涨停；反包板（涨停打开再封）与打开高度标注不计入梯队但需保留
11. **腾讯行情 qt.gtimg.cn**：HTTP GET `q=sh600000,sz000001,...` 批量返回，单请求数百只、毫秒级，全市场 ~5300 只分 10~20 批，**3s 全市场实时可行**
12. **腾讯返回字段含涨停价/跌停价**——涨停检测直接用涨停价比对现价（±0.01 元容差），无需近似计算；其他字段：现价/昨收/涨跌幅/最高/最低/成交额/换手率/量比/市值/PE
13. **竞价阶段（9:15–9:25）腾讯同样返回昨收与盘口**，可用于集合竞价涨停检测；新股/涨停价字段为 0 时用规则推导兜底
14. **东财板块资金流**：`push2delay.eastmoney.com/api/qt/clist/get`（`fs=m:90+t:2,m:90+t:1`，`f62` 主力净流入、`f184` 占比、`f66/f69` 超大单、`f72/f75` 大单、`f78/f84` 中/小单）；分钟资金流 `api/qt/stock/fflow/kline/get?klt=1`；板块 ID 为东财 BKxxxx 体系，需与 KPL 801xxx 映射（`sector_map.json`）
15. **选股宝领涨原因**：`flash-api.xuangubao.cn/api/surge_stock/plates`（板块 description=领涨原因 + 涨停数）、`/stocks?uplimit=true`（涨停股）、`/api/plate/plate_set?id=`（成分股）、`/api/stock_label/labels`（个股标签）；即涨停原因 4 源中的 `xgb` 源

## 10. 数据源分层与容错降级

| 层 | 数据源 | 用途 | 采集节奏 | 缺失影响与对策 |
|---|---|---|---|---|
| 主源 | 开盘啦 KPL | 板块/题材/连板/情绪/涨停原因（结构化） | 主数据 09:10 增量；盘中 3s 板块+题材+涨停池 | 结构化缺失；行情/涨停池由腾讯兜底 |
| 实时行情 | 腾讯行情 qt.gtimg.cn | 全市场价格/涨跌幅/量比/成交额 + **涨停检测** | 盘中 3s 全市场批量 | 无 → 涨停检测与交集引擎核心输入 |
| 收盘权威 | TDX | EOD 收盘价（归档 quotes 优先）、list_date、交易日历 | 15:05 盘后 | 归档口径退化到 KPL 末值 |
| 补充 | akshare | 交易日历、list_date | 每日 | 无 |
| 盘后 enrich | jygs/ths/xgb | 涨停原因 4 源合并 | 15:20 前 | 原因退化为 kpl 单源 |

**KPL 已知缺失场景与对策**：

- Token 过期/认证失败 → 自动抓包刷新；刷新失败则当日结构化数据缺失，行情照常
- 非交易时段 `BaceFaceList` 返回空 → 需传 `Date=交易日期`；历史回补走 apphis
- 板块量比/机构增仓仅 Socket → 缺省降级（规则 9）
- 子板块成分股走 Socket → 盘中子板块成分可能不全，行情用腾讯补
- 接口偶发 `errcode=0 但 List=[]` → 重试 N 次后降级

**涨停检测规则（独立于 KPL，腾讯行情 + 规则推导）**：

- 优先用腾讯返回的**涨停价字段**比对现价（容差 ±0.01 元）
- 规则推导兜底（涨停价字段为 0 / 新股时）：`涨停价 = round(昨收 × (1+limit) × 100) / 100`
- 阈值按板块与 ST 状态：

| 板块 | 代码前缀 | 普通 | ST |
|---|---|---|---|
| 主板 | 60 / 00 | 10% | 5% |
| 创业板 | 30 | 20% | 20% |
| 科创板 | 68 | 20% | 20% |
| 北交所 | 8 / 4 / 92 | 30% | 30% |
| 新股（名称含 N / 上市 ≤5 日） | — | 首日无限制，不判涨停 | — |

- 固定 9.8% 阈值仅作预筛——低价股涨停价四舍五入后涨幅可能 <9.8%，固定阈值会漏检
- 检测结果与 KPL 涨停池交叉验证：KPL 有而腾讯无 = 疑似炸板；腾讯有而 KPL 无 = KPL 缺失，写入 `detected_by`

## 12. 策略引擎与日K/实时数据结合

**三层时间轴**：

```text
历史：kline/（前复权日K）→ 盘后算一次指标 MA/RSI14/箱体/量能梯度/背驰（盘中不变，昨日定格）
当日：intraday/（腾讯实时价/量比/涨幅）→ 当日K线最后一根（盘中每 3s 刷新）
定版：facts/<d>/（收盘归档）→ kline 追加当日末根
```

**kline 文件结构**（`data/kline/<stock_id>.json`，策略公式输入，须含 OHLCV）：

```json
{
  "stock_id": "SH600000", "adjusted": "qfq",
  "bars": [
    { "d": "2026-08-14", "o": 10.20, "h": 10.50, "l": 10.10, "c": 10.45, "v": 123456789, "amt": 1287654321 }
  ]
}
```

- 字段：`d` 日期、`o/h/l/c` 开盘/最高/最低/收盘（前复权）、`v` 成交量（股）、`amt` 成交额（元）
- 兼容通达信 vipdoc `.day` 原始二进制（32 字节/根：date/o/h/l/c/amt/v/reserved），同步时解析转 JSON
- 策略公式（如 §9 金量买入 BUYA）直接消费该结构，无需再读 TDX

**执行**（策略定义与参数见 `docs/STRATEGY_MODEL.md`，配置外置 `config/strategy.json` 可编辑）：

- **盘后 15:10**：`strategy_engine.py` 同步 kline（TDX vipdoc 前复权）→ 17 模型全量扫描 → `facts/<d>/strategy.json`（`run_id` 含策略配置版本）
- **叠加确认层**：模型命中（基础层）∧ 板块强度 ≥4000 ∧ 板块主力净流入>0/排名前N（`money_flow.json`）∧ 板块有领涨原因（`leading_reason.json`）→ 四维共振 4 星置顶（`confirm` + `stars`，见 `docs/STRATEGY_MODEL.md` §8）；权重/阈值在 `config/strategy.json` 的 `stacking` 可编辑
- **盘中（3s/30s）**：模型条件拆两半——
  - 历史条件（昨日定格）：MA、RSI14、箱体、量能梯度、均线排列
  - 当日实时条件（腾讯代入）：现价突破（vs 箱顶/前20日高点）、当日量比、当日涨幅
  - 命中 → 写 `events(signal_hit, source=tdx_model)` → `alert` 池置顶（`model_hit` + `priority: high`）
- **示例**：②横盘突破盘中触发 = 昨日箱体(定格) ∧ 现价＞箱顶(实时) ∧ 量比≥1.2(实时)
- **配置热更**：改 `config/strategy.json` → 重跑盘后扫描；历史 run 仍引用旧配置，可回测对比
- **回测**：kline 历史 + 预警记录 + 后续 N 日收益（见 §11.3）

## 13. 存储与 Web 发布（页面加载性能）

**实测基线**（2026-08-14）：`kpl_<date>_stocks.json` 6.4MB（gzip 后 1.4MB，省 78%）、`limitup_multi` 100KB（gzip 后 21.5KB，省 78%）。

结论：把 facts 全字段 JSON 直接铺给前端不可行（单日 7MB+、11+ 个请求）。方案 = **存储分层：事实源与 Web 视图层分离**。

### 13.1 三层存储

| 层 | 位置 | 内容 | 用途 |
|---|---|---|---|
| 事实源 | `data/{normalized,facts,kline,intraday}` | 规范化 JSON（保留全字段） | 分析/回测/Agent，**不进前端** |
| **Web 视图层** | `data/web/` | 每日聚合+裁剪+预排序 JSON（派生数据） | nginx 静态直出，页面唯一数据源 |
| 查询后端 | `data/db/market.db` SQLite（V0.2 可选） | 跨日期/复杂查询 | `/DSH/api/`、回测 |

### 13.2 Web 视图层结构

```text
data/web/
├── index.json               # 日期清单 + 每日摘要（首屏，<5KB）
├── day_latest.json          # 当日聚合视图（今日别名）
├── day_20260814.json        # 历史日聚合视图
├── day_20260814.detail.json # 详情懒加载（涨停原因原文等长文本）
└── 所有 .json 的 .gz         # 归档时 gzip 预压缩（nginx gzip_static 直出）
```

`day_*.json` 聚合规则（15:20 归档时生成）：
- **字段裁剪**：quotes 63 字段裁到 ~12（价格/涨跌/量比/换手/市值/主力净额）；涨停原因 `detail` 长文移入 `.detail.json`（弹窗按需）
- **预排序**：板块按强度/资金流降序、涨停按连板+评分降序——前端零排序直接渲染
- **预计算**：四维共振星级/confirm、买点分、止损位归档时算好，页面不重算
- **题材冻结**：`theme_limitup` 保存题材→当日涨停股，`theme_concept_limitup` 保存主概念/细分概念→当日涨停股；随 15:20 日视图归档后不可变，历史日期只读取该日口径
- 表格列用数组/精简对象，避免冗余嵌套

### 13.3 HTTP 传输与缓存（nginx）

```nginx
gzip_static on;                              # 直接吐预压缩 .gz，免动态压缩
gzip_types application/json application/javascript text/css;

# 历史日文件不可变 → 永久缓存，切换历史日期 0 网络请求
location ~* ^/DSH/data/web/day_\d{8}\.json(\.gz)?$ {
    alias C:/nginx/html/DSH/data/web/;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
location = /DSH/data/web/index.json {
    add_header Cache-Control "public, max-age=300";   # 日期清单 5 分钟
}
location = /DSH/data/web/day_latest.json {
    add_header Cache-Control "no-cache";              # 当日实时校验（ETag）
}
```

缓存策略：历史 `day_*` → `immutable` 一年；当日 → `no-cache`；`index.json` → 5 分钟；`apps/web` 静态资源（app.js/css）→ `immutable`。

### 13.4 前端加载策略

1. **首屏**：只请求 `index.json` + `day_latest.json`（当日聚合）——1~2 个请求
2. **历史日期**：`day_<date>.json`——命中 immutable 缓存，0 网络请求
3. **IndexedDB 本地缓存**：已访问日期写本地库，离线可看、切换更快
4. **详情懒加载**：涨停原因原文弹窗时按需拉 `day_<date>.detail.json`
5. **实时轮询**：用户打开“今日实时”后轮询 `/DSH/api/intraday/latest`（当前快照 + 同日涨停池/模型命中/事件摘要，~10-30KB），竞价/开盘 3s、其余交易阶段 30s；盘中不加载全量 intraday NDJSON
6. **双态隔离**：实时题材/概念涨停数仅在浏览器内存中按当前涨停池重算，不写回 `day_<date>.json`；关闭实时开关后恢复用户此前选择的历史归档日

### 13.5 数据量对比（单日）

| 方案 | 传输量 | 请求数 |
|---|---|---|
| 现状（facts 直出） | ~7MB | 11+ |
| 视图层 + gzip + 缓存 | 首屏 ~50KB，历史 0 | 2 |

## 11. 预警池与通达信联动

### 11.1 单票联动

- 通达信：`http://www.treeid/code_<6位代码>` 或 `treeid://`（用主数据 `treeid` 字段）
- 同花顺：`hexin://`，失败降级网页链接

### 11.2 批量联动（预警池 → 通达信自定义板块）

- 生成通达信自定义板块文件（`.blk`），每行 `代码|名称|市场`（市场：0=深圳、1=上海；北交按目标通达信版本格式）
- 两种交付：
  1. **服务器定时写入**：开盘前把 `alert` / `candidate` / `limitup` 池写入通达信安装目录 `T0002\blocknew\`，开盘即可在通达信"自定义板块"查看
  2. **前端下载**：提供当日 `.blk` 文件下载，手动导入
- 归档：`pool.json` 保留当日成员，`.blk` 可由 pool.json 随时再生成（历史可还原）
- 部署时以目标通达信版本实测 blocknew 目录与格式（不同版本有差异）

### 11.3 历史可查与回测闭环

- 查询：`/api/pools?date=`（当日各池）、`/api/pools?stock=`（个股所有历史进出）、`/api/events?type=`（按事件类型）
- 回测：预警池记录 + 后续 N 日收益（复用 TDX/腾讯历史行情）→ 命中率/收益统计 → 迭代 `score_breakdown` 权重
