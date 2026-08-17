# V0.1a 任务 4：kline_sync 测试（.day 解析 + 前复权，TDD）
import json
import os

from services.collector.kline_sync import (
    adjust_bars,
    load_universe_from_stocks,
    parse_day_file,
    to_kline_bars,
    write_kline_json,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "600000_5bars.day")


def test_parse_day_file_ohlcv():
    bars = parse_day_file(FIXTURE)
    assert len(bars) == 5
    b = bars[-1]
    assert set(b) == {"d", "o", "h", "l", "c", "v", "amt"}
    assert b["d"] == 20260814
    # 口径：o/h/l/c 保持 .day 原始 int×100（与 tdx_tri_screener 一致）
    assert b["o"] == 1020 and b["h"] == 1030 and b["l"] == 1015 and b["c"] == 1025
    assert b["h"] >= b["l"]
    assert b["v"] == 1_400_000
    assert abs(b["amt"] - 1_678_901.0) < 1e-6


def test_parse_day_file_empty_missing(tmp_path):
    assert parse_day_file(str(tmp_path / "nope.day")) == []


def test_adjust_bars_fallback_gap(monkeypatch):
    # 无 gbbq 时回退价格跳空推断：非 300/688 股票跳空 >11.5% → 前复权乘比（int×100 输入）
    from services.collector import kline_sync

    monkeypatch.setattr(kline_sync, "_load_gbbq", lambda: (False, {}))  # 强制 fallback
    bars = [
        {"d": 20260810, "o": 1000, "h": 1010, "l": 995, "c": 1005, "v": 1_000_000, "amt": 1.0},
        {"d": 20260811, "o": 1200, "h": 1210, "l": 1195, "c": 1205, "v": 1_100_000, "amt": 1.0},
    ]
    out = adjust_bars(bars, "600000")
    ratio = 1205.0 / 1005.0
    assert abs(out[0]["c"] - 1005.0 * ratio) < 1e-9  # 历史根按比放大
    assert abs(out[1]["c"] - 1205.0) < 1e-9          # 最新根不变
    assert out[1]["v"] == 1_100_000                  # 只调 OHLC，量不变


def test_adjust_bars_no_gap_unchanged():
    bars = [
        {"d": 20260810, "o": 1000, "h": 1010, "l": 995, "c": 1005, "v": 1_000_000, "amt": 1.0},
        {"d": 20260811, "o": 1005, "h": 1015, "l": 1000, "c": 1010, "v": 1_100_000, "amt": 1.0},
    ]
    out = adjust_bars(bars, "600000")
    assert abs(out[0]["c"] - 1005.0) < 1e-9


def test_to_kline_bars_converts_yuan():
    raw = [
        {"d": 20260814, "o": 1020, "h": 1030, "l": 1015, "c": 1025, "v": 1_400_000, "amt": 1_678_901.0},
    ]
    kb = to_kline_bars(raw)
    assert kb[0]["o"] == 10.20 and kb[0]["c"] == 10.25
    assert kb[0]["v"] == 1_400_000


def test_write_kline_json_shape(tmp_path):
    bars = parse_day_file(FIXTURE)
    adjusted = adjust_bars(bars, "600000")
    out = write_kline_json("SH600000", to_kline_bars(adjusted), str(tmp_path))
    with open(out, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["stock_id"] == "SH600000"
    assert doc["adjusted"] == "qfq"
    assert len(doc["bars"]) == 5
    assert set(doc["bars"][0]) == {"d", "o", "h", "l", "c", "v", "amt"}
    assert doc["bars"][-1]["c"] == 10.25  # 无事件时前复权=原价


def test_load_universe_from_stocks(tmp_path):
    path = tmp_path / "stocks.json"
    path.write_text(json.dumps({"SZ300487": {"code": "300487", "status": "active"},
                                "SH600000": {"code": "600000", "status": "source_missing"}}), encoding="utf-8")
    assert load_universe_from_stocks(str(path)) == ["300487"]
