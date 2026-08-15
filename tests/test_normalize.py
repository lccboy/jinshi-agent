# V0.1a 任务 2：normalize 核心库测试（TDD 红绿循环）
import json
import os

from services.collector.normalize import (
    clean_ps_artifact,
    merge_limitup_sources,
    normalize_limitup_multi,
    sector_type,
    stock_id,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "limitup_multi_sample.json")


def test_stock_id_market_prefix():
    assert stock_id("300487") == "SZ300487"
    assert stock_id("600000") == "SH600000"
    assert stock_id("920275") == "BJ920275"
    assert stock_id(300487) == "SZ300487"  # 数字输入也兼容


def test_sector_type_by_prefix():
    assert sector_type("801001") == "concept"
    assert sector_type("880123") == "industry"
    assert sector_type("803029") == "industry"


def test_clean_ps_artifact_parses_hashtable():
    raw = "@{reason=液冷; detail=算力(液冷)；…; concepts=液冷、汽车热管理; boards=首板; name=康盛股份; source=kpl}"
    out = clean_ps_artifact(raw)
    assert out["reason"] == "液冷"
    assert out["boards"] == "首板"
    assert out["concepts"] == "液冷、汽车热管理"
    assert out["source"] == "kpl"


def test_clean_ps_artifact_passthrough_dict():
    # 真实数据为嵌套 JSON 对象，原样透传
    assert clean_ps_artifact({"reason": "x"}) == {"reason": "x"}


def test_merge_limitup_sources_priority_and_count():
    sources = {
        "kpl": {"reason": "存储", "detail": "a", "boards": "首板", "name": "蓝晓科技"},
        "jygs": {"reason": "存储+AI", "detail": "b", "boards": "首板", "name": "蓝晓科技"},
        "ths": {"reason": "存储", "detail": "c", "boards": "首板", "name": "蓝晓科技"},
        "xgb": {"reason": "存储概念", "detail": "d", "boards": "首板", "name": "蓝晓科技"},
    }
    merged = merge_limitup_sources(sources)
    assert merged["primary"] == "kpl"
    assert merged["sourceCount"] == 4
    assert merged["sources"]["xgb"]["reason"] == "存储概念"
    assert merged["sources"]["kpl"]["detail"] == "a"  # 各源原文保留


def test_merge_limitup_sources_missing_primary_falls_back():
    sources = {"ths": {"reason": "x"}, "xgb": {"reason": "y"}}
    merged = merge_limitup_sources(sources)
    assert merged["primary"] == "ths"
    assert merged["sourceCount"] == 2


def test_merge_limitup_sources_empty():
    assert merge_limitup_sources({}) is None


def test_merge_limitup_sources_ps_string_input():
    # 防御性：某源以 PS 序列化字符串形态出现时也能合并
    sources = {
        "kpl": "@{reason=液冷; detail=d; boards=首板; name=康盛股份; source=kpl}",
        "xgb": {"reason": "液冷概念", "detail": "e", "boards": "首板", "name": "康盛股份"},
    }
    merged = merge_limitup_sources(sources)
    assert merged["primary"] == "kpl"
    assert merged["sources"]["kpl"]["reason"] == "液冷"
    assert merged["sourceCount"] == 2


def test_normalize_limitup_multi_fixture():
    with open(FIXTURE, encoding="utf-8") as fh:
        data = json.load(fh)
    out = normalize_limitup_multi(data)
    assert len(out) == 3
    for sid, entry in out.items():
        assert sid[:2] in ("SH", "SZ", "BJ")
        assert entry["primary"] in ("kpl", "jygs", "ths", "xgb")
        assert 1 <= entry["sourceCount"] <= 4
        # 清洗后 sources 不允许残留字符串形态
        for src in entry["sources"].values():
            assert isinstance(src, dict)
        assert isinstance(entry["concepts"], list)
        assert isinstance(entry["reason"], str) and entry["reason"]
