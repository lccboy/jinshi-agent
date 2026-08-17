from services.collector.kpl_sector_realtime import (
    parse_ranking,
    parse_sub_sectors,
    parse_stocks,
)


def test_parse_ranking_uses_kpl_strength_and_money_fields():
    row = ["801001", "芯片", 8256, 2.241, 1.753, 741100390108, 20950806038,
           189582213248, -168631407210, 1.343, 28567121046420, 1.89,
           9113199319, 38985103614136, 212141277621, 67.7, 45.5, 8256, 2.241]
    sectors = parse_ranking({"list": [row], "Max": "1130", "Time": 1786939042})
    assert sectors[0]["strength"] == 8256
    assert sectors[0]["mainNet"] == 209.51
    assert sectors[0]["volume"] == 7411.0
    assert sectors[0]["rank"] == 1


def test_parse_sub_sectors_sorts_by_server_strength():
    rows = parse_sub_sectors({"List": [["801722", "存储", -10.2], ["801490", "半导体设备", 556.69]]})
    assert [x["id"] for x in rows] == ["801490", "801722"]
    assert rows[0]["strength"] == 556.69


def test_parse_stocks_keeps_reference_numeric_columns():
    row = [None] * 63
    row[0], row[1], row[2], row[4] = "300487", "蓝晓科技", "基金", "芯片、存储"
    row[5], row[6], row[7] = 12.3, 10.01, 123000000
    row[11], row[12], row[13] = 30000000, -8000000, 22000000
    row[19], row[21], row[23], row[24], row[25] = 2.1, 1.8, "首板", "一", 8.2
    row[37], row[38], row[47] = 4560000000, 5000000000, "20.1"
    stock = parse_stocks({"list": [row]})[0]
    assert stock["stock_id"] == "SZ300487"
    assert stock["amount"] == 123000000
    assert stock["main_net"] == 22000000
    assert stock["circ_market_cap"] == 4560000000
