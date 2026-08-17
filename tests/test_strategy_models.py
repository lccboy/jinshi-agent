# V0.3 任务 2：17 模型条件测试（合成序列命中/不命中）
import datetime
import json
from pathlib import Path

from services.collector.strategy_models import (
    MODELS,
    m_breakout,
    m_golden_vol,
    m_ma_momentum,
    m_multi_factor,
    m_perfect_ten,
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


def _golden_vol_bars():
    """21 根：整体上行，末 3 根专门构造（n-3 光头光脚放量 250，n-2 缩量 200，n-1 放量 250 但非光头光脚）。"""
    n = 21
    closes = [10.0 + 0.04 * i for i in range(n)]
    # 覆盖末 3 根（index 18/19/20）
    closes[18], closes[19], closes[20] = 11.2, 10.6, 11.2  # n-3 高位，n-2 回踩，n-1 收回
    opens = [c - 0.02 for c in closes]
    highs = [c + 0.05 for c in closes]
    lows = [c - 0.05 for c in closes]
    vols = [100.0 + i * 8 for i in range(n)]
    # n-3：光头光脚阳线 → BUYA == VOL == 250（3 日峰值）
    opens[18], lows[18], closes[18], highs[18], vols[18] = 10.9, 10.9, 11.2, 11.2, 250.0
    # n-2：缩量回踩（BUYA 约 < 200）
    opens[19], closes[19], vols[19] = 11.1, 10.6, 200.0
    # n-1：放量收回，非光头光脚（BUYA < 250），vol 250 > 200×1.2
    opens[20], highs[20], closes[20], lows[20], vols[20] = 11.0, 11.4, 11.2, 10.9, 250.0
    return make_bars(closes, vols=vols, opens=opens, highs=highs, lows=lows)


def test_golden_vol_ctx_vol_mult_blocks():
    """ctx.vol_mult 必须真正生效：3.0 倍量门槛 → 250 非 200×3 → 不命中。"""
    bars = _golden_vol_bars()
    hit, _, detail = m_golden_vol(bars, {"vol_mult": 3.0})
    assert hit is False, detail


def test_golden_vol_ctx_window():
    """ctx.window 必须真正生效：window=1 只看当日 BUYA → 当日非峰值 → 不命中（window=3 时命中）。"""
    bars = _golden_vol_bars()
    hit3, _, d3 = m_golden_vol(bars, {"window": 3})
    assert hit3 is True, d3
    hit1, _, d1 = m_golden_vol(bars, {"window": 1})
    assert hit1 is False, d1


def test_perfect_ten_hit_with_min7():
    """⑦ 十全十美 min_conditions=7（无 L2 数据，仅 OHLCV 7 条件）→ 全部满足应命中。"""
    closes = [10.0 + 0.05 * (i % 2) for i in range(30)]  # 30 根震荡
    closes[29] = 9.95  # 小跌 → RSI12 的 loss>0，RSI6(急涨段)=100 > RSI12
    closes += [9.95 + 0.28 * j for j in range(1, 12)]  # 11 根急涨收尾
    n = len(closes)
    vols = [800_000 + i * 20_000 for i in range(n)]  # 递增放量
    opens = [c - 0.02 for c in closes]
    highs = [c + 0.01 for c in closes]  # 收盘接近最高 → no_chase 成立
    lows = [c - 0.05 for c in closes]
    bars = make_bars(closes, vols=vols, opens=opens, highs=highs, lows=lows)
    hit, score, detail = m_perfect_ten(bars, {"min_conditions": 7})
    assert hit is True, detail
    assert score > 0


def test_models_registry_complete():
    assert set(MODELS) == {
        "reversal", "breakout", "weekly", "dwm", "lowstart", "volbrk", "perfect_ten",
        "golden_vol", "hub_breakout", "div_reversal", "ma_momentum", "bottom_rev",
        "multi_factor", "sub_low", "sub_trend_vol", "sub_breakout", "sub_main",
    }


def test_all_enabled_models_have_chinese_display_names():
    config = json.loads(Path("config/strategy.json").read_text(encoding="utf-8"))
    enabled = {mid: item for mid, item in config["models"].items() if item.get("enabled")}
    assert set(enabled) == set(MODELS)
    assert all(item.get("name") and any("\u4e00" <= ch <= "\u9fff" for ch in item["name"])
               for item in enabled.values())
