# V0.2.2 任务 2：theme_collector 测试（题材字典解析，TDD）
import json
import os

from services.collector.theme_collector import collect, discover_theme_source, merge_themes_into_master, parse_theme_dump


def test_parse_theme_dump():
    dump = {"9": {"n": "光刻机概念", "l": 1,
                  "t": [{"n1": "电子特气", "st": [{"c": "002971", "r": "试生产"}],
                         "l2": [{"n2": "二氯二氢硅", "st": [{"c": "603938", "r": "批量"}]}]}],
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
    # 概念层级树：n1 → l2 → 成分股
    assert t["tree"][0]["n1"] == "电子特气"
    assert t["tree"][0]["st"] == ["SZ002971"]
    assert t["tree"][0]["l2"][0]["n2"] == "二氯二氢硅"
    assert t["tree"][0]["l2"][0]["st"] == ["SH603938"]


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


def test_merge_themes_replaces_old_memberships():
    stocks = {
        "SZ300487": {"stock_id": "SZ300487", "code": "300487", "name": "蓝晓科技",
                       "current": {"themes": ["old", "9"], "sectors": []}},
        "SH600000": {"stock_id": "SH600000", "code": "600000", "name": "浦发银行",
                       "current": {"themes": ["old"], "sectors": []}},
    }
    out = merge_themes_into_master(stocks, {"9": {"name": "光刻机"}},
                                   {"9": ["SZ300487"]}, {}, "2026-08-17")
    assert out["SZ300487"]["current"]["themes"] == ["9"]
    assert out["SH600000"]["current"]["themes"] == []


def test_discover_theme_source_prefers_live_file(tmp_path):
    live = tmp_path / "all_themes_slim.json"
    backup = tmp_path / ".deploy_backups" / "old" / "all_themes_slim.json"
    backup.parent.mkdir(parents=True)
    live.write_text("{}", encoding="utf-8")
    backup.write_text("{}", encoding="utf-8")
    assert discover_theme_source(str(tmp_path)) == str(live)


def test_collect_records_source_freshness_in_manifest(tmp_path):
    source = tmp_path / "all_themes_slim.json"
    source.write_text(json.dumps({"9": {"n": "光刻机", "t": [], "s": []}}, ensure_ascii=False), encoding="utf-8")
    source_ts = 1786500000  # 固定源文件时间，不能被采集当天覆盖
    os.utime(source, (source_ts, source_ts))
    out = tmp_path / "data" / "normalized"
    report = collect(str(source), str(out), collected_at="2026-08-17T09:00:00+08:00")
    theme = json.loads((out / "themes.json").read_text(encoding="utf-8"))["9"]
    manifest = json.loads((tmp_path / "data" / "manifest.json").read_text(encoding="utf-8"))["themes"]
    assert theme["updated_at"] == manifest["source_updated_at"][:10]
    assert manifest["collected_at"] == "2026-08-17T09:00:00+08:00"
    assert manifest["source_path"] == str(source.resolve())
    assert len(manifest["source_hash"]) == 64
    assert manifest["count"] == report["themes"] == 1
