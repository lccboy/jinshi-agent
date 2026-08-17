# V0.3 任务 4：盘中事件引擎测试（TDD）
# 依据 docs/DATA_MODEL.md §4.12/4.13 + STRATEGY_MODEL.md §7：
# 昨日定格（收盘指标）+ 腾讯实时代入 → limitup/broken/volume_surge/signal_hit 事件 + 预警池维护
import json
import os

from services.collector.realtime_engine import (
    build_frozen_ctx,
    detect_events,
    load_pool,
    load_frozen_context,
    save_pool,
    update_pool_from_events,
)


# ---------- 昨日定格上下文 ----------

def test_build_frozen_ctx():
    # 收盘 strategy.json → 昨日定格上下文（箱体顶/前高/量比基线等）
    bars = [
        {"d": 20260813, "o": 10.0, "h": 10.4, "l": 9.9, "c": 10.2, "v": 1_000_000, "amt": 0},
        {"d": 20260814, "o": 10.1, "h": 10.3, "l": 10.0, "c": 10.25, "v": 1_100_000, "amt": 0},
    ]
    strategy = {"SZ300001": {"models": {"breakout": 90.0}, "score": 88.0, "buy_point": 10.1}}
    ctx = build_frozen_ctx("SZ300001", bars, strategy)
    assert ctx["sid"] == "SZ300001"
    assert ctx["models"] == ["breakout"]
    assert ctx["box_top"] == 10.4          # 20 日最高 → 箱顶
    assert ctx["prev_close"] == 10.25
    assert ctx["base_score"] == 88.0


def test_build_frozen_ctx_no_strategy():
    ctx = build_frozen_ctx("SZ300001", [], {})
    assert ctx["models"] == []
    assert ctx["box_top"] == 0
    assert ctx["base_score"] == 0


# ---------- 事件判定 ----------

def test_detect_events_limitup():
    # 现价 = 涨停价（腾讯字段）→ limitup 事件
    ctx = build_frozen_ctx("SZ300001", [], {})
    quote = {"price": 12.0, "preclose": 10.0, "limit_up": 12.0, "vol_ratio": 2.0, "change_pct": 20.0}
    events = detect_events(ctx, quote, prev_quote=None)
    types = [e["type"] for e in events]
    assert "limitup" in types
    lu = next(e for e in events if e["type"] == "limitup")
    assert lu["stock_id"] == "SZ300001"
    assert lu["price"] == 12.0


def test_detect_events_volume_surge():
    # 量比 ≥ 阈值（默认 2.0）→ volume_surge
    ctx = build_frozen_ctx("SZ300001", [], {})
    quote = {"price": 10.3, "preclose": 10.0, "limit_up": 12.0, "vol_ratio": 3.5, "change_pct": 3.0}
    events = detect_events(ctx, quote, prev_quote=None)
    assert any(e["type"] == "volume_surge" for e in events)


def test_detect_events_no_surge():
    # 量比 1.2、未涨停 → 无事件
    ctx = build_frozen_ctx("SZ300001", [], {})
    quote = {"price": 10.2, "preclose": 10.0, "limit_up": 12.0, "vol_ratio": 1.2, "change_pct": 2.0}
    assert detect_events(ctx, quote, prev_quote=None) == []


def test_detect_events_broken():
    # 昨日/上一快照涨停，现价跌破涨停价 → broken（炸板）
    ctx = build_frozen_ctx("SZ300001", [], {})
    prev = {"price": 12.0, "preclose": 10.0, "limit_up": 12.0, "vol_ratio": 2.0, "change_pct": 20.0}
    quote = {"price": 11.5, "preclose": 10.0, "limit_up": 12.0, "vol_ratio": 2.1, "change_pct": 15.0}
    events = detect_events(ctx, quote, prev_quote=prev)
    assert any(e["type"] == "broken" for e in events)


def test_detect_events_model_hit():
    # 昨日定格箱体 + 现价突破箱顶 + 量比达标 → signal_hit（模型盘中命中）
    bars = [
        {"d": 20260813, "o": 10.0, "h": 10.4, "l": 9.9, "c": 10.2, "v": 1_000_000, "amt": 0},
        {"d": 20260814, "o": 10.1, "h": 10.3, "l": 10.0, "c": 10.25, "v": 1_100_000, "amt": 0},
    ]
    strategy = {"SZ300001": {"models": {"breakout": 90.0}, "score": 88.0}}
    ctx = build_frozen_ctx("SZ300001", bars, strategy)
    # 现价突破箱顶 10.4 且量比 ≥ 1.2 → 盘中 signal_hit
    quote = {"price": 10.55, "preclose": 10.25, "limit_up": 12.0, "vol_ratio": 1.8, "change_pct": 2.9}
    events = detect_events(ctx, quote, prev_quote=None)
    hits = [e for e in events if e["type"] == "signal_hit"]
    assert hits, "模型盘中命中应产生 signal_hit"
    assert hits[0]["source"] == "tdx_model"
    assert hits[0]["score"] == 88.0


