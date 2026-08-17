# V0.1a 任务 6：archive_job / Web 视图层测试（裁剪/预排序/gzip，TDD）
import gzip
import json
import os

from services.collector.archive_job import (
    build_day_view,
    build_detail_view,
    build_stocks_slim,
    compute_confirm,
    trim_quotes,
    write_day_view,
    write_master_lib,
    promote_day_view,
    build_kpl_sector_views,
    update_sector_trend,
)


def test_trim_quotes_drops_detail_fields():
    full = {"price": 1.0, "change": 1.0, "volRatio": 1.0, "turnover": 0.5,
            "mainNet": 100, "circMarketCap": 1000, "totalMarketCap": 1000,
            "close_seal_amount": 0, "detail_long": "x" * 1000, "popularity": 5}
    out = trim_quotes(full)
    assert "detail_long" not in out
    assert "close_seal_amount" not in out
    assert "popularity" not in out
    assert "price" in out and "volRatio" in out and "mainNet" in out


def test_compute_confirm_all_dimensions():
    # 四维共振：板块强度≥4000 ∧ 资金流入 ∧ 有领涨原因
    sectors_fact = {"801001": {"name": "芯片", "strength": 5000, "change": 3.0}}
    money_flow = {"801001": {"name": "芯片", "main": 100}}
    leading = {"801001": {"name": "芯片", "reason": "存储涨价"}}
    c = compute_confirm(["801001", "999999"], sectors_fact, money_flow, leading)
    assert c == {"sector_strength": True, "money_flow": True, "leading_reason": True}


def test_compute_confirm_missing_sector_all_false():
    c = compute_confirm(["999999"], {}, {}, {})
    assert c == {"sector_strength": False, "money_flow": False, "leading_reason": False}


def test_compute_confirm_strength_below_threshold():
    sectors_fact = {"801001": {"name": "芯片", "strength": 3000}}
    c = compute_confirm(["801001"], sectors_fact, {"801001": {"main": 100}}, {"801001": {"reason": "x"}})
    assert c["sector_strength"] is False
    assert c["money_flow"] is True and c["leading_reason"] is True


def test_build_day_view_sections():
    facts = {
        "market": {"limit_up": 52},
        "sectors": {"801001": {"name": "芯片", "strength": 5000}},
        "money_flow": {"801001": {"name": "芯片", "main": 100}},
    }
    view = build_day_view("2026-08-14", facts)
    assert view["date"] == "2026-08-14"
    assert view["market"]["limit_up"] == 52
    assert view["sectors"][0]["id"] == "801001"


def test_build_day_view_sorts_sectors_desc():
    facts = {"sectors": {"801001": {"name": "芯片", "strength": 100},
                         "801722": {"name": "存储", "strength": 500}}}
    view = build_day_view("d", facts)
    assert [s["id"] for s in view["sectors"]] == ["801722", "801001"]


def test_build_day_view_sorts_limitup_by_board_height():
    facts = {"limitup": {
        "SZ300487": {"reason": "存储", "boards": "首板", "concepts": ["存储"], "primary": "kpl", "sourceCount": 4},
        "SH600785": {"reason": "芯片", "boards": "4连板", "concepts": ["芯片"], "primary": "kpl", "sourceCount": 2},
        "SZ002636": {"reason": "3天2板", "boards": "3天2板", "concepts": [], "primary": "kpl", "sourceCount": 1},
    }}
    view = build_day_view("d", facts)
    assert view["limitup"][0]["stock_id"] == "SH600785"  # 4连板最前
    assert view["limitup"][-1]["stock_id"] == "SZ300487"  # 首板最后


def test_build_day_view_includes_stock_name():
    facts = {
        "stock_names": {"SZ300487": "蓝晓科技"},
        "limitup": {"SZ300487": {"reason": "存储", "boards": "首板"}},
    }
    view = build_day_view("2026-08-14", facts)
    assert view["limitup"][0]["name"] == "蓝晓科技"


def test_build_day_view_counts_daily_limitups_by_theme():
    facts = {
        "limitup": {"SZ300487": {}, "SH600000": {}},
        "theme_stocks": {
            "9": ["SZ300487", "SH600000", "SH600519"],
            "13": ["SH600519"],
        },
    }
    view = build_day_view("2026-08-14", facts)
    assert view["theme_limitup"]["9"] == ["SH600000", "SZ300487"]
    assert view["theme_limitup"]["13"] == []


def test_build_day_view_counts_limitups_by_main_and_sub_concept():
    facts = {
        "limitup": {"SZ300487": {}, "SH600000": {}},
        "theme_stocks": {"9": ["SZ300487", "SH600000"]},
        "themes": {"9": {"tree": [
            {"n1": "设备", "st": [], "l2": [
                {"n2": "光刻机", "st": ["SZ300487", "SH600000"]},
                {"n2": "清洗设备", "st": ["SH600000"]},
            ]},
            {"n1": "材料", "st": ["SZ300487"], "l2": []},
            {"n1": "无涨停", "st": ["SH600519"], "l2": []},
        ]}},
    }
    view = build_day_view("2026-08-14", facts)
    concepts = view["theme_concept_limitup"]["9"]
    assert [(x["level"], x["name"], len(x["stock_ids"])) for x in concepts] == [
        (1, "设备", 2), (2, "光刻机", 2), (1, "材料", 1), (2, "清洗设备", 1)
    ]


