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
import json
import os
import re
import urllib.parse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA_DIR = "data"
HOST = "127.0.0.1"
PORT = 8787


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
        entry["pool"] = {"alert": sid in (pool.get("alert") or {}), "candidate": sid in (pool.get("candidate") or {})}
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


def intraday_latest():
    """最新 intraday 目录 snapshots.ndjson 末行（轻量实时快照）。"""
    dirs = sorted(glob.glob(_path("intraday", "*")), reverse=True)
    if not dirs:
        return {}
    ndjson = os.path.join(dirs[0], "snapshots.ndjson")
    if not os.path.exists(ndjson):
        return {}
    last = ""
    with open(ndjson, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                last = line
    if not last:
        return {}
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        return {}


# ---------------- HTTP 服务 ----------------

def ok(data, date_str, source):
    return {"data": data, "meta": {"data_date": date_str, "source": source,
                                   "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}


def handle_api(path, query):
    """路由 → (payload, status)。"""
    date_str = query.get("date", [None])[0]

    if path == "/api/health":
        return {"status": "ok", "latest": latest_date()}, 200
    if path == "/api/days":
        idx = load_json("web", "index.json") or {}
        return ok({"days": idx.get("days", [])}, None, "view"), 200
    if path == "/api/day":
        view, d = day_view(date_str)
        return (ok(view, d, "view"), 200) if view else ({"error": "date not found"}, 404)
    if path == "/api/instruments":
        data = load_json("normalized", "stocks.json")
        return (ok(data, None, "kpl"), 200) if data is not None else ({"error": "no instruments"}, 404)

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
        return ok(intraday_latest(), None, "intraday"), 200

    return {"error": "not found"}, 404


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        accept_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if accept_gzip and len(body) > 512:
            body = gzip.compress(body)
            self.send_response(status)
            self.send_header("Content-Encoding", "gzip")
        else:
            self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
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

    def log_message(self, fmt, *args):
        pass  # 静默访问日志（生产可改 logging）


def make_server(data_dir, port=PORT, host=HOST):
    global DATA_DIR
    DATA_DIR = os.path.abspath(data_dir)
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="统一数据服务（market-data-service）")
    ap.add_argument("--host", default=HOST, help=f"监听地址（默认 {HOST}，勿暴露公网）")
    ap.add_argument("--port", type=int, default=PORT, help=f"端口（默认 {PORT}）")
    ap.add_argument("--data", default="data", help="数据根目录（默认 data）")
    args = ap.parse_args(argv)
    make_server(args.data, args.port, args.host).serve_forever()


if __name__ == "__main__":
    main()
