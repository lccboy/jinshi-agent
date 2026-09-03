# -*- coding: utf-8 -*-
"""统一数据服务（V0.2，market-data-service）

服务器本地进程（默认 127.0.0.1:8787，nginx 反代 `/DSH/api/`）。
纯 stdlib `http.server`，零第三方依赖；读 `data/web/`（视图层）+ `data/facts/<date>/` + `data/kline/`，
响应统一 `{"data": ..., "meta": {"data_date", "source", "fetched_at"}}`，支持 gzip 与内存缓存。

部署：开发期本地 8787（形态 B）；生产用 NSSM/计划任务注册（形态 A），见 docs/DEPLOY.md。
"""
import argparse
import datetime
import gzip
import glob
import hashlib
import json
import os
import re
import time
import urllib.parse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_DIR = "data"
HOST = "127.0.0.1"
PORT = 8787
STRATEGY_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "config", "strategy.json")
_LEADING_REALTIME_CACHE = {"expires": 0.0, "rows": [], "ts": ""}
_EXPECTED_REALTIME_CACHE = {"expires": 0.0, "rows": [], "ts": ""}
_MONEY_FLOW_REALTIME_CACHE = {"expires": 0.0, "rows": [], "ts": ""}
_EXPECTED_RELATED_QUOTES_CACHE = {}


# ---------------- 数据读取（lru 缓存） ----------------

def _path(*parts):
    return os.path.join(DATA_DIR, *parts)


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=256)
def _cached_json(rel_path, mtime_ns):
    return _read_json(_path(*rel_path))


def load_json(*rel_parts):
    """带 mtime 键的缓存读取（文件不可变 → 缓存有效）。"""
    path = _path(*rel_parts)
    if not os.path.exists(path):
        return None
    mtime = int(os.stat(path).st_mtime_ns)
    return _cached_json(tuple(rel_parts), mtime)


@lru_cache(maxsize=4)
def _cached_model_names(mtime_ns):
    config = _read_json(STRATEGY_CONFIG) or {}
    return {mid: item.get("name", mid) for mid, item in (config.get("models") or {}).items()}


def load_model_names():
    if not os.path.isfile(STRATEGY_CONFIG):
        return {}
    return _cached_model_names(int(os.stat(STRATEGY_CONFIG).st_mtime_ns))


def latest_date():
    idx = load_json("web", "index.json") or {}
    days = idx.get("days") or []
    return days[0]["date"] if days else None


def day_view(date_str=None):
    if date_str in (None, "", "latest"):
        view = load_json("web", "day_latest.json")
        date_str = view.get("date") if view else latest_date()
        return view, date_str
    return load_json("web", f"day_{date_str}.json"), date_str


# ---------------- 历史个股时间线 ----------------

def history_for_stock(sid):
    """聚合该股跨日期：strategy/pool/limitup/events。"""
    timeline = []
    for day in sorted(glob.glob(_path("facts", "*")), reverse=True):
        date_str = os.path.basename(day)
        entry = {"date": date_str}
        strat = load_json("facts", date_str, "strategy.json") or {}
        if sid in strat:
            entry["strategy"] = strat[sid]
        pool = (load_json("facts", date_str, "pool.json") or {}).get("pools") or {}
        pool_flags = {"alert": sid in (pool.get("alert") or {}),
                      "candidate": sid in (pool.get("candidate") or {})}
        if any(pool_flags.values()):
            entry["pool"] = pool_flags
        lu = load_json("facts", date_str, "limitup.json") or {}
        if sid in lu:
            entry["limitup"] = lu[sid]
        evs = (load_json("facts", date_str, "events.json") or {}).get("events") or []
        mine = [e for e in evs if e.get("stock_id") == sid]
        if mine:
            entry["events"] = mine
        if any(k in entry for k in ("strategy", "pool", "limitup", "events")):
            timeline.append(entry)
    return timeline


def recent_limitup_reasons(date_str, stock_ids):
    """为当天缺原因的实时涨停股查找最近一个历史交易日原因。"""
    missing = set(stock_ids)
    found = {}
    day_dirs = sorted(glob.glob(_path("facts", "*")), reverse=True)
    for day_dir in day_dirs:
        reason_date = os.path.basename(day_dir)
        if reason_date >= date_str or not re.match(r"^\d{4}-\d{2}-\d{2}$", reason_date):
            continue
        doc = load_json("facts", reason_date, "limitup.json") or {}
        for sid in list(missing):
            entry = doc.get(sid)
            if not isinstance(entry, dict) or not str(entry.get("reason") or "").strip():
                continue
            item = dict(entry)
            item.update({"reason_date": reason_date, "reason_is_history": True})
            found[sid] = item
            missing.remove(sid)
        if not missing:
            break
    return found


def attach_sector_reasons(stocks, reasons):
    """把最近历史涨停原因附加到 KPL 实时成分股；不改变无历史原因的股票。"""
    for stock in stocks:
        reason = reasons.get(stock.get("stock_id"))
        if reason:
            stock.update(reason)
    return stocks


def compute_sector_strength(snapshot_stocks, membership, top_n=50):
    """盘中实时板块强度代理：涨停×100 + 涨超6%×50 + 平均涨幅×10。

    KPL 无全市场实时强度时的排序代理（仅用于精选板块 TOP 排序展示）。
    membership: {sid: [sector_id, ...]}；板块样本 <2 只过滤，按强度降序取 top_n。
    """
    agg = {}
    for sid, quote in snapshot_stocks.items():
        raw = quote.get("change_pct")
        if raw is None:
            raw = quote.get("change")
        try:
            chg = float(raw or 0)
        except (TypeError, ValueError):
            chg = 0.0
        for sec in membership.get(sid, []):
            bucket = agg.setdefault(sec, {"lu": 0, "up6": 0, "sum_chg": 0.0, "cnt": 0})
            bucket["cnt"] += 1
            bucket["sum_chg"] += chg
            if chg >= 9.8:
                bucket["lu"] += 1
            elif chg >= 6:
                bucket["up6"] += 1
    out = []
    for sec, bucket in agg.items():
        if bucket["cnt"] < 2:
            continue
        avg = bucket["sum_chg"] / bucket["cnt"]
        strength = round(bucket["lu"] * 100 + bucket["up6"] * 50 + avg * 10, 1)
        out.append({"sector_id": sec, "strength": strength, "limitup": bucket["lu"],
                    "up6": bucket["up6"], "count": bucket["cnt"]})
    out.sort(key=lambda item: item["strength"], reverse=True)
    return out[:top_n]


def read_last_ndjson_record(path, block_size=64 * 1024):
    """从文件尾部反向读取最后一条完整 NDJSON，避免轮询时扫描全文件。"""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        buf = b""
        while pos > 0:
            take = min(block_size, pos)
            pos -= take
            fh.seek(pos)
            buf = fh.read(take) + buf
            lines = buf.split(b"\n")
            complete = lines if pos == 0 else lines[1:]
            for raw in reversed(complete):
                if raw.strip():
                    try:
                        return json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return None
        return None


