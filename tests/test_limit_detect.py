# V0.3 任务 2：涨停检测测试（TDD）
# 规则依据 docs/DATA_MODEL.md §10：腾讯涨停价字段优先 + 板块/ST 阈值规则推导兜底
from services.collector.limit_detect import (
    cross_validate,
    is_limit_up,
    limit_price,
    rule_limit_up,
)


# ---------- 规则推导（DATA_MODEL §10 表） ----------

def test_limit_price_main_board():
    # 主板 10%：60/00 前缀
    assert limit_price(10.0, "600000") == 11.0
    assert limit_price(10.0, "000001") == 11.0
    # 四舍五入到分：2.5 × 1.1 = 2.75
    assert limit_price(2.5, "600000") == 2.75
    # 低价股边界：1.21 × 1.1 = 1.331 → round 1.33（低价股涨幅可能 <9.8%，固定阈值会漏检）
    assert limit_price(1.21, "600000") == 1.33


def test_limit_price_st_boards():
    # ST 主板 5%；创业板/科创板/北交所 ST 不降（20%/30%）
    assert limit_price(10.0, "600000", is_st=True) == 10.5
    assert limit_price(10.0, "000001", is_st=True) == 10.5
    assert limit_price(10.0, "300001", is_st=True) == 12.0   # 创业板 20%
    assert limit_price(10.0, "688001", is_st=True) == 12.0   # 科创板 20%
    assert limit_price(10.0, "830799", is_st=True) == 13.0   # 北交所 30%


def test_limit_price_gem_star_bj():
    assert limit_price(10.0, "300487") == 12.0   # 创业板 20%
    assert limit_price(10.0, "688001") == 12.0   # 科创板 20%
    assert limit_price(10.0, "830799") == 13.0   # 北交所 30%
    assert limit_price(10.0, "920083") == 13.0   # 北交所 30%


# ---------- 判定 ----------

def test_is_limit_up_tencent_field_priority():
    # 腾讯涨停价字段优先：现价≥涨停价−0.01 容差 → 涨停
    assert is_limit_up(11.0, 10.0, "600000", tencent_limit_up=11.0) is True
    assert is_limit_up(10.99, 10.0, "600000", tencent_limit_up=11.0) is True   # 容差内
    assert is_limit_up(10.98, 10.0, "600000", tencent_limit_up=11.0) is False
    # 字段缺失（0）→ 规则推导
    assert is_limit_up(11.0, 10.0, "600000", tencent_limit_up=0) is True
    assert is_limit_up(10.98, 10.0, "600000", tencent_limit_up=0) is False


def test_is_limit_up_st():
    # ST 主板 5%：现价 10.5 涨停；10.4 不涨停
    assert is_limit_up(10.5, 10.0, "600000", is_st=True) is True
    assert is_limit_up(10.4, 10.0, "600000", is_st=True) is False


def test_is_limit_up_gem():
    # 创业板 20%：11.98 未到 12.0（差 0.02 > 容差）
    assert is_limit_up(11.98, 10.0, "300487") is False
    assert is_limit_up(12.0, 10.0, "300487") is True
    # 11.99 = 12.0 − 0.01，在容差内 → 涨停
    assert is_limit_up(11.99, 10.0, "300487") is True


def test_rule_limit_up_new_stock():
    # 新股（名称含 N / 上市≤5日）不判涨停 → None
    assert rule_limit_up(15.0, 10.0, "600000", is_new=True) is None


# ---------- 双源交叉验证（§10） ----------

def test_cross_validate():
    kpl_set = {"SH600000", "SZ300487"}
    tencent_set = {"SZ300487", "SH688001"}
    result = cross_validate(kpl_set, tencent_set)
    # 双源都有 → both；仅腾讯 → tencent（KPL 缺失）；仅 KPL → kpl（疑似炸板）
    assert result["SZ300487"] == "both"
    assert result["SH688001"] == "tencent"
    assert result["SH600000"] == "kpl"


def test_cross_validate_empty():
    assert cross_validate(set(), set()) == {}
    assert cross_validate({"SH600000"}, set()) == {"SH600000": "kpl"}
    assert cross_validate(set(), {"SH600000"}) == {"SH600000": "tencent"}
