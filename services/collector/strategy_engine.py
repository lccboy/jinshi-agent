# -*- coding: utf-8 -*-
"""策略引擎（V0.3 任务 3）

流程：读 `config/strategy.json`（可编辑）→ 遍历 universe（data/kline/）→ 17 模型命中
→ 买点评分（STRATEGY_MODEL §4）→ 叠加层确认（sectors/money_flow/leading_reason facts + master 归属）
→ 写 `facts/<date>/strategy.json`（run_id）、`pool.json`（alert/candidate + confirm/stars）、`events.json`（signal_hit）、`runs/strategy_runs.json`。
"""
import argparse
import datetime
import json
import os
import glob

from .archive_job import compute_confirm
from .indicators import hhv, llv, ma
from .normalize import stock_id
from .strategy_models import MODELS


def load_config(path="config/strategy.json"):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_kline(sid, kline_dir):
    path = os.path.join(kline_dir, f"{sid}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def _bell(x, lo, hi, hard_lo, hard_hi):
    if x < hard_lo or x > hard_hi:
        return 0.0
    if lo <= x <= hi:
        return 1.0
    if x < lo:
        return (x - hard_lo) / (lo - hard_lo)
    return (hard_hi - x) / (hard_hi - hi)


def buy_point(bars, hits, cfg):
    """STRATEGY_MODEL §4 买点评分；不满足过滤返回 None。"""
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    vols = [b["v"] for b in bars]
    n = len(closes)
    c, t = closes[-1], bars[-1]
    ma5, ma10, ma20 = ma(closes, 5, n - 1), ma(closes, 10, n - 1), ma(closes, 20, n - 1)
    v5 = sum(vols[-6:-1]) / 5
    bias5, bias10 = c / ma5 - 1, c / ma10 - 1
    chg = c / closes[-2] - 1
    vr = t["v"] / v5 if v5 else 1.0

    bp_cfg = cfg.get("buy_point", {})
    bell = bp_cfg.get("bell_ranges", {})
    b5 = bell.get("bias5", [-0.005, 0.025, -0.04, 0.07])
    b10 = bell.get("bias10", [0, 0.045, -0.03, 0.10])
    bc = bell.get("chg", [0.01, 0.05, -0.03, 0.098])
    bv = bell.get("vol", [1.2, 2.6, 0.7, 5.0])
    br = bell.get("rr", [3, 18, 1.2, 40])

    # 权重外置（STRATEGY_MODEL §4/§6）：config buy_point.weights 驱动，缺省用文档默认值
    w = bp_cfg.get("weights") or {}
    w_bias = w.get("bias", 30)
    w_bias5 = w_bias * 0.6   # 文档展开：bias5=18 / bias10=12（60/40 拆分）
    w_bias10 = w_bias * 0.4
    w_chg = w.get("chg", 12)
    w_vol = w.get("vol", 13)
    w_risk = w.get("stop_dist", 18)
    w_rr = w.get("rr", 20)
    w_close = w.get("close_pos", 4)
    w_fam = w.get("cross_family", 12)

    # 支撑/止损按模型族（与 gen_tri_report 口径一致）
    models = set(hits)
    if "breakout" in models or "hub_breakout" in models:
        brk = hits.get("breakout", {}).get("brk_pct") or hits.get("hub_breakout", {}).get("brk_pct") or 1.0
        support = c / (1 + brk / 100.0)
        stop, buy_lo = support * 0.98, support * 1.001
    elif "volbrk" in models:
        support = c / (1 + hits["volbrk"].get("brk20", 1.0) / 100.0)
        stop, buy_lo = support * 0.98, support * 1.001
    elif "reversal" in models:
        stop, buy_lo = min(lows[-10:]) * 0.99, ma5
    elif "lowstart" in models or "sub_low" in models:
        stop, buy_lo = ma20 * 0.98, ma20 * 1.003
    elif "sub_trend_vol" in models or "sub_breakout" in models:
        support = max(highs[-21:-1])
        stop, buy_lo = support * 0.98, support * 1.001
    else:
        stop, buy_lo = ma10 * 0.97, ma5 * 0.995
    stop = min(stop, c * 0.985)
    risk = c - stop
    target = max(hhv(highs, 120, n - 1) if n >= 120 else max(highs), c * 1.08)
    rr = (target - c) / risk if risk > 0 else 0

    s_bias = w_bias5 * _bell(bias5, *b5) + w_bias10 * _bell(bias10, *b10)
    s_chg = w_chg * _bell(chg, *bc)
    s_vol = w_vol * _bell(vr, *bv)
    s_risk = w_risk if risk / c <= 0.03 else (w_risk * 2 / 3 if risk / c <= 0.05 else (w_risk / 3 if risk / c <= 0.08 else 1.0))
    s_rr = w_rr * _bell(rr, *br)
    s_close = w_close if t["h"] > t["l"] and (t["h"] - c) / (t["h"] - t["l"]) <= 0.3 else 0.0
    families = {cfg["models"][m]["family"] for m in models if m in cfg.get("models", {})}
    s_fam = w_fam if len(families) > 1 else 0.0
    score = round(s_bias + s_chg + s_vol + s_risk + s_rr + s_close + s_fam, 1)

    flt = bp_cfg.get("filter", {})
    if rr < flt.get("min_rr", 3.0) or risk / c * 100 > flt.get("max_stop_pct", 4.0):
        return None
    return {"score": score, "buy_lo": round(buy_lo, 3), "stop": round(stop, 3), "target": round(target, 3),
            "rr": round(rr, 1)}


def load_facts(date_str, out_root):
    """读当日叠加层 facts（存在才返回）。"""
    day = os.path.join(out_root, "facts", date_str)
    def rd(name, key=None):
        path = os.path.join(day, name)
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc.get(key, doc) if key else doc
    return {
        "sectors": rd("sectors.json", "sectors"),
        "money_flow": rd("money_flow.json", "sectors"),
        "leading_reason": rd("leading_reason.json", "plates"),
    }


def load_membership(out_root):
    """master stocks.json current.sectors → {sid: [sector_ids]}。"""
    path = os.path.join(out_root, "normalized", "stocks.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        stocks = json.load(fh)
    return {sid: list(rec.get("current", {}).get("sectors", [])) for sid, rec in stocks.items()}


def cap_alert_pool(pools, top_n):
    """落实 alert_pool.top_n：预警只保留最高分，其余降为候选而不丢失。"""
    ranked = sorted((pools.get("alert") or {}).items(), key=lambda item: item[1].get("score", 0), reverse=True)
    keep = ranked[:max(0, int(top_n))]
    overflow = ranked[max(0, int(top_n)):]
    pools["alert"] = dict(keep)
    candidate = pools.setdefault("candidate", {})
    for sid, entry in overflow:
        candidate[sid] = entry
    return pools


def run_strategy(date_str, kline_dir, out_root, config_path="config/strategy.json", universe=None):
    cfg = load_config(config_path)
    facts = load_facts(date_str, out_root)
    membership = load_membership(out_root)

    # RS 基准：指数 20 日收益
    index_sid = cfg.get("data", {}).get("rs_index", "SH000001")
    index_bars = load_kline(index_sid, kline_dir)
    index_ret20 = index_bars[-1]["c"] / index_bars[-21]["c"] - 1 if index_bars and len(index_bars) > 21 else 0.0

    if universe is None:
        stocks_path = os.path.join(out_root, "normalized", "stocks.json")
        if os.path.exists(stocks_path):
            with open(stocks_path, encoding="utf-8") as fh:
                stocks = json.load(fh)
            universe = [sid for sid, rec in stocks.items()
                        if rec.get("status") not in ("source_missing", "invalid_instrument")]
        else:
            universe = [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(kline_dir, "*.json"))
                        if os.path.basename(p)[:-5].startswith(("SH", "SZ", "BJ"))]
    universe = [s for s in universe if s != index_sid]

    run_id = date_str.replace("-", "") + "_" + datetime.datetime.now().strftime("%H%M")
    strategy, pool, events = {}, {"pools": {"alert": {}, "candidate": {}, "limitup": {}, "ladder": {}, "watchlist": {}}}, []

    enabled = [m for m, conf in cfg.get("models", {}).items() if conf.get("enabled", True)]
    min_score = cfg.get("alert_pool", {}).get("min_score", 60)

    for sid in universe:
        bars = load_kline(sid, kline_dir)
        if not bars or len(bars) < 30:
            continue
        stock_ret20 = bars[-1]["c"] / bars[-21]["c"] - 1 if len(bars) > 21 else 0.0
        ctx = {"code": sid[2:], "rs20": stock_ret20 - index_ret20}
        if "perfect_ten" in cfg.get("models", {}):
            ctx["min_conditions"] = cfg["models"]["perfect_ten"].get("params", {}).get("min_conditions", 7)

        hits = {}
        for mid in enabled:
            try:
                hit, score, detail = MODELS[mid](bars, ctx)
            except Exception:
                continue
            if hit:
                hits[mid] = {"score": score, **{k: v for k, v in detail.items() if isinstance(v, (int, float, str, bool))}}

        if not hits:
            continue
        bp = buy_point(bars, hits, cfg)
        score = bp["score"] if bp else max(h["score"] for h in hits.values())
        models_out = {m: round(h["score"], 1) for m, h in hits.items()}

        secs = membership.get(sid, [])
        confirm = compute_confirm(secs, facts["sectors"], facts["money_flow"], facts["leading_reason"])
        stars = 4 if all(confirm.values()) else (3 if sum(confirm.values()) >= 2 else 2)
        stop_pct = round((bars[-1]["c"] - bp["stop"]) / bars[-1]["c"] * 100, 2) if bp else None

        strategy[sid] = {"run_id": run_id, "models": models_out, "score": score,
                         "buy_point": bp["buy_lo"] if bp else None, "target": bp["target"] if bp else None,
                         "stop": bp["stop"] if bp else None, "stop_pct": stop_pct, "rr": bp["rr"] if bp else None,
                         "confirm": confirm, "stars": stars}
        pool_entry = {"entry_time": datetime.datetime.now().strftime("%H:%M"), "score": score,
                      "status": "active", "model_hit": sorted(models_out), "confirm": confirm, "stars": stars,
                      "buy_point": bp["buy_lo"] if bp else None, "stop": bp["stop"] if bp else None,
                      "stop_pct": stop_pct, "rr": bp["rr"] if bp else None, "target": bp["target"] if bp else None}
        pool["pools"]["alert" if score >= min_score else "candidate"][sid] = pool_entry
        events.append({"ts": f"{date_str}T{datetime.datetime.now().strftime('%H:%M:%S')}", "type": "signal_hit",
                       "stock_id": sid, "score": score, "detail": "策略引擎 17 模型盘后扫描", "source": "tdx_model"})

    cap_alert_pool(pool["pools"], cfg.get("alert_pool", {}).get("top_n", 30))

    day_dir = os.path.join(out_root, "facts", date_str)
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, "strategy.json"), "w", encoding="utf-8") as fh:
        json.dump(strategy, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(day_dir, "pool.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": date_str, **pool}, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(day_dir, "events.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": date_str, "events": events}, fh, ensure_ascii=False, indent=2)

    runs_dir = os.path.join(out_root, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    runs_path = os.path.join(runs_dir, "strategy_runs.json")
    runs = {}
    if os.path.exists(runs_path):
        with open(runs_path, encoding="utf-8") as fh:
            runs = json.load(fh)
    runs[run_id] = {"date": date_str, "models": enabled, "universe": len(universe),
                    "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with open(runs_path, "w", encoding="utf-8") as fh:
        json.dump(runs, fh, ensure_ascii=False, indent=2)

    return {"run_id": run_id, "hits": len(strategy), "alert": len(pool["pools"]["alert"]),
            "candidate": len(pool["pools"]["candidate"])}


def main(argv=None):
    ap = argparse.ArgumentParser(description="策略引擎（strategy_engine）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--kline", default="data/kline", help="kline 目录（默认 data/kline）")
    ap.add_argument("--out", default="data", help="数据根目录（默认 data）")
    ap.add_argument("--config", default="config/strategy.json", help="策略配置（默认 config/strategy.json）")
    ap.add_argument("--universe-file", help="universe 名单（每行一个 stock_id，缺省扫描 kline 目录）")
    args = ap.parse_args(argv)

    universe = None
    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as fh:
            universe = [ln.strip() for ln in fh if ln.strip()]
        # 兼容裸 6 位代码 → 归一为 stock_id（SZ300487）
        universe = [stock_id(s) if len(s) == 6 and s.isdigit() else s for s in universe]
    report = run_strategy(args.date, args.kline, args.out, args.config, universe)
    print(f"[OK] run={report['run_id']} 命中={report['hits']} 预警={report['alert']} 候选={report['candidate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
