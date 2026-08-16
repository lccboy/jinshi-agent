# V0.3 任务 2：17 模型条件测试（合成序列命中/不命中）
import datetime

from services.collector.strategy_models import (
    MODELS,
    m_breakout,
    m_golden_vol,
    m_ma_momentum,
    m_multi_factor,
    m_reversal,
)


def make_bars(closes, vols=None, opens=None, highs=None, lows=None, start=datetime.date(2026, 1, 1)):
    out = []
    for i, c in enumerate(closes):
        o = opens[i] if opens else c - 0.02
        h = highs[i] if highs else max(c + 0.05, o, c)
        l = lows[i] if lows else min(c - 0.05, o, c)
        v = vols[i] if vols else 1_000_000
        d = (start + datetime.timedelta(days=i)).strftime("%Y%m%d")
        out.append({"d": int(d), "o": round(o, 3), "h": round(h, 3), "l": round(l, 3),
                    "c": round(c, 3), "v": v, "amt": v * 10})
    return out


def test_breakout_hit():
    # 30 根箱体（9.9~10.4）+ 放量突破 11.0
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 10.8, "h": 11.05, "l": 10.8, "c": 11.0, "v": 2_500_000, "amt": 0})
    hit, score, detail = m_breakout(bars, {})
    assert hit is True
    assert detail["days"] >= 15
    assert score > 0


def test_breakout_no_break():
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 10.2, "h": 10.3, "l": 10.1, "c": 10.25, "v": 1_000_000, "amt": 0})
    assert m_breakout(bars, {})[0] is False


def test_reversal_hit():
    # 60 日回撤 >22%（10→7.5）后缩量阳线站回 MA5 企稳
    closes = [10.0 - 0.04 * i for i in range(60)]  # 10.0 → 7.64
    closes[-5:] = [7.52, 7.56, 7.60, 7.64, 7.70]  # 反弹站上 MA5
    vols = [1_500_000] * 55 + [600_000, 500_000, 450_000, 420_000, 400_000]
    bars = make_bars(closes, vols=vols, opens=[c - 0.1 for c in closes],
                     highs=[c + 0.05 for c in closes], lows=[c - 0.05 for c in closes])
    hit, score, detail = m_reversal(bars, {})
    assert hit is True, detail
    assert score > 0


def test_ma_momentum_hit():
    closes = [10.0 + 0.09 * i for i in range(65)]  # 单边上涨，够 MA60
    vols = [800_000 + i * 20_000 for i in range(65)]
    bars = make_bars(closes, vols=vols)
    hit, score, detail = m_ma_momentum(bars, {})
    assert hit is True, detail


def test_multi_factor_hit():
    closes = [10.0 + 0.09 * i for i in range(65)]
    vols = [800_000 + i * 20_000 for i in range(65)]
    bars = make_bars(closes, vols=vols)
    hit, score, detail = m_multi_factor(bars, {"code": "600000"})
    assert hit is True, detail


def test_golden_vol_hit():
    # 复用 golden_vol 自检样本（21 根，末两根光头光脚放量）
    n = 21
    opens = [10.0 + 0.02 * i for i in range(n)]
    closes = [10.03 + 0.02 * i for i in range(n)]
    highs = [c + 0.04 for c in closes]
    lows = [o - 0.03 for o in opens]
    vols = [100.0 + i for i in range(n)]
    for i in (n - 2, n - 1):
        opens[i] = closes[i - 1] + 0.01
        lows[i] = opens[i]
        closes[i] = opens[i] + 0.06
        highs[i] = closes[i]
    vols[n - 2], vols[n - 1] = 160.0, 200.0
    bars = make_bars(closes, vols=vols, opens=opens, highs=highs, lows=lows)
    hit, score, detail = m_golden_vol(bars, {})
    assert hit is True, detail


def test_models_registry_complete():
    assert set(MODELS) == {
        "reversal", "breakout", "weekly", "dwm", "lowstart", "volbrk", "perfect_ten",
        "golden_vol", "hub_breakout", "div_reversal", "ma_momentum", "bottom_rev",
        "multi_factor", "sub_low", "sub_trend_vol", "sub_breakout", "sub_main",
    }
