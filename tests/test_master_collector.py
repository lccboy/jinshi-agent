# V0.1a 任务 3：master_collector 测试（离线模式，纯函数 TDD）
from services.collector.master_collector import (
    build_stock_record,
    derive_market_board,
    diff_universe,
    is_st,
    merge_universe,
    read_kpl_stocks_file,
)


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