def latest_snapshot_source():
    """返回最新盘中或收盘归档快照；同日优先仍在写入的 intraday。"""
    candidates = []
    for area, priority in (("archive", 0), ("intraday", 1)):
        for directory in glob.glob(_path(area, "*")):
            date_str = os.path.basename(directory)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                continue
            latest = os.path.join(directory, "public_latest.json")
            path = latest if os.path.isfile(latest) else os.path.join(directory, "snapshots.ndjson")
            if os.path.isfile(path):
                if path.endswith(".json"):
                    try:
                        with open(path, encoding="utf-8") as handle:
                            record = json.load(handle)
                    except (OSError, json.JSONDecodeError):
                        record = {}
                else:
                    record = read_last_ndjson_record(path) or {}
                candidates.append((date_str, str(record.get("ts") or ""), priority, path, area))
    if not candidates:
        return None
    date_str, _, priority, path, area = max(candidates, key=lambda row: (row[0], row[1], row[2]))
    return date_str, priority, path, area


def sync_latest(cursor=None):
    """供会员助手增量同步的公共快照；私有 K 线绝不进入该接口。"""
    source = latest_snapshot_source()
    if not source:
        return {"available": False, "changed": False, "cursor": "", "data_date": None}
    date_str, _, path, area = source
    if path.endswith(".json"):
        try:
            with open(path, encoding="utf-8") as handle:
                snapshot = json.load(handle)
        except (OSError, json.JSONDecodeError):
            snapshot = {}
    else:
        snapshot = read_last_ndjson_record(path) or {}
    ts = str(snapshot.get("ts") or "")
    stocks = snapshot.get("stocks") or {}
    digest = hashlib.sha256(f"sync-v2|{date_str}|{ts}|{len(stocks)}".encode()).hexdigest()[:24]
    base = {"available": True, "changed": digest != (cursor or ""), "cursor": digest,
            "data_date": date_str, "ts": ts, "phase": snapshot.get("phase"), "source": area}
    if not base["changed"]:
        return base
    allowed = ("price", "preclose", "limit_up", "vol_ratio", "change_pct", "volume", "amount")
    base["stocks"] = {}
    for sid, quote in stocks.items():
        if not isinstance(quote, dict):
            continue
        compact = {key: quote.get(key) for key in allowed if key in quote}
        if "vol_ratio" not in compact and "volRatio" in quote:
            compact["vol_ratio"] = quote.get("volRatio")
        base["stocks"][sid] = compact
    pool_doc = load_json("facts", date_str, "pool.json") or {}
    base["auction_radar"] = build_auction_radar_payload(
        snapshot, date_str, pool_doc.get("pools") or {}, pool_doc.get("removed") or {},
        load_json("normalized", "stocks.json") or {})
    return base


