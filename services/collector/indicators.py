# -*- coding: utf-8 -*-
"""技术指标纯函数库（V0.3 任务 1）

输入统一为裸序列（list[float]）或 bars（[{d,o,h,l,c,v,amt}]）；无状态、无第三方依赖。
策略口径依据 `docs/STRATEGY_MODEL.md` §2（17 模型触发条件）与 §1（复权/涨跌停规则）。
"""
import math


def ma(arr, n, i):
    """第 i 根的 n 日均值；窗口不足返回 None。"""
    lo = i - n + 1
    if lo < 0:
        return None
    return sum(arr[lo:i + 1]) / n


def ema_series(arr, n):
    """EMA 序列（首值初始化）。"""
    if not arr:
        return []
    k = 2.0 / (n + 1)
    out = [arr[0]]
    for x in arr[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi_series(closes, n=14):
    """RSI（Wilder 平滑）。"""
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gain = loss = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gain += d
        else:
            loss -= d
    avg_g, avg_l = gain / n, loss / n
    out[n] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d >= 0 else 0.0
        l = -d if d < 0 else 0.0
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        out[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def macd_series(closes, fast=12, slow=26, signal=9):
    """(DIFF, DEA) 序列；不足 slow 前为 None。"""
    if len(closes) < slow:
        return [None] * len(closes), [None] * len(closes)
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    diff = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    # DEA = EMA(DIFF, signal)，起点取第一个有效 DIFF
    dea = [None] * len(closes)
    start = slow - 1
    dea[start] = diff[start]
    k = 2.0 / (signal + 1)
    for i in range(start + 1, len(closes)):
        dea[i] = diff[i] * k + dea[i - 1] * (1 - k)
    return diff, dea


def kdj_series(bars, n=9):
    """(K, D, J) 序列；bars 含 h/l/c。"""
    k, d, j = [], [], []
    k_prev = d_prev = 50.0
    for i, b in enumerate(bars):
        lo = max(0, i - n + 1)
        hh = max(b["h"] for b in bars[lo:i + 1])
        ll = min(b["l"] for b in bars[lo:i + 1])
        rsv = 50.0 if hh == ll else (b["c"] - ll) / (hh - ll) * 100.0
        k_cur = 2.0 / 3.0 * k_prev + 1.0 / 3.0 * rsv
        d_cur = 2.0 / 3.0 * d_prev + 1.0 / 3.0 * k_cur
        k.append(k_cur)
        d.append(d_cur)
        j.append(3.0 * k_cur - 2.0 * d_cur)
        k_prev, d_prev = k_cur, d_cur
    return k, d, j


def bbi(closes, i):
    """BBI = (MA3+MA6+MA12+MA24)/4。"""
    vals = [ma(closes, n, i) for n in (3, 6, 12, 24)]
    if any(v is None for v in vals):
        return None
    return sum(vals) / 4.0


def boll(closes, i, n=20, k=2.0):
    """(中轨, 上轨, 下轨)。"""
    mid = ma(closes, n, i)
    if mid is None:
        return None, None, None
    lo = i - n + 1
    seg = closes[lo:i + 1]
    std = math.sqrt(sum((x - mid) ** 2 for x in seg) / n)
    return mid, mid + k * std, mid - k * std


def lwr(closes, i, n=9):
    """LWR1 = (HHV - C)/(HHV - LLV) × 100。"""
    hh = hhv(closes, n, i)
    ll = llv(closes, n, i)
    if hh == ll:
        return 50.0
    return (hh - closes[i]) / (hh - ll) * 100.0


def hhv(arr, n, i):
    lo = max(0, i - n + 1)
    return max(arr[lo:i + 1])


def llv(arr, n, i):
    lo = max(0, i - n + 1)
    return min(arr[lo:i + 1])


def limit_pct(code):
    """按代码前缀返回涨停幅度（STRATEGY_MODEL §1 / DATA_MODEL §10）。"""
    code = str(code)
    if code.startswith(("60", "00")):
        return 0.10
    if code.startswith(("30", "68")):
        return 0.20
    return 0.30  # 北交所


def is_limit_up(bar, prev_close, code, tolerance=0.01):
    """当日是否涨停：close ≥ round(prev×(1+limit)×100)/100 − 容差。"""
    if not prev_close or prev_close <= 0:
        return False
    limit_price = round(prev_close * (1 + limit_pct(code)) * 100) / 100.0
    return bar["c"] >= limit_price - tolerance
