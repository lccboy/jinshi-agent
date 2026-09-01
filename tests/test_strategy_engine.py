# V0.3 任务 3：策略引擎测试（合成 kline 端到端）
import datetime
import json

from services.collector.strategy_engine import (build_model_ctx, buy_point, cap_alert_pool,
                                                pool_admission, run_strategy)


def test_pool_admission_requires_valid_buy_point_and_minimum_score():
    cfg = {"strategy_pool": {"require_buy_point": True, "min_score": 70}}
    assert pool_admission({"bp_pass": True, "score": 70}, cfg) is True
    assert pool_admission({"bp_pass": True, "score": 69.9}, cfg) is False
    assert pool_admission({"bp_pass": False, "score": 99}, cfg) is False


def test_run_strategy_accepts_public_fact_and_membership_overrides(tmp_path, monkeypatch):
    from services.collector import strategy_engine

    monkeypatch.setattr(strategy_engine, "load_facts", lambda *_: (_ for _ in ()).throw(
        AssertionError("private facts must not replace supplied public facts")))
    monkeypatch.setattr(strategy_engine, "load_membership", lambda *_: (_ for _ in ()).throw(
        AssertionError("private membership must not replace supplied public membership")))
    monkeypatch.setattr(strategy_engine, "load_config", lambda *_: {"models": {}})
    result = strategy_engine.run_strategy(
        "2026-09-01", str(tmp_path / "kline"), str(tmp_path / "member"),
        facts_override={"sectors": [], "money_flow": [], "leading_reason": []},
        membership_override={"SH600000": ["S1"]}, universe=[])
    assert result["hits"] == 0


def test_strategy_config_has_nonempty_model_families_and_preserves_golden_formula():
    cfg = json.load(open("config/strategy.json", encoding="utf-8"))
    assert all(str(model.get("family") or "").strip() for model in cfg["models"].values())
    assert cfg["models"]["golden_vol"]["params"] == {"window": 3, "vol_mult": 1.2}
    assert cfg["strategy_pool"] == {"require_buy_point": True, "min_score": 70, "publish_raw": False}


def test_build_model_ctx_isolates_each_models_params():
    cfg = {"models": {
        "weekly_platform_breakout": {"params": {"volume_ratio": 1.8}},
        "weekly_double_volume": {"params": {"volume_ratio": 2.2}},
    }}
    common = {"code": "300001", "rs20": 0.05}
    breakout_ctx = build_model_ctx(common, cfg, "weekly_platform_breakout")
    double_ctx = build_model_ctx(common, cfg, "weekly_double_volume")
    assert breakout_ctx == {"code": "300001", "rs20": 0.05, "volume_ratio": 1.8}
    assert double_ctx == {"code": "300001", "rs20": 0.05, "volume_ratio": 2.2}
    assert common == {"code": "300001", "rs20": 0.05}


def test_build_model_ctx_merges_sandwich_radar_thresholds_and_model_overrides():
    cfg = {
        "auction_radar": {"sandwich": {"platform_days_min": 5, "support_tolerance": 0.03}},
        "models": {"sandwich": {"params": {
            "support_tolerance": 0.02,
            "signal_states": ["near_breakout", "second_launch"],
        }}},
    }
    ctx = build_model_ctx({"code": "300001"}, cfg, "sandwich")
    assert ctx["platform_days_min"] == 5
    assert ctx["support_tolerance"] == 0.02
    assert ctx["signal_states"] == ["near_breakout", "second_launch"]


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


def test_load_kline_asof_slices_bars(tmp_path):
    # asof 切片：只保留 d <= asof 的 bars（历史回填依赖）
    from services.collector.strategy_engine import load_kline
    bars = make_bars([10.0, 10.1, 10.2, 10.3])
    write_kline("SZ300001", bars, str(tmp_path))
    full = load_kline("SZ300001", str(tmp_path))
    assert len(full) == 4
    sliced = load_kline("SZ300001", str(tmp_path), asof=20260102)
    assert len(sliced) == 2
    assert sliced[-1]["d"] == 20260102
    assert load_kline("SZ300001", str(tmp_path), asof=20250101) == []