def test_detect_events_model_no_break():
    # 现价未突破箱顶 → 不触发 signal_hit
    bars = [{"d": 20260813, "o": 10.0, "h": 10.4, "l": 9.9, "c": 10.2, "v": 1_000_000, "amt": 0}]
    strategy = {"SZ300001": {"models": {"breakout": 90.0}, "score": 88.0}}
    ctx = build_frozen_ctx("SZ300001", bars, strategy)
    quote = {"price": 10.3, "preclose": 10.2, "limit_up": 12.0, "vol_ratio": 1.5, "change_pct": 1.0}
    assert not any(e["type"] == "signal_hit" for e in detect_events(ctx, quote, prev_quote=None))


# ---------- 预警池维护 ----------

def test_update_pool_from_events_limitup():
    events = [{"ts": "2026-08-14T09:35:03", "type": "limitup", "stock_id": "SZ300001",
               "score": 92, "detail": "涨停"}]
    pool = {"pools": {"limitup": {}, "ladder": {}, "alert": {}, "candidate": {}, "watchlist": {}}}
    update_pool_from_events(pool, events)
    assert "SZ300001" in pool["pools"]["limitup"]
    assert pool["pools"]["limitup"]["SZ300001"]["status"] == "active"


def test_update_pool_from_events_signal_hit_priority():
    # 模型命中 → alert 池，priority high + model_hit
    events = [{"ts": "2026-08-14T10:00:00", "type": "signal_hit", "stock_id": "SZ300001",
               "score": 88, "detail": "模型 breakout 命中", "source": "tdx_model",
               "models": ["breakout"]}]
    pool = {"pools": {"limitup": {}, "ladder": {}, "alert": {}, "candidate": {}, "watchlist": {}}}
    update_pool_from_events(pool, events)
    entry = pool["pools"]["alert"]["SZ300001"]
    assert entry["priority"] == "high"
    assert "breakout" in entry["model_hit"]
    assert entry["status"] == "active"


def test_update_pool_from_events_broken_removed():
    # 炸板 → limitup 池成员移入 removed（保留历史）
    events = [{"ts": "2026-08-14T10:47:00", "type": "broken", "stock_id": "SZ300001",
               "score": 0, "detail": "炸板"}]
    pool = {"pools": {"limitup": {"SZ300001": {"entry_time": "09:35", "status": "active"}},
                      "ladder": {}, "alert": {}, "candidate": {}, "watchlist": {}}, "removed": {}}
    update_pool_from_events(pool, events)
    assert "SZ300001" not in pool["pools"]["limitup"]
    assert pool["removed"]["SZ300001"]["exit_reason"] == "炸板"


# ---------- 读写 ----------

def test_pool_roundtrip(tmp_path):
    pool = {"data_date": "2026-08-14",
            "pools": {"limitup": {"SZ300001": {"status": "active"}},
                      "ladder": {}, "alert": {}, "candidate": {}, "watchlist": {}}}
    path = save_pool(pool, str(tmp_path))
    loaded = load_pool(str(tmp_path))
    assert loaded["data_date"] == "2026-08-14"
    assert "SZ300001" in loaded["pools"]["limitup"]


def test_load_pool_missing(tmp_path):
    assert load_pool(str(tmp_path)) is None


def test_load_frozen_context_uses_latest_previous_strategy(tmp_path):
    facts = tmp_path / "facts"
    day = facts / "2026-08-14"
    day.mkdir(parents=True)
    (day / "strategy.json").write_text(json.dumps({"SZ300001": {"models": {"breakout": 90}, "score": 88}}), encoding="utf-8")
    kline = tmp_path / "kline"
    kline.mkdir()
    bars = [{"d": 20260813, "o": 10, "h": 10.4, "l": 9.9, "c": 10.2, "v": 100, "amt": 0},
            {"d": 20260814, "o": 10.1, "h": 10.5, "l": 10, "c": 10.3, "v": 110, "amt": 0}]
    (kline / "SZ300001.json").write_text(json.dumps({"bars": bars}), encoding="utf-8")
    frozen, source_date = load_frozen_context(str(facts), "2026-08-17", str(kline))
    assert source_date == "2026-08-14"
    assert frozen["SZ300001"]["models"] == ["breakout"]
