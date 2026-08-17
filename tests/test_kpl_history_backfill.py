from services.collector.kpl_history_backfill import (
    merge_ranking_pages,
    parse_plate_stats,
    parse_stock_rows,
    parse_sub_sectors,
)


def test_merge_ranking_pages_deduplicates_overlapping_index_windows():
    pages = [
        {"list": [["801001", "芯片", 9000, 2.1, 0, 100000000, 20000000, 0, 0, 0, 3000000000,
                    0, 0, 0, 0, 0, 0, 9000, 2.1],
                   ["801002", "算力", 8000, 1.8, 0, 90000000, 10000000, 0, 0, 0, 2000000000,
                    0, 0, 0, 0, 0, 0, 8000, 1.8]]},
        {"list": [["801002", "算力", 8000, 1.8, 0, 90000000, 10000000, 0, 0, 0, 2000000000,
                    0, 0, 0, 0, 0, 0, 8000, 1.8],
                   ["801003", "机器人", 7000, 1.2, 0, 80000000, 5000000, 0, 0, 0, 1000000000,
                    0, 0, 0, 0, 0, 0, 7000, 1.2]]},
    ]
    rows = merge_ranking_pages(pages, limit=80)
    assert [row["id"] for row in rows] == ["801001", "801002", "801003"]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert rows[0]["volume"] == 1.0


def test_parse_plate_stats_uses_kpl_authoritative_limit_up_field():
    stats = parse_plate_stats({"List": [1, 23819, 1293095249688, 20752101639, 4.29,
                                         23, 2692083412, 1283613819]})
    assert stats == {
        "zt": 23,
        "seal_amount": 2692083412,
        "big_seal_amount": 1283613819,
        "limit_up_source": "kpl_plate_info",
    }


def test_parse_sub_sectors_and_stock_rows_keep_reference_columns():
    subs = parse_sub_sectors({"List": [["801490", "存储芯片", 123.4]]})
    assert subs == [{"id": "801490", "name": "存储芯片", "strength": 123.4}]
    raw = [""] * 63
    raw[0], raw[1], raw[5], raw[6] = "300487", "蓝晓科技", 67.25, 10.01
    raw[7], raw[13], raw[21], raw[23], raw[24], raw[25] = 123456789, 5164307, 1.2, "首板", "龙一", 8.2
    raw[37], raw[47] = 34122276088, 30.26
    rows = parse_stock_rows({"list": [raw]}, "801001", subs[0])
    assert rows[0]["code"] == "300487"
    assert rows[0]["position"] == "龙一"
    assert rows[0]["_blockId"] == "801001"
    assert rows[0]["_subCode"] == "801490"