def test_run_strategy_asof_uses_sliced_close(tmp_path):
    # asof 重跑：买点/止损基于切片截面而非最新收盘（回填 08-03~08-13 依赖）
    kline_dir = str(tmp_path / "kline")
    out_root = str(tmp_path / "data")
    idx = make_bars([10.0 + 0.01 * i for i in range(65)])
    write_kline("SH000001", idx, kline_dir)
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260201, "o": 10.4, "h": 10.45, "l": 10.38, "c": 10.44, "v": 3_000_000, "amt": 0})
    cutoff = bars[-1]["d"]
    # 后续 5 根大涨 bar：asof 重跑必须看不到它们
    bars.extend(make_bars([20.0 + 0.1 * i for i in range(5)], vols=[9_000_000] * 5,
                          start=datetime.date(2026, 2, 2)))
    write_kline("SZ300001", bars, kline_dir)
    run_strategy("2026-02-01", kline_dir, out_root,
                 config_path="config/strategy.json", universe=["SZ300001"], asof=cutoff)
    day = json.load(open(str(tmp_path / "data" / "facts" / "2026-02-01" / "strategy.json"), encoding="utf-8"))
    assert "SZ300001" in day
    entry = day["SZ300001"]
    # 买点应锚定切片收盘 10.44 附近，而非 20+ 的最新收盘
    assert entry["buy_point"] is not None and entry["buy_point"] < 12.0


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


def test_buy_point_pass_marks_bp_pass_true():
    # 贴箱顶突破 → 过过滤，bp_pass=True
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 10.48, "h": 10.6, "l": 10.45, "c": 10.55, "v": 2_500_000, "amt": 0})
    hits = {"breakout": {"brk_pct": 0.5}}
    cfg = {"models": {"breakout": {"family": "breakout"}}, "buy_point": {"filter": {}}}
    bp = buy_point(bars, hits, cfg)
    assert bp is not None and bp["bp_pass"] is True


def test_buy_point_filter_fail_still_returns_values():
    # 远离箱顶突破（brk=20%）→ 止损距离 ~19% 过滤不通过，但买点字段仍完整返回
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260301, "o": 12.3, "h": 12.6, "l": 12.3, "c": 12.55, "v": 2_500_000, "amt": 0})
    hits = {"breakout": {"brk_pct": 20.0}}
    cfg = {"models": {"breakout": {"family": "breakout"}}, "buy_point": {"filter": {}}}
    bp = buy_point(bars, hits, cfg)
    assert bp is not None
    assert bp["bp_pass"] is False
    assert bp["stop"] and bp["buy_lo"] and bp["target"]
    assert bp["rr"] is not None


def test_run_strategy_filter_fail_entry_keeps_stop_rr(tmp_path):
    # 远离箱顶放量突破 → 过滤不通过（止损距离过大），strategy.json 仍落盘买点/止损/rr 且 bp_pass=False
    kline_dir = str(tmp_path / "kline")
    out_root = str(tmp_path / "data")
    idx = make_bars([10.0 + 0.01 * i for i in range(65)])
    write_kline("SH000001", idx, kline_dir)
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    bars.append({"d": 20260302, "o": 12.3, "h": 12.6, "l": 12.3, "c": 12.55, "v": 3_000_000, "amt": 0})
    write_kline("SZ300001", bars, kline_dir)
    run_strategy("2026-08-14", kline_dir, out_root,
                 config_path="config/strategy.json", universe=["SZ300001"])
    day = json.load(open(str(tmp_path / "data" / "facts" / "2026-08-14" / "strategy.json"), encoding="utf-8"))
    assert "SZ300001" in day
    entry = day["SZ300001"]
    assert entry["bp_pass"] is False
    assert entry["stop"] is not None and entry["buy_point"] is not None
    assert entry["stop_pct"] is not None and entry["rr"] is not None
    assert entry["score"] == max(entry["models"].values())


def test_run_strategy_end_to_end(tmp_path):
    # 一只突破票 + 一只平淡票 + 指数 → strategy/pool 输出；盘后批处理不伪装盘中事件
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

    # 盘中题材直播先于盘后策略扫描写入；策略运行不得覆盖这类只增事实。
    day_dir = tmp_path / "data" / "facts" / "2026-08-14"
    day_dir.mkdir(parents=True)
    (day_dir / "events.json").write_text(json.dumps({"data_date": "2026-08-14", "events": [{
        "ts": "2026-08-14 10:00:00", "type": "theme_live", "plate": "机器人",
        "detail": "题材直播原文", "source": "kpl_live",
    }]}, ensure_ascii=False), encoding="utf-8")

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
    admitted = {**pool["pools"]["candidate"], **pool["pools"]["alert"]}
    assert all(entry["bp_pass"] is True and entry["score"] >= 70
               for entry in admitted.values())
    assert not any(event["type"] == "signal_hit" for event in events["events"])
    assert any(event["type"] == "theme_live" for event in events["events"])

    run_strategy("2026-08-14", kline_dir, out_root,
                 config_path="config/strategy.json", universe=["SZ300001", "SH600001"])
    rerun = json.load(open(str(day_dir / "events.json"), encoding="utf-8"))["events"]
    assert not any(event.get("type") == "signal_hit" for event in rerun)
    assert sum(event.get("type") == "theme_live" for event in rerun) == 1

    runs = json.load(open(str(tmp_path / "data" / "runs" / "strategy_runs.json"), encoding="utf-8"))
    assert report["run_id"] in runs
    assert runs[report["run_id"]]["universe"] == 2


