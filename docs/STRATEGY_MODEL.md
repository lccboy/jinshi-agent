# 金十模型池策略定义（自 TDX-Model 提炼）

> 来源：`C:\Users\Administrator\WorkBuddy\2026-07-26-12-39-03\TDX-Model.html` + `gen_tri_report.py` + `tdx_daily_run.py`
> 本文件把策略从 HTML/脚本中提炼为**结构化定义**：17 个模型、买点评分、铁律、模型族与交叉验证，
> 并给出**可编辑配置** `config/strategy.json` 的规范——策略参数不再硬编码在脚本里。

## 1. 数据口径（铁律，不可改）

- **日线**：通达信本地 `vipdoc` 日线，gbbq 权息文件**前复权**，权息缺失时回退简易复权；成交量单位=股
- **K 线截断**：历史班次按数据日期截断（`bars <= data_date`），回填不受后续行情影响
- **周/月线**：由日线重采样，量能按"日均成交量"归一（消除节假日周/月天数差异）；月取最近 3 个完整月、周取最近 3 个完整周
- **涨跌停**：主板 10% / 创业板·科创板 20%（按代码前缀）
- **相对强度 RS**：个股 20 日涨幅 − 沪指 sh000001 20 日涨幅（本地日线）
- **买入区/止损**：按模型类型取支撑（见 §4），止损不超过现价 −1.5%（`stop = min(stop, c×0.985)`）
- **股票联动**：所有代码/名称经 `http://www.treeid/code_XXXXXX` 联动通达信（原生 `<a>` 跳转，不可 preventDefault）

## 2. 模型清单（17 个）

| # | id | 名称 | 族 | 触发条件（全部满足） | 评分输入 |
|---|---|---|---|---|---|
| ① | `reversal` | 低吸反转 | reversal | 60日高点回撤≥22% ＋ 近10日振幅≤7.5% 且 10日均量≤60日均量×1.25 ＋ 今日收阳站MA5 或 长下影≥1.5倍实体 ＋ 今日量≥5日均量×0.8 | 回撤深度＋K线形态＋量能 |
| ② | `breakout` | 横盘突破 | breakout | 15~60日箱体振幅≤25% ＋ 今日收盘＞箱顶 ＋ 量≥箱体均量×1.2 ＋ 涨幅≥1.2% ＋ 收日内高位 | 箱体长度＋突破幅度＋放量倍数 |
| ③ | `weekly` | 周线堆量 | trend | 3个完整周量能逐周递增 且 第3周≥第1周×1.2 ＋ 周收盘重心上移 ＋ 站20周线 ＋ 今日跌幅＜4% | 量能梯度＋价格斜率＋趋势位置 |
| ④ | `dwm` | 日周月堆量主升共振 | trend | 日：5日均量＞10日＞20日×1.1 且 MA5＞MA10＞MA20 且 20日涨幅≥8% 且 距120日新高≤10%；周：日均量递增≥1.2×、重心上移、站20周线；月：日均量递增≥1.08×、重心上移、站10月线 | 日量梯＋周梯度＋月梯度＋主升位置 |
| ⑤ | `lowstart` | 低位启动 | reversal | 20日波动率＜7.5% ＋ 今日收盘金叉20日线 ＋ 量≥20日均量×1.35 ＋ 距60日高点回撤＜18% | 波动收敛度＋放量＋站线幅度＋位置 |
| ⑥ | `volbrk` | 突破放量 | breakout | 收盘突破近20日最高收盘 ＋ 量≥20日均量×1.5 ＋ 收盘价＞MA5＞MA20＞MA60 ＋ RS＞0（跑赢沪指） | 突破幅度＋放量倍数＋相对强度＋趋势位置 |
| ⑦ | `perfect_ten` | 十全十美 | money | 11项**全部满足**：MACD金叉＋MA5上行＋主力＞散户＋KDJ金叉＋RSI短＞长＋LWR金叉＋收盘站BBI＋MMS＞MMM＋形态过滤＋今日量能确认 | 满足条件数（最严苛，命中即核心候选） |
| ⑧ | `golden_vol` | 金量买入 | money | 4项**全部满足**：主动买盘创3日峰值（**通达信公式转化，见 §10**，纯 OHLCV 无需 L2） ＋ MA20多头排列（连续上升） ＋ BUYA＞VOL/2（净流入） ＋ 成交量＞昨日×1.2（倍量） | BUYA/TJ（公式）＋MA20斜率＋量比 |
| ⑨ | `hub_breakout` | 中枢突破 | breakout | 15~50日横盘振幅≤18% ＋ 放量突破上轨（量比≥1.5x） ＋ 收日内高位 ＋ 涨幅≥1.5% | 箱体长度＋突破幅度＋放量倍数 |
| ⑩ | `div_reversal` | 背驰反转 | reversal | 价格创近20日新低 但 MACD DIFF 未同步新低（底背驰） ＋ 下跌缩量止跌 ＋ 放量阳线反转K线 | 背驰强度＋放量倍数 |
| ⑪ | `ma_momentum` | 多头排列 | trend | MA5＞MA10＞MA20＞MA60 ＋ 站MA20 且 偏离MA60≤35% ＋ 5日均量＞20日均量 ＋ 布林中轨上方 | 均线发散度＋偏离度＋量能 |
| ⑫ | `bottom_rev` | 底部起涨 | reversal | 60日跌幅≥12% ＋ 地量确认 ＋ 底部形态（双底/V反） ＋ 放量≥2x起涨 配合实体放大反转K线 | 跌幅深度＋放量＋低位确认 |
| ⑬ | `multi_factor` | 多因共振 | trend | 均线多头＋站MA20＋放量＋MACD多头＋RSI＞50＋20日新高＋阳线，7项**至少5项** ＋ 偏离MA60≤40% | 信号数量＋放量＋站线幅度 |
| ⑭ | `sub_low` | 低吸型 | sub | 强趋势缩量回踩MA20附近后二次启动；RSI14 42~62、量能收敛、收盘站回MA5、近30日涨停基因 | 技术面＋板块强度＋子板块强度＋地位 |
| ⑮ | `sub_trend_vol` | 趋势放量型 | sub | MA20/60/120多头 且 MA60斜率向上 ＋ 量≥20日均量1.5倍 ＋ 突破前20日高点 ＋ RSI14 50~70 | 同上 |
| ⑯ | `sub_breakout` | 突破型 | sub | 20日箱体振幅≤22% ＋ 放量1.4~3.5倍突破箱顶 ＋ 收日内高位 ＋ RSI14 55~75 ＋ 活跃量价记忆 | 同上 |
| ⑰ | `sub_main` | 主升型 | sub | MA5/10/20/60全线多头且斜率向上 ＋ 价贴20日高点 ＋ 5/10日涨幅加速区 ＋ RSI14 60~82 ＋ 近15日涨停基因 | 同上 |

