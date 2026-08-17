# -*- coding: utf-8 -*-
"""回补 KPL 历史板块排行与权威涨停统计。"""
import argparse
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_HIS = "https://apphis.longhuvip.com/w1/api/index.php"
KPL_UA = "Dalvik/2.1.0 (Linux; U; Android 13; NOP-AN00 Build/HUAWEINOP-AN00)"
COMMON = {"PhoneOSNew": "1", "VerSion": "5.21.0.2", "apiv": "w42"}


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_ranking_page(payload):
    result = []
    for item in payload.get("list", []) or []:
        if not isinstance(item, list) or len(item) < 19:
            continue
        result.append({
            "id": str(item[0]), "name": str(item[1]).strip(),
            "strength": _integer(item[2]), "change": round(_number(item[3]), 2),
            "volume": round(_number(item[5]) / 1e8, 2),
            "mainNet": round(_number(item[6]) / 1e8, 2),
            "marketCap": round(_number(item[10]) / 1e8, 2),
        })
    return result


def merge_ranking_pages(pages, limit=80):
    merged, seen = [], set()
    for payload in pages:
        for row in parse_ranking_page(payload):
            if not row["id"] or row["id"] in seen:
                continue
            seen.add(row["id"])
            merged.append(row)
            if limit and len(merged) >= limit:
                break
        if limit and len(merged) >= limit:
            break
    for rank, row in enumerate(merged, 1):
        row["rank"] = rank
    return merged


def parse_plate_stats(payload):
    raw = payload.get("List", []) or []
    if raw and isinstance(raw[0], list):
        raw = raw[0]
    if not isinstance(raw, list) or len(raw) < 8:
        return {}
    return {"zt": _integer(raw[5]), "seal_amount": _integer(raw[6]),
            "big_seal_amount": _integer(raw[7]), "limit_up_source": "kpl_plate_info"}


def parse_sub_sectors(payload):
    result = []
    for item in payload.get("List", []) or []:
        if isinstance(item, list) and len(item) >= 3:
            result.append({"id": str(item[0]), "name": str(item[1]).strip(),
                           "strength": round(_number(item[2]), 2)})
    result.sort(key=lambda row: -row["strength"])
    return result


def parse_stock_rows(payload, parent_id, sub_sector=None):
    result = []
    for item in payload.get("list", payload.get("List", [])) or []:
        if not isinstance(item, list) or len(item) < 63:
            continue
        row = {
            "code": str(item[0]), "name": str(item[1]).strip(),
            "price": item[5] if item[5] != "--" else "",
            "change": item[6] if item[6] != "--" else "",
            "turnover": item[25] if item[25] not in (None, "", "--") else "",
            "volume": item[7], "mainBuy": item[11], "mainSell": item[12],
            "mainNet": item[13],
            "volRatio": item[21] if item[21] not in (None, "", "--") else "",
            "boards": str(item[23]) if item[23] else "",
            "position": str(item[24]) if item[24] else "",
            "netFlowRatio": item[19] if item[19] not in (None, "", "--") else "",
            "circMarketCap": item[37], "totalMarketCap": item[38],
            "pe1": item[47] if item[47] != "--" else "",
            "pe2": item[48] if item[48] != "--" else "",
            "fundType": str(item[2]) if item[2] else "",
            "concepts": str(item[4]) if item[4] else "",
            "_blockId": str(parent_id),
        }
        if sub_sector:
            row.update({"_subCode": str(sub_sector["id"]), "_subName": sub_sector["name"]})
        result.append(row)
    return result


def merge_close_snapshot(staging, close_view):
    """用盘后冻结摘要恢复同日 KPL 中间层，历史回补不得覆盖该口径。"""
    if staging.get("date") and close_view.get("date") != staging.get("date"):
        raise ValueError("收盘快照日期与目标日期不一致")
    sectors, sub_map = [], {}
    aliases = {"limit_up_count": "zt", "up6_count": "up6", "stock_count": "n"}
    for archived in close_view.get("sectors", []) or []:
        row = {k: v for k, v in archived.items() if k != "sub_sectors"}
        for source_key, target_key in aliases.items():
            if source_key in row:
                row[target_key] = row.pop(source_key)
        row["limit_up_source"] = "kpl_close_snapshot"
        sectors.append(row)
        sub_map[str(row.get("id", ""))] = list(archived.get("sub_sectors", []) or [])
    result = dict(staging)
    result.update({"date": close_view.get("date"), "sectors": sectors, "sub": sub_map,
                   "history_quality": {"sector_count": len(sectors),
                                       "authoritative_limit_up_count": len(sectors),
                                       "complete": len(sectors) >= 80,
                                       "source": "kpl_close_snapshot"}})
    return result


