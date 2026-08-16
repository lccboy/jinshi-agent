# V0.2.3 任务 1：membership 生成测试（TDD）
from services.collector.membership_collector import build_membership, load_plate_orders, position_by_rank


def test_position_by_rank():
    assert position_by_rank(1, 50) == "龙头"
    assert position_by_rank(2, 50) == "龙头"   # 前 5%（2/50=4%）
    assert position_by_rank(6, 50) == "中军"   # 12%
    assert position_by_rank(30, 50) == "跟风"
    assert position_by_rank(0, 50) == "跟风"   # 不在板块序中


def test_build_membership():
    stocks = {
        "SZ300487": {"current": {"sectors": ["801001", "801722"], "themes": ["9"]}},
        "SH600000": {"current": {"sectors": ["801001"], "themes": []}},
    }
    sectors = {"801001": {"name": "芯片", "parent_id": None, "level": 1},
               "801722": {"name": "存储", "parent_id": "801001", "level": 2}}
    themes = {"9": {"name": "光刻机概念"}}
    orders = {"801001": ["SH600000", "SZ300487"], "801722": ["SZ300487"]}
    m = build_membership(stocks, sectors, themes, orders)
    by_type = {x["type"]: x for x in m["SZ300487"]}
    # SZ300487 在 801001 排第 2（共 2）→ 分位 100% → 跟风；在 801722 排第 1（共 1）→ 龙头
    assert by_type["sector"]["id"] == "801001" and by_type["sector"]["rank"] == 2
    assert by_type["sector"]["position"] == "跟风"
    assert by_type["subsector"]["id"] == "801722" and by_type["subsector"]["parent_id"] == "801001"
    assert by_type["subsector"]["position"] == "龙头"
    assert by_type["theme"]["name"] == "光刻机概念" and by_type["theme"]["position"] is None
    assert m["SH600000"][0]["rank"] == 1 and m["SH600000"][0]["type"] == "sector"
