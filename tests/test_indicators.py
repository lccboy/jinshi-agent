# V0.3 任务 1：指标库测试（TDD）
from services.collector.indicators import (
    bbi,
    boll,
    ema_series,
    hhv,
    is_limit_up,
    kdj_series,
    llv,
    lwr,
    ma,
    macd_series,
    rsi_series,
)


def test_ma():
    assert ma([1, 2, 3, 4, 5], 3, 4) == 4.0
    assert ma([1, 2, 3], 3, 2) == 2.0
    assert ma([1, 2, 3], 5, 2) is None


def test_ema_series_length_and_last():
    closes = [float(i) for i in range(1, 21)]
    out = ema_series(closes, 12)
    assert len(out) == 20
    assert 10.0 < out[-1] < 20.0  # EMA 平滑后落在区间内


def test_rsi_series_range():
    closes = [10 + i * 0.1 for i in range(30)]
    rsi = rsi_series(closes, 14)
    assert len(rsi) == 30
    assert all(r is None or 0 <= r <= 100 for r in rsi)
    # 持续上涨 → RSI 高位
    assert rsi[-1] is not None and rsi[-1] > 70


def test_macd_golden_cross():
    # 先跌后涨 → 出现 DIFF 上穿 DEA（金叉；DEA 需过 slow 预热期）
    closes = [10.0] + [10 - 0.1 * i for i in range(1, 15)] + [9.0 + 0.3 * i for i in range(1, 30)]
    diff, dea = macd_series(closes)
    cross = any(dea[i] is not None and diff[i] > dea[i] and diff[i - 1] <= dea[i - 1]
                for i in range(1, len(closes)))
    assert cross


def test_kdj_series():
    closes = [10 + i * 0.2 for i in range(30)]
    k, d, j = kdj_series([{"h": c + 0.3, "l": c - 0.2, "c": c} for c in closes])
    assert len(k) == 30
    assert 0 <= k[-1] <= 100 and 0 <= d[-1] <= 100


def test_bbi_boll_lwr():
    closes = [10 + i * 0.1 for i in range(30)]
    assert bbi(closes, 29) > 0
    boll_mid, boll_up, boll_low = boll(closes, 29, 20)
    assert boll_low < boll_mid < boll_up
    l = lwr(closes, 29, 9)
    assert 0 <= l <= 100


def test_hhv_llv():
    arr = [3, 1, 4, 1, 5, 9, 2]
    assert hhv(arr, 5, 6) == 9
    assert llv(arr, 5, 6) == 1
    assert hhv(arr, 3, 2) == 4


def test_is_limit_up():
    # 主板 10%：昨收 10.0，今收 11.0 → 涨停（含 9.8%+ 容差）
    assert is_limit_up({"c": 11.0, "l": 10.0}, prev_close=10.0, code="600000") is True
    # 创业板 20%
    assert is_limit_up({"c": 12.0, "l": 10.0}, prev_close=10.0, code="300487") is True
    assert is_limit_up({"c": 11.5, "l": 10.0}, prev_close=10.0, code="300487") is False
