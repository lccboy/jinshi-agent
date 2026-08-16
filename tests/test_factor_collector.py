# V0.1a 任务 5：factor_collector 测试（板块因子映射，纯函数 TDD）
from services.collector.factor_collector import (
    build_sector_map,
    compute_ranks,
    map_em_flow,
    map_leading_reason,
)


def test_map_em_flow_fields():
    # 东财 clist 行 → money_flow 记录（DATA_MODEL §4.14 字段）
    row = {"f12": "BK1036", "f14": "芯片", "f2": 1234.5, "f3": 3.98,
           "f62": 8437255508, "f184": 3.2,
           "f66": 5123456789, "f69": 1.9, "f72": 3313798719, "f75": 1.3,
           "f78": -123456789, "f81": -0.1, "f84": -876543210, "f87": -0.3}
    out = map_em_flow(row)
    assert out["em_code"] == "BK1036"
    assert out["name"] == "芯片"
    assert out["main"] == 8437255508 and out["main_pct"] == 3.2
    assert out["super"] == 5123456789 and out["big"] == 3313798719
    assert out["mid"] == -123456789 and out["small"] == -876543210


def test_map_em_flow_missing_fields_default():
    out = map_em_flow({"f12": "BK1036", "f14": "芯片"})
    assert out["main"] == 0 and out["main_pct"] == 0.0


def test_map_leading_reason():
    p = {"plate_id": "1234", "name": "存储", "description": "存储涨价", "limit_up_count": 5}
    out = map_leading_reason(p)
    assert out["xgb_id"] == "1234"
    assert out["name"] == "存储"
    assert out["reason"] == "存储涨价"
    assert out["limit_up_count"] == 5


def test_map_leading_reason_id_key():
    # 选股宝实际响应 key 为 id（非 plate_id）
    p = {"id": 18129294, "name": "光通信", "description": "龙头业绩超预期"}
    out = map_leading_reason(p)
    assert out["xgb_id"] == "18129294"
    assert out["reason"] == "龙头业绩超预期"
    assert out["limit_up_count"] == 0


def test_build_sector_map_exact_and_normalized():
    kpl = {"801001": {"name": "芯片"}, "801722": {"name": "存储"}, "803023": {"name": "AI应用"}}
    em = [{"em_code": "BK1036", "name": "芯片"}, {"em_code": "BK0001", "name": "存储"}]
    reasons = [{"xgb_id": "1234", "name": "存储"}]
    mapping, report = build_sector_map(kpl, em, reasons)
    assert mapping["801001"]["em_code"] == "BK1036"
    assert mapping["801722"]["em_code"] == "BK0001"
    assert mapping["801722"]["xgb_id"] == "1234"
    assert mapping["803023"]["em_code"] is None
    assert report["em_matched"] == 2 and report["xgb_matched"] == 1
    assert report["em_unmatched"] == 1


def test_build_sector_map_suffix_normalization():
    # 名称含"概念/板块"后缀差异也能匹配（两边去掉后缀再比）
    kpl = {"801159": {"name": "机器人概念"}}
    em = [{"em_code": "BK0800", "name": "机器人概念"}]
    reasons = [{"xgb_id": "99", "name": "机器人"}]
    mapping, report = build_sector_map(kpl, em, reasons)
    assert mapping["801159"]["em_code"] == "BK0800"
    assert mapping["801159"]["xgb_id"] == "99"


def test_build_sector_map_alias_table():
    # KPL 题材名 ↔ 东财行业名不同体系，靠别名表命中
    kpl = {"801001": {"name": "芯片"}, "801660": {"name": "通信"}}
    em = [{"em_code": "BK1036", "name": "半导体"}, {"em_code": "BK1234", "name": "通信设备"}]
    aliases = {"em": {"芯片": "半导体", "通信": "通信设备"}}
    mapping, report = build_sector_map(kpl, em, [], aliases)
    assert mapping["801001"]["em_code"] == "BK1036"
    assert mapping["801660"]["em_code"] == "BK1234"
    assert report["em_alias_hit"] == 2
    assert report["em_matched"] == 2


def test_build_sector_map_exact_beats_alias():
    # 解析顺序：精确名优先于别名
    kpl = {"801001": {"name": "芯片"}}
    em = [{"em_code": "BK_EXACT", "name": "芯片"}, {"em_code": "BK_ALIAS", "name": "半导体"}]
    aliases = {"em": {"芯片": "半导体"}}
    mapping, _ = build_sector_map(kpl, em, [], aliases)
    assert mapping["801001"]["em_code"] == "BK_EXACT"


def test_compute_ranks():
    flows = [
        {"name": "芯片", "main": 100},
        {"name": "存储", "main": 50},
        {"name": "AI应用", "main": -10},
    ]
    ranked = compute_ranks(flows)
    assert ranked[0]["rank_in"] == 1 and ranked[2]["rank_in"] == 3
    assert ranked[0]["main_pct_rank"] == 1
