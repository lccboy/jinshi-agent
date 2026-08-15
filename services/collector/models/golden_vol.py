# -*- coding: utf-8 -*-
"""⑧ 金量买入 — 通达信选股公式转化实现（不降级）

原通达信公式（用户提供，勿改动口径）::

    AA:=VOL/((HIGH-LOW)*2-ABS(CLOSE-OPEN));
    BUYA:=IF(CLOSE>OPEN,AA*(HIGH-LOW),IF(CLOSE,AA*((HIGH-OPEN)+(CLOSE-LOW)),VOL/2));
    TJ:=V=HHV(BUYA,3);
    XG:TJ;

含义:
    AA   = 主动性买盘估算系数（量 / 振幅口径）
    BUYA = 当日主动性买盘估算量
           阳线(CLOSE>OPEN)      → AA*(HIGH-LOW)
           阴线/平(CLOSE<=OPEN)  → AA*((HIGH-OPEN)+(CLOSE-LOW))（TDX IF(CLOSE,..) 中 CLOSE≠0 即真）
           停牌(CLOSE==0)        → VOL/2
    TJ   = 今日成交量 V 恰好等于近 3 日 BUYA 最高值（主动买盘创 3 日峰值）

完整 ⑧ 模型判定（与 gen_tri_report 口径一致，4 项全部满足）:
    1. TJ                    —— 主动买盘创 3 日峰值（本公式）
    2. MA20 连续上升          —— 趋势保护
    3. BUYA > VOL/2           —— 主动买盘 > 主动卖盘（净流入，因 VOL = BUYA + 卖盘）
    4. VOL > 昨日VOL × 1.2    —— 倍量（市场关注度提升）

输入: 前复权日K OHLCV（与通达信显示口径一致，见 docs/DATA_MODEL.md §12 kline 底库）。
输出: 各序列 + 当日命中判定。纯 Python，无第三方依赖。

用法::

    from golden_vol import golden_vol_hit
    hit, detail = golden_vol_hit(opens, highs, lows, closes, vols)
"""

from __future__ import annotations

from typing import List, Optional


def active_buy_series(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    vols: List[float],
) -> List[float]:
    """通达信 BUYA 序列（逐根K线，长度与输入一致）。

    公式逐行对照:
        AA   = VOL / ((HIGH-LOW)*2 - ABS(CLOSE-OPEN))
        BUYA = IF(CLOSE>OPEN, AA*(HIGH-LOW),
                  IF(CLOSE, AA*((HIGH-OPEN)+(CLOSE-LOW)), VOL/2))
    """
    n = len(closes)
    buya: List[float] = []
    for i in range(n):
        span = (highs[i] - lows[i]) * 2.0 - abs(closes[i] - opens[i])
        aa = vols[i] / span if span > 0 else vols[i]
        if closes[i] > opens[i]:
            buya.append(aa * (highs[i] - lows[i]))
        elif closes[i] != 0.0:  # TDX IF(CLOSE,..) 数值非 0 即真
            buya.append(aa * ((highs[i] - opens[i]) + (closes[i] - lows[i])))
        else:  # 停牌 CLOSE==0
            buya.append(vols[i] / 2.0)
    return buya


def tj_series(buya: List[float], vols: List[float], window: int = 3) -> List[bool]:
    """TJ = V = HHV(BUYA, window)。TDX 语义为精确相等，量纲一致（股）。"""
    n = len(buya)
    tj: List[bool] = []
    for i in range(n):
        lo = max(0, i - window + 1)
        tj.append(vols[i] == max(buya[lo : i + 1]))
    return tj


def ma(series: List[float], period: int, i: int) -> Optional[float]:
    lo = i - period + 1
    if lo < 0:
        return None
    return sum(series[lo : i + 1]) / period


def golden_vol_hit(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    vols: List[float],
    window: int = 3,
    vol_mult: float = 1.2,
    require_ma20_up: bool = True,
    require_net_in: bool = True,
) -> tuple:
    """⑧ 金量买入完整判定，返回 (当日是否命中, 明细 dict)。

    明细含四项条件各自结果与 BUYA/TJ 序列，便于调试与回测。
    """
    buya = active_buy_series(opens, highs, lows, closes, vols)
    tj = tj_series(buya, vols, window)
    n = len(closes)

    ma20_now = ma(closes, 20, n - 1)
    ma20_prev = ma(closes, 20, n - 2)
    cond_ma20 = ma20_now is not None and ma20_prev is not None and ma20_now > ma20_prev

    cond_net_in = buya[-1] > vols[-1] / 2.0 if n else False

    cond_vol = n >= 2 and vols[-1] > vols[-2] * vol_mult

    hit = bool(tj[-1]) and (not require_ma20_up or cond_ma20) and (not require_net_in or cond_net_in) and cond_vol

    detail = {
        "hit": hit,
        "tj": tj[-1],
        "ma20_up": cond_ma20,
        "net_in": cond_net_in,
        "vol_mult_ok": cond_vol,
        "buya_now": buya[-1] if n else None,
        "vol_now": vols[-1] if n else None,
        "buya": buya,
        "tj_series": tj,
    }
    return hit, detail


if __name__ == "__main__":
    # 自检：构造 20 根日K，末两根为光头光脚阳线（BUYA==VOL），
    # 末根放量满足: TJ(V==HHV(BUYA,3)) ∧ MA20上行 ∧ 净流入 ∧ 倍量
    n = 21  # ≥21 根，保证 MA20 在末两根都有值
    opens = [10.0 + 0.02 * i for i in range(n)]
    closes = [10.03 + 0.02 * i for i in range(n)]
    highs = [c + 0.04 for c in closes]
    lows = [o - 0.03 for o in opens]
    vols = [100.0 + i for i in range(n)]
    # 末两根改光头光脚阳线（open==low, close==high）→ BUYA==VOL
    for i in (n - 2, n - 1):
        opens[i] = closes[i - 1] + 0.01
        lows[i] = opens[i]
        closes[i] = opens[i] + 0.06
        highs[i] = closes[i]
    vols[n - 2] = 160.0
    vols[n - 1] = 200.0  # > 160×1.2=192 → 倍量成立

    hit, d = golden_vol_hit(opens, highs, lows, closes, vols)
    print("hit:", hit)
    print("detail:", {k: v for k, v in d.items() if k not in ("buya", "tj_series")})
    print("buya 末5:", [round(x, 2) for x in d["buya"][-5:]])
    print("tj 末5:", d["tj_series"][-5:])