def public_sync_manifest():
    """生成会员本地缓存清单；只包含公共 Web 视图，不包含服务器 K 线或会员数据。"""
    snapshot = sync_latest()
    date_str = snapshot.get("data_date")
    phase = str(snapshot.get("phase") or "")
    market_status = "closed" if snapshot.get("source") == "archive" or phase in ("closed", "after_close") else "trading"
    required_names = {"index.json", "day_latest.json", "themes.json", "theme_stocks.json",
                      "stocks_slim.json", "sectors.json", "strategy_all.json",
                      f"strategy_all_{date_str}.json"}
    # 同步清单只推送工作台启动与当天实时页所需文件；旧交易日由历史页按需缓存。
    # 避免会员端每次 revision 都重新校验和下载全部历史 JSON。
    sync_names = required_names | {"themes_tree.json", f"day_{date_str}.json",
                                   f"day_{date_str}.detail.json", f"day_{date_str}.sector.json"}
    files = []
    web_root = _path("web")
    if os.path.isdir(web_root):
        for file_path in sorted(glob.glob(os.path.join(web_root, "*.json"))):
            name = os.path.basename(file_path)
            if name not in sync_names:
                continue
            body_size = os.path.getsize(file_path)
            with open(file_path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            files.append({"path": "web/" + name, "url": "../data/web/" + name,
                          "size": body_size, "sha256": digest,
                          "required": name in required_names})
    revision_source = "|".join(item["path"] + ":" + item["sha256"] for item in files)
    revision_hash = hashlib.sha256(revision_source.encode()).hexdigest()[:12]
    compact_date = str(date_str or "none").replace("-", "")
    pool_doc = load_json("facts", date_str, "pool.json") or {}
    pools = pool_doc.get("pools") or {}
    strategy_doc = load_json("facts", date_str, "strategy.json") or {}
    strategy_map = strategy_doc.get("strategies", strategy_doc) if isinstance(strategy_doc, dict) else {}
    source_ids = ({sid for sid in strategy_map if isinstance(sid, str) and len(sid) == 8} |
                  set((pools.get("alert") or {}).keys()) | set((pools.get("candidate") or {}).keys()))
    strategy_web = load_json("web", f"strategy_all_{date_str}.json") or {}
    published_ids = {row.get("stock_id") for row in (strategy_web.get("list") or [])
                     if isinstance(row, dict) and row.get("stock_id")}
    event_doc = load_json("facts", date_str, "events.json") or {}
    auction_event_ids = {row.get("stock_id") for row in (event_doc.get("events") or [])
                         if row.get("type") == "auction_candidate" and row.get("stock_id")}
    radar_path = _path("facts", date_str, "auction_radar.json")
    radar_doc = load_json("facts", date_str, "auction_radar.json") or {}
    radar_ids = {row.get("stock_id") for row in (radar_doc.get("candidates") or [])
                 if isinstance(row, dict) and row.get("stock_id")}
    current_day = load_json("web", f"day_{date_str}.json") or {}
    theme_doc = load_json("web", "themes.json") or {}
    theme_stock_doc = load_json("web", "theme_stocks.json") or {}

    # 历史日文件不进入核心 files；这里只发布轻量目录摘要，客户端切换日期时再按需缓存。
    archive_paths = []
    archive_dates = set()
    for file_path in glob.glob(os.path.join(web_root, "*.json")) if os.path.isdir(web_root) else []:
        name = os.path.basename(file_path)
        matched = re.match(r"^(?:day|strategy_all)_(\d{4}-\d{2}-\d{2})(?:\.(?:detail|sector))?\.json$", name)
        if not matched:
            continue
        archive_dates.add(matched.group(1))
        archive_paths.append(file_path)
    ordered_archive_dates = sorted(archive_dates)
    history_archive = {
        "download_mode": "on_demand",
        "available_days": len(ordered_archive_dates),
        "date_from": ordered_archive_dates[0] if ordered_archive_dates else None,
        "date_to": ordered_archive_dates[-1] if ordered_archive_dates else None,
        "file_count": len(archive_paths),
        "total_bytes": sum(os.path.getsize(path) for path in archive_paths),
        "datasets": ["theme_library", "sector_strength", "leading_reason"],
    }
    datasets = {
        "auction": {"complete": os.path.isfile(radar_path) and auction_event_ids == radar_ids,
                    "event_count": len(auction_event_ids), "candidate_count": len(radar_ids)},
        "strategy": {"complete": source_ids.issubset(published_ids),
                     "source_count": len(source_ids), "published_count": len(published_ids)},
        "history": {"complete": isinstance(pools, dict) and
                    all(name in pools for name in ("alert", "candidate", "limitup")),
                    "alert_count": len(pools.get("alert") or {}),
                    "candidate_count": len(pools.get("candidate") or {})},
        "theme_library": {"complete": bool(theme_doc) and bool(theme_stock_doc),
                          "theme_count": len(theme_doc.get("themes") or theme_doc.get("list") or []),
                          "mapping_count": len(theme_stock_doc)},
        "sector_strength": {"complete": "sectors" in current_day,
                            "current_count": len(current_day.get("sectors") or []),
                            "archive_days": len(ordered_archive_dates)},
        "leading_reason": {"complete": "leading_reason" in current_day,
                           "current_count": len(current_day.get("leading_reason") or []),
                           "archive_days": len(ordered_archive_dates)},
    }
    complete = bool(files) and all(item["complete"] for item in datasets.values()) and all(
        any(file["path"] == "web/" + name for file in files) for name in required_names)
    return {"schema_version": "public-sync-v1", "active_trade_date": date_str,
            "market_status": market_status, "revision": f"public-{compact_date}-{revision_hash}",
            "min_client_version": "1.0.10", "files": files,
            "complete": complete, "datasets": datasets, "history_archive": history_archive,
            "cursor": snapshot.get("cursor"), "available": snapshot.get("available", False)}


def rank_actionable_alerts(model_hits, frozen_rows, sector_strength, limitup_ids=None, top_n=12,
                           alert_pool=None):
    """把模型命中叠加买点风控与板块共振，仅作候选排名，不改模型口径。"""
    frozen = {row.get("stock_id"): row for row in (frozen_rows or []) if row.get("stock_id")}
    sector_rank = {row.get("sector_id"): i for i, row in enumerate(sector_strength or [], 1)}
    limitup_ids = set(limitup_ids or ())
    alert_pool = alert_pool or {}
    ranked = []
    for hit in model_hits or []:
        sid = hit.get("stock_id")
        row = frozen.get(sid) or {}
        try:
            price, buy = float(hit.get("price") or 0), float(row.get("buy_lo") or 0)
            stop, rr = float(row.get("stop") or 0), float(row.get("rr") or 0)
            stop_pct = float(row.get("stop_pct") or 999)
            chg = float(hit.get("change_pct") or 0)
        except (TypeError, ValueError):
            continue
        if (row.get("bp_pass") is not True or rr < 3 or stop_pct > 4 or not price or not buy or
                price <= stop or price > buy * 1.05 or chg < -4 or chg >= 8 or sid in limitup_ids):
            continue
        models = list(hit.get("model_hit") or [])
        ranks = [sector_rank[s] for s in (row.get("sectors") or []) if s in sector_rank]
        best_sector_rank = min(ranks) if ranks else None
        proximity_pct = abs(price / buy - 1) * 100
        quality = float(hit.get("score") or row.get("score") or 0)
        quality += max(0, len(models) - 1) * 8
        quality += max(0, 20 - best_sector_rank * 2) if best_sector_rank else 0
        quality += max(0, 10 - proximity_pct * 2)
        reasons = [f"命中{len(models)}模型", f"RR {rr:.1f}", f"距买点 {proximity_pct:.1f}%"]
        if best_sector_rank and best_sector_rank <= 10:
            reasons.append("板块共振")
        level = "A" if len(models) >= 2 and best_sector_rank and best_sector_rank <= 10 else "B"
        alert_entry = alert_pool.get(sid) or {}
        confirm = dict(alert_entry.get("confirm") or {})
        stars = alert_entry.get("stars")
        if stars is None:
            stars = (1 if models else 0) + sum(bool(confirm.get(key)) for key in
                                               ("sector_strength", "money_flow", "leading_reason"))
        ranked.append({**hit, "buy_lo": buy, "stop": stop, "stop_pct": stop_pct, "rr": rr,
                       "target": row.get("target"), "sectors": list(row.get("sectors") or []),
                       "level": level, "quality_score": round(quality, 1), "reasons": reasons,
                       "sector_rank": best_sector_rank, "confirm": confirm, "stars": stars})
    ranked.sort(key=lambda item: (item["level"] != "A", -item["quality_score"], item.get("ts", "")))
    return ranked[:top_n]


def load_actionable_baseline(date_str):
    """读取可买预警风控基线；当天 Web 指针为空时回退到同日事实。"""
    web_doc = load_json("web", "strategy_all.json") or {}
    web_rows = web_doc.get("list") or []
    if web_doc.get("date") == date_str and web_rows:
        return web_rows

    strategy = load_json("facts", date_str, "strategy.json") or {}
    membership = load_json("facts", date_str, "membership.json") or {}
    rows = []
    for sid, entry in strategy.items():
        if not isinstance(entry, dict):
            continue
        sectors = [str(item.get("id")) for item in (membership.get(sid) or [])
                   if isinstance(item, dict) and item.get("type") == "sector" and item.get("id")]
        rows.append({"stock_id": sid, "buy_lo": entry.get("buy_point"),
                     "stop": entry.get("stop"), "stop_pct": entry.get("stop_pct"),
                     "rr": entry.get("rr"), "target": entry.get("target"),
                     "bp_pass": entry.get("bp_pass"), "score": entry.get("score", 0),
                     "sectors": sectors})
    return rows


def realtime_leading_reasons(ttl=30, now=None):
    """服务端缓存选股宝领涨原因，避免前端轮询放大第三方请求。"""
    current = time.time() if now is None else float(now)
    if _LEADING_REALTIME_CACHE["expires"] > current:
        return _LEADING_REALTIME_CACHE["rows"], _LEADING_REALTIME_CACHE["ts"]
    try:
        from services.collector.factor_collector import fetch_leading_reasons
    except ModuleNotFoundError:  # services/market_data_service.py 脚本路径启动
        from collector.factor_collector import fetch_leading_reasons
    rows = fetch_leading_reasons()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _LEADING_REALTIME_CACHE.update({"expires": current + ttl, "rows": rows, "ts": ts})
    return rows, ts


def realtime_expected_leaders(ttl=30, now=None, data_date=None):
    """服务端缓存东财预期事件候选；与已发生的选股宝领涨事实严格分开。"""
    current = time.time() if now is None else float(now)
    if _EXPECTED_REALTIME_CACHE["expires"] > current:
        return _EXPECTED_REALTIME_CACHE["rows"], _EXPECTED_REALTIME_CACHE["ts"]
    try:
        from services.collector.factor_collector import fetch_expected_leaders
    except ModuleNotFoundError:
        from collector.factor_collector import fetch_expected_leaders
    rows = fetch_expected_leaders(data_date=data_date)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _EXPECTED_REALTIME_CACHE.update({"expires": current + ttl, "rows": rows, "ts": ts})
    return rows, ts


def map_realtime_money_flow(flows, sector_map, top_n=10):
    """把东财 BK 资金流映射为系统 KPL 板块，并按主力净流入排序。"""
    by_em = {str(row.get("em_code") or ""): row for row in flows or []}
    rows = []
    for sector_id, mapping in (sector_map or {}).items():
        flow = by_em.get(str(mapping.get("em_code") or ""))
        if not flow:
            continue
        rows.append({"id": str(sector_id), "name": mapping.get("name") or flow.get("name") or str(sector_id),
                     **{key: flow.get(key, 0) for key in
                        ("main", "main_pct", "super", "super_pct", "big", "big_pct", "mid", "small")}})
    rows.sort(key=lambda row: float(row.get("main") or 0), reverse=True)
    return rows[:top_n]


def realtime_money_flow(ttl=30, now=None):
    """服务端缓存东财实时板块资金流，避免 3 秒前端轮询放大第三方请求。"""
    current = time.time() if now is None else float(now)
    if _MONEY_FLOW_REALTIME_CACHE["expires"] > current:
        return _MONEY_FLOW_REALTIME_CACHE["rows"], _MONEY_FLOW_REALTIME_CACHE["ts"]
    try:
        from services.collector.factor_collector import fetch_em_flows
    except ModuleNotFoundError:
        from collector.factor_collector import fetch_em_flows
    rows = map_realtime_money_flow(fetch_em_flows(), load_json("normalized", "sector_map.json") or {}, top_n=10)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _MONEY_FLOW_REALTIME_CACHE.update({"expires": current + ttl, "rows": rows, "ts": ts})
    return rows, ts


def _previous_minute_baseline(date_str):
    dates = sorted((os.path.basename(path) for path in glob.glob(_path("facts", "*"))
                    if os.path.basename(path) < date_str), reverse=True)
    for source_date in dates:
        document = load_json("facts", source_date, "minute_baseline.json")
        if isinstance(document, dict):
            if (document.get("quality") or {}).get("status") != "pass":
                recovery = load_json("DZH", f"minute_baseline_{source_date}.json") or {}
                recovered = {
                    sid: row for sid, row in (recovery.get("stocks") or {}).items()
                    if isinstance(row, dict) and int(row.get("bar_count") or 0) >= 200
                    and float(row.get("max_1m_volume") or 0) > 0
                    and float(row.get("day_amount") or 0) > 0
                }
                if recovery.get("data_date") == source_date and recovered:
                    return {"data_date": source_date,
                            "source": "tencent_ifzq_minute_recovery",
                            "source_updated_at": recovery.get("generated_at"),
                            "quality": {"status": "pass", "coverage": 1.0,
                                        "valid_stocks": len(recovered), "invalid_stocks": 0,
                                        "missing_minutes": 0,
                                        "scope": "yesterday_limitup_subset", "degraded": True},
                            "stocks": recovered}
            return document
    return None


def _minute_volume_path(date_str):
    for layer in ("intraday", "archive"):
        for name in ("minute_volume.ndjson.gz", "minute_volume.ndjson"):
            path = _path(layer, date_str, name)
            if os.path.isfile(path):
                return path
    return None


def minute_volume_payload(date_str=None, selected_sid=None, min_ratio=1.0, source_only=False):
    """读取轻量分钟物化文件；不在请求时扫描GB级原始快照。"""
    if not date_str:
        source = latest_snapshot_source()
        date_str = source[0] if source else latest_date()
    try:
        from services.collector.minute_volume_radar import (read_minute_records,
            build_minute_volume_payload, build_minute_volume_source_payload)
    except ModuleNotFoundError:
        from collector.minute_volume_radar import (read_minute_records,
            build_minute_volume_payload, build_minute_volume_source_payload)
    current_path = _minute_volume_path(date_str) if date_str else None
    current = read_minute_records(current_path) if current_path else []
    instruments = load_json("normalized", "stocks.json") or {}
    if source_only:
        return build_minute_volume_source_payload(str(date_str), current, instruments,
                                                  selected_sid=selected_sid)
    prior_dates = sorted((os.path.basename(path) for path in glob.glob(_path("facts", "*"))
                          if os.path.basename(path) < str(date_str)), reverse=True)[:2]
    history = {}
    for day in prior_dates:
        path = _minute_volume_path(day)
        history[day] = read_minute_records(path) if path else []
    baseline = _previous_minute_baseline(str(date_str)) or {}
    pools = (load_json("facts", str(date_str), "pool.json") or {}).get("pools") or {}
    return build_minute_volume_payload(str(date_str), current, history, baseline, instruments,
                                       min_ratio=min_ratio, selected_sid=selected_sid,
                                       watchlist=pools.get("watchlist") or {})


def _source_time_from_snapshot(snapshot):
    values = [str(row.get("source_ts")) for row in (snapshot.get("stocks") or {}).values()
              if isinstance(row, dict) and row.get("source_ts")]
    return max(values) if values else None


def build_auction_radar_payload(snapshot, date_str, pools, removed, instruments, cursor=None):
    config = (strategy_config() or {}).get("auction_radar") or {}
    baseline = _previous_minute_baseline(date_str) or {}
    allowed = ("stage", "trajectory", "potential_grade", "tradability", "confirmation",
               "evidence", "failed_evidence", "source_date", "auction_price",
               "candidate_source", "yesterday_limitup_date",
               "invalidation_price", "sector_sync_count", "auction_volume",
               "auction_amount", "final_gap", "auction_day_amount_ratio",
               "auction_max_1m_volume_ratio", "auction_yesterday_amount_ratio",
               "auction_turnover", "yesterday_auction_amount", "sector_gap_percentile",
               "sector_auction_amount_percentile", "data_gaps")
    candidates = []
    depth_by_stock = {}
    try:
        from services.collector.auction_depth import read_depth_records, classify_volume_break
    except ModuleNotFoundError:
        from collector.auction_depth import read_depth_records, classify_volume_break
    for depth in read_depth_records(_path("intraday", date_str)):
        if (depth.get("record_type") != "auction_depth" or depth.get("status") == "error"
                or not depth.get("stock_id")):
            continue
        key = (str(depth.get("poll_slot") or ""), str(depth.get("received_at") or ""))
        prior = depth_by_stock.get(depth["stock_id"])
        prior_key = ((str(prior.get("poll_slot") or ""), str(prior.get("received_at") or ""))
                     if prior else ("", ""))
        if key >= prior_key:
            depth_by_stock[depth["stock_id"]] = depth
    materialized = load_json("facts", date_str, "auction_radar.json") or {}
    for entry in materialized.get("candidates") or []:
        sid = entry.get("stock_id")
        if not sid:
            continue
        row = {"stock_id": sid, "name": (instruments.get(sid) or {}).get("name", sid)}
        row.update({key: entry.get(key) for key in allowed if key in entry})
        candidates.append(row)
    if not candidates:  # 兼容尚未物化的旧日数据。
        for pool_name in ("alert", "candidate"):
            for sid, entry in (pools.get(pool_name) or {}).items():
                if (entry or {}).get("signal_family") != "auction_radar":
                    continue
                row = {"stock_id": sid, "name": (instruments.get(sid) or {}).get("name", sid)}
                row.update({key: entry.get(key) for key in allowed if key in entry})
                candidates.append(row)
        for sid, entry in (removed or {}).items():
            if (entry or {}).get("signal_family") != "auction_radar":
                continue
            row = {"stock_id": sid, "name": (instruments.get(sid) or {}).get("name", sid)}
            row.update({key: entry.get(key) for key in allowed if key in entry})
            row["confirmation"] = "invalidated"
            candidates.append(row)
    baseline_stocks = baseline.get("stocks") or {}
    for row in candidates:
        depth = depth_by_stock.get(row["stock_id"])
        if not depth:
            row.setdefault("depth_pattern", "depth_unconfirmed")
            row.setdefault("volume_break_type", "volume_baseline_unavailable" if
                           not (baseline_stocks.get(row["stock_id"]) or {}).get("max_1m_volume")
                           else "none")
            continue
        features = depth.get("features") or {}
        row["depth_pattern"] = depth.get("depth_pattern") or "depth_unconfirmed"
        for key in ("trial_limit_hold_ratio", "trial_buy_peak", "withdraw_ratio",
                    "matched_growth", "peak_to_match_ratio", "negative_flip_count",
                    "late_price_range", "last_unmatched_signed", "opening_match_volume",
                    "opening_match_amount"):
            if key in features:
                row[key] = features.get(key)
        row["depth_source_time"] = depth.get("received_at")
        row["depth_evidence"] = depth.get("depth_evidence") or []
        row["depth_failed_evidence"] = depth.get("depth_failed_evidence") or []
        opening = depth.get("opening_match") or {}
        baseline_row = baseline_stocks.get(row["stock_id"]) or {}
        volume_break = classify_volume_break(opening.get("volume"),
                                             baseline_row.get("max_1m_volume"))
        row.update(volume_break)
        row["data_gaps"] = [gap for gap in (row.get("data_gaps") or [])
                            if gap != "auction_depth_unavailable"]
    reason_docs = {}
    for row in candidates:
        reason_date = row.get("yesterday_limitup_date")
        if not reason_date:
            continue
        if reason_date not in reason_docs:
            reason_docs[reason_date] = load_json("facts", reason_date, "limitup.json") or {}
        reason = (reason_docs[reason_date] or {}).get(row["stock_id"]) or {}
        if not isinstance(reason, dict):
            continue
        concepts = reason.get("concepts") or []
        if isinstance(concepts, str):
            concepts = [item.strip() for item in concepts.replace("、", ",").split(",") if item.strip()]
        row.update({
            "limitup_reason": reason.get("reason") or "",
            "limitup_detail": reason.get("detail") or "",
            "limitup_boards": reason.get("boards") or "",
            "limitup_concepts": concepts if isinstance(concepts, list) else [],
            "limitup_reason_source": reason.get("primary") or "",
        })
    try:
        from services.collector.auction_radar import rank_candidates
    except ModuleNotFoundError:
        from collector.auction_radar import rank_candidates
    candidates = rank_candidates(candidates)
    phase = str(snapshot.get("phase") or "")
    for row in candidates:
        if phase not in ("auction", "preopen"):
            if row.get("confirmation") == "confirmed":
                row["tradability"] = "tradable"
            elif row.get("confirmation") == "invalidated":
                row["tradability"] = "not_tradable"
            elif row.get("tradability") == "wait":
                row["tradability"] = "not_confirmed"
    trajectory_groups = {}
    snapshot_stocks = snapshot.get("stocks") or {}
    for row in candidates:
        trajectory = str(row.get("trajectory") or "unclassified")
        group = trajectory_groups.setdefault(trajectory, {
            "trajectory": trajectory, "sample_count": 0, "current_limit_count": 0})
        group["sample_count"] += 1
        quote = snapshot_stocks.get(row.get("stock_id")) or {}
        try:
            at_limit = float(quote.get("price")) >= float(quote.get("limit_up")) - 0.001
        except (TypeError, ValueError):
            at_limit = False
        group["current_limit_count"] += int(at_limit)
    trajectory_stats = []
    for group in trajectory_groups.values():
        group["current_limit_rate"] = round(
            group["current_limit_count"] / group["sample_count"], 6) if group["sample_count"] else 0
        trajectory_stats.append(group)
    trajectory_stats.sort(key=lambda group: (-group["current_limit_rate"], -group["sample_count"],
                                             group["trajectory"]))
    source_ts = _source_time_from_snapshot(snapshot)
    received_at = str(snapshot.get("ts") or "")
    latency_ms = None
    if source_ts and received_at:
        try:
            source_time = datetime.datetime.strptime(source_ts, "%Y%m%d%H%M%S")
            received_time = datetime.datetime.strptime(received_at, "%Y-%m-%d %H:%M:%S")
            latency_ms = max(0, int((received_time - source_time).total_seconds() * 1000))
        except ValueError:
            pass
    digest_input = json.dumps({"phase": snapshot.get("phase"), "source_ts": source_ts,
                               "candidates": candidates}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:24]
    payload = {"available": bool(config.get("enabled", False)), "changed": digest != (cursor or ""),
               "cursor": digest, "phase": snapshot.get("phase"), "source_ts": source_ts,
               "received_at": received_at, "latency_ms": latency_ms,
               "quote_count": len(snapshot.get("stocks") or {}),
               "baseline_quality": (baseline.get("quality") or {"status": "missing"}),
               "baseline_source": baseline.get("source"),
               "baseline_source_date": baseline.get("data_date"),
               "source_capabilities": {
                   "process_0915_0925": True,
                   "process_source": "tencent_snapshots",
                   "cumulative_volume_amount": True,
                   "auction_turnover": True,
                   "unmatched_order_depth": bool(depth_by_stock),
               },
               "config_version": str(config.get("version") or "unavailable"),
               "trajectory_stats": trajectory_stats}
    if payload["changed"]:
        payload["candidates"] = candidates
    return payload


def intraday_latest(cursor=None, include_auction=True):
    """最新盘中快照 + 同日涨停池/模型命中/事件，供工作台轻量轮询。"""
    source = latest_snapshot_source()
    if not source:
        return {"available": False, "data_date": None, "stocks": [], "limitup": [],
                "model_hits": [], "actionable_alerts": [], "events": []}
    date_str, _, ndjson, _ = source
    snapshot = read_last_ndjson_record(ndjson)
    if snapshot is None:
        return {"available": False, "data_date": date_str, "stocks": [], "limitup": [],
                "model_hits": [], "actionable_alerts": [], "events": []}

    pool_doc = load_json("facts", date_str, "pool.json") or {}
    pools = pool_doc.get("pools") or {}
    limitup_pool = pools.get("limitup") or {}
    alert_pool = pools.get("alert") or {}

    # 历史选股页的“当天·实时”投影。只暴露原有策略预警/候选池，竞价雷达候选
    # 仍由独立页签消费；同时沿用 Web 归档的 30/100 上限，避免轮询传输无界增长。
    def history_rank(item):
        sid, entry = item
        confirm = entry.get("confirm") or {}
        return (-int(entry.get("stars") or 0), -sum(bool(v) for v in confirm.values()),
                -float(entry.get("score") or 0), -len(entry.get("model_hit") or []), str(sid))

    history_source = {
        key: {sid: entry for sid, entry in (pools.get(key) or {}).items()
              if (entry or {}).get("signal_family") != "auction_radar"}
        for key in ("alert", "candidate")
    }
    history_limits = {"alert": 30, "candidate": 100}
    history_web = {
        key: dict(sorted(rows.items(), key=history_rank)[:history_limits[key]])
        for key, rows in history_source.items()
    }
    reasons = load_json("facts", date_str, "limitup.json") or {}
    # 实时轮询只读有界物化尾窗，避免 events.json 达到几十 MB 后每次变更都重新解析全量。
    event_doc = (load_json("facts", date_str, "events_recent.json") or
                 load_json("facts", date_str, "events.json") or {})
    raw_events = event_doc.get("events") or []
    instruments = load_json("normalized", "stocks.json") or {}
    try:
        from services.collector.archive_job import EVENT_SCHEMA_VERSION, build_event_view
    except ModuleNotFoundError:
        from collector.archive_job import EVENT_SCHEMA_VERSION, build_event_view
    events = build_event_view(raw_events, {
        sid: rec.get("name", sid) for sid, rec in instruments.items() if isinstance(rec, dict)
    })
    snapshot_stocks = snapshot.get("stocks") or {}
    model_name_map = load_model_names()

    missing_reason_ids = [sid for sid in limitup_pool
                          if not str((reasons.get(sid) or {}).get("reason") or "").strip()]
    fallback_reasons = recent_limitup_reasons(date_str, missing_reason_ids)
    limitups = []
    for sid, pool_entry in limitup_pool.items():
        item = {"stock_id": sid, "name": (instruments.get(sid) or {}).get("name", sid)}
        current_reason = reasons.get(sid) or {}
        if str(current_reason.get("reason") or "").strip():
            item.update(current_reason)
            item.update({"reason_date": date_str, "reason_is_history": False})
        elif sid in fallback_reasons:
            item.update(fallback_reasons[sid])
        for key in ("entry_time", "score", "status"):
            if key in (pool_entry or {}):
                item[key] = pool_entry[key]
        limitups.append(item)

    model_hits = []
    seen = set()
    def model_hit_item(sid, models, score, ts):
        quote = snapshot_stocks.get(sid) or {}
        return {"stock_id": sid, "name": (instruments.get(sid) or {}).get("name", sid),
                "model_hit": models, "model_names": [model_name_map.get(mid, mid) for mid in models],
                "score": score, "ts": ts, "price": quote.get("price"),
                "change_pct": quote.get("change_pct")}

    for sid, entry in alert_pool.items():
        models = entry.get("model_hit") or []
        if not models:
            continue
        model_hits.append(model_hit_item(sid, models, entry.get("score"), entry.get("entry_time", "")))
        seen.add(sid)
    for event in sorted(raw_events, key=lambda e: e.get("ts", ""), reverse=True):
        sid = event.get("stock_id")
        if event.get("type") != "signal_hit" or not sid or sid in seen:
            continue
        models = event.get("models") or []
        model_hits.append(model_hit_item(sid, models, event.get("score"), event.get("ts", "")))
        seen.add(sid)
    model_hits.sort(key=lambda item: item.get("ts", ""), reverse=True)

    result = {key: value for key, value in snapshot.items() if key != "stocks"}
    # 前端实时题材只需涨停池；5000+ 只行情保留在 append-only NDJSON，不随轮询重复下发。
    result["stocks"] = {}
    result["quote_count"] = len(snapshot_stocks)
    if include_auction:
        result["auction_radar"] = build_auction_radar_payload(
            snapshot, date_str, pools, pool_doc.get("removed") or {}, instruments, cursor=cursor)
    # 盘中实时板块强度代理（精选板块 TOP 排序用）
    membership = {sid: list(rec.get("current", {}).get("sectors", []) or [])
                  for sid, rec in instruments.items() if isinstance(rec, dict)}
    # 板块页需要一次补齐整个左栏的涨停/涨超 6% 数；几百条聚合结果体积很小，
    # 避免用户逐个点击板块后才得到当前板块计数。
    result["sector_strength"] = compute_sector_strength(snapshot_stocks, membership, top_n=500)
    result["actionable_alerts"] = rank_actionable_alerts(
        model_hits, load_actionable_baseline(date_str), result["sector_strength"], limitup_pool.keys(),
        alert_pool=alert_pool)
    result["leading_reason"], result["leading_reason_ts"] = [], ""
    result["expected_leaders"], result["expected_leaders_ts"] = [], ""
    result["money_flow"], result["money_flow_ts"] = [], ""
    if date_str == datetime.date.today().strftime("%Y-%m-%d"):
        try:
            result["money_flow"], result["money_flow_ts"] = realtime_money_flow()
        except Exception:
            # 东财短时不可用时，前端沿用日视图，不清空既有数据。
            pass
        try:
            result["leading_reason"], result["leading_reason_ts"] = realtime_leading_reasons()
        except Exception:
            # 第三方短时不可用时由前端沿用最新归档，不阻断核心盘中行情。
            pass
        try:
            result["expected_leaders"], result["expected_leaders_ts"] = realtime_expected_leaders(
                data_date=date_str)
        except Exception:
            # 预期事件是增强信息，失败时沿用归档，不影响实时领涨事实。
            pass
    result.update({"available": True, "data_date": date_str, "limitup": limitups,
                   "event_schema_version": EVENT_SCHEMA_VERSION,
                   "model_hits": model_hits, "events": events,
                   "history_pools": {"data_date": date_str, "pools": history_web},
                   "history_pool_summary": {
                       key: {"total": len(history_source[key]), "shown": len(history_web[key])}
                       for key in ("alert", "candidate")
                   }})
    return result


def sector_realtime(plate_id=None, sub_id=None):
    """开盘啦原生实时板块强度、资金、子板块和成分股。"""
    try:
        from services.collector.kpl_sector_realtime import fetch_realtime
    except ModuleNotFoundError:  # 直接执行 services/market_data_service.py 时的模块根目录
        from collector.kpl_sector_realtime import fetch_realtime
    data = fetch_realtime(plate_id, sub_id=sub_id)
    data_date = datetime.date.today().strftime("%Y-%m-%d")
    reason_ids = [row["stock_id"] for row in data.get("stocks", []) if float(row.get("change") or 0) >= 9.8]
    attach_sector_reasons(data.get("stocks", []), recent_limitup_reasons(data_date, reason_ids))
    data["data_date"] = data_date
    return data


def merge_expected_related_quotes(stock_ids, tencent_quotes, kpl_rows, em_flows=None):
    """合并相关股实时字段；KPL 个股板块行情优先，腾讯用于补齐。"""
    requested = list(dict.fromkeys(stock_ids))
    kpl_by_id = {}
    for row in kpl_rows or []:
        sid = row.get("stock_id")
        if sid in requested:
            kpl_by_id[sid] = row
    em_by_id = em_flows or {}
    result = []
    for sid in requested:
        quote = (tencent_quotes or {}).get(sid) or {}
        kpl = kpl_by_id.get(sid) or {}
        em = em_by_id.get(sid) or {}
        result.append({
            "stock_id": sid,
            "name": kpl.get("name") or quote.get("name") or sid,
            "price": kpl.get("price") if kpl else quote.get("price"),
            "change_pct": kpl.get("change") if kpl else quote.get("change_pct"),
            "main_net": em.get("main_net") if em.get("main_net") is not None else
                        (kpl.get("main_net") if kpl else None),
            "vol_ratio": kpl.get("vol_ratio") if kpl else quote.get("vol_ratio"),
            "turnover": kpl.get("turnover") if kpl else quote.get("turnover"),
        })
    return result


def expected_related_quotes(stock_ids, plate_ids, ttl=15, now=None):
    """批量读取相关活跃股行情；板块接口失败不影响腾讯行情回退。"""
    current = time.monotonic() if now is None else now
    key = (tuple(stock_ids), tuple(plate_ids))
    cached = _EXPECTED_RELATED_QUOTES_CACHE.get(key)
    if cached and cached[0] > current:
        return cached[1]
    try:
        from services.collector.quote_collector import fetch_quotes
        from services.collector.factor_collector import fetch_em_stock_flows
    except ModuleNotFoundError:
        from collector.quote_collector import fetch_quotes
        from collector.factor_collector import fetch_em_stock_flows
    quotes = fetch_quotes(stock_ids)
    try:
        em_flows = {row["stock_id"]: row for row in fetch_em_stock_flows(stock_ids) if row.get("stock_id")}
    except Exception:
        em_flows = {}
    kpl_rows = []
    missing_main = {sid for sid in stock_ids if sid not in em_flows or em_flows[sid].get("main_net") is None}
    for plate_id in plate_ids if missing_main else []:
        try:
            kpl_rows.extend(sector_realtime(plate_id).get("stocks") or [])
        except Exception:
            continue
    rows = merge_expected_related_quotes(stock_ids, quotes, kpl_rows, em_flows)
    _EXPECTED_RELATED_QUOTES_CACHE[key] = (current + ttl, rows)
    if len(_EXPECTED_RELATED_QUOTES_CACHE) > 128:
        expired = [cache_key for cache_key, value in _EXPECTED_RELATED_QUOTES_CACHE.items() if value[0] <= current]
        for cache_key in expired:
            _EXPECTED_RELATED_QUOTES_CACHE.pop(cache_key, None)
    return rows


# ---------------- HTTP 服务 ----------------

def ok(data, date_str, source):
    return {"data": data, "meta": {"data_date": date_str, "source": source,
                                   "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}


def handle_api(path, query):
    """路由 → (payload, status)。"""
    date_str = query.get("date", [None])[0]

    if path == "/api/health":
        return {"status": "ok", "latest": latest_date()}, 200
    if path == "/api/strategy/config":
        return ok(strategy_config(), None, "config"), 200
    if path == "/api/days":
        idx = load_json("web", "index.json") or {}
        return ok({"days": idx.get("days", [])}, None, "view"), 200
    if path == "/api/day":
        view, d = day_view(date_str)
        return (ok(view, d, "view"), 200) if view else ({"error": "date not found"}, 404)
    if path == "/api/instruments":
        data = load_json("normalized", "stocks.json")
        return (ok(data, None, "kpl"), 200) if data is not None else ({"error": "no instruments"}, 404)
    if path == "/api/minute-volume":
        selected_sid = query.get("stock", [None])[0]
        try:
            min_ratio = max(0.0, float(query.get("ratio", [1.0])[0]))
        except (TypeError, ValueError):
            return {"error": "invalid ratio"}, 400
        source_only = str(query.get("source", [""])[0]).lower() in ("1", "true", "yes")
        payload = minute_volume_payload(date_str, selected_sid, min_ratio, source_only=source_only)
        return ok(payload, payload.get("data_date"), "minute_volume_materialization"), 200

    # facts/<date> 单文件端点
    simple = {"strategies": "strategy.json", "pools": "pool.json", "events": "events.json",
              "limitups": "limitup.json", "market": "market.json", "index": "index.json",
              "ladder": "ladder.json", "abnormal": "abnormal.json",
              "money-flow": "money_flow.json", "leading-reason": "leading_reason.json",
              "membership": "membership.json"}
    m = re.match(r"^/api/(strategies|pools|events|limitups|market|index|ladder|abnormal|money-flow|leading-reason|membership)$", path)
    if m:
        key = m.group(1)
        d = date_str or latest_date()
        data = load_json("facts", d, simple[key])
        return (ok(data, d, "engine"), 200) if data is not None else ({"error": "no data"}, 404)

    m = re.match(r"^/api/kline/([A-Z]{2}\d{6})$", path)
    if m:
        sid = m.group(1)
        data = load_json("kline", f"{sid}.json")
        return (ok(data, None, "tdx"), 200) if data else ({"error": "no kline"}, 404)

    if path == "/api/history":
        sid = (query.get("stock") or [""])[0]
        if not re.match(r"^[A-Z]{2}\d{6}$", sid):
            return {"error": "stock required, e.g. ?stock=SZ300487"}, 400
        return ok({"stock": sid, "timeline": history_for_stock(sid)}, None, "engine"), 200

    if path == "/api/intraday/latest":
        include_auction = str((query.get("scope") or [""])[0]).lower() != "core"
        data = intraday_latest((query.get("cursor") or [None])[0], include_auction=include_auction)
        return ok(data, data.get("data_date"), "intraday"), 200

    if path == "/api/sync/manifest":
        data = public_sync_manifest()
        return ok(data, data.get("data_date"), "sync"), 200

    if path == "/api/sync/latest":
        data = sync_latest((query.get("cursor") or [None])[0])
        return ok(data, data.get("data_date"), "sync"), 200

    if path == "/api/sectors/realtime":
        plate_id = (query.get("plate") or [""])[0]
        sub_id = (query.get("sub") or [None])[0]
        if plate_id and not re.match(r"^\d{6}$", plate_id):
            return {"error": "invalid plate"}, 400
        if sub_id and not re.match(r"^\d{6}$", sub_id):
            return {"error": "invalid sub plate"}, 400
        try:
            data = sector_realtime(plate_id, sub_id=sub_id)
        except Exception as exc:
            return {"error": "KPL realtime unavailable", "detail": str(exc)}, 503
        return ok(data, data.get("data_date"), "kpl"), 200

    if path == "/api/expected-related-quotes":
        stock_ids = [part.strip().upper() for part in (query.get("ids") or [""])[0].split(",") if part.strip()]
        plate_ids = [part.strip() for part in (query.get("plates") or [""])[0].split(",") if part.strip()]
        if not stock_ids or len(stock_ids) > 200 or any(not re.match(r"^(SH|SZ|BJ)\d{6}$", sid) for sid in stock_ids):
            return {"error": "invalid ids; use up to 200 SH/SZ/BJ stock_ids"}, 400
        if len(plate_ids) > 8 or any(not re.match(r"^\d{6}$", pid) for pid in plate_ids):
            return {"error": "invalid plates; use up to 8 six-digit sector ids"}, 400
        data = expected_related_quotes(list(dict.fromkeys(stock_ids)), list(dict.fromkeys(plate_ids)))
        return ok(data, datetime.date.today().strftime("%Y-%m-%d"), "tencent+eastmoney+kpl"), 200

    if path == "/api/agent/summary":
        # V0.4 Agent 聚合：一次返回当天信号摘要（涨停/策略/预警/事件/板块/资金流/个股名）
        view, d = day_view(date_str)
        if not view:
            return {"error": "date not found"}, 404
        pools = (view.get("pools") or {}).get("pools") or {}
        alert_pool = pools.get("alert") or {}
        candidate_pool = pools.get("candidate") or {}
        events = view.get("events") or []
        stocks = load_json("normalized", "stocks.json") or {}
        names = {sid: (rec.get("name") or "") for sid, rec in stocks.items()}
        summary = {
            "date": d,
            "market": view.get("market") or {},
            "limit_up_count": (view.get("market") or {}).get("limit_up", len(view.get("limitup") or [])),
            "limitup": view.get("limitup") or [],
            "top_sectors": (view.get("sectors") or [])[:10],
            "top_money_flow": (view.get("money_flow") or [])[:10],
            "leading_reason": view.get("leading_reason") or [],
            "expected_leaders": view.get("expected_leaders") or [],
            "strategy_top": view.get("strategy_top") or [],
            "alert_count": len(alert_pool),
            "candidate_count": len(candidate_pool),
            "alert": alert_pool,
            "candidate": candidate_pool,
            "limitup_pool": pools.get("limitup") or {},
            "event_counts": {},
            "events": events[:50],
            "stock_names": names,
        }
        for e in events:
            summary["event_counts"][e.get("type", "")] = summary["event_counts"].get(e.get("type", ""), 0) + 1
        return ok(summary, d, "engine"), 200

    return {"error": "not found"}, 404


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        etag = '"' + hashlib.sha256(body).hexdigest()[:24] + '"'
        if status == 200 and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        accept_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if accept_gzip and (len(body) > 512 or self.path.startswith("/api/minute-volume")):
            body = gzip.compress(body)
            self.send_response(status)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            payload, status = handle_api(parsed.path, query)
        except Exception as exc:  # 服务容错：单接口异常不拖垮进程
            payload, status = {"error": str(exc)}, 500
        self._send(payload, status)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in ("/api/strategy/config", "/api/watchlist"):
            self._send({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/api/strategy/config":
                saved = save_strategy_config(body)
                self._send({"ok": True, "path": saved,
                            "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, 200)
                return
            sid = str(body.get("stock_id") or "")
            action = str(body.get("action") or "add")
            date_str = str(body.get("date") or datetime.date.today().isoformat())
            source_date = str(body.get("source_date") or date_str)
            if not re.match(r"^[A-Z]{2}\d{6}$", sid):
                raise ValueError("invalid stock_id")
            if action not in ("add", "remove"):
                raise ValueError("invalid action")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", source_date):
                raise ValueError("invalid date")
            try:
                from services.collector.realtime_engine import update_watchlist
            except ModuleNotFoundError:
                from collector.realtime_engine import update_watchlist
            result = update_watchlist(_path("facts"), date_str, sid, action,
                                      note=str(body.get("note") or "历史选股加入"), source_date=source_date)
            self._send(ok(result, date_str, "engine"), 200)
        except Exception as exc:
            self._send({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志（生产可改 logging）


def make_server(data_dir, port=PORT, host=HOST):
    global DATA_DIR
    DATA_DIR = os.path.abspath(data_dir)
    return ThreadingHTTPServer((host, port), Handler)


def strategy_config():
    """读 config/strategy.json（项目根下一级，DATA_DIR 的上级）。"""
    path = os.path.join(os.path.dirname(DATA_DIR), "config", "strategy.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_strategy_config(cfg):
    """校验并原子写回 config/strategy.json（前端策略配置面板保存）。"""
    models = cfg.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("models 缺失或为空")
    path = os.path.join(os.path.dirname(DATA_DIR), "config", "strategy.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(temp, path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="统一数据服务（market-data-service）")
    ap.add_argument("--host", default=HOST, help=f"监听地址（默认 {HOST}，勿暴露公网）")
    ap.add_argument("--port", type=int, default=PORT, help=f"端口（默认 {PORT}）")
    ap.add_argument("--data", default="data", help="数据根目录（默认 data）")
    args = ap.parse_args(argv)
    make_server(args.data, args.port, args.host).serve_forever()


if __name__ == "__main__":
    main()
