# V0.2.2 任务 2：theme_collector 测试（题材字典解析，TDD）
import datetime

from services.collector.theme_collector import merge_themes_into_master, parse_theme_dump


def test_parse_theme_dump():
    dump = {"9": {"n": "光刻机概念", "l": 1,
                  "t": [{"n1": "电子特气", "st": [], "l2": [{"n2": "二氯二氢硅", "st": []}]}],
                  "s": [{"c": "600895", "n": "张江高科", "h": 386},
                        {"c": "300487", "n": "蓝晓科技", "h": 100}]}}
    themes, theme_stocks, names = parse_theme_dump(dump, "2026-08-16")
    t = themes["9"]
    assert t["name"] == "光刻机概念"
    assert "电子特气" in t["sub_concepts"] and "二氯二氢硅" in t["sub_concepts"]
    assert t["hot"] == 243  # (386+100)/2
    assert t["stock_count"] == 2
    assert t["source"] == "题材库" and t["updated_at"] == "2026-08-16"
    assert theme_stocks["9"] == ["SH600895", "SZ300487"]
    assert names["SH600895"] == "张江高科"


def test_parse_theme_dump_ignores_empty():
    dump = {"1": {"n": "", "t": [], "s": []}}
    themes, theme_stocks, _ = parse_theme_dump(dump, "2026-08-16")
    assert "1" in themes  # 保留空题材条目但无成分
    assert theme_stocks["1"] == []


def test_merge_themes_into_master():
    stocks = {"SZ300487": {"stock_id": "SZ300487", "code": "300487", "name": "蓝晓科技",
                           "market": "SZ", "board": "创业板", "treeid": "300487", "hexin": "300487",
                           "is_st": False, "current": {"themes": ["9"], "sectors": ["801001"],
                                                       "updated_at": "2026-08-15"}, "updated_at": "2026-08-15"}}
    themes = {"9": {"name": "光刻机概念"}}
    theme_stocks = {"9": ["SZ300487", "SH600895"]}
    names = {"SH600895": "张江高科"}
    out = merge_themes_into_master(stocks, themes, theme_stocks, names, "2026-08-16")
    assert "SH600895" in out  # 缺失个股被补入
    assert out["SH600895"]["name"] == "张江高科"
    assert out["SZ300487"]["current"]["themes"] == ["9"]  # 去重不回写重复
    assert out["SH600895"]["current"]["themes"] == ["9"]
    assert out["SH600895"]["market"] == "SH"  # 推导字段完整
