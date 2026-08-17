# -*- coding: utf-8 -*-
"""盘中事件引擎（V0.3 任务 4，盘中实时链路）

依据 `docs/DATA_MODEL.md` §4.12/4.13 + `docs/STRATEGY_MODEL.md` §7：
- **昨日定格**：收盘日K（箱体顶/前20日高点/昨收）+ 收盘 strategy.json（模型命中/评分）盘中不变
- **实时代入**：腾讯行情（现价/量比/涨幅/涨停价）每 3s/30s 代入 → 事件判定
- 事件类型：`limitup`（涨停确认）、`broken`（炸板：涨停后跌破涨停价）、
  `volume_surge`（量比 ≥ 阈值）、`signal_hit`（模型盘中命中：昨日定格 ∧ 现价突破 ∧ 量比达标）
- 预警池维护：limitup/ladder/alert/candidate/watchlist + removed（炸板等退出保留历史）
- **只增不改**：events 追加；pool 更新（alert 池 `model_hit` + `priority: high` 置顶）
"""
import argparse
import datetime
import json
import os

from .indicators import hhv

# 默认阈值（config/strategy.json 可覆盖）
VOL_SURGE_RATIO = 2.0     # 量比 ≥ 2.0 → volume_surge
MODEL_VOL_RATIO = 1.2     # 模型盘中命中量比下限（STRATEGY_MODEL §7 示例）
MIN_SCORE = 60            # alert 池评分下限

POOL_KEYS = ("limitup", "ladder", "alert", "candidate", "watchlist")


def _empty_pool():
    return {"pools": {k: {} for k in POOL_KEYS}, "removed": {}}


