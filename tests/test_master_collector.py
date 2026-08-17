# V0.1a 任务 3：master_collector 测试（离线模式，纯函数 TDD）
from services.collector.master_collector import (
    build_sectors_from_daily,
    build_stock_record,
    collect_from_rows,
    derive_market_board,
    diff_universe,
    is_st,
    merge_universe,
    read_kpl_stocks_file,
    verify,
    backfill_list_dates_from_vipdoc,
)


def test_build_sectors_from_daily():
    # kpl_<date>.json（sectors + sub）→ 板块/子板块字典（DATA_MODEL §3.3）
    daily = {"sectors": [{"id": "801001", "name": "芯片"}, {"id": "880123", "name": "行业X"}],
             "sub": {"801001": [{"id": "801722", "name": "存储"}]}}
    secs = build_sectors_from_daily(daily)
    assert secs["801001"]["level"] == 1 and secs["801001"]["parent_id"] is None
    assert secs["801001"]["type"] == "concept"
    assert secs["880123"]["type"] == "industry"
    assert secs["801722"]["level"] == 2 and secs["801722"]["parent_id"] == "801001"
    assert secs["801722"]["type"] == "concept"
    assert all(v["source"] == "kpl" for v in secs.values())


def test_read_kpl_stocks_file_flattens_dict(tmp_path):
    # 现网 kpl_<date>_stocks.json 为 {板块ID: [成分股行]}，需展平并补 _blockId
    raw = {
        "t": "2026-08-14 10:11:32",
        "stocks": {
            "801001": [{"code": "300487", "name": "蓝晓科技"}],
            "801722": [{"code": "300487", "name": "蓝晓科技"}, {"code": "600000", "name": "浦发银行"}],
        },
    }
    path = tmp_path / "kpl_stocks.json"
    import json

    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    rows, t = read_kpl_stocks_file(str(path))
    assert t == "2026-08-14 10:11:32"
    assert len(rows) == 3
    assert rows[1]["_blockId"] == "801722"  # 第二只行无 _blockId 时按板块补
    assert {r["code"] for r in rows} == {"300487", "600000"}


def test_merge_universe_dedup():
    rows = [
        {"code": "300487", "name": "蓝晓科技", "_blockId": "801001"},
        {"code": "300487", "name": "蓝晓科技", "_blockId": "801722"},
        {"code": "600000", "name": "浦发银行", "_blockId": "801001"},
    ]
    uni = merge_universe(rows)
    assert len(uni) == 2
    assert set(uni["SZ300487"]["sectors"]) == {"801001", "801722"}
    assert uni["SH600000"]["name"] == "浦发银行"


def test_merge_universe_skips_bad_codes():
    rows = [
        {"code": "300487", "name": "蓝晓科技", "_blockId": "801001"},
        {"code": "", "name": "空代码", "_blockId": "801001"},
        {"code": "000000", "name": "无效", "_blockId": "801001"},
        {"code": "110075", "name": "可转债", "_blockId": "801001"},
    ]
    uni = merge_universe(rows)
    assert len(uni) == 1


def test_derive_market_board():
    assert derive_market_board("600000") == ("SH", "主板")
    assert derive_market_board("688176") == ("SH", "科创板")
    assert derive_market_board("000001") == ("SZ", "主板")
    assert derive_market_board("300487") == ("SZ", "创业板")
    assert derive_market_board("920275") == ("BJ", "北交所")


def test_is_st():
    assert is_st("ST凯利") is True
    assert is_st("*ST尔雅") is True
    assert is_st("浦发银行") is False


def test_build_stock_record_shape():
    # 字段形状符合 DATA_MODEL §3.1
    rec = build_stock_record("300487", "蓝晓科技", {"801001", "801722"}, "2026-08-16")
    assert rec["stock_id"] == "SZ300487"
    assert rec["code"] == "300487"
    assert rec["market"] == "SZ" and rec["board"] == "创业板"
    assert rec["treeid"] == "300487" and rec["hexin"] == "300487"
    assert rec["is_st"] is False
    assert rec["current"]["sectors"] == ["801001", "801722"]  # 排序稳定
    assert rec["current"]["themes"] == []
    assert rec["updated_at"] == "2026-08-16"


def test_build_stock_record_derives_industry_from_industry_sector():
    sectors = {
        "801001": {"name": "芯片", "type": "concept"},
        "880301": {"name": "基础化工", "type": "industry"},
    }
    rec = build_stock_record("300487", "蓝晓科技", {"801001", "880301"}, "2026-08-17", sectors)
    assert rec["industry"] == "基础化工"


def test_diff_universe_detects_changes():
    prev = {
        "SZ300487": build_stock_record("300487", "蓝晓科技", {"801001"}, "2026-08-15"),
        "SH600000": build_stock_record("600000", "浦发银行", {"801001"}, "2026-08-15"),
    }
    new = {
        "SZ300487": {"code": "300487", "name": "蓝晓科技", "sectors": {"801001", "801722"}},
        "SH600000": {"code": "600000", "name": "浦发银行", "sectors": {"801001"}},
        "BJ920275": {"code": "920275", "name": "驱动力", "sectors": {"801045"}},
    }
    ch = diff_universe(prev, new)
    assert ch["added"] == ["BJ920275"]
    assert ch["renamed"] == []
    assert ch["st"] == []
    assert ch["sectors"] == ["SZ300487"]


