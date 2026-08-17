# -*- coding: utf-8 -*-
"""开盘啦板块强度实时读取。

强度值只取 KPL 服务端返回，不在本地重算。主排行、子板块和成分股分别来自
RealRankingInfo / SonPlate_Info / ZhiShuStockList_W8。
"""
import json
import threading
import time
import urllib.parse
import urllib.request
import uuid

from .normalize import stock_id

KPL_HQ = "https://apphwhq.longhuvip.com/w1/api/index.php"
KPL_UA = "Dalvik/2.1.0 (Linux; U; Android 13; NOP-AN00 Build/HUAWEINOP-AN00)"
VERSION = "5.21.0.2"
API_VERSION = "w42"
CACHE_TTL = 3.0
_cache = {}
_cache_lock = threading.Lock()


def _num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money_yi(value):
    return round(_num(value) / 1e8, 2)


def parse_ranking(doc):
    sectors = []
    for row in doc.get("list", []) or []:
        if not isinstance(row, list) or len(row) < 11:
            continue
        sectors.append({
            "id": str(row[0]), "name": str(row[1]), "strength": int(_num(row[2])),
            "change": round(_num(row[3]), 2), "speed": round(_num(row[4]), 3),
            "volume": _money_yi(row[5]), "mainNet": _money_yi(row[6]),
            "mainBuy": _money_yi(row[7]), "mainSell": _money_yi(row[8]),
            "vol_ratio": round(_num(row[9]), 3), "marketCap": _money_yi(row[10]),
            "rank": len(sectors) + 1,
        })
    return sectors


def parse_sub_sectors(doc):
    subs = []
    for row in doc.get("List", []) or []:
        if isinstance(row, list) and len(row) >= 3:
            subs.append({"id": str(row[0]), "name": str(row[1]).strip(),
                         "strength": round(_num(row[2]), 2)})
        elif isinstance(row, dict):
            subs.append({"id": str(row.get("code", row.get("id", ""))),
                         "name": str(row.get("name", "")).strip(),
                         "strength": round(_num(row.get("strength")), 2)})
    return sorted(subs, key=lambda x: -x["strength"])


def parse_stocks(doc):
    stocks = []
    for row in doc.get("list", doc.get("List", [])) or []:
        if not isinstance(row, list) or len(row) < 63 or not row[0]:
            continue
        code = str(row[0]).zfill(6)
        stocks.append({
            "stock_id": stock_id(code), "code": code, "name": str(row[1]),
            "position": str(row[24] or ""), "change": _num(row[6]), "price": _num(row[5]),
            "turnover": _num(row[25]), "amount": _num(row[7]), "main_net": _num(row[13]),
            "vol_ratio": _num(row[21]), "net_flow_ratio": _num(row[19]),
            "boards": str(row[23] or ""), "pe": row[47] if row[47] not in (None, "--") else "",
            "circ_market_cap": _num(row[37]), "total_market_cap": _num(row[38]),
            "fund_type": str(row[2] or ""), "concepts": str(row[4] or ""),
        })
    return stocks


def _request(params):
    payload = dict(params)
    payload.setdefault("PhoneOSNew", "1")
    payload.setdefault("VerSion", VERSION)
    payload.setdefault("apiv", API_VERSION)
    payload.setdefault("DeviceID", str(uuid.uuid4()))
    url = KPL_HQ + "?" + urllib.parse.urlencode(payload)
    req = urllib.request.Request(url, headers={"User-Agent": KPL_UA, "Connection": "Keep-Alive"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _cached(key, loader):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    value = loader()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def fetch_realtime(plate_id, sub_id=None):
    ranking_doc = _cached("ranking", lambda: _request({
        "Order": "1", "st": "80", "a": "RealRankingInfo", "Type": "1",
        "c": "ZhiShuRanking", "ZSType": "7",
    }))
    max_time = str(ranking_doc.get("Max") or "1500")
    sectors = parse_ranking(ranking_doc)
    subs_doc = _cached("subs:" + plate_id, lambda: _request({
        "a": "SonPlate_Info", "c": "ZhiShuRanking", "IsShow": "1", "PlateID": plate_id,
    }))
    target_id = sub_id or plate_id
    stocks_doc = _cached("stocks:" + target_id + ":" + max_time, lambda: _request({
        "Order": "1", "a": "ZhiShuStockList_W8", "st": "300", "c": "ZhiShuRanking",
        "RStart": "0925", "REnd": max_time, "old": "1", "Type": "6", "PlateID": target_id,
    }))
    stocks = parse_stocks(stocks_doc)
    return {
        "available": True, "source": "kpl", "source_time": ranking_doc.get("Time"),
        "min_time": ranking_doc.get("Min"), "max_time": max_time,
        "plate_id": plate_id, "selected_plate_id": target_id,
        "sectors": sectors, "sub_sectors": parse_sub_sectors(subs_doc), "stocks": stocks,
        "stock_count": len(stocks),
        "limit_up_count": sum(1 for row in stocks if row["change"] >= 9.8),
        "up6_count": sum(1 for row in stocks if 6 <= row["change"] < 9.8),
    }