def load_pool(facts_dir, date_str=None):
    """读当日 pool.json（不存在返回 None）。"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join(facts_dir, date_str, "pool.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_pool(pool, facts_dir, date_str=None):
    """写 pool.json（保持 data_date 键控）。"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    day_dir = os.path.join(facts_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)
    doc = {"data_date": date_str, **pool}
    path = os.path.join(day_dir, "pool.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return path


def load_events(facts_dir, date_str=None):
    """读当日 events.json（不存在返回空列表）。"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    path = os.path.join(facts_dir, date_str, "events.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return doc.get("events", [])


def append_events(facts_dir, new_events, date_str=None):
    """events 只增：读现有 + 追加新事件 + 写回。"""
    if date_str is None:
        date_str = datetime.date.today().strftime("%Y-%m-%d")
    events = load_events(facts_dir, date_str)
    events.extend(new_events)
    day_dir = os.path.join(facts_dir, date_str)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, "events.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"data_date": date_str, "events": events}, fh, ensure_ascii=False, indent=2)
    return path


def build_frozen_ctx(sid, bars, strategy):
    """昨日定格上下文：模型命中/评分 + 收盘箱体顶/前20日高点/昨收。

    bars: 收盘日K（含当日末根）；strategy: facts/<d>/strategy.json（{sid: entry}）。
    盘中不变——历史条件（STRATEGY_MODEL §7）。
    """
    entry = (strategy or {}).get(sid, {})
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    n = len(closes)
    return {
        "sid": sid,
        "models": sorted((entry.get("models") or {}).keys()),
        "base_score": float(entry.get("score") or 0),
        "box_top": hhv(highs, 20, n - 1) if n else 0,
        "prev_close": closes[-1] if n else 0,
    }


def load_frozen_context(facts_dir, date_str, kline_dir):
    """加载目标交易日前最近一个有策略结果的交易日，作为盘中冻结上下文。"""
    candidates = []
    if os.path.isdir(facts_dir):
        candidates = sorted((name for name in os.listdir(facts_dir)
                             if name < date_str and os.path.isfile(os.path.join(facts_dir, name, "strategy.json"))),
                            reverse=True)
    if not candidates:
        return {}, None
    source_date = candidates[0]
    with open(os.path.join(facts_dir, source_date, "strategy.json"), encoding="utf-8") as fh:
        strategy = json.load(fh)
    frozen = {}
    for sid in strategy:
        path = os.path.join(kline_dir, f"{sid}.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            bars = json.load(fh).get("bars", [])
        if bars:
            frozen[sid] = build_frozen_ctx(sid, bars, strategy)
    return frozen, source_date


def _ts_now():
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def detect_events(ctx, quote, prev_quote=None, vol_surge_ratio=VOL_SURGE_RATIO,
                  model_vol_ratio=MODEL_VOL_RATIO, now=None):
    """单只股票事件判定：腾讯实时代入（当日实时条件）。

    quote: {price, preclose, limit_up, vol_ratio, change_pct}
    prev_quote: 上一快照（炸板判定）；None 表示首帧（不判炸板）。
    返回事件列表（可能为空）。
    """
    now = now or _ts_now()
    sid = ctx["sid"]
    events = []
    price = float(quote.get("price") or 0)
    preclose = float(quote.get("preclose") or ctx.get("prev_close") or 0)
    limit_up = float(quote.get("limit_up") or 0)
    vol_ratio = float(quote.get("vol_ratio") or 0)

    # 涨停确认（腾讯涨停价字段优先）
    if limit_up and preclose and price >= limit_up - 0.01:
        events.append({"ts": now, "type": "limitup", "stock_id": sid,
                       "score": ctx["base_score"], "price": price, "detail": "涨停"})

    # 炸板：上一快照涨停，现价跌破涨停价
    if prev_quote:
        prev_limit = float(prev_quote.get("limit_up") or 0)
        prev_price = float(prev_quote.get("price") or 0)
        if prev_limit and prev_price >= prev_limit - 0.01 and price < prev_limit - 0.01:
            events.append({"ts": now, "type": "broken", "stock_id": sid,
                           "score": 0, "detail": "炸板"})

    # 量比异动
    if vol_ratio >= vol_surge_ratio:
        events.append({"ts": now, "type": "volume_surge", "stock_id": sid,
                       "score": ctx["base_score"], "vol_ratio": vol_ratio, "detail": "量比异动"})

    # 模型盘中命中：昨日定格（箱体顶）+ 实时代入（突破 + 量比）→ signal_hit
    if ctx["models"] and ctx["box_top"] and price > ctx["box_top"] and vol_ratio >= model_vol_ratio:
        events.append({"ts": now, "type": "signal_hit", "stock_id": sid,
                       "score": ctx["base_score"], "detail": "模型盘中命中",
                       "source": "tdx_model", "models": ctx["models"]})
    return events


def update_pool_from_events(pool, events):
    """事件 → 预警池维护（DATA_MODEL §4.13）。

    - limitup → limitup 池（active）
    - signal_hit → alert 池（priority high + model_hit + stars 保留）
    - broken → 从 limitup 池移入 removed（exit_reason 炸板）
    """
    pools = pool.setdefault("pools", {k: {} for k in POOL_KEYS})
    removed = pool.setdefault("removed", {})
    for e in events:
        sid = e.get("stock_id")
        etype = e.get("type")
        if not sid:
            continue
        if etype == "limitup":
            pools["limitup"].setdefault(sid, {"entry_time": e["ts"][11:19],
                                              "score": e.get("score", 0),
                                              "status": "active",
                                              "detected_by": "tencent"})
        elif etype == "signal_hit":
            entry = pools["alert"].setdefault(sid, {})
            entry.update({"entry_time": e["ts"][11:19], "score": e.get("score", 0),
                          "status": "active", "priority": "high",
                          "model_hit": list(set(entry.get("model_hit", [])) | set(e.get("models", []))),
                          "reasons": entry.get("reasons", []) + [e.get("detail", "")]})
        elif etype == "broken":
            if sid in pools["limitup"]:
                entry = pools["limitup"].pop(sid)
                entry.update({"exit_time": e["ts"][11:19], "exit_reason": e.get("detail", "炸板"),
                              "status": "removed"})
                removed[sid] = entry
    return pool


def scan_snapshot(facts_dir, date_str, frozen, quotes, prev_quotes=None,
                  vol_surge_ratio=VOL_SURGE_RATIO, now=None):
    """一帧快照全量扫描：每只股票事件判定 + 预警池维护 + events 追加。

    frozen: {sid: build_frozen_ctx(...)}（昨日定格）
    quotes: 腾讯行情 {sid: quote}
    返回新事件列表。
    """
    events = []
    prev_quotes = prev_quotes or {}
    for sid, quote in quotes.items():
        ctx = frozen.get(sid)
        if not ctx:
            continue
        events.extend(detect_events(ctx, quote, prev_quotes.get(sid),
                                    vol_surge_ratio=vol_surge_ratio, now=now))
    if events:
        append_events(facts_dir, events, date_str)
        pool = load_pool(facts_dir, date_str) or _empty_pool()
        pool["data_date"] = date_str
        update_pool_from_events(pool, events)
        save_pool(pool, facts_dir, date_str)
    return events


def main(argv=None):
    ap = argparse.ArgumentParser(description="盘中事件引擎（realtime_engine）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--facts", default="data/facts", help="facts 根目录（默认 data/facts）")
    ap.add_argument("--kline", default="data/kline", help="kline 目录（默认 data/kline）")
    ap.add_argument("--quotes", help="腾讯行情 JSON（quote_collector 输出；缺省实时拉取）")
    ap.add_argument("--universe-file", help="股票名单（每行 stock_id；缺省读昨日 strategy.json 键）")
    args = ap.parse_args(argv)

    frozen, source_date = load_frozen_context(args.facts, args.date, args.kline)
    if not frozen:
        print(f"[ERROR] {args.date} 之前没有可用 strategy/kline 冻结上下文")
        return 1

    # 行情输入
    if args.quotes:
        with open(args.quotes, encoding="utf-8") as fh:
            quotes = json.load(fh)
    else:
        from .quote_collector import fetch_quotes
        codes = list(frozen.keys()) if not args.universe_file else \
            [ln.strip() for ln in open(args.universe_file, encoding="utf-8") if ln.strip()]
        quotes = fetch_quotes(codes)

    events = scan_snapshot(args.facts, args.date, frozen, quotes)
    by_type = {}
    for e in events:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"[OK] 冻结日={source_date} 扫描 {len(quotes)} 只，新事件 {len(events)} 个：{by_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