def test_diff_universe_detects_rename_and_st():
    prev = {
        "SH600000": build_stock_record("600000", "浦发银行", {"801001"}, "2026-08-15"),
    }
    new = {
        "SH600000": {"code": "600000", "name": "ST浦发", "sectors": {"801001"}},
    }
    ch = diff_universe(prev, new)
    assert ch["renamed"] == ["SH600000"]
    assert ch["st"] == ["SH600000"]


def test_incremental_merge_preserves_supplemental_fields_and_history(tmp_path):
    import json
    out = tmp_path / "normalized"
    out.mkdir()
    previous = {
        "SZ300487": {**build_stock_record("300487", "蓝晓科技", {"801001"}, "2026-08-16"),
                       "list_date": "2015-07-02", "industry": "基础化工",
                       "sources": {"listing": {"source": "tdx"}}},
        "SH600000": build_stock_record("600000", "浦发银行", {"880001"}, "2026-08-16"),
    }
    previous["SZ300487"]["current"]["themes"] = ["9"]
    (out / "stocks.json").write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
    rows = [{"code": "300487", "name": "蓝晓股份", "_blockId": "801002"}]
    _, changes = collect_from_rows(rows, str(out), updated_at="2026-08-17", mode="incr")
    current = json.loads((out / "stocks.json").read_text(encoding="utf-8"))
    rec = current["SZ300487"]
    assert rec["current"]["themes"] == ["9"]
    assert rec["list_date"] == "2015-07-02" and rec["industry"] == "基础化工"
    assert rec["sources"]["listing"]["source"] == "tdx"
    assert rec["name_history"][-1]["name"] == "蓝晓科技"
    assert current["SH600000"]["source_status"]["kpl"] == "missing"
    assert current["SH600000"]["status"] == "source_missing"
    assert rec["status"] == "active" and rec["last_seen"] == "2026-08-17"
    assert changes["removed"] == ["SH600000"]


def test_incremental_rejects_implausibly_empty_primary_source(tmp_path):
    import json
    import pytest
    out = tmp_path / "normalized"
    out.mkdir()
    previous = {f"SH60{i:04d}": build_stock_record(f"60{i:04d}", f"股票{i}", {"801001"}, "2026-08-16")
                for i in range(100)}
    path = out / "stocks.json"
    path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="主源股票池异常"):
        collect_from_rows([], str(out), updated_at="2026-08-17", mode="incr")
    assert path.read_bytes() == before


def test_verify_reports_master_data_coverage():
    records = {
        "SZ300487": {**build_stock_record("300487", "蓝晓科技", {"801001"}, "2026-08-17"),
                       "industry": "基础化工", "list_date": "2015-07-02"},
        "SH600000": build_stock_record("600000", "浦发银行", set(), "2026-08-17"),
    }
    ok, report = verify(records, sectors={"801001": {"type": "concept"}})
    assert ok
    assert report["stocks_without_sectors"] == 1
    assert report["stocks_without_industry"] == 1
    assert report["stocks_without_list_date"] == 1
    assert report["sector_coverage"] == 0.5
    assert report["sector_types"] == {"concept": 1}


def test_fetch_plates_uses_offset_pagination(monkeypatch):
    from services.collector import master_collector as mc
    indexes = []

    def fake_request(params):
        indexes.append(params["Index"])
        if params["Index"] == "0":
            row = ["881172", "电子化学品"] if params["ZSType"] == "4" else ["801001", "芯片"]
            return {"list": [row] * 30}
        return {"list": []}

    monkeypatch.setattr(mc, "_request", fake_request)
    plates = mc.fetch_plates()
    assert indexes == ["0", "30", "0", "30"]
    assert plates[0]["type"] == "concept"
    assert next(p for p in plates if p["id"] == "881172")["type"] == "industry"


def test_fetch_stocks_uses_history_endpoint(monkeypatch):
    from services.collector import master_collector as mc
    bases = []

    def fake_request(params, base=None):
        bases.append(base)
        return {"list": [["300487", "蓝晓科技"]]}

    monkeypatch.setattr(mc, "_request", fake_request)
    rows = mc.fetch_stocks("801001", "2026-08-14")
    assert rows == [{"code": "300487", "name": "蓝晓科技", "_blockId": "801001"}]
    assert set(bases) == {mc.KPL_HIS_BASE}


def test_backfill_list_dates_from_vipdoc(tmp_path):
    import shutil
    root = tmp_path / "vipdoc"
    day_dir = root / "sh" / "lday"
    day_dir.mkdir(parents=True)
    shutil.copyfile("tests/fixtures/600000_5bars.day", day_dir / "sh600000.day")
    records = {"SH600000": build_stock_record("600000", "浦发银行", set(), "2026-08-17"),
               "SZ000001": build_stock_record("000001", "平安银行", set(), "2026-08-17")}
    report = backfill_list_dates_from_vipdoc(records, str(root))
    assert records["SH600000"]["list_date"] == "2026-08-10"
    assert records["SH600000"]["sources"]["listing"]["source"] == "tdx_vipdoc"
    assert report == {"updated": 1, "missing": 1, "invalid": 0}