def test_build_day_view_skips_missing_sections():
    view = build_day_view("2026-08-14", {})
    assert view["date"] == "2026-08-14"
    assert view["sectors"] == [] and view["limitup"] == []
    assert view["market"] == {}
    assert view["events"] == []


def test_build_day_view_events_sorted_desc():
    # 事件流裁剪字段 + 按时间倒序（最新在前，上限 200）
    facts = {"events": [
        {"ts": "2026-08-14T09:35:03", "type": "limitup", "stock_id": "SZ300487",
         "score": 92, "detail": "涨停", "source": "tencent", "price": 12.0},
        {"ts": "2026-08-14T10:47:00", "type": "broken", "stock_id": "SZ002636",
         "score": 0, "detail": "炸板"},
    ]}
    view = build_day_view("2026-08-14", facts)
    assert view["events"][0]["ts"].startswith("2026-08-14T10:47")
    assert view["events"][0]["type"] == "broken"
    assert set(view["events"][0]) == {"ts", "type", "stock_id", "score", "detail"}  # 字段裁剪
    assert "price" not in view["events"][0]


def test_day_view_gzip_roundtrip():
    facts = {"sectors": {f"801{i:03d}": {"name": f"板块{i}", "strength": 1000 + i, "change": 1.0, "mainNet": 100}
                         for i in range(300)}}
    view = build_day_view("2026-08-14", facts)
    raw = json.dumps(view, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(raw)
    assert len(compressed) < len(raw) * 0.5  # gzip 必须有效（DATA_MODEL §13）


def test_write_day_view_files(tmp_path):
    view = {"date": "2026-08-14", "sectors": []}
    write_day_view("2026-08-14", view, str(tmp_path))
    assert (tmp_path / "day_2026-08-14.json").exists()
    assert (tmp_path / "day_2026-08-14.json.gz").exists()
    assert (tmp_path / "day_latest.json").exists()
    with open(tmp_path / "index.json", encoding="utf-8") as fh:
        idx = json.load(fh)
    assert "2026-08-14" in [d["date"] for d in idx["days"]]


def test_build_detail_view_keeps_sources():
    # V0.1b 任务 1：懒加载 detail 文件保留涨停原因原文与 4 源
    facts = {"limitup": {"SZ300487": {"reason": "存储", "detail": "长文…", "primary": "kpl",
                                      "sourceCount": 4, "sources": {"kpl": {"reason": "存储"},
                                                                     "xgb": {"reason": "存储概念"}}}}}
    detail = build_detail_view("2026-08-14", facts)
    assert detail["date"] == "2026-08-14"
    entry = detail["limitup"]["SZ300487"]
    assert entry["detail"] == "长文…"
    assert entry["sources"]["kpl"]["reason"] == "存储"
    assert entry["sourceCount"] == 4


def test_write_detail_view_files(tmp_path):
    detail = {"date": "2026-08-14", "limitup": {"SZ300487": {"detail": "x" * 500}}}
    from services.collector.archive_job import write_detail_view

    paths = write_detail_view("2026-08-14", detail, str(tmp_path))
    assert (tmp_path / "day_2026-08-14.detail.json").exists()
    assert (tmp_path / "day_2026-08-14.detail.json.gz").exists()
    gz = gzip.open(tmp_path / "day_2026-08-14.detail.json.gz", "rt", encoding="utf-8")
    assert json.load(gz)["date"] == "2026-08-14"


def test_build_stocks_slim():
    # V0.3.0：成分股 slim（名称+归属 ID，裁剪体积）
    stocks = {"SZ300487": {"name": "蓝晓科技", "current": {"sectors": ["801001"], "themes": ["9"]}},
              "SH600000": {"name": "浦发银行", "current": {}}}
    slim = build_stocks_slim(stocks)
    assert slim["SZ300487"] == {"n": "蓝晓科技", "s": ["801001"], "t": ["9"]}
    assert slim["SH600000"] == {"n": "浦发银行", "s": [], "t": []}


def test_build_stocks_slim_excludes_source_missing():
    stocks = {"SZ300487": {"name": "蓝晓科技", "status": "active", "current": {}},
              "SH600000": {"name": "旧记录", "status": "source_missing", "current": {}}}
    assert set(build_stocks_slim(stocks)) == {"SZ300487"}


def test_write_master_lib(tmp_path):
    # normalized 字典 → web/ 出 4 个 .json + .gz（懒加载主数据）
    norm = tmp_path / "normalized"
    norm.mkdir()
    (norm / "themes.json").write_text(json.dumps({"9": {"name": "光刻机"}}), encoding="utf-8")
    (norm / "theme_stocks.json").write_text(json.dumps({"9": ["SZ300487"]}), encoding="utf-8")
    (norm / "sectors.json").write_text(json.dumps({"801001": {"name": "芯片"}}), encoding="utf-8")
    (norm / "stocks.json").write_text(
        json.dumps({"SZ300487": {"name": "蓝晓科技", "current": {"sectors": ["801001"], "themes": ["9"]}}}),
        encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    write_master_lib(str(norm), str(web))
    for name in ("themes.json", "theme_stocks.json", "sectors.json", "stocks_slim.json"):
        assert (web / name).exists(), name
        assert (web / (name + ".gz")).exists(), name + ".gz"
    slim = json.loads((web / "stocks_slim.json").read_text(encoding="utf-8"))
    assert slim["SZ300487"]["n"] == "蓝晓科技"


def test_day_view_can_be_staged_without_publishing_latest(tmp_path):
    view = {"date": "2026-08-17", "sectors": [], "limitup": []}
    write_day_view("2026-08-17", view, str(tmp_path), publish_latest=False)
    assert (tmp_path / "day_2026-08-17.json").exists()
    assert not (tmp_path / "day_latest.json").exists()
    promote_day_view("2026-08-17", str(tmp_path))
    assert json.loads((tmp_path / "day_latest.json").read_text(encoding="utf-8"))["date"] == "2026-08-17"


def test_promote_day_view_is_atomic_and_requires_staged_file(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        promote_day_view("2026-08-17", str(tmp_path))


def test_build_day_view_caps_large_pools():
    pool = {"data_date": "2026-08-17", "pools": {
        "alert": {f"A{i}": {"score": i} for i in range(50)},
        "candidate": {f"C{i}": {"score": i} for i in range(150)},
        "limitup": {}, "ladder": {}, "watchlist": {},
    }}
    view = build_day_view("2026-08-17", {"pool": pool})
    assert len(view["pools"]["pools"]["alert"]) == 30
    assert len(view["pools"]["pools"]["candidate"]) == 100
    assert next(iter(view["pools"]["pools"]["candidate"])) == "C149"


def test_build_kpl_sector_views_keeps_reference_fields_and_children():
    daily = {"sectors": [{"id": "801001", "name": "芯片", "strength": 8256, "change": 3.2,
                           "volume": 1200, "mainNet": 209.5, "marketCap": 30000,
                           "rank": 1, "zt": 41, "up6": 61, "n": 300}],
             "sub": {"801001": [{"id": "801490", "name": "半导体设备", "strength": 4500}]}}
    stocks = {"stocks": {"801001": [{"code": "300487", "name": "蓝晓科技", "price": 12.3,
                                        "change": 10.01, "turnover": 8.2, "volume": 123000000,
                                        "mainNet": 22000000, "volRatio": 1.8, "position": "一",
                                        "netFlowRatio": 2.1, "boards": "首板", "pe1": "20.1",
                                        "circMarketCap": 4560000000}],
                           "801490": [{"code": "300487", "name": "蓝晓科技", "change": 10.01}]}}
    sectors, detail = build_kpl_sector_views(daily, stocks)
    assert sectors[0]["limit_up_count"] == 41 and sectors[0]["up6_count"] == 61
    assert sectors[0]["stock_count"] == 300
    assert sectors[0]["sub_sectors"][0] == {"id": "801490", "name": "半导体设备", "strength": 4500}
    assert detail["plates"]["801001"][0]["stock_id"] == "SZ300487"
    assert detail["plates"]["801001"][0]["circ_market_cap"] == 4560000000
    assert detail["plates"]["801490"][0]["change"] == 10.01


def test_build_kpl_sector_views_backfills_missing_limit_counts_from_plate_stocks():
    daily = {"sectors": [{"id": "801001", "name": "芯片", "strength": 100}], "sub": {}}
    stocks = {"stocks": {"801001": [
        {"code": "000001", "name": "甲", "change": 10.01},
        {"code": "300001", "name": "乙", "change": 7.2},
        {"code": "600001", "name": "丙", "change": 1.2},
    ]}}
    sectors, _ = build_kpl_sector_views(daily, stocks)
    assert sectors[0]["limit_up_count"] == 1
    assert sectors[0]["up6_count"] == 1
    assert sectors[0]["stock_count"] == 3


def test_update_sector_trend_keeps_latest_ten_trading_days():
    idx = {"days": [{"date": f"2026-08-{day:02d}"} for day in range(1, 13)]}
    views = {d["date"]: {"sectors": [{"id": "801001", "name": "芯片", "rank": 1,
                                        "limit_up_count": int(d["date"][-2:])}]} for d in idx["days"]}
    update_sector_trend(idx, views)
    assert len(idx["sector_trend"]) == 10
    assert idx["sector_trend"][0]["date"] == "2026-08-12"
    assert idx["sector_trend"][0]["top"][0]["limit_up_count"] == 12