def restore_close_snapshot(date_str, output_dir, close_view_path):
    path = os.path.join(output_dir, f"kpl_{date_str}.json")
    with open(path, encoding="utf-8-sig") as fh:
        staging = json.load(fh)
    with open(close_view_path, encoding="utf-8-sig") as fh:
        close_view = json.load(fh)
    restored = merge_close_snapshot(staging, close_view)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(restored, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return restored["history_quality"]


class KplHistoryClient:
    def __init__(self, timeout=20):
        self.timeout = timeout

    def post(self, params):
        body = {**COMMON, "DeviceID": str(uuid.uuid4()), **params}
        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(BASE_HIS, data=body, headers={"User-Agent": KPL_UA},
                                         timeout=self.timeout)
                response.raise_for_status()
                return json.loads(response.content.decode("utf-8"))
            except (requests.RequestException, UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.3 * (attempt + 1))
        raise last_error

    def ranking(self, date_str, limit=80, page_size=70):
        pages = []
        for index in range(0, max(limit, page_size), page_size):
            payload = self.post({"Order": "1", "a": "RealRankingInfo", "st": str(page_size),
                                 "Index": str(index), "c": "ZhiShuRanking", "Type": "1",
                                 "ZSType": "7", "Date": date_str})
            pages.append(payload)
            if len(payload.get("list", []) or []) < page_size:
                break
        return merge_ranking_pages(pages, limit=limit)

    def plate_stats(self, date_str, plate_id):
        return parse_plate_stats(self.post({"a": "GetPlate_Info_QJ", "c": "ZhiShuRanking",
                                            "Date": date_str, "PlateID": plate_id,
                                            "RStart": "0925", "REnd": "1500"}))

    def sub_sectors(self, date_str, plate_id):
        return parse_sub_sectors(self.post({"a": "SonPlate_Info", "c": "ZhiShuRanking",
                                            "IsShow": "1", "Date": date_str,
                                            "PlateID": plate_id}))

    def stocks(self, date_str, plate_id, parent_id=None, sub_sector=None):
        payload = self.post({"Order": "1", "a": "ZhiShuStockList_W8", "st": "300",
                             "c": "ZhiShuRanking", "Type": "6", "PlateID": plate_id,
                             "Date": date_str, "RStart": "0925", "REnd": "1500", "old": "1"})
        return parse_stock_rows(payload, parent_id or plate_id, sub_sector)


def backfill_day(date_str, output_dir, limit=80, workers=10, client=None, with_details=False):
    client = client or KplHistoryClient()
    path = os.path.join(output_dir, f"kpl_{date_str}.json")
    current = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as fh:
            current = json.load(fh)
    sectors = client.ranking(date_str, limit=limit)
    if not sectors:
        raise RuntimeError(f"{date_str}: KPL 历史排行为空")
    old_by_id = {str(row.get("id")): row for row in current.get("sectors", [])}
    for row in sectors:
        old = old_by_id.get(row["id"], {})
        for key in ("up6", "n"):
            if key in old:
                row[key] = old[key]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.plate_stats, date_str, row["id"]): row for row in sectors}
        for future in as_completed(futures):
            row = futures[future]
            try:
                row.update(future.result())
            except Exception as exc:
                row["limit_up_error"] = str(exc)
    authoritative = sum(row.get("limit_up_source") == "kpl_plate_info" for row in sectors)
    if with_details:
        sub_map = {}
        stocks_path = os.path.join(output_dir, f"kpl_{date_str}_stocks.json")
        stocks_doc = {"date": date_str, "stocks": {}}
        if os.path.exists(stocks_path):
            with open(stocks_path, encoding="utf-8-sig") as fh:
                stocks_doc = json.load(fh)
        plates = stocks_doc.setdefault("stocks", {})
        with ThreadPoolExecutor(max_workers=workers) as pool:
            tasks = {}
            for row in sectors:
                tasks[pool.submit(client.sub_sectors, date_str, row["id"])] = ("sub", row)
                tasks[pool.submit(client.stocks, date_str, row["id"])] = ("stock", row)
            for future in as_completed(tasks):
                kind, row = tasks[future]
                try:
                    value = future.result()
                    if kind == "sub":
                        sub_map[row["id"]] = value
                    elif value:
                        plates[row["id"]] = value
                except Exception:
                    if kind == "sub":
                        sub_map.setdefault(row["id"], [])
        sub_tasks = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for parent_id, children in sub_map.items():
                for child in children:
                    sub_tasks[pool.submit(client.stocks, date_str, child["id"], parent_id, child)] = child["id"]
            for future in as_completed(sub_tasks):
                try:
                    value = future.result()
                    if value:
                        plates[sub_tasks[future]] = value
                except Exception:
                    pass
        current["sub"] = sub_map
        stocks_doc["history_quality"] = {
            "main_plate_count": sum(1 for row in sectors if row["id"] in plates),
            "sub_plate_count": sum(1 for rows in sub_map.values() for row in rows if row["id"] in plates),
        }
        stocks_tmp = stocks_path + ".tmp"
        with open(stocks_tmp, "w", encoding="utf-8") as fh:
            json.dump(stocks_doc, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(stocks_tmp, stocks_path)
    current.update({"date": date_str, "sectors": sectors,
                    "history_quality": {"sector_count": len(sectors),
                                        "authoritative_limit_up_count": authoritative,
                                        "complete": len(sectors) >= limit and authoritative >= limit}})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return current["history_quality"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="回补 KPL 近 N 日历史板块排行与涨停统计")
    parser.add_argument("--output", required=True)
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--with-details", action="store_true")
    parser.add_argument("--close-view", help="盘后冻结的 day_<date>.json；提供时只恢复摘要，不请求历史接口")
    args = parser.parse_args(argv)
    for date_str in args.dates:
        if args.close_view:
            quality = restore_close_snapshot(date_str, args.output, args.close_view)
        else:
            quality = backfill_day(date_str, args.output, args.limit, args.workers,
                                   with_details=args.with_details)
        print(f"{date_str}: {quality}", flush=True)


if __name__ == "__main__":
    main()