## 3. 模型族与交叉验证

模型族（**同族信号不叠加，跨族才加成**）：

| 族 | 模型 |
|---|---|
| `reversal` | ① ⑤ ⑩ ⑫ |
| `breakout` | ② ⑥ ⑨ |
| `trend` | ③ ④ ⑪ ⑬ |
| `money` | ⑦ ⑧ |
| `sub` | ⑭ ⑮ ⑯ ⑰ |

交叉验证对（命中即提示，`inter` 字段）：④∩②、④∩③、②×③、⑤∩①、⑥∩②、六模型全中；⑧∩②/③/⑦；⑦∩④/②/③/⑥；⑨∩②/⑧/⑬；⑪∩③/⑦/⑧；⑫∩①/⑧；⑬∩⑦/⑨/⑧。

## 4. 买点评分（入场质量，满分 109）

```
s_bias = 18×bell(bias5, -0.5%, 2.5%, -4%, 7%) + 12×bell(bias10, 0, 4.5%, -3%, 10%)   # 乖离率 30
s_chg  = 12×bell(当日涨幅, 1%, 5%, -3%, 9.8%)                                        # 当日强度 12
s_vol  = 13×bell(量比, 1.2, 2.6, 0.7, 5.0)                                            # 量能健康 13
s_risk = 止损距离 ≤3%→18 / ≤5%→12 / ≤8%→6 / 其余→1                                   # 止损距离 18
s_rr   = 20×bell(RR, 3, 18, 1.2, 40)                                                  # 风险回报比 20
s_close= 收盘位置 4（收日内高位得分）
s_fam  = 跨模型族共振 12（不同族命中叠加，同族不叠加）
```

**候选先过滤**：RR≥3 且 止损幅度≤4%。**目标价** = max(120日最高, 现价×1.08)。

支撑/止损按模型类型：

| 模型 | 买入区/止损 |
|---|---|
| ②/⑨ 突破类 | 箱顶（买入箱顶×1.001，止损箱顶×0.98） |
| ⑥ 量破 | 前20日高点 |
| ① 反转 | 10日最低（止损×0.99），买入 MA5 |
| ⑤/⑭ 低吸 | MA20（线上做多破线就撤） |
| ⑮ 趋势放量/⑯ 突破 | 前20日高点 |
| 其余趋势 | MA5/MA10 |

## 5. 铁律评分（题材热度，独立于模型）

