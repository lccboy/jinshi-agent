# -*- coding: utf-8 -*-
"""17 模型条件与评分（V0.3 任务 2）

每个模型 `(bars, ctx) -> (hit, score, detail)`：
- bars: [{d,o,h,l,c,v,amt}]（前复权日K，升序）
- ctx: 可选注入 {code, rs20(跑赢沪指), min_conditions(⑦), ...}
口径依据 `docs/STRATEGY_MODEL.md` §2；⑧金量买入复用 `models/golden_vol.py`（公式口径不可改）。
"""

import datetime
import math

from .indicators import bbi, boll, hhv, is_limit_up, kdj_series, llv, lwr, ma, macd_series, rsi_series
from .models.golden_vol import golden_vol_hit


def _series(bars):
    return [b["o"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars], \
        [b["c"] for b in bars], [b["v"] for b in bars]


def _resample(bars, kind):
    """按周/月重采样 → 组列表 [(key, bars)]。"""
    groups, cur, cur_key = [], None, None
    for b in bars:
        d = datetime.date(b["d"] // 10000, (b["d"] // 100) % 100, b["d"] % 100)
        key = d.isocalendar()[:2] if kind == "week" else (d.year, d.month)
        if cur_key != key:
            cur_key, cur = key, []
            groups.append((key, cur))
        cur.append(b)
    return groups


def _avg_vol(group_bars):
    return sum(b["v"] for b in group_bars) / len(group_bars)


def _complete_weeks(bars, n=3):
    groups = _resample(bars, "week")
    complete = groups[:-1] if groups else []
    return complete[-n:]


def _complete_months(bars, n=3):
    groups = _resample(bars, "month")
    complete = groups[:-1] if groups else []
    return complete[-n:]


def _bounded(x, lo, hi, hard_lo=None, hard_hi=None):
    hard_lo = lo if hard_lo is None else hard_lo
    hard_hi = hi if hard_hi is None else hard_hi
    if x < hard_lo or x > hard_hi:
        return 0.0
    if lo <= x <= hi:
        return 1.0
    if x < lo:
        return (x - hard_lo) / (lo - hard_lo)
    return (hard_hi - x) / (hard_hi - hi)


def _limit_genes(bars, code, days=30):
    """近 days 日内是否出现过涨停（含今日）。"""
    for i in range(max(1, len(bars) - days), len(bars)):
        prev = bars[i - 1]["c"]
        if prev > 0 and is_limit_up(bars[i], prev, code):
            return True
    return False


# ---------------- ①~⑰ ----------------

def m_reversal(bars, ctx):
    """① 低吸反转：超跌 + 缩量企稳 + 反转K线。"""
    _, highs, lows, closes, vols = _series(bars)
    n, c, o = len(closes), closes[-1], bars[-1]["o"]
    ret60 = c / hhv(highs, 60, n - 1) - 1 if n >= 60 else 0
    if ret60 > -0.22:
        return False, 0, {"reason": "60日回撤不足"}
    amp10 = sum((highs[i] - lows[i]) / closes[i] for i in range(n - 10, n)) / 10
    if amp10 > 0.075:
        return False, 0, {"reason": "10日振幅过大"}
    ma10v, ma60v = ma(vols, 10, n - 1), ma(vols, 60, n - 1)
    if ma10v is None or ma60v is None or ma10v > ma60v * 1.25:
        return False, 0, {"reason": "量能未收敛"}
    ma5 = ma(closes, 5, n - 1)
    body = abs(c - o)
    bull = (c > o and ma5 is not None and c >= ma5) or (min(o, c) - bars[-1]["l"] >= 1.5 * body)
    if not bull:
        return False, 0, {"reason": "无反转K线"}
    if vols[-1] < ma(vols, 5, n - 1) * 0.8:
        return False, 0, {"reason": "量能不足"}
    score = _bounded(-ret60, 0.22, 0.40) * 40 + (30 if c > o else 15) + _bounded(vols[-1] / ma(vols, 5, n - 1), 1.0, 2.0) * 30
    return True, round(score, 1), {"ret60": round(ret60 * 100, 1), "amp10": round(amp10 * 100, 1)}


def _longest_box(bars, lo_days, hi_days):
    """最长满足振幅≤25% 的箱体（不含当日）→ (箱顶, 箱底, 天数, 均量) 或 None。"""
    n = len(bars)
    best = None
    for days in range(hi_days, lo_days - 1, -1):
        if n < days + 1:
            continue
        seg = bars[n - days - 1:n - 1]  # 截至昨日，排除当日突破
        top = max(b["h"] for b in seg)
        bottom = min(b["l"] for b in seg)
        if bottom > 0 and (top - bottom) / bottom <= 0.25:
            best = (top, bottom, days, sum(b["v"] for b in seg) / days)
            break
    return best


def m_breakout(bars, ctx):
    """② 横盘突破：箱体上沿放量突破。"""
    box = _longest_box(bars, 15, 60)
    if not box:
        return False, 0, {"reason": "无 15~60 日箱体"}
    top, bottom, days, avg_v = box
    _, highs, _, closes, vols = _series(bars)
    c, prev_c = closes[-1], closes[-2]
    if c <= top:
        return False, 0, {"reason": "未突破箱顶"}
    if vols[-1] < avg_v * 1.2:
        return False, 0, {"reason": "放量不足"}
    if c / prev_c - 1 < 0.012:
        return False, 0, {"reason": "涨幅不足"}
    h, l = highs[-1], bars[-1]["l"]
    if h > l and (h - c) / (h - l) > 0.3:
        return False, 0, {"reason": "未收日内高位"}
    brk = (c / top - 1) * 100
    score = _bounded(days, 15, 50) * 30 + _bounded(brk, 1, 8) * 35 + _bounded(vols[-1] / avg_v, 1.2, 3.0) * 35
    return True, round(score, 1), {"days": days, "brk_pct": round(brk, 2), "vol_mult": round(vols[-1] / avg_v, 2)}


def m_weekly(bars, ctx):
    """③ 周线堆量：3 个完整周量能递增 + 重心上移。"""
    weeks = _complete_weeks(bars, 3)
    if len(weeks) < 3:
        return False, 0, {"reason": "不足 3 个完整周"}
    vols_w = [_avg_vol(g) for _, g in weeks]
    closes_w = [sum(b["c"] for b in g) / len(g) for _, g in weeks]
    if not (vols_w[1] > vols_w[0] and vols_w[2] >= vols_w[0] * 1.2):
        return False, 0, {"reason": "周量能未递增"}
    if not (closes_w[1] > closes_w[0] and closes_w[2] > closes_w[1]):
        return False, 0, {"reason": "周重心未上移"}
    _, _, _, closes, _ = _series(bars)
    ma100 = ma(closes, 100, len(closes) - 1)
    if ma100 is None or closes[-1] < ma100:
        return False, 0, {"reason": "未站 20 周线"}
    if closes[-1] / closes[-2] - 1 < -0.04:
        return False, 0, {"reason": "今日跌幅过大"}
    grad = vols_w[2] / vols_w[0]
    score = _bounded(grad, 1.2, 2.0) * 50 + _bounded(closes[-1] / ma100 - 1, 0.0, 0.3) * 50
    return True, round(score, 1), {"grad": round(grad, 2)}


def m_dwm(bars, ctx):
    """④ 日周月堆量主升共振。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 120:
        return False, 0, {"reason": "历史不足"}
    v5, v10, v20 = ma(vols, 5, n - 1), ma(vols, 10, n - 1), ma(vols, 20, n - 1)
    m5, m10, m20 = ma(closes, 5, n - 1), ma(closes, 10, n - 1), ma(closes, 20, n - 1)
    day_ok = v5 > v10 > v20 * 1.1 and m5 > m10 > m20 and closes[-1] / closes[-21] - 1 >= 0.08 \
        and hhv(closes, 120, n - 1) / closes[-1] - 1 <= 0.10
    weeks = _complete_weeks(bars, 3)
    week_ok = len(weeks) >= 3 and _avg_vol(weeks[2][1]) >= _avg_vol(weeks[0][1]) * 1.2 \
        and sum(b["c"] for b in weeks[2][1]) / len(weeks[2][1]) > sum(b["c"] for b in weeks[1][1]) / len(weeks[1][1])
    months = _complete_months(bars, 3)
    month_ok = len(months) >= 3 and _avg_vol(months[2][1]) >= _avg_vol(months[0][1]) * 1.08 \
        and sum(b["c"] for b in months[2][1]) / len(months[2][1]) > sum(b["c"] for b in months[1][1]) / len(months[1][1])
    if not (day_ok and week_ok and month_ok):
        return False, 0, {"day": day_ok, "week": week_ok, "month": month_ok}
    score = 40 + _bounded(v5 / v20, 1.1, 2.5) * 30 + _bounded(closes[-1] / closes[-21] - 1, 0.08, 0.3) * 30
    return True, round(score, 1), {"v5/v20": round(v5 / v20, 2), "ret20": round((closes[-1] / closes[-21] - 1) * 100, 1)}


def m_lowstart(bars, ctx):
    """⑤ 低位启动：低波动 + 金叉 MA20 + 放量。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 21:
        return False, 0, {"reason": "历史不足"}
    rets = [closes[i] / closes[i - 1] - 1 for i in range(n - 20, n)]
    vol20 = sum(x * x for x in rets) / 20
    if math.sqrt(vol20) > 0.075:
        return False, 0, {"reason": "波动率过大"}
    ma20 = ma(closes, 20, n - 1)
    ma20_prev = ma(closes, 20, n - 2)
    if ma20 is None or ma20_prev is None or not (closes[-1] > ma20 and closes[-2] <= ma20_prev):
        return False, 0, {"reason": "未金叉 MA20"}
    if vols[-1] < ma(vols, 20, n - 1) * 1.35:
        return False, 0, {"reason": "放量不足"}
    if hhv(closes, 60, n - 1) and closes[-1] / hhv(closes, 60, n - 1) - 1 < -0.18:
        return False, 0, {"reason": "深跌"}
    score = _bounded(math.sqrt(vol20), 0.0, 0.075) * 40 + _bounded(vols[-1] / ma(vols, 20, n - 1), 1.35, 3.0) * 60
    return True, round(score, 1), {"vol20": round(math.sqrt(vol20) * 100, 2)}


def m_volbrk(bars, ctx):
    """⑥ 突破放量：20 日新高 + 多头排列 + 跑赢沪指。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 61:
        return False, 0, {"reason": "历史不足"}
    c = closes[-1]
    if c <= hhv(closes, 20, n - 2):
        return False, 0, {"reason": "未创 20 日新高"}
    if vols[-1] < ma(vols, 20, n - 1) * 1.5:
        return False, 0, {"reason": "放量不足"}
    m5, m20, m60 = ma(closes, 5, n - 1), ma(closes, 20, n - 1), ma(closes, 60, n - 1)
    if not (m5 and m20 and m60 and c > m5 > m20 > m60):
        return False, 0, {"reason": "非多头排列"}
    if ctx.get("rs20", 1) <= 0:
        return False, 0, {"reason": "未跑赢沪指"}
    brk = (c / hhv(closes, 20, n - 2) - 1) * 100
    score = _bounded(brk, 0, 10) * 40 + _bounded(vols[-1] / ma(vols, 20, n - 1), 1.5, 4.0) * 60
    return True, round(score, 1), {"brk20": round(brk, 2), "rs20": round(ctx.get("rs20", 0), 2)}


def m_perfect_ten(bars, ctx):
    """⑦ 十全十美：已定义条件计数（MACD金叉/MA5上行/KDJ金叉/RSI短>长/站BBI/量能确认/形态过滤）。"""
    _, highs, lows, closes, vols = _series(bars)
    n = len(closes)
    if n < 30:
        return False, 0, {"reason": "历史不足"}
    diff, dea = macd_series(closes)
    k, d, _ = kdj_series(bars)
    rsi6, rsi12 = rsi_series(closes, 6)[-1], rsi_series(closes, 12)[-1]
    m5, m5_prev = ma(closes, 5, n - 1), ma(closes, 5, n - 2)
    conds = {
        "macd_gold": diff[-1] > dea[-1],
        "ma5_up": m5 is not None and m5_prev is not None and m5 > m5_prev,
        "kdj_gold": k[-1] > d[-1],
        "rsi_short_long": rsi6 is not None and rsi12 is not None and rsi6 > rsi12,
        "close_bbi": bbi(closes, n - 1) is not None and closes[-1] > bbi(closes, n - 1),
        "vol_confirm": vols[-1] > ma(vols, 5, n - 1),
        "no_chase": (highs[-1] - lows[-1]) > 0 and (highs[-1] - closes[-1]) / (highs[-1] - lows[-1]) < 0.3,
    }
    satisfied = sum(1 for v in conds.values() if v)
    need = ctx.get("min_conditions", 7)  # 11 需 MMS/MMM/主力 数据补全后调回
    if satisfied < need:
        return False, 0, {"satisfied": satisfied, "need": need, "conds": conds}
    return True, round(50 + satisfied * 5, 1), {"satisfied": satisfied, "need": need}


def m_golden_vol(bars, ctx):
    """⑧ 金量买入：通达信公式转化（口径不可改，见 STRATEGY_MODEL §9）。
    参数 window/vol_mult 从 ctx 读取（由 strategy_engine 注入 config 值），缺省回落默认值。"""
    o, h, l, c, v = _series(bars)
    if len(c) < 21:
        return False, 0, {"reason": "历史不足"}
    window = ctx.get("window", 3)
    vol_mult = ctx.get("vol_mult", 1.2)
    hit, d = golden_vol_hit(o, h, l, c, v, window=window, vol_mult=vol_mult)
    if not hit:
        return False, 0, d
    score = 40 + (20 if d["ma20_up"] else 0) + (20 if d["net_in"] else 0) + (20 if d["vol_mult_ok"] else 0)
    return True, score, {k: d[k] for k in ("tj", "ma20_up", "net_in", "vol_mult_ok")}


def m_hub_breakout(bars, ctx):
    """⑨ 中枢突破：窄幅横盘 + 放量突破上轨。"""
    n = len(bars)
    if n < 51:
        return False, 0, {"reason": "历史不足"}
    box = None
    for days in range(50, 14, -1):
        seg = bars[n - days - 1:n - 1]  # 不含当日
        top = max(b["h"] for b in seg)
        bottom = min(b["l"] for b in seg)
        if bottom > 0 and (top - bottom) / bottom <= 0.18:
            box = (top, bottom, days, sum(b["v"] for b in seg) / days)
            break
    if not box:
        return False, 0, {"reason": "无窄幅中枢"}
    top, bottom, days, avg_v = box
    _, highs, _, closes, vols = _series(bars)
    c, prev_c = closes[-1], closes[-2]
    if c <= top or vols[-1] / avg_v < 1.5 or c / prev_c - 1 < 0.015:
        return False, 0, {"reason": "未放量突破上轨"}
    h, l = highs[-1], bars[-1]["l"]
    if h > l and (h - c) / (h - l) > 0.3:
        return False, 0, {"reason": "未收高位"}
    score = _bounded(days, 15, 50) * 30 + _bounded((c / top - 1) * 100, 1.5, 8) * 35 + _bounded(vols[-1] / avg_v, 1.5, 3.5) * 35
    return True, round(score, 1), {"days": days, "brk_pct": round((c / top - 1) * 100, 2)}


def m_div_reversal(bars, ctx):
    """⑩ 背驰反转：价格新低 + MACD 底背驰 + 放量阳线。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 30:
        return False, 0, {"reason": "历史不足"}
    c = closes[-1]
    if c >= llv(closes, 20, n - 2):
        return False, 0, {"reason": "未创新低"}
    diff, _ = macd_series(closes)
    if diff[-1] <= llv([x for x in diff[10:-1] if x is not None], 20, len([x for x in diff[10:-1] if x is not None]) - 1):
        return False, 0, {"reason": "DIFF 同步新低"}
    if vols[-1] > ma(vols, 10, n - 1):
        return False, 0, {"reason": "未缩量止跌"}
    if not (bars[-1]["c"] > bars[-1]["o"] and vols[-1] > vols[-2] * 1.2):
        return False, 0, {"reason": "无放量阳线"}
    score = 50 + _bounded(vols[-1] / vols[-2], 1.2, 3.0) * 50
    return True, round(score, 1), {}


def m_ma_momentum(bars, ctx):
    """⑪ 多头排列：均线多头 + 量能扩张 + 布林中轨上方。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 61:
        return False, 0, {"reason": "历史不足"}
    m5, m10, m20, m60 = (ma(closes, p, n - 1) for p in (5, 10, 20, 60))
    c = closes[-1]
    if not (m5 and m10 and m20 and m60 and m5 > m10 > m20 > m60 and c > m20):
        return False, 0, {"reason": "非多头排列"}
    if c / m60 - 1 > 0.35:
        return False, 0, {"reason": "过度偏离 MA60"}
    if ma(vols, 5, n - 1) <= ma(vols, 20, n - 1):
        return False, 0, {"reason": "量能未扩张"}
    mid, _, _ = boll(closes, n - 1)
    if mid is None or c <= mid:
        return False, 0, {"reason": "布林下轨下方"}
    score = _bounded(c / m60 - 1, 0.05, 0.35) * 50 + _bounded(ma(vols, 5, n - 1) / ma(vols, 20, n - 1), 1.0, 2.0) * 50
    return True, round(score, 1), {"dev_ma60": round((c / m60 - 1) * 100, 1)}


def m_bottom_rev(bars, ctx):
    """⑫ 底部起涨：60 日跌幅 + 地量 + 放量起涨。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 61:
        return False, 0, {"reason": "历史不足"}
    c = closes[-1]
    if c / hhv(closes, 60, n - 1) - 1 > -0.12:
        return False, 0, {"reason": "跌幅不足 12%"}
    if vols[-1] > llv(vols, 20, n - 1) * 1.5:
        return False, 0, {"reason": "非地量区"}
    if not (bars[-1]["c"] > bars[-1]["o"] and vols[-1] >= ma(vols, 20, n - 1) * 2.0 and c > ma(closes, 5, n - 1)):
        return False, 0, {"reason": "无放量起涨"}
    score = _bounded(-(c / hhv(closes, 60, n - 1) - 1), 0.12, 0.4) * 50 + _bounded(vols[-1] / ma(vols, 20, n - 1), 2.0, 5.0) * 50
    return True, round(score, 1), {"ret60": round((c / hhv(closes, 60, n - 1) - 1) * 100, 1)}


def m_multi_factor(bars, ctx):
    """⑬ 多因共振：7 项至少 5 项。"""
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    if n < 61:
        return False, 0, {"reason": "历史不足"}
    m5, m10, m20, m60 = (ma(closes, p, n - 1) for p in (5, 10, 20, 60))
    diff, dea = macd_series(closes)
    rsi = rsi_series(closes, 14)[-1]
    c = closes[-1]
    conds = {
        "ma_bull": m5 > m10 > m20,
        "above_ma20": c > m20,
        "vol_up": vols[-1] > ma(vols, 5, n - 1),
        "macd_bull": diff[-1] > dea[-1],
        "rsi_gt50": rsi is not None and rsi > 50,
        "new_high20": c >= hhv(closes, 20, n - 1),
        "yang": bars[-1]["c"] > bars[-1]["o"],
    }
    satisfied = sum(1 for v in conds.values() if v)
    if satisfied < 5:
        return False, 0, {"satisfied": satisfied}
    if c / m60 - 1 > 0.40:
        return False, 0, {"reason": "过度偏离 MA60"}
    score = satisfied * 10 + _bounded(c / m20 - 1, 0, 0.2) * 30
    return True, round(score, 1), {"satisfied": satisfied}


def _trend_base(bars):
    """⑭⑮⑰ 共用的强趋势判断 → (ok, ma20, ma60 斜率上)。"""
    _, _, _, closes, _ = _series(bars)
    n = len(closes)
    if n < 121:
        return False, None, None
    m20, m60, m120 = ma(closes, 20, n - 1), ma(closes, 60, n - 1), ma(closes, 120, n - 1)
    m60_prev = ma(closes, 60, n - 2)
    ok = m20 and m60 and m120 and m60_prev and m20 > m60 > m120 and m60 > m60_prev
    return ok, m20, m60


def m_sub_low(bars, ctx):
    """⑭ 低吸型：强趋势回踩 MA20 + RSI 低位 + 涨停基因。"""
    ok, m20, _ = _trend_base(bars)
    if not ok:
        return False, 0, {"reason": "非强趋势"}
    _, _, _, closes, vols = _series(bars)
    n = len(closes)
    c = closes[-1]
    if abs(c / m20 - 1) > 0.03:
        return False, 0, {"reason": "未回踩 MA20"}
    if vols[-1] > ma(vols, 5, n - 1):
        return False, 0, {"reason": "未缩量"}
    if c <= ma(closes, 5, n - 1):
        return False, 0, {"reason": "未站回 MA5"}
    rsi = rsi_series(closes, 14)[-1]
    if rsi is None or not (42 <= rsi <= 62):
        return False, 0, {"reason": "RSI 不在 42~62"}
    if not _limit_genes(bars, ctx.get("code", ""), 30):
        return False, 0, {"reason": "近 30 日无涨停基因"}
    score = 50 + _bounded(1.0 - abs(c / m20 - 1), 0.0, 0.03) * 50
    return True, round(score, 1), {"rsi14": round(rsi, 1)}


def m_sub_trend_vol(bars, ctx):
    """⑮ 趋势放量型：多头 + 放量 1.5x + 突破 20 日高点。"""
    ok, _, _ = _trend_base(bars)
    if not ok:
        return False, 0, {"reason": "非强趋势"}
    _, highs, _, closes, vols = _series(bars)
    n = len(closes)
    if vols[-1] < ma(vols, 20, n - 1) * 1.5:
        return False, 0, {"reason": "放量不足 1.5x"}
    if closes[-1] <= hhv(highs, 20, n - 2):
        return False, 0, {"reason": "未突破 20 日高点"}
    rsi = rsi_series(closes, 14)[-1]
    if rsi is None or not (50 <= rsi <= 70):
        return False, 0, {"reason": "RSI 不在 50~70"}
    score = 50 + _bounded(vols[-1] / ma(vols, 20, n - 1), 1.5, 4.0) * 50
    return True, round(score, 1), {"rsi14": round(rsi, 1)}


def m_sub_breakout(bars, ctx):
    """⑯ 突破型：20 日箱体 + 放量 1.4~3.5x 突破。"""
    n = len(bars)
    if n < 22:
        return False, 0, {"reason": "历史不足"}
    seg = bars[n - 21:n - 1]  # 20 日箱体（不含当日）
    top = max(b["h"] for b in seg)
    bottom = min(b["l"] for b in seg)
    if bottom <= 0 or (top - bottom) / bottom > 0.22:
        return False, 0, {"reason": "箱体振幅过大"}
    _, highs, _, closes, vols = _series(bars)
    ratio = vols[-1] / ma(vols, 20, n - 1)
    c = closes[-1]
    if c <= top or not (1.4 <= ratio <= 3.5):
        return False, 0, {"reason": "未放量突破箱顶"}
    h, l = highs[-1], bars[-1]["l"]
    if h > l and (h - c) / (h - l) > 0.3:
        return False, 0, {"reason": "未收高位"}
    rsi = rsi_series(closes, 14)[-1]
    if rsi is None or not (55 <= rsi <= 75):
        return False, 0, {"reason": "RSI 不在 55~75"}
    score = _bounded(ratio, 1.4, 3.0) * 50 + _bounded((c / top - 1) * 100, 0, 8) * 50
    return True, round(score, 1), {"ratio": round(ratio, 2), "rsi14": round(rsi, 1)}


def m_sub_main(bars, ctx):
    """⑰ 主升型：全多头加速 + 贴 20 日高点 + 涨停基因。"""
    _, _, _, closes, _ = _series(bars)
    n = len(closes)
    if n < 61:
        return False, 0, {"reason": "历史不足"}
    m5, m10, m20, m60 = (ma(closes, p, n - 1) for p in (5, 10, 20, 60))
    m5_prev = ma(closes, 5, n - 2)
    c = closes[-1]
    if not (m5 and m10 and m20 and m60 and m5_prev and m5 > m10 > m20 > m60 and m5 > m5_prev):
        return False, 0, {"reason": "非全多头加速"}
    if c < hhv(closes, 20, n - 1) * 0.95:
        return False, 0, {"reason": "未贴 20 日高点"}
    ret5 = c / closes[-6] - 1 if n >= 6 else 0
    if ret5 < 0.03:
        return False, 0, {"reason": "5 日涨幅未加速"}
    rsi = rsi_series(closes, 14)[-1]
    if rsi is None or not (60 <= rsi <= 82):
        return False, 0, {"reason": "RSI 不在 60~82"}
    if not _limit_genes(bars, ctx.get("code", ""), 15):
        return False, 0, {"reason": "近 15 日无涨停基因"}
    score = _bounded(ret5, 0.03, 0.15) * 50 + _bounded(rsi, 60, 82) * 50
    return True, round(score, 1), {"ret5": round(ret5 * 100, 1), "rsi14": round(rsi, 1)}


MODELS = {
    "reversal": m_reversal, "breakout": m_breakout, "weekly": m_weekly, "dwm": m_dwm,
    "lowstart": m_lowstart, "volbrk": m_volbrk, "perfect_ten": m_perfect_ten,
    "golden_vol": m_golden_vol, "hub_breakout": m_hub_breakout, "div_reversal": m_div_reversal,
    "ma_momentum": m_ma_momentum, "bottom_rev": m_bottom_rev, "multi_factor": m_multi_factor,
    "sub_low": m_sub_low, "sub_trend_vol": m_sub_trend_vol, "sub_breakout": m_sub_breakout,
    "sub_main": m_sub_main,
}
