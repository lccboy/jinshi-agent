# V0.3 任务 3：策略引擎测试（合成 kline 端到端）
import datetime
import json

from services.collector.strategy_engine import buy_point, cap_alert_pool, run_strategy


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


def write_kline(sid, bars, kline_dir):
    import os
    os.makedirs(kline_dir, exist_ok=True)
    with open(os.path.join(kline_dir, f"{sid}.json"), "w", encoding="utf-8") as fh:
        json.dump({"stock_id": sid, "adjusted": "qfq", "bars": bars}, fh, ensure_ascii=False)


def test_buy_point_returns_dict():
    # 突破命中（+2.5%，止损距离 <4%）→ 买点评分结构
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 10.48, "h": 10.6, "l": 10.45, "c": 10.55, "v": 2_500_000, "amt": 0})
    hits = {"breakout": {"brk_pct": 0.5}}  # 贴近箱顶突破：止损≈2.5%，RR≈3.2，过过滤
    cfg = {"models": {"breakout": {"family": "breakout"}}, "buy_point": {"filter": {}}}
    bp = buy_point(bars, hits, cfg)
    assert bp is not None
    assert set(["score", "buy_lo", "stop", "target", "rr"]) <= set(bp)
    assert bp["stop"] < bp["buy_lo"] < bp["target"]


def test_buy_point_respects_configured_weights():
    # config weights 必须真正影响分数（rr 权重清零 → 分数下降），无 weights 时用文档默认值
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 10.48, "h": 10.6, "l": 10.45, "c": 10.55, "v": 2_500_000, "amt": 0})
    hits = {"breakout": {"brk_pct": 0.5}}
    models = {"breakout": {"family": "breakout"}}
    base_cfg = {"models": models, "buy_point": {"filter": {}}}
    zero_rr_cfg = {"models": models, "buy_point": {"filter": {}, "weights": {
        "bias": 30, "chg": 12, "vol": 13, "stop_dist": 18, "rr": 0, "close_pos": 4, "cross_family": 12}}}
    base = buy_point(bars, hits, base_cfg)
    zero_rr = buy_point(bars, hits, zero_rr_cfg)
    assert base["score"] > zero_rr["score"]
    assert base["score"] > 0


def test_run_strategy_end_to_end(tmp_path):
    # 一只突破票 + 一只平淡票 + 指数 → strategy/pool/events 输出
    kline_dir = str(tmp_path / "kline")
    out_root = str(tmp_path / "data")

    # 指数（平淡，RS≈0）
    idx = make_bars([10.0 + 0.01 * i for i in range(65)])
    write_kline("SH000001", idx, kline_dir)

    # 突破票：箱体后放量突破
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.extend(make_bars([11.0 + 0.03 * i for i in range(30)], vols=[2_500_000] * 30,
                          start=datetime.date(2026, 2, 1)))
    write_kline("SZ300001", bars, kline_dir)

    # 平淡票：窄幅横盘
    flat = make_bars([10.0 + 0.005 * i for i in range(65)])
    write_kline("SH600001", flat, kline_dir)

    report = run_strategy("2026-08-14", kline_dir, out_root,
                          config_path="config/strategy.json", universe=["SZ300001", "SH600001"])
    assert report["run_id"]

    day = json.load(open(str(tmp_path / "data" / "facts" / "2026-08-14" / "strategy.json"), encoding="utf-8"))
    pool = json.load(open(str(tmp_path / "data" / "facts" / "2026-08-14" / "pool.json"), encoding="utf-8"))
    events = json.load(open(str(tmp_path / "data" / "facts" / "2026-08-14" / "events.json"), encoding="utf-8"))

    assert day  # 至少突破票命中
    for sid, entry in day.items():
        assert entry["run_id"] == report["run_id"]
        assert entry["score"] > 0
    assert pool["pools"]["alert"] or pool["pools"]["candidate"]
    assert events["events"] and events["events"][0]["type"] == "signal_hit"

    runs = json.load(open(str(tmp_path / "data" / "runs" / "strategy_runs.json"), encoding="utf-8"))
    assert report["run_id"] in runs
    assert runs[report["run_id"]]["universe"] == 2


def test_cap_alert_pool_keeps_highest_scores():
    pools = {"alert": {"A": {"score": 70}, "B": {"score": 90}, "C": {"score": 80}},
             "candidate": {"D": {"score": 50}}}
    cap_alert_pool(pools, 2)
    assert list(pools["alert"]) == ["B", "C"]
    assert set(pools["candidate"]) == {"A", "D"}