- 来源：铁律公众号文章（`wechat_article_*.md`，解析出代码/名称/评分/等级/题材热点），六维度评级 A/B+/B
- `MIN_IRON = 60`：铁律分低于 60 的概念组丢弃
- **精选概念TOP** = 铁律评分 ∩ 模型池命中，按铁律分降序（A>B+>B）
- **精选板块TOP** = 最新日板块强度 > 4000 ∩ 模型池命中，按强度降序（归一化：4000→40，25000→100，与铁律分可比），地位=当日板块内排名（龙一/龙二…）
- 铁律分高 ≠ 买点分高：铁律反映题材热度，买点分反映入场时机，两者结合择时最佳

## 6. 可编辑策略配置（`config/strategy.json`）

策略参数**全部外置**，改配置即重跑盘后扫描，无需改代码：

```json
{
  "version": "1.0",
  "data": { "vipdoc": "C:\\new_tdx\\vipdoc", "gbbq": true, "rs_index": "sh000001" },
  "models": {
    "breakout": {
      "enabled": true, "family": "breakout",
      "params": { "box_days_min": 15, "box_days_max": 60, "box_amp_max": 25, "vol_mult": 1.2, "min_chg": 1.2, "close_high": true },
      "score_weights": { "box_length": 0.4, "break_pct": 0.3, "vol_mult": 0.3 },
      "alert": { "priority": 1, "intraday_check": true },
      "confirm": { "sector_strength": false, "money_flow": false, "leading_reason": false }
    },
    "perfect_ten": {
      "enabled": true, "family": "money",
      "params": { "min_conditions": 11 },
      "confirm": { "money_flow": false }
    },
    "golden_vol": {
      "enabled": true, "family": "money",
      "params": { "window": 3, "vol_mult": 1.2, "ma20_up": true, "net_in": true },
      "confirm": { "money_flow": false }
    }
  },
  "stacking": {
    "enabled": true,
    "weights": { "sector_strength": 25, "money_flow": 25, "leading_reason": 20 },
    "thresholds": { "sector_strength_min": 4000, "money_flow_rank_top": 30, "leading_reason_min_zt": 2 },
    "stars": { "silver": 3, "gold": 4 }
  },
  "buy_point": {
    "filter": { "min_rr": 3.0, "max_stop_pct": 4 },
    "weights": { "bias": 30, "chg": 12, "vol": 13, "stop_dist": 18, "rr": 20, "close_pos": 4, "cross_family": 12 },
    "bell_ranges": { "bias5": [-0.005, 0.025, -0.04, 0.07], "bias10": [0, 0.045, -0.03, 0.10], "chg": [0.01, 0.05, -0.03, 0.098], "vol": [1.2, 2.6, 0.7, 5.0], "rr": [3, 18, 1.2, 40] }
  },
  "iron_law": { "enabled": true, "min_score": 60, "source": "wechat_article_*.md", "tiers": ["A", "B+", "B"] },
  "kpl_intersect": { "board_strength_min": 4000, "top_n": 20 },
  "alert_pool": { "top_n": 20, "model_hit_first": true, "min_score": 60 }
}
```

- `models.<id>.enabled`：启停单个模型；`params` 全部阈值可调；`score_weights` 评分权重
- `buy_point.weights`/`bell_ranges`：买点评分权重与钟形区间
- `alert_pool.model_hit_first`：**盘中预警池中模型命中票置顶**（"重点突出我的模型策略选出来"）
- 配置变更后：`strategy_engine.py --config config/strategy.json` 重跑盘后扫描，历史 run_id 仍引用旧配置（可回测对比）

## 7. 盘中实时命中机制（日K定格 + 实时代入）

模型条件拆两半：

- **历史条件（昨日收盘定格，盘中不变）**：MA、RSI14、箱体、量能梯度、背驰、均线排列——盘后由日K计算一次
- **当日实时条件（盘中每 3s 刷新）**：现价突破（vs 箱顶/前20日高点）、当日量比、当日涨幅——腾讯行情代入

示例（②横盘突破盘中触发）：昨日箱体(定格) ∧ 现价＞箱顶(实时) ∧ 量比≥1.2(实时) → 写 `events(signal_hit, source=tdx_model)` → 预警池置顶

执行时间轴：

```
15:10 盘后  kline 同步(TDX vipdoc 前复权) → 全量扫描 17 模型 → facts/<d>/strategy.json
09:15-15:00 盘中  昨日定格指标 + 腾讯实时 → 模型盘中触发检测 → events + alert 池
```

## 8. 叠加确认层（四维共振）

技术面模型命中是**基础层（必要条件）**；叠加三个确认维度给候选排序/定星级，不改 17 模型的纯技术口径：