def test_run_strategy_preserves_intraday_and_manual_pool_state(tmp_path):
    kline_dir = str(tmp_path / "kline")
    out_root = str(tmp_path / "data")
    write_kline("SH000001", make_bars([10.0 + 0.01 * i for i in range(65)]), kline_dir)
    day_dir = tmp_path / "data" / "facts" / "2026-08-14"
    day_dir.mkdir(parents=True)
    existing = {
        "data_date": "2026-08-14",
        "pools": {
            "limitup": {"SH600001": {"status": "active"}},
            "ladder": {"SH600001": {"boards": "2连板"}},
            "watchlist": {"SZ300002": {"status": "watching"}},
            "alert": {"SZ300003": {"score": 70}},
            "candidate": {"SZ300004": {"signal_family": "auction_radar", "status": "candidate"}},
        },
        "removed": {"SH600002": {"exit_reason": "炸板"}},
    }
    (day_dir / "pool.json").write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    run_strategy("2026-08-14", kline_dir, out_root,
                 config_path="config/strategy.json", universe=[])
    pool = json.loads((day_dir / "pool.json").read_text(encoding="utf-8"))

    assert pool["pools"]["limitup"] == existing["pools"]["limitup"]
    assert pool["pools"]["ladder"] == existing["pools"]["ladder"]
    assert pool["pools"]["watchlist"] == existing["pools"]["watchlist"]
    assert pool["removed"] == existing["removed"]
    assert pool["pools"]["candidate"]["SZ300004"]["signal_family"] == "auction_radar"
    assert "SZ300003" not in pool["pools"]["alert"]


def test_cap_alert_pool_keeps_highest_scores():
    pools = {"alert": {"A": {"score": 70}, "B": {"score": 90}, "C": {"score": 80}},
             "candidate": {"D": {"score": 50}}}
    cap_alert_pool(pools, 2)
    assert list(pools["alert"]) == ["B", "C"]
    assert set(pools["candidate"]) == {"A", "D"}


def test_strategy_entry_carries_stop_and_rr(tmp_path):
    # 策略条目必须落盘止损位/止损%/风险回报比（前端"止损位|止损%|风险回报比"栏位依赖）
    kline_dir = str(tmp_path / "kline")
    out_root = str(tmp_path / "data")
    idx = make_bars([10.0 + 0.01 * i for i in range(65)])
    write_kline("SH000001", idx, kline_dir)
    closes = [10.0 + 0.01 * i for i in range(30)]
    bars = make_bars(closes, highs=[10.4] * 30, lows=[9.9] * 30, vols=[1_000_000] * 30)
    # 突破日：贴箱顶放量小阳（brk≈0.4%，收盘近高位，RR>3 过买点过滤）
    bars.append({"d": 20260302, "o": 10.4, "h": 10.45, "l": 10.38, "c": 10.44, "v": 3_000_000, "amt": 0})
    write_kline("SZ300001", bars, kline_dir)
    run_strategy("2026-08-14", kline_dir, out_root,
                 config_path="config/strategy.json", universe=["SZ300001"])
    day = json.load(open(str(tmp_path / "data" / "facts" / "2026-08-14" / "strategy.json"), encoding="utf-8"))
    assert "SZ300001" in day
    entry = day["SZ300001"]
    assert entry["stop"] is not None and entry["stop"] < entry["buy_point"]
    assert entry["stop_pct"] is not None and 0 < entry["stop_pct"] < 10
    assert entry["rr"] is not None and entry["rr"] > 0


def test_strategy_config_exposes_versioned_auction_radar_contract():
    from services.collector.strategy_engine import load_config

    cfg = load_config("config/strategy.json")
    radar = cfg["auction_radar"]
    assert radar["enabled"] is True
    assert radar["version"] == "1.2-auction-only"
    assert set(("trajectory", "sandwich", "quality_gate")) <= set(radar)
    assert "open_confirmation" not in radar
    assert radar["trajectory"]["final_gap_min"] == 0.01
    assert radar["trajectory"]["final_gap_max"] == 0.07
    assert radar["trajectory"]["min_auction_amount"] == 10_000_000
    assert radar["trajectory"]["min_yesterday_amount_ratio"] == 0.03
    assert radar["trajectory"]["min_yesterday_max_1m_volume_ratio"] == 1.0
    assert radar["trajectory"]["sector_sync_min"] == 2
    assert radar["quality_gate"]["fail_closed"] is True

    # 竞价前置形态不得改变用户指定的⑧金量买入参数。
    golden = cfg["models"]["golden_vol"]["params"]
    assert golden == {"window": 3, "vol_mult": 1.2}