| 维度 | 数据源 | 判定 | 默认权重 |
|---|---|---|---|
| T 模型命中 | kline + 17 模型 | 命中模型数/评分（**基础层，必要条件**） | — |
| S 板块强度 | KPL `sectors.json` | 板块强度 ≥ 4000（归一化 4000→40，25000→100） | 25 |
| F 资金流入 | 东财板块资金流 `money_flow.json` | 板块主力净流入 > 0 且排名前 N；分钟资金流持续净流入加分 | 25 |
| R 领涨原因 | 选股宝 `leading_reason.json` | 板块有明确领涨原因 description 且涨停数 ≥ 阈值 | 20 |

**星级与预警**：

- 3 星 = T ∧（S∨F∨R 中任 2 个）
- **4 星 = T ∧ S ∧ F ∧ R** → 预警池 `priority: high` 置顶
- 总评分 = 模型分 + S + F + R（权重可编辑），`score_breakdown` 记录各维贡献

**板块精选升级**：精选板块 = 强度>4000 ∧ 主力净流入>0 ∧ 有领涨原因（原仅有强度条件）。

**17 模型优化点**：

- ⑦十全十美：11 项全满足 → `min_conditions` 可配置（默认 11，可降 10，避免信号过稀缺）
- ⑧金量买入：已按通达信选股公式转化（§10）——主动买盘 BUYA 由 OHLCV 精确估算，**不需要 L2 数据，不降级**；参考实现 `services/collector/models/golden_vol.py`
- ①低吸反转：可挂 confirm（回踩期板块资金流出收敛），默认关
- ②⑥⑨⑯ 突破类：可挂 confirm（板块强度>4000 / 板块主力净流入>0），默认关
- 所有 confirm 均为**可编辑开关**，不改模型主体条件

## 9. 通达信公式转化（⑧金量买入）

**原公式（用户提供，口径不可改）**：

```text
AA:=VOL/((HIGH-LOW)*2-ABS(CLOSE-OPEN));
BUYA:=IF(CLOSE>OPEN,AA*(HIGH-LOW),IF(CLOSE,AA*((HIGH-OPEN)+(CLOSE-LOW)),VOL/2));
TJ:=V=HHV(BUYA,3);
XG:TJ;
```

**逐行转化**：

| 公式行 | 含义 | Python 实现 |
|---|---|---|
| `AA = VOL/((H-L)*2-ABS(C-O))` | 主动买盘估算系数（量/振幅口径） | `span=(h-l)*2-abs(c-o); aa=v/span`（span≤0 取 v 防除零） |
| `BUYA` 阳线分支 `IF(C>O, AA*(H-L), …)` | 阳线主动买盘 | `aa*(h-l)` |
| `BUYA` 阴线/平分支 `IF(CLOSE, …)` | 阴线主动买盘（TDX 中数值非 0 即真） | `aa*((h-o)+(c-l))`；`c==0`（停牌）→ `v/2` |
| `TJ = V = HHV(BUYA,3)` | 今日成交量精确等于近 3 日 BUYA 最高值（创 3 日峰值） | `vols[i] == max(buya[i-2:i+1])`（TDX 精确相等语义） |

**完整 ⑧ 判定**（4 项全部满足，`require_*` 可配置）：

1. `TJ` —— 主动买盘创 3 日峰值（本公式）
2. MA20 连续上升（`MA20[今日] > MA20[昨日]`）
3. 净流入：`BUYA > VOL/2`（因 `VOL = BUYA + 主动卖盘`）
4. 倍量：`VOL > 昨日VOL × 1.2`

**关键点**：公式只用 **OHLCV**（前复权日K，`data/kline/` 即 TDX vipdoc 同步），**不需要 L2 主动买卖盘数据 → 不降级**。

参考实现：`services/collector/models/golden_vol.py`（`golden_vol_hit(opens, highs, lows, closes, vols)` 返回命中与四项条件明细，自检通过）。

口径要求：输入 K 线必须与通达信显示一致的前复权（gbbq），量纲=股；`V=HHV(BUYA,3)` 为精确相等比较，勿加容差。

## 10. 部署映射

| 原实现 | 新落点 |
|---|---|
| `tdx_daily_run.py`（17 模型 + 读 vipdoc） | `services/collector/strategy_engine.py`（读 `data/kline/` + `config/strategy.json`） |
| `gen_tri_report.py`（买点评分 + 铁律 + 交叉） | `strategy_engine.py` 评分模块 + `facts/<d>/strategy.json` |
| 硬编码阈值/权重 | `config/strategy.json`（可编辑） |
| `TDX-Model.html` 报告 | V0.1b 策略模型视图 + V0.3 预警池（模型命中置顶） |
