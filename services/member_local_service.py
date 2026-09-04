# -*- coding: utf-8 -*-
"""会员电脑本地数据助手：保存私有 vipdoc 配置，不向公共服务器上传路径或日 K。"""
import argparse
import filecmp
import gzip
import hashlib
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import ctypes
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse
from urllib.request import urlopen

from services.auction_control import AuctionProcessManager, test_eltdx_connection
from services.local_license import (license_allows_member, load_license_cache,
                                    refresh_cloud_license)


MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HELPER_VERSION = "1.0.41"
_GENERATION_LOCK = threading.Lock()
_GENERATION_THREADS = {}
_SYNC_THREAD = None
_CALC_LOCK = threading.Lock()
LOCAL_SERVER_API = "http://127.0.0.1:8787/api"
REMOTE_SERVER_API = "http://114.132.236.131/dsh/api"


def default_bootstrap_path(local_appdata=None):
    base = Path(local_appdata or os.environ.get("LOCALAPPDATA") or
                Path.home() / "AppData" / "Local")
    return base / "JinshiDSH" / "bootstrap.json"


def load_bootstrap(path=None):
    bootstrap = Path(path or default_bootstrap_path())
    if not bootstrap.is_file():
        return {}
    document = json.loads(bootstrap.read_text(encoding="utf-8-sig"))
    data_root = str(document.get("data_root") or "").strip()
    if not data_root:
        return {}
    return {"schema_version": 1, "data_root": str(Path(data_root).expanduser().resolve())}


def save_bootstrap(data_root, path=None):
    selected = Path(data_root).expanduser().resolve()
    if selected == Path(selected.anchor):
        raise ValueError("数据根目录不能直接使用磁盘根目录")
    selected.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 1, "data_root": str(selected)}
    bootstrap = Path(path or default_bootstrap_path())
    _atomic_json(bootstrap, document)
    return document


def local_paths(data_root=None, local_appdata=None, bootstrap_path=None):
    bootstrap = load_bootstrap(bootstrap_path or default_bootstrap_path(local_appdata))
    legacy = Path(local_appdata or os.environ.get("LOCALAPPDATA") or
                  Path.home() / "AppData" / "Local") / "JinshiDSH"
    root = Path(data_root or bootstrap.get("data_root") or legacy).expanduser().resolve()
    paths = {"root": root}
    for name in ("shared", "members", "runtime", "logs", "backup"):
        paths[name] = root / name
    for target in paths.values():
        target.mkdir(parents=True, exist_ok=True)
    return paths


def default_web_root():
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.extend([
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "apps" / "web",
            Path(sys.executable).resolve().parent / "web",
        ])
    candidates.append(Path(__file__).resolve().parents[1] / "apps" / "web")
    return next((path for path in candidates if (path / "index.html").is_file()), candidates[0])


def render_setup_page(data_root, message="", error=""):
    current = html.escape(str(data_root or ""), quote=True)
    notice = ""
    if message:
        notice = f'<p class="ok">{html.escape(message)}</p>'
    elif error:
        notice = f'<p class="bad">{html.escape(error)}</p>'
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>金十DSH 数据目录</title>
<style>body{{margin:0;background:#0d1117;color:#c9d1d9;font:14px Arial,"Microsoft YaHei"}}main{{max-width:760px;margin:50px auto;padding:28px;background:#161b22;border:1px solid #30363d;border-radius:10px}}label{{display:block;margin:22px 0;color:#8b949e}}input{{display:block;width:100%;box-sizing:border-box;margin-top:8px;padding:12px;background:#0d1117;color:#fff;border:1px solid #30363d;border-radius:6px}}button{{padding:11px 18px;border:0;border-radius:6px;background:#238636;color:#fff}}.ok{{color:#3fb950}}.bad{{color:#f85149}}a{{color:#58a6ff}}</style></head>
<body><main><h1>本地数据根目录</h1>{notice}<p>公共缓存、会员 K 线、策略历史和日志将统一放在该目录。修改这里只保存新位置，不会移动或删除旧目录。</p>
<form method="post" action="/setup/save"><label>数据根目录<input name="data_root" value="{current}" placeholder="例如 H:\\JinshiDSH\\data" required></label><button type="submit">保存数据目录</button></form>
<p><a href="/">返回工作台</a></p></main></body></html>"""


def default_shared_root():
    return local_paths()["shared"]


def _atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _atomic_bytes(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    temp.write_bytes(payload)
    os.replace(temp, target)


def _shared_web_document(shared_root, filename):
    shared = Path(shared_root)
    candidates = []
    try:
        current = json.loads((shared / "current.json").read_text(encoding="utf-8"))
        revision = str(current.get("revision") or "")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", revision):
            candidates.append(shared / "revisions" / revision / "web" / filename)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    candidates.append(shared / "legacy" / "web" / filename)
    for path in candidates:
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _stock_metadata_from_documents(*documents):
    result = {}
    stack = list(documents)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            sid = str(value.get("stock_id") or "")
            if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", sid):
                result[sid] = {"n": value.get("name") or value.get("n") or sid,
                               "s": value.get("sectors") or value.get("s") or []}
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return result


def materialize_member_strategy_archive(config, date_str, shared_root=None):
    """把会员本地策略物化为前端单日视图；不写公共同步目录。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date_str or "")):
        raise ValueError("invalid strategy archive date")
    member_root = Path(config["kline_dir"]).resolve().parent
    facts = member_root / "facts" / date_str
    strategy_path, pool_path = facts / "strategy.json", facts / "pool.json"
    if not strategy_path.is_file() or not pool_path.is_file():
        raise FileNotFoundError(f"member strategy inputs missing: {date_str}")
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    if not isinstance(strategy, dict) or not strategy:
        raise ValueError(f"member strategy input empty: {date_str}")
    shared = Path(shared_root or default_shared_root())
    strategy_config = json.loads(_bundled_strategy_config().read_text(encoding="utf-8"))
    if not (strategy_config.get("strategy_pool") or {}).get("publish_raw", False):
        named_pools = pool.get("pools") or {}
        published = set(named_pools.get("alert") or {}) | set(named_pools.get("candidate") or {})
        strategy = {sid: entry for sid, entry in strategy.items() if sid in published}
        if not strategy:
            raise ValueError(f"member admitted strategy pool empty: {date_str}")
    slim = _shared_web_document(shared, "stocks_slim.json")
    names = {sid: str((row or {}).get("n") or sid) for sid, row in slim.items()}
    from services.collector.archive_job import build_strategy_all
    document = build_strategy_all(
        date_str, strategy, pool, str(Path(config["kline_dir"])), names,
        facts_dir=str(member_root / "facts"), stocks_slim=slim)
    if int(document.get("count") or 0) <= 0:
        raise ValueError(f"member strategy materialization empty: {date_str}")
    web = member_root / "web"
    encoded = json.dumps(document, ensure_ascii=False).encode("utf-8")
    _atomic_bytes(web / f"strategy_all_{date_str}.json", encoded)
    _atomic_bytes(web / f"strategy_all_{date_str}.json.gz", gzip.compress(encoded, compresslevel=6))
    latest_path = web / "strategy_all.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        latest = {}
    if str(latest.get("date") or "") <= date_str:
        _atomic_bytes(latest_path, encoded)
        _atomic_bytes(web / "strategy_all.json.gz", gzip.compress(encoded, compresslevel=6))
    return document


def sync_public_once(shared_root=None, server_api="http://114.132.236.131/dsh/api", opener=urlopen):
    """增量下载服务器公共行情到本机；只写 shared，不上传会员数据。"""
    root = Path(shared_root or default_shared_root())
    state_path = root / "sync_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        with opener(server_api.rstrip("/") + "/sync/manifest", timeout=10) as response:
            manifest = json.loads(response.read().decode("utf-8")).get("data") or {}
        promotion = None
        if manifest.get("schema_version") == "public-sync-v1":
            from services.local_sync import apply_manifest, validate_manifest

            checked = validate_manifest(manifest, client_version=HELPER_VERSION)
            revision = checked["revision"]
            current_path = root / "current.json"
            try:
                current = json.loads(current_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = {}
            destination = root / "revisions" / revision
            can_reuse = bool(current.get("revision") == revision and destination.is_dir())

            def fetch_public_file(item):
                address = urljoin(server_api.rstrip("/") + "/", str(item.get("url") or ""))
                with opener(address, timeout=30) as response:
                    return response.read()

            if can_reuse:
                promotion = {"revision": revision, "promoted": False, "reused": True}
            else:
                pending = {"ok": True, "phase": "downloading", "cursor": state.get("cursor") or "",
                           "data_date": checked["active_trade_date"], "revision": revision,
                           "file_count": len(checked["files"]),
                           "total_bytes": sum(item["size"] for item in checked["files"]),
                           "datasets": checked.get("datasets") or {},
                           "history_archive": manifest.get("history_archive") or {},
                           "synced_at": datetime.now().isoformat(timespec="seconds"), "error": ""}
                _atomic_json(state_path, pending)
                promotion = apply_manifest(checked, fetch_public_file, root, root.parent / "runtime",
                                           client_version=HELPER_VERSION)
        cursor = str(state.get("cursor") or "")
        suffix = "/sync/latest" + (("?cursor=" + cursor) if cursor else "")
        with opener(server_api.rstrip("/") + suffix, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8")).get("data") or {}
        if data.get("changed") and data.get("stocks") is not None:
            _atomic_json(root / "realtime" / "latest.json", data)
        try:
            with opener(server_api.rstrip("/") + "/intraday/latest?scope=core", timeout=20) as response:
                public = json.loads(response.read().decode("utf-8")).get("data") or {}
            _atomic_json(root / "public" / "latest.json", public)
        except Exception:
            pass
        new_state = {"ok": True, "cursor": data.get("cursor") or manifest.get("cursor") or cursor,
                     "data_date": (data.get("data_date") or manifest.get("active_trade_date") or
                                   manifest.get("data_date")),
                     "revision": (promotion or {}).get("revision") or manifest.get("revision"),
                     "market_status": manifest.get("market_status"),
                     "manifest_verified": bool(promotion),
                     "complete": bool(manifest.get("complete")) if promotion else False,
                     "datasets": manifest.get("datasets") or {},
                     "history_archive": manifest.get("history_archive") or {},
                     "phase": "complete",
                     "sync_mode": "reused" if (promotion or {}).get("reused") else "downloaded",
                     "file_count": len(manifest.get("files") or []),
                     "total_bytes": sum(int(item.get("size") or 0) for item in (manifest.get("files") or [])),
                     "synced_at": datetime.now().isoformat(timespec="seconds"), "error": ""}
        _atomic_json(state_path, new_state)
        return new_state
    except Exception as exc:
        failed = {"ok": False, "cursor": "", "data_date": None,
                  "synced_at": datetime.now().isoformat(timespec="seconds"), "error": str(exc)}
        _atomic_json(state_path, failed)
        return failed


def sync_public_best_available(shared_root=None, server_api=None, opener=urlopen):
    """采集机优先本机 API；普通会员电脑本机不可用时自动回退公共服务器。"""
    configured = str(server_api or os.environ.get("JINSHI_SERVER_API") or "").strip()
    candidates = (("configured", configured),) if configured else (
        ("local", LOCAL_SERVER_API), ("remote", REMOTE_SERVER_API))
    result = None
    for scope, api in candidates:
        result = sync_public_once(shared_root, api, opener=opener)
        if result.get("ok"):
            result["server_scope"] = scope
            _atomic_json(Path(shared_root or default_shared_root()) / "sync_state.json", result)
            return result
    return result or {"ok": False, "cursor": "", "data_date": None,
                      "synced_at": datetime.now().isoformat(timespec="seconds"),
                      "server_scope": "unavailable", "error": "没有可用公共数据源"}


def sync_poll_interval(state, trading_interval=15):
    status = str((state or {}).get("market_status") or "")
    if status in ("closed", "holiday"):
        return max(int(trading_interval), 300)
    if status == "preopen":
        return max(int(trading_interval), 30)
    return max(int(trading_interval), 5)


def start_public_sync(shared_root=None, server_api=None, interval=15, members_root=None, runtime_root=None):
    global _SYNC_THREAD
    if _SYNC_THREAD and _SYNC_THREAD.is_alive():
        return _SYNC_THREAD
    def worker():
        while True:
            state = sync_public_best_available(shared_root, server_api)
            if state.get("ok"):
                cache = load_license_cache(runtime_root or local_paths()["runtime"])
                member_id = str(cache.get("member_id") or "")
                if license_allows_member(cache, member_id, cache.get("device_fingerprint")):
                    config_path = Path(members_root or default_members_root()) / member_id / "config.json"
                    if config_path.is_file():
                        try:
                            run_member_calculation_once(
                                json.loads(config_path.read_text(encoding="utf-8")),
                                shared_root or default_shared_root())
                        except Exception:
                            pass
            time.sleep(sync_poll_interval(state, interval))
    _SYNC_THREAD = threading.Thread(target=worker, name="public-data-sync", daemon=True)
    _SYNC_THREAD.start()
    return _SYNC_THREAD


def _bundled_strategy_config():
    candidates = [Path(__file__).resolve().parents[1] / "config" / "strategy.json"]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) /
                          "config" / "strategy.json")
    return next((path for path in candidates if path.is_file()), candidates[0])


def _previous_kline_date(kline_dir, target_date):
    target = int(str(target_date).replace("-", ""))
    latest = 0
    for path in Path(kline_dir).glob("*.json"):
        try:
            bars = json.loads(path.read_text(encoding="utf-8")).get("bars") or []
            latest = max(latest, max((int(bar.get("d") or 0) for bar in bars
                                      if int(bar.get("d") or 0) < target), default=0))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if latest:
            break
    return latest or None


def _strategy_public_facts(day):
    """把同步下来的 Web 列表还原为策略引擎按板块 id 查询的事实映射。"""
    def by_id(rows):
        return {str(row.get("id")): row for row in (rows or [])
                if isinstance(row, dict) and row.get("id")}

    reasons = {}
    for row in day.get("leading_reason") or []:
        if not isinstance(row, dict):
            continue
        ids = list(row.get("sector_ids") or [])
        if row.get("id"):
            ids.append(row["id"])
        for sector_id in ids:
            reasons[str(sector_id)] = row
    return {"sectors": by_id(day.get("sectors")),
            "money_flow": by_id(day.get("money_flow")),
            "leading_reason": reasons}


def _run_member_strategy_baseline(config, date_str, member_root, shared_root=None):
    from services.collector.strategy_engine import run_strategy
    strategy_path = member_root / "facts" / date_str / "strategy.json"
    marker_path = strategy_path.with_name("strategy.member-input.json")
    config_path = _bundled_strategy_config()
    kline_count = sum(1 for _ in Path(config["kline_dir"]).glob("*.json"))
    asof = _previous_kline_date(config["kline_dir"], date_str)
    shared = Path(shared_root or default_shared_root())
    public_stocks = _shared_web_document(shared, "stocks_slim.json")
    public_day = _shared_web_document(shared, f"day_{date_str}.json")
    public_universe = sorted(public_stocks.keys())
    membership = {sid: list((row or {}).get("s") or []) for sid, row in public_stocks.items()}
    public_facts = _strategy_public_facts(public_day)
    universe_hash = hashlib.sha256("\n".join(public_universe).encode("ascii")).hexdigest()
    public_context_hash = hashlib.sha256(json.dumps(
        {"membership": membership, "facts": public_facts}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    marker = {
        "schema_version": "member-strategy-input-v1",
        "data_date": date_str,
        "asof": asof,
        "kline_count": kline_count,
        "universe_count": len(public_universe),
        "universe_sha256": universe_hash,
        "public_context_sha256": public_context_hash,
        "strategy_config_sha256": (hashlib.sha256(config_path.read_bytes()).hexdigest()
                                   if config_path.is_file() else "missing"),
    }
    try:
        previous = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    if strategy_path.is_file() and previous == marker:
        return
    if not public_universe:
        raise ValueError("public stock universe unavailable")
    run_strategy(date_str, config["kline_dir"], str(member_root),
                 str(config_path), universe=public_universe, asof=asof,
                 facts_override=public_facts, membership_override=membership)
    _atomic_json(marker_path, marker)


def build_member_auction_context(config, date_str, member_root=None):
    """用目标日前的会员前复权 K 线生成私有竞价前置形态；已有日事实不覆盖。"""
    from services.collector.auction_pattern import evaluate_sandwich_pattern
    root = Path(member_root or Path(config["kline_dir"]).resolve().parent)
    path = root / "facts" / date_str / "auction_context.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), path
    strategy_config = json.loads(_bundled_strategy_config().read_text(encoding="utf-8"))
    radar_config = strategy_config.get("auction_radar") or {}
    params = radar_config.get("sandwich") or {}
    version = str(radar_config.get("version") or "1.0")
    cutoff = int(date_str.replace("-", ""))
    stocks = {}
    input_asof = 0
    for kline_path in Path(config["kline_dir"]).glob("*.json"):
        try:
            kline = json.loads(kline_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        bars = [bar for bar in (kline.get("bars") or []) if int(bar.get("d") or 0) < cutoff]
        if not bars:
            continue
        input_asof = max(input_asof, max(int(bar.get("d") or 0) for bar in bars))
        result = evaluate_sandwich_pattern(bars, params, asof=input_asof, config_version=version)
        if result.get("state") != "not_matched":
            stock_id = str(kline.get("stock_id") or kline_path.stem)
            stocks[stock_id] = result
    document = {
        "data_date": date_str,
        "input_asof": input_asof or None,
        "config_version": version,
        "stocks": stocks,
        "private": True,
    }
    _atomic_json(path, document)
    return document, path


def _previous_private_minute_baseline(member_root, target_date):
    facts = Path(member_root) / "facts"
    if not facts.is_dir():
        return None
    for day in sorted((path.name for path in facts.iterdir()
                       if path.is_dir() and path.name < target_date), reverse=True):
        path = facts / day / "minute_baseline.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (document.get("source") == "tdx_vipdoc_lc1" and document.get("private") is True and
                (document.get("quality") or {}).get("status") == "pass"):
            return document
    return None


def build_member_minute_baseline(config, target_date, stock_ids, member_root=None):
    """生成/读取会员私有 LC1 基线；路径与原始分钟数据永不进入公共响应。"""
    root = Path(member_root or Path(config["kline_dir"]).resolve().parent)
    vipdoc = str(config.get("vipdoc") or "").strip()
    if not vipdoc:
        return _previous_private_minute_baseline(root, target_date)
    from services.collector.minute_volume_baseline import generate_vipdoc_lc1_baseline
    try:
        document, _ = generate_vipdoc_lc1_baseline(
            vipdoc, target_date, stock_ids, root, expected_minutes=240, min_coverage=0.95)
        return document
    except (OSError, ValueError):
        return None


def merge_member_minute_volume_source(public_source, baseline, history, *, min_ratio=1.0,
                                      selected_sid=None, watchlist=None, filter_name=None):
    """把公共当天分钟量与会员本地 LC1 基线合并，返回仅供本机页面使用的结果。"""
    quality = (baseline or {}).get("quality") or {"status": "missing"}
    if quality.get("status") != "pass":
        return {"available": False, "private": True,
                "data_date": (public_source or {}).get("data_date"), "rows": [],
                "sectors": [], "detail": None, "events": [], "quality": quality,
                "reason": "本地 VIPDOC 昨日分钟峰值基线不可用",
                "baseline_source": (baseline or {}).get("source")}
    baseline_stocks = (baseline or {}).get("stocks") or {}
    rows = []
    for source_row in (public_source or {}).get("rows") or []:
        sid = source_row.get("stock_id")
        reference = baseline_stocks.get(sid) or {}
        peak = reference.get("max_1m_volume")
        volume = source_row.get("minute_volume")
        try:
            ratio = float(volume) / float(peak)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        matched = ((filter_name == "near" and 0.8 <= ratio < 1.0) or
                   (filter_name == "half" and ratio >= 0.5) or
                   (filter_name == "peak" and ratio >= 1.0) or
                   (filter_name == "strong" and ratio >= 1.5) or
                   (filter_name == "extreme" and ratio >= 2.0))
        if filter_name and filter_name in {"near", "half", "peak", "strong", "extreme"}:
            if not matched:
                continue
        elif ratio < float(min_ratio):
            continue
        row = dict(source_row)
        row.setdefault("name", sid)
        row.setdefault("sectors", [])
        row.update({"yesterday_peak_volume": peak, "volume_ratio": round(ratio, 2),
                    "amount_ratio": (round(float(row.get("minute_amount") or 0) /
                                           float(reference.get("max_1m_amount")), 2)
                                     if reference.get("max_1m_amount") else None),
                    "selected": sid in (watchlist or {})})
        rows.append(row)
    sector_counts = {}
    for row in rows:
        for sector in row.get("sectors") or []:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
    for row in rows:
        row["sector_sync_count"] = max([sector_counts.get(item, 0)
                                         for item in row.get("sectors") or []] or [0])
    rows.sort(key=lambda item: (-item["volume_ratio"], -float(item.get("minute_amount") or 0),
                                item["stock_id"]))
    row_ids = {row["stock_id"] for row in rows}
    selected_sid = selected_sid if selected_sid in row_ids else (rows[0]["stock_id"] if rows else None)
    detail = None
    if selected_sid:
        selected = next(row for row in rows if row["stock_id"] == selected_sid)
        public_detail = (public_source or {}).get("detail") or {}
        current_series = (public_detail.get("current_series") or []) \
            if public_detail.get("stock_id") == selected_sid else []
        detail = {**selected, "volume_days": [{"date": public_source.get("data_date"),
                                                "series": current_series}] + list(history or []),
                  "price_series": [{"minute": item.get("minute"), "price": item.get("price")}
                                   for item in current_series if item.get("price") is not None]}
    sectors = [{"sector_id": key, "count": value} for key, value in sector_counts.items()]
    sectors.sort(key=lambda item: (-item["count"], item["sector_id"]))
    events = [{"ts": row.get("minute"),
               "type": "minute_peak_break" if row["volume_ratio"] >= 1 else "minute_near_peak",
               "stock_id": row["stock_id"], "name": row["name"],
               "detail": (("首次超昨峰" if row["volume_ratio"] >= 1 else "接近昨日峰值") +
                          f"，达到 {row['volume_ratio']:.2f}×")} for row in rows[:20]]
    all_ratios = []
    for source_row in (public_source or {}).get("rows") or []:
        reference = baseline_stocks.get(source_row.get("stock_id")) or {}
        try:
            all_ratios.append(float(source_row.get("minute_volume")) /
                              float(reference.get("max_1m_volume")))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    tiers = {"half": sum(value >= .5 for value in all_ratios),
             "near": sum(.8 <= value < 1 for value in all_ratios),
             "peak": sum(value >= 1 for value in all_ratios),
             "strong": sum(value >= 1.5 for value in all_ratios),
             "extreme": sum(value >= 2 for value in all_ratios)}
    return {"available": bool((public_source or {}).get("available")), "private": True,
            "data_date": (public_source or {}).get("data_date"),
            "minute": (public_source or {}).get("minute"), "rows": rows,
            "sectors": sectors, "detail": detail, "events": events, "quality": quality,
            "baseline_date": baseline.get("data_date"), "baseline_source": baseline.get("source"),
            "filter": filter_name, "tier_counts": tiers}


def run_member_minute_archive_once(members_root, data_date):
    """为所有已配置会员生成指定日独立分钟归档；单会员失败不扩散。"""
    results = []
    from services.collector.minute_volume_baseline import archive_vipdoc_lc1_day, _lc1_path
    for config_path in Path(members_root).glob("*/config.json"):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            vipdoc = str(config.get("vipdoc") or "")
            kline_dir = Path(config.get("kline_dir") or config_path.parent / "kline")
            stock_ids = [path.stem for path in kline_dir.glob("*.json")
                         if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", path.stem) and
                         (_lc1_path(vipdoc, path.stem) or Path()).is_file()]
            manifest, path = archive_vipdoc_lc1_day(
                vipdoc, data_date, stock_ids, config_path.parent,
                expected_minutes=240, min_coverage=0.95)
            results.append({"member_id": config_path.parent.name, "ok": True,
                            "status": manifest.get("status"), "path": str(path)})
        except Exception as exc:
            results.append({"member_id": config_path.parent.name, "ok": False,
                            "error": str(exc)})
    return results


def start_member_minute_archive_scheduler(members_root, runtime_root, *, now_fn=None,
                                          interval=300, run_fn=None):
    """15:20 后执行并在启动时补偿；状态独立，不阻塞公共同步。"""
    now_fn = now_fn or (lambda: datetime.now().astimezone())
    run_fn = run_fn or run_member_minute_archive_once
    state_path = Path(runtime_root) / "member_minute_archive_state.json"

    def worker():
        while True:
            now = now_fn()
            day = now.date().isoformat()
            state = {}
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            if now.weekday() < 5 and now.time() >= datetime.strptime("15:20", "%H:%M").time() \
                    and state.get("completed_date") != day:
                results = run_fn(members_root, day)
                complete = bool(results) and all(item.get("ok") and item.get("status") == "complete"
                                                 for item in results)
                state = {"last_attempt_date": day, "updated_at": now.isoformat(),
                         "results": results}
                if complete:
                    state["completed_date"] = day
                _atomic_json(state_path, state)
            time.sleep(max(30, int(interval)))

    thread = threading.Thread(target=worker, name="member-minute-archive", daemon=True)
    thread.start()
    return thread


def expand_public_minute_source(public_source):
    """把公共精简线协议展开成本地合并结构；兼容旧对象行。"""
    source = dict(public_source or {})
    if source.get("schema_version") != "minute-source-v2":
        return source
    minute = source.get("minute")
    rows = []
    for item in source.get("rows") or []:
        if not isinstance(item, list) or len(item) < 5:
            continue
        rows.append({"stock_id": item[0], "minute_volume": item[1],
                     "minute_amount": item[2], "price": item[3],
                     "change_pct": item[4], "minute": minute})
    selected = source.get("selected") or {}
    source["rows"] = rows
    source["detail"] = ({"stock_id": selected.get("stock_id"),
                         "current_series": selected.get("current_series") or []}
                        if selected.get("stock_id") else None)
    return source


def merge_member_auction_radar(public_radar, auction_context, strategy,
                                minute_baseline=None, radar_config=None, target_date=None):
    """在会员电脑上叠加私有形态/模型/RR；不修改公共载荷。"""
    public_radar = public_radar if isinstance(public_radar, dict) else {}
    merged = {key: value for key, value in public_radar.items() if key != "candidates"}
    local_patterns = (auction_context or {}).get("stocks") or {}
    baseline = minute_baseline if isinstance(minute_baseline, dict) else {}
    source_date = str(baseline.get("data_date") or "")
    target_date = str(target_date or "")
    baseline_valid = bool(
        baseline.get("private") is True and baseline.get("source") == "tdx_vipdoc_lc1" and
        (baseline.get("quality") or {}).get("status") == "pass" and source_date and
        (not target_date or source_date < target_date)
    )
    baseline_stocks = baseline.get("stocks") or {} if baseline_valid else {}
    trajectory_config = (radar_config or {}).get("trajectory") or {}
    promising = {"steady_strengthen", "limit_withdraw_absorption", "late_accumulation"}
    candidates = []
    for public_row in public_radar.get("candidates") or []:
        row = dict(public_row)
        sid = row.get("stock_id")
        row["failed_evidence"] = list(row.get("failed_evidence") or [])
        row["evidence"] = list(row.get("evidence") or [])
        pattern = local_patterns.get(sid)
        strategy_row = (strategy or {}).get(sid) or {}
        if pattern:
            row["local_pattern"] = pattern
        if strategy_row:
            row["local_model_hit"] = sorted((strategy_row.get("models") or {}).keys())
            row["local_risk"] = {key: strategy_row.get(key) for key in
                                 ("rr", "stop", "buy_point", "bp_pass")}
        baseline_row = baseline_stocks.get(sid) if baseline_valid else None
        try:
            auction_volume = float(row.get("auction_volume"))
            max_volume = float((baseline_row or {}).get("max_1m_volume"))
            volume_ratio = auction_volume / max_volume if max_volume > 0 else None
        except (TypeError, ValueError):
            volume_ratio = None
        try:
            auction_amount = float(row.get("auction_amount"))
            day_amount = float((baseline_row or {}).get("day_amount"))
            amount_ratio = auction_amount / day_amount if day_amount > 0 else None
        except (TypeError, ValueError):
            auction_amount = None
            amount_ratio = None
        if baseline_valid and baseline_row and volume_ratio is not None:
            row.update({
                "local_baseline": True,
                "yesterday_max_1m_volume": baseline_row.get("max_1m_volume"),
                "yesterday_max_1m_volume_time": baseline_row.get("max_1m_volume_time"),
                "auction_max_1m_volume_ratio": round(volume_ratio, 6),
                "auction_day_amount_ratio": round(amount_ratio, 6) if amount_ratio is not None else None,
            })
            row["failed_evidence"] = [item for item in row["failed_evidence"]
                                      if item != "minute_baseline_unavailable"]
            gap = row.get("final_gap")
            try:
                gap = float(gap)
            except (TypeError, ValueError):
                gap = None
            gates = (
                auction_amount is not None and
                auction_amount >= float(trajectory_config.get("min_auction_amount", 0)) and
                amount_ratio is not None and
                amount_ratio >= float(trajectory_config.get("min_yesterday_amount_ratio", 0)) and
                volume_ratio >= float(trajectory_config.get("min_yesterday_max_1m_volume_ratio", 0)) and
                gap is not None and
                float(trajectory_config.get("final_gap_min", 0)) <= gap <=
                float(trajectory_config.get("final_gap_max", 1))
            )
            if (gates and row.get("potential_grade") == "watch" and
                    row.get("trajectory") in promising):
                row["potential_grade"] = "A"
                row["evidence"].append("local_lc1_volume_gate")
        else:
            row["failed_evidence"].append("local_minute_baseline_invalid")
        row["evidence"] = list(dict.fromkeys(row["evidence"]))
        row["failed_evidence"] = list(dict.fromkeys(row["failed_evidence"]))
        candidates.append(row)
    from services.collector.auction_radar import rank_candidates
    merged.update({"candidates": rank_candidates(candidates), "local_merged": True, "private": True,
                   "baseline_source": baseline.get("source") if baseline_valid else None,
                   "baseline_source_date": source_date if baseline_valid else None,
                   "baseline_quality": ((baseline.get("quality") or {}) if baseline_valid else
                                        {"status": "missing"})})
    return merged


def calculate_member_realtime(config, shared_root=None):
    """公共行情结合会员前复权 K 线计算；输出只写 members/<id>。"""
    shared_path = Path(shared_root or default_shared_root()) / "realtime" / "latest.json"
    snapshot = json.loads(shared_path.read_text(encoding="utf-8"))
    date_str = str(snapshot.get("data_date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise ValueError("公共行情缺少有效日期")
    member_root = Path(config["kline_dir"]).resolve().parent
    facts_root = member_root / "facts"
    with _CALC_LOCK:
        _run_member_strategy_baseline(config, date_str, member_root, shared_root)
        auction_context, _ = build_member_auction_context(config, date_str, member_root)
        minute_baseline = build_member_minute_baseline(
            config, date_str, (snapshot.get("stocks") or {}).keys(), member_root)
        strategy_config = json.loads(_bundled_strategy_config().read_text(encoding="utf-8"))
        strategy_path = facts_root / date_str / "strategy.json"
        strategy = json.loads(strategy_path.read_text(encoding="utf-8")) if strategy_path.is_file() else {}
        from services.collector.realtime_engine import build_frozen_ctx, scan_snapshot
        frozen = {}
        cutoff = int(date_str.replace("-", ""))
        for sid in strategy:
            path = Path(config["kline_dir"]) / f"{sid}.json"
            if not path.is_file():
                continue
            bars = [bar for bar in (json.loads(path.read_text(encoding="utf-8")).get("bars") or [])
                    if int(bar.get("d") or 0) < cutoff]
            if bars:
                frozen[sid] = build_frozen_ctx(sid, bars, strategy)
        quotes = {}
        for sid, raw_quote in (snapshot.get("stocks") or {}).items():
            quote = dict(raw_quote or {})
            quote.setdefault("code", sid[2:])
            quote.setdefault("stock_id", sid)
            quote.setdefault("preclose", (frozen.get(sid) or {}).get("prev_close") or quote.get("price") or 0)
            quotes[sid] = quote
        scan_snapshot(str(facts_root), date_str, frozen, quotes, now=snapshot.get("ts"))
        pool_path = facts_root / date_str / "pool.json"
        event_path = facts_root / date_str / "events.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8")) if pool_path.is_file() else {"pools": {}}
        raw_events = json.loads(event_path.read_text(encoding="utf-8")).get("events", []) if event_path.is_file() else []
        try:
            from services.collector.archive_job import EVENT_SCHEMA_VERSION, build_event_view
        except ModuleNotFoundError:
            from collector.archive_job import EVENT_SCHEMA_VERSION, build_event_view
        events = build_event_view(raw_events)
        model_hits, actionable = [], []
        for sid, entry in strategy.items():
            quote = quotes.get(sid) or {}
            models = sorted((entry.get("models") or {}).keys())
            if not models:
                continue
            hit = {"stock_id": sid, "model_hit": models, "score": entry.get("score"),
                   "price": quote.get("price"), "change_pct": quote.get("change_pct"),
                   "ts": snapshot.get("ts", "")}
            model_hits.append(hit)
            try:
                price, buy, stop = float(quote.get("price") or 0), float(entry.get("buy_point") or 0), float(entry.get("stop") or 0)
                rr, chg = float(entry.get("rr") or 0), float(quote.get("change_pct") or 0)
            except (TypeError, ValueError):
                continue
            if entry.get("bp_pass") is True and rr >= 3 and stop < price <= buy * 1.05 and -4 <= chg < 8:
                actionable.append({**hit, "quality_score": entry.get("score"),
                                   "confirm": entry.get("confirm") or {},
                                   "buy_lo": buy, "stop": stop, "stop_pct": entry.get("stop_pct"),
                                   "rr": rr, "target": entry.get("target"), "level": "本地",
                                   "reasons": ["本地会员模型", "会员前复权K线"], "stars": entry.get("stars", 2)})
        model_hits.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
        actionable.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
        result = {"available": True, "member_id": config["member_id"], "data_date": date_str,
                  "event_schema_version": EVENT_SCHEMA_VERSION,
                  "ts": snapshot.get("ts"), "quote_count": len(quotes), "model_hits": model_hits,
                  "actionable_alerts": actionable[:30], "events": events,
                  "pool": pool.get("pools") or {},
                  "auction_context_count": len(auction_context.get("stocks") or {}),
                  "auction_radar": merge_member_auction_radar(
                      snapshot.get("auction_radar") or {}, auction_context, strategy,
                      minute_baseline=minute_baseline,
                      radar_config=strategy_config.get("auction_radar") or {}, target_date=date_str),
                  "private": True}
        _atomic_json(member_root / "realtime" / "latest.json", result)
        materialize_member_strategy_archive(config, date_str, shared_root)
        return result


def member_calculation_revision(config, shared_root=None):
    shared = Path(shared_root or default_shared_root())
    member_root = Path(config["kline_dir"]).resolve().parent

    def read(path):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    sync = read(shared / "sync_state.json")
    generation = read(member_root / "generation_status.json")
    strategy_path = _bundled_strategy_config()
    strategy_hash = hashlib.sha256(strategy_path.read_bytes()).hexdigest() if strategy_path.is_file() else "missing"
    inputs = {"member_id": config.get("member_id"), "data_date": sync.get("data_date"),
              "public_revision": sync.get("revision"), "public_cursor": sync.get("cursor"),
              "kline_finished_at": generation.get("finished_at"),
              "kline_generated": generation.get("generated"),
              "strategy_config_hash": strategy_hash, "engine_version": HELPER_VERSION}
    canonical = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_member_calculation_once(config, shared_root=None, calculate_fn=None, now=None,
                                min_interval_seconds=60):
    shared = Path(shared_root or default_shared_root())
    member_root = Path(config["kline_dir"]).resolve().parent
    state_path = member_root / "runtime" / "calculation_state.json"
    revision = member_calculation_revision(config, shared)
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    if previous.get("revision") == revision and previous.get("status") == "success":
        return {**previous, "status": "skipped", "reason": "revision unchanged"}
    clock = now or datetime.now()
    if previous.get("status") == "success" and previous.get("finished_at"):
        try:
            elapsed = (clock - datetime.fromisoformat(previous["finished_at"])).total_seconds()
        except (TypeError, ValueError):
            elapsed = min_interval_seconds
        if elapsed < min_interval_seconds:
            return {**previous, "status": "skipped", "reason": "minimum interval",
                    "pending_revision": revision}
    run_id = f"member-{clock.strftime('%Y%m%dT%H%M%S')}-{revision[:12]}"
    running = {"schema_version": "member-calculation-v1", "run_id": run_id,
               "revision": revision, "status": "running",
               "started_at": clock.isoformat(timespec="seconds"), "error": ""}
    _atomic_json(state_path, running)
    try:
        result = (calculate_fn or calculate_member_realtime)(config, shared)
        completed = {**running, "status": "success",
                     "finished_at": (now or datetime.now()).isoformat(timespec="seconds"),
                     "quote_count": int(result.get("quote_count") or 0),
                     "model_count": len(result.get("model_hits") or []),
                     "actionable_count": len(result.get("actionable_alerts") or [])}
        _atomic_json(state_path, completed)
        return completed
    except Exception as exc:
        failed = {**running, "status": "failed",
                  "finished_at": (now or datetime.now()).isoformat(timespec="seconds"),
                  "error": f"{type(exc).__name__}: {exc}"}
        _atomic_json(state_path, failed)
        raise


def load_member_realtime(member_id, members_root=None):
    config = load_member_config(member_id, members_root)
    path = Path(config.get("kline_dir") or "").resolve().parent / "realtime" / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def project_member_history_pools(pool, data_date, limits=None):
    """Build a bounded current-day history view from the existing local result."""
    source = (pool or {}).get("pools") or (pool or {})
    caps = {"alert": 30, "candidate": 100}
    caps.update(limits or {})

    def rank(item):
        stock_id, row = item
        confirm = row.get("confirm") or {}
        confirmed = sum(1 for value in confirm.values() if value is True)
        model_hit = row.get("model_hit") or row.get("model_hits") or []
        return (-int(row.get("stars") or 0), -confirmed,
                -float(row.get("score") or 0), -len(model_hit), stock_id)

    projected = {}
    summary = {}
    for name in ("alert", "candidate"):
        rows = source.get(name) or {}
        items = rows.items() if isinstance(rows, dict) else []
        eligible = [(stock_id, row) for stock_id, row in items
                    if isinstance(row, dict) and row.get("signal_family") != "auction_radar"]
        ordered = sorted(eligible, key=rank)
        shown = ordered[:max(0, int(caps[name]))]
        projected[name] = dict(shown)
        summary[name] = {"total": len(eligible), "shown": len(shown)}
    return {"data_date": data_date, "pools": projected}, summary


def monitoring_dashboard(config, shared_root=None):
    member_root = Path(config.get("kline_dir") or "").resolve().parent
    shared = Path(shared_root or default_shared_root())
    def read(path, fallback):
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback
        except (OSError, json.JSONDecodeError):
            return fallback
    local = read(member_root / "realtime" / "latest.json", {})
    public = read(shared / "public" / "latest.json", {})
    sync = read(shared / "sync_state.json", {})
    date_str = local.get("data_date") or sync.get("data_date") or ""
    strategy = read(member_root / "facts" / date_str / "strategy.json", {}) if date_str else {}
    return {"monitoring": bool(sync.get("ok") and config.get("kline_dir")), "sync": sync,
            "data_date": date_str, "ts": local.get("ts") or public.get("ts") or "",
            "quote_count": int(local.get("quote_count") or 0), "baseline_count": len(strategy),
            "public": {"limitup_count": len(public.get("limitup") or []),
                       "actionable_count": len(public.get("actionable_alerts") or []),
                       "event_count": len(public.get("events") or []),
                       "actionable": (public.get("actionable_alerts") or [])[:10]},
            "local": {"model_count": len(local.get("model_hits") or []),
                      "actionable_count": len(local.get("actionable_alerts") or []),
                      "event_count": len(local.get("events") or []),
                      "actionable": (local.get("actionable_alerts") or [])[:20]}}


def build_runtime_status(data_root, shared_root, runtime_root, members_root, now=None):
    clock = now or datetime.now()

    def read(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8-sig")) if Path(path).is_file() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    sync = read(Path(shared_root) / "sync_state.json")
    try:
        synced = datetime.fromisoformat(str(sync.get("synced_at") or ""))
        sync_age = max(0, (clock - synced).total_seconds())
    except ValueError:
        sync_age = None
    freshness_limit = 660 if sync.get("market_status") in ("closed", "holiday") else 90
    sync_fresh = bool(sync.get("ok") and sync_age is not None and sync_age <= freshness_limit)
    datasets_complete = bool(sync.get("manifest_verified") and sync.get("complete"))
    license_cache = load_license_cache(runtime_root)
    member_id = str(license_cache.get("member_id") or "")
    license_valid = license_allows_member(
        license_cache, member_id, license_cache.get("device_fingerprint"), now=clock)
    calculation = read(Path(members_root) / member_id / "runtime" / "calculation_state.json") if member_id else {}
    calculation_ok = calculation.get("status") == "success" and int(calculation.get("quote_count") or 0) > 0
    return {"service": "jinshi-local-workbench", "version": HELPER_VERSION,
            "data_root": str(Path(data_root).resolve()),
            "monitoring": bool(sync_fresh and datasets_complete and license_valid and calculation_ok),
            "stage": ("monitoring" if sync_fresh and datasets_complete and license_valid and calculation_ok else
                      "license_required" if not license_valid else
                      "sync_stale" if not sync_fresh else
                      "data_incomplete" if not datasets_complete else "calculation_pending"),
            "sync": {**sync, "fresh": sync_fresh, "age_seconds": sync_age,
                     "freshness_limit_seconds": freshness_limit,
                     "datasets_complete": datasets_complete},
            "license": {"valid": license_valid, "member_id": member_id,
                        "plan": license_cache.get("plan"),
                        "expire_date": license_cache.get("expire_date"),
                        "remaining_days": license_cache.get("remaining_days"),
                        "checked_at": license_cache.get("checked_at")},
            "calculation": calculation}


def install_paths(local_appdata=None, appdata=None):
    local = Path(local_appdata or os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    roaming = Path(appdata or os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return {
        "exe": local / "JinshiDSH" / "bin" / f"JinshiDSH-MemberHelper-{HELPER_VERSION}.exe",
        "startup": roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" /
                   "JinshiDSH-MemberHelper.cmd",
    }


def startup_command(executable):
    return '@echo off\r\nstart "" "{}" --serve\r\n'.format(Path(executable))


def installation_status_message(already_installed):
    if already_installed:
        return "金十DSH 本地助手已运行。\n\n请返回会员中心，点击“重新检测助手”。"
    return "金十DSH 本地助手安装成功并已启动。\n\n请等待约 10 秒，再返回会员中心点击“重新检测助手”。"


def show_installation_status(already_installed):
    """无控制台 EXE 给用户明确反馈；非 Windows 环境静默跳过。"""
    try:
        ctypes.windll.user32.MessageBoxW(0, installation_status_message(already_installed),
                                        "金十DSH 本地助手", 0x40)
    except (AttributeError, OSError):
        pass


def older_helper_image_names():
    patch = int(HELPER_VERSION.rsplit(".", 1)[1])
    return tuple(f"JinshiDSH-MemberHelper-1.0.{index}.exe" for index in range(patch))


def running_helper_version():
    try:
        with urlopen("http://127.0.0.1:8790/api/health", timeout=1) as response:
            document = json.loads(response.read().decode("utf-8"))
            return str(document.get("version") or ("legacy" if document.get("ok") else ""))
    except Exception:
        return ""


def stop_older_helpers():
    for image in older_helper_image_names():
        subprocess.run(["taskkill", "/F", "/IM", image], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install_frozen_helper(executable=None):
    """把单文件 EXE 安装到当前用户目录并注册启动项；返回安装后的 EXE。"""
    source = Path(executable or sys.executable).resolve()
    paths = install_paths()
    target = paths["exe"]
    target.parent.mkdir(parents=True, exist_ok=True)
    paths["startup"].parent.mkdir(parents=True, exist_ok=True)
    same_binary = target.is_file() and filecmp.cmp(source, target, shallow=False)
    if source != target.resolve() and not same_binary:
        temp = target.with_suffix(".tmp.exe")
        shutil.copy2(source, temp)
        try:
            os.replace(temp, target)
        except PermissionError:
            # Windows 会锁定正在运行的 EXE。同版本重复安装或升级时复用当前
            # 可执行文件，启动项仍会被刷新；下一个版本使用独立版本文件名。
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            if not target.is_file():
                raise
    paths["startup"].write_text(startup_command(target), encoding="utf-8")
    return target


def default_members_root():
    return local_paths()["members"]


def find_gbbq_path(tdx_root):
    root = Path(tdx_root)
    candidates = (root / "T0002" / "hq_cache" / "gbbq",
                  root / "T0002" / "hq_cache" / "gbbq.dat")
    return next((path for path in candidates if path.is_file()), candidates[0])


def normalize_member_config(payload, members_root=None):
    root = Path(members_root or default_members_root()).resolve()
    member_id = str((payload or {}).get("member_id") or "").strip()
    if not MEMBER_ID_RE.fullmatch(member_id):
        raise ValueError("会员 ID 只能包含字母、数字、下划线和短横线")
    raw_vipdoc = str((payload or {}).get("vipdoc") or "").strip().strip('"')
    if not raw_vipdoc:
        raise ValueError("请填写通达信 vipdoc 路径")
    vipdoc = Path(raw_vipdoc).expanduser().resolve()
    valid = (vipdoc / "sh" / "lday").is_dir() and (vipdoc / "sz" / "lday").is_dir()
    raw_tdx_root = str((payload or {}).get("tdx_root") or "").strip().strip('"')
    tdx_root = Path(raw_tdx_root).expanduser().resolve() if raw_tdx_root else vipdoc.parent
    raw_gbbq = str((payload or {}).get("gbbq_path") or "").strip().strip('"')
    gbbq_path = Path(raw_gbbq).expanduser().resolve() if raw_gbbq else find_gbbq_path(tdx_root).resolve()
    member_dir = (root / member_id).resolve()
    if root not in member_dir.parents:
        raise ValueError("会员目录越界")
    return {"member_id": member_id, "vipdoc": str(vipdoc), "tdx_root": str(tdx_root),
            "gbbq_path": str(gbbq_path), "gbbq_valid": gbbq_path.is_file(),
            "kline_dir": str(member_dir / "kline"), "vipdoc_valid": valid}


def save_member_config(payload, members_root=None):
    root = Path(members_root or default_members_root()).resolve()
    config = normalize_member_config(payload, root)
    member_dir = root / config["member_id"]
    member_dir.mkdir(parents=True, exist_ok=True)
    Path(config["kline_dir"]).mkdir(parents=True, exist_ok=True)
    path = member_dir / "config.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return config


def load_member_config(member_id, members_root=None):
    if not MEMBER_ID_RE.fullmatch(str(member_id or "")):
        raise ValueError("会员 ID 不合法")
    path = Path(members_root or default_members_root()) / member_id / "config.json"
    if not path.is_file():
        return {"member_id": member_id, "vipdoc": "", "tdx_root": "", "gbbq_path": "",
                "gbbq_valid": False, "kline_dir": "", "vipdoc_valid": False}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_generation_status(config, status):
    path = Path(config["kline_dir"]).parent / "generation_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def load_generation_status(config):
    path = Path(config.get("kline_dir") or "").parent / "generation_status.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def generate_member_klines(config, progress=None):
    """扫描会员 vipdoc，按 DATA_MODEL 输出前复权 `kline/<stock_id>.json`。"""
    from services.collector import kline_sync
    from services.collector.normalize import is_equity_code

    vipdoc = Path(config["vipdoc"])
    files = []
    for market in ("sh", "sz", "bj"):
        files.extend((market, path) for path in sorted((vipdoc / market / "lday").glob(f"{market}*.day")))
    files = [(market, path) for market, path in files
             if len(path.stem) >= 8 and is_equity_code(path.stem[-6:])]
    os.environ["TDX_ROOT"] = config.get("tdx_root") or str(vipdoc.parent)
    os.environ["TDX_GBBQ_PATH"] = config.get("gbbq_path") or ""
    kline_sync._GBBQ_CACHE = None
    generated, failed = 0, []
    total = len(files)
    for index, (market, path) in enumerate(files, 1):
        code = path.stem[-6:]
        try:
            _, count = kline_sync.sync_stock(code, market, str(vipdoc), config["kline_dir"])
            if count:
                generated += 1
            else:
                failed.append(code)
        except Exception as exc:
            failed.append(f"{code}: {exc}")
        if progress and (index == total or index % 25 == 0):
            progress({"total": total, "processed": index, "generated": generated,
                      "failed": len(failed), "current": code})
    return {"total": total, "processed": total, "generated": generated,
            "failed": len(failed), "failed_samples": failed[:20]}


def start_member_generation(config):
    member_id = config["member_id"]
    with _GENERATION_LOCK:
        running = _GENERATION_THREADS.get(member_id)
        if running and running.is_alive():
            return load_generation_status(config)
        status = {"state": "running", "total": 0, "processed": 0, "generated": 0,
                  "failed": 0, "started_at": datetime.now().isoformat(timespec="seconds")}
        _write_generation_status(config, status)

        def worker():
            def update(partial):
                status.update(partial)
                _write_generation_status(config, status)
            try:
                status.update(generate_member_klines(config, update))
                status["state"] = "complete"
            except Exception as exc:
                status.update({"state": "failed", "error": str(exc)})
            status["finished_at"] = datetime.now().isoformat(timespec="seconds")
            _write_generation_status(config, status)

        thread = threading.Thread(target=worker, name=f"kline-{member_id}", daemon=True)
        _GENERATION_THREADS[member_id] = thread
        thread.start()
        return status


def render_member_page(config=None, message="", error="", generation=None):
    config = config or {}
    member_id = html.escape(str(config.get("member_id") or ""), quote=True)
    vipdoc = html.escape(str(config.get("vipdoc") or ""), quote=True)
    tdx_root = html.escape(str(config.get("tdx_root") or ""), quote=True)
    gbbq_path = html.escape(str(config.get("gbbq_path") or ""), quote=True)
    kline_dir = html.escape(str(config.get("kline_dir") or ""), quote=True)
    notice = html.escape(error or message)
    notice_class = "bad" if error else "ok"
    generation = generation or {}
    state = generation.get("state")
    if state == "running":
        total, processed = generation.get("total", 0), generation.get("processed", 0)
        generation_html = f'<div class="progress">正在生成：{processed}/{total or "扫描中"}，已成功 {generation.get("generated", 0)}，失败 {generation.get("failed", 0)}。页面会自动刷新。</div>'
        refresh = '<meta http-equiv="refresh" content="3">'
    elif state == "complete":
        generation_html = f'<div class="notice ok">生成完成：共扫描 {generation.get("total", 0)}，成功 {generation.get("generated", 0)}，失败 {generation.get("failed", 0)}。</div>'
        refresh = ""
    elif state == "failed":
        generation_html = '<div class="notice bad">生成失败：' + html.escape(str(generation.get("error") or "未知错误")) + '</div>'
        refresh = ""
    else:
        generation_html = ""
        refresh = ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<title>金十DSH 本地日K配置</title><style>*{{box-sizing:border-box}}body{{margin:0;font:14px Arial,"Microsoft YaHei";background:#0d1117;color:#c9d1d9}}.page{{display:grid;grid-template-columns:220px 1fr;min-height:100vh}}.side{{padding:24px 16px;background:#161b22;border-right:1px solid #30363d}}.side b{{font-size:18px;color:#fff}}.side p{{color:#8b949e;line-height:1.7}}.side a{{display:block;margin-top:24px;color:#58a6ff;text-decoration:none}}.main{{padding:38px;max-width:860px}}.card{{padding:26px;background:#161b22;border:1px solid #30363d;border-radius:10px}}h1{{margin-top:0;font-size:21px}}label{{display:block;margin:18px 0;color:#8b949e}}input{{display:block;width:100%;margin-top:7px;padding:11px;border:1px solid #30363d;border-radius:6px;background:#0d1117;color:#fff}}button{{margin-right:10px;padding:11px 18px;border:0;border-radius:6px;background:#238636;color:#fff;cursor:pointer}}button.secondary{{background:#1f6feb}}.notice,.progress{{margin:0 0 18px;padding:12px;border-radius:6px}}.notice.ok,.progress{{background:#12351f;color:#3fb950}}.notice.bad{{background:#3d1719;color:#f85149}}.hint{{color:#8b949e;line-height:1.7}}@media(max-width:700px){{.page{{grid-template-columns:1fr}}.side{{border-right:0;border-bottom:1px solid #30363d}}.main{{padding:20px}}}}</style></head><body><div class="page"><aside class="side"><b>金十DSH 本地助手</b><p>通达信路径、权息数据和会员 K 线都只保存在本机，不经过公共服务器。</p><a href="http://114.132.236.131/dsh/index.html#member">← 返回会员中心</a></aside><main class="main"><div class="card"><h1>本地日 K 配置与生成</h1>{(f'<div class="notice {notice_class}">{notice}</div>' if notice else '')}{generation_html}<p class="hint">原始日线读取 vipdoc；前复权读取通达信根目录下的 T0002\\hq_cache\\gbbq（或 gbbq.dat）。</p><form method="post"><label>云会员编号<input name="member_id" value="{member_id}" readonly required></label><label>通达信 vipdoc 路径<input name="vipdoc" value="{vipdoc}" placeholder="例如 D:\\通达信\\vipdoc" required></label><label>通达信根目录（复权权息数据）<input name="tdx_root" value="{tdx_root}" placeholder="例如 D:\\通达信"></label><label>检测到的权息文件<input value="{gbbq_path}" readonly placeholder="自动查找 T0002\\hq_cache\\gbbq"></label><label>会员 K 线目录<input value="{kline_dir}" readonly placeholder="保存后自动生成"></label><button type="submit" formaction="/member/save">仅保存配置</button><button class="secondary" type="submit" formaction="/member/generate">保存配置并生成会员 K 线</button></form></div></main></div></body></html>"""


_render_member_config_page = render_member_page


def render_member_page(config=None, message="", error="", generation=None, dashboard=None):
    """本地助手工作台：先显示监控/信号/基线，再显示原配置表单。"""
    config = config or {}
    dashboard = dashboard or (monitoring_dashboard(config) if config.get("kline_dir") else {})
    public, local, sync = dashboard.get("public") or {}, dashboard.get("local") or {}, dashboard.get("sync") or {}
    def signal_rows(items):
        rows = []
        for item in items or []:
            reason = "、".join(item.get("reasons") or item.get("model_hit") or [])
            rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(item.get("stock_id") or "")), html.escape(str(item.get("score") or "-")),
                html.escape(str(item.get("price") or "-")), html.escape(reason)))
        return "".join(rows) or '<tr><td colspan="4" class="hint">当前暂无</td></tr>'
    running = dashboard.get("monitoring")
    status = "● 正在监控" if running else "● 尚未开始监控"
    status_class = "on" if running else "off"
    member_id = html.escape(str(config.get("member_id") or ""), quote=True)
    vipdoc = html.escape(str(config.get("vipdoc") or ""), quote=True)
    tdx_root = html.escape(str(config.get("tdx_root") or ""), quote=True)
    gbbq = html.escape(str(config.get("gbbq_path") or ""), quote=True)
    kline = html.escape(str(config.get("kline_dir") or ""), quote=True)
    notice = html.escape(error or message)
    generation = generation or {}
    generation_text = ""
    if generation.get("state"):
        generation_text = '<p class="hint">K线生成：{}，成功 {}，失败 {}</p>'.format(
            html.escape(str(generation.get("state"))), generation.get("generated", 0), generation.get("failed", 0))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>金十DSH 本地助手</title>
<style>*{{box-sizing:border-box}}body{{margin:0;font:14px Arial,"Microsoft YaHei";background:#0d1117;color:#c9d1d9}}.page{{display:grid;grid-template-columns:220px 1fr;min-height:100vh}}aside{{padding:24px 16px;background:#161b22;border-right:1px solid #30363d}}aside b{{font-size:18px;color:white}}aside a{{display:block;margin-top:18px;color:#58a6ff;text-decoration:none}}main{{padding:28px;max-width:1200px}}.card,.dash{{padding:22px;background:#161b22;border:1px solid #30363d;border-radius:10px;margin-bottom:18px}}h1{{margin-top:0}}h2{{font-size:17px}}.status{{display:inline-block;padding:7px 12px;border-radius:20px}}.on{{background:#12351f;color:#3fb950}}.off{{background:#3d1719;color:#f85149}}.metrics,.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}}.grid{{grid-template-columns:1fr 1fr}}.metrics div{{padding:14px;background:#0d1117;border-radius:7px}}.metrics b,.metrics span{{display:block}}.metrics span,.hint{{color:#8b949e;margin-top:6px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #30363d;text-align:left}}label{{display:block;margin:16px 0;color:#8b949e}}input{{display:block;width:100%;margin-top:6px;padding:10px;background:#0d1117;color:white;border:1px solid #30363d;border-radius:6px}}button{{padding:10px 16px;margin-right:8px;border:0;border-radius:6px;background:#238636;color:white}}button.secondary{{background:#1f6feb}}a{{color:#58a6ff}}@media(max-width:800px){{.page{{grid-template-columns:1fr}}.metrics,.grid{{grid-template-columns:1fr}}}}</style></head>
<body><div class="page"><aside><b>金十DSH 本地助手</b><p class="hint">公共行情来自服务器；会员K线、策略基线和本地预警只保存在本机。</p><a href="#monitor">监控状态</a><a href="#public">公共信号</a><a href="#baseline">策略基线</a><a href="#local">本地可买预警</a><a href="#config">日K配置</a></aside><main>
<section class="dash" id="monitor"><h1>监控运行状态</h1><span class="status {status_class}">{status}</span><div class="metrics"><div><b>{html.escape(str(dashboard.get('data_date') or '-'))}</b><span>数据日期</span></div><div><b>{html.escape(str(dashboard.get('ts') or '-'))}</b><span>行情时间</span></div><div><b>{dashboard.get('quote_count',0)}</b><span>公共行情只数</span></div><div><b>{dashboard.get('baseline_count',0)}</b><span>策略基线只数</span></div></div><p class="hint">最近同步：{html.escape(str(sync.get('synced_at') or '-'))}　游标：{html.escape(str(sync.get('cursor') or '-'))}　助手版本：{HELPER_VERSION}</p></section>
<div class="grid"><section class="card" id="public"><h2>公共信号</h2><p>涨停 {public.get('limitup_count',0)}　可买预警 {public.get('actionable_count',0)}　事件 {public.get('event_count',0)}</p><p><a href="http://114.132.236.131/dsh/index.html#signal">打开服务器实时信号页</a></p><table><thead><tr><th>代码</th><th>分数</th><th>现价</th><th>原因</th></tr></thead><tbody>{signal_rows(public.get('actionable'))}</tbody></table></section>
<section class="card" id="baseline"><h2>策略基线</h2><p>冻结模型股票：<b>{dashboard.get('baseline_count',0)}</b> 只</p><p>实时模型候选：<b>{local.get('model_count',0)}</b> 只</p><p class="hint">位置：会员目录 / facts / {html.escape(str(dashboard.get('data_date') or '日期'))} / strategy.json</p></section></div>
<section class="card" id="local"><h2>本地可买预警</h2><p>当前 {local.get('actionable_count',0)} 条；本地事件 {local.get('event_count',0)} 条。</p><table><thead><tr><th>代码</th><th>分数</th><th>现价</th><th>原因</th></tr></thead><tbody>{signal_rows(local.get('actionable'))}</tbody></table></section>
<section class="card" id="config"><h2>本地日 K 配置</h2>{('<p>'+notice+'</p>' if notice else '')}{generation_text}<form method="post"><label>云会员编号<input name="member_id" value="{member_id}" readonly required></label><label>通达信 vipdoc 路径<input name="vipdoc" value="{vipdoc}" required></label><label>通达信根目录（复权权息数据）<input name="tdx_root" value="{tdx_root}"></label><label>检测到的权息文件<input value="{gbbq}" readonly></label><label>会员 K 线目录<input value="{kline}" readonly></label><button formaction="/member/save">仅保存配置</button><button class="secondary" formaction="/member/generate">保存配置并生成会员 K 线</button></form></section>
</main></div></body></html>'''


def encode_json_transport(body, accept_encoding=""):
    """Encode a JSON response once and apply bounded HTTP compression metadata."""
    raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
    etag = '"' + hashlib.sha256(raw).hexdigest()[:24] + '"'
    headers = {"ETag": etag}
    if "gzip" in str(accept_encoding).lower() and len(raw) > 512:
        raw = gzip.compress(raw, compresslevel=4)
        headers["Content-Encoding"] = "gzip"
    return raw, headers


class MemberHandler(BaseHTTPRequestHandler):
    _paths = local_paths()
    data_root = _paths["root"]
    members_root = _paths["members"]
    shared_root = _paths["shared"]
    web_root = default_web_root()
    local_token = secrets.token_urlsafe(32)
    upstream_api = REMOTE_SERVER_API
    bootstrap_path = default_bootstrap_path()
    runtime_root = _paths["runtime"]
    license_api = "http://114.132.236.131:18908/api"
    license_required = True
    auction_manager = AuctionProcessManager()
    auction_probe = staticmethod(test_eltdx_connection)

    def _member_authorized(self, member_id):
        if not self.license_required:
            return True
        cache = load_license_cache(self.runtime_root)
        return license_allows_member(cache, member_id, cache.get("device_fingerprint"))

    def _active_member_id(self):
        cache = load_license_cache(self.runtime_root)
        member_id = str(cache.get("member_id") or "").strip()
        if member_id:
            return member_id
        configs = sorted(Path(self.members_root).glob("*/config.json"))
        if len(configs) == 1:
            try:
                return str(json.loads(configs[0].read_text(encoding="utf-8")).get("member_id") or "")
            except (OSError, json.JSONDecodeError):
                pass
        return ""

    def _allowed_origin(self):
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return ""
        parsed = urlparse(origin)
        return origin if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") else ""

    def _write_authorized(self):
        origin = str(self.headers.get("Origin") or "").strip()
        if origin and not self._allowed_origin():
            return False
        supplied = str(self.headers.get("X-Jinshi-Local-Token") or "")
        if not supplied:
            cookies = {}
            for item in str(self.headers.get("Cookie") or "").split(";"):
                if "=" in item:
                    key, value = item.strip().split("=", 1)
                    cookies[key] = value
            supplied = cookies.get("JINSHI_LOCAL_TOKEN", "")
        return bool(supplied and secrets.compare_digest(supplied, self.local_token))

    def _send(self, status, body):
        raw, transport = encode_json_transport(body, self.headers.get("Accept-Encoding") or "")
        if status == 200 and self.headers.get("If-None-Match") == transport["ETag"]:
            self.send_response(304)
            self.send_header("ETag", transport["ETag"])
            self.end_headers()
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in transport.items():
            self.send_header(name, value)
        allowed_origin = self._allowed_origin()
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jinshi-Local-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(raw)

    def _send_script(self, status, callback, body):
        raw = (callback + "(" + json.dumps(body, ensure_ascii=False) + ");").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, status, document):
        raw = document.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", f"JINSHI_LOCAL_TOKEN={self.local_token}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(raw)

    def _send_static(self, relative_path):
        root = Path(self.web_root).resolve()
        target = (root / relative_path).resolve()
        if target != root and root not in target.parents:
            return self._send(404, {"ok": False, "error": "not found"})
        if not target.is_file():
            return self._send(404, {"ok": False, "error": "not found"})
        raw = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store" if target.name == "index.html" else "public, max-age=3600")
        if target.name == "index.html":
            self.send_header("Set-Cookie", f"JINSHI_LOCAL_TOKEN={self.local_token}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(raw)

    def _send_public_cache(self, relative_path):
        raw = None
        target = None
        normalized = str(relative_path or "").replace("\\", "/").lstrip("/")
        if re.fullmatch(r"web/strategy_all(?:_\d{4}-\d{2}-\d{2})?\.json(?:\.gz)?", normalized):
            member_id = self._active_member_id()
            if member_id and self._member_authorized(member_id):
                private_target = (Path(self.members_root) / member_id / "web" /
                                  normalized.removeprefix("web/"))
                if private_target.is_file():
                    raw = private_target.read_bytes()
                    target = private_target
        current_path = Path(self.shared_root) / "current.json"
        try:
            if raw is not None:
                raise FileExistsError("member-local strategy cache selected")
            current = json.loads(current_path.read_text(encoding="utf-8"))
            revision = str(current.get("revision") or "")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", revision):
                raise ValueError("invalid revision")
            root = (Path(self.shared_root) / "revisions" / revision).resolve()
            target = (root / relative_path).resolve()
            if root not in target.parents or not target.is_file():
                raise FileNotFoundError(relative_path)
            raw = target.read_bytes()
        except FileExistsError:
            pass
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        if raw is None:
            parts = tuple(part for part in normalized.split("/") if part)
            if len(parts) < 2 or parts[0] != "web" or any(part in (".", "..") for part in parts):
                return self._send(404, {"ok": False, "error": "public cache not available"})
            legacy_root = (Path(self.shared_root) / "legacy").resolve()
            target = (legacy_root.joinpath(*parts)).resolve()
            if legacy_root not in target.parents:
                return self._send(404, {"ok": False, "error": "public cache not available"})
            parsed_upstream = urlparse(self.upstream_api)
            site_path = parsed_upstream.path.rstrip("/")
            if site_path.endswith("/api"):
                site_path = site_path[:-4]
            site_root = f"{parsed_upstream.scheme}://{parsed_upstream.netloc}{site_path}/"
            address = urljoin(site_root, "data/" + normalized)
            try:
                with urlopen(address, timeout=20) as response:
                    downloaded = response.read()
                if not downloaded:
                    raise ValueError("empty public web response")
                if target.suffix.lower() == ".json":
                    json.loads(downloaded.decode("utf-8-sig"))
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(target.suffix + ".tmp")
                temp.write_bytes(downloaded)
                os.replace(temp, target)
                raw = downloaded
            except Exception:
                try:
                    raw = target.read_bytes()
                except OSError:
                    return self._send(404, {"ok": False, "error": "public cache not available"})
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)

    def _proxy_public_get(self):
        parsed = urlparse(self.path)
        suffix = parsed.path.removeprefix("/api/")
        if suffix == "intraday/latest":
            cached = Path(self.shared_root) / "public" / "latest.json"
            try:
                document = json.loads(cached.read_text(encoding="utf-8"))
                return self._send(200, {"data": document, "meta": {
                    "data_date": document.get("data_date"), "source": "member-local-cache",
                    "fetched_at": datetime.fromtimestamp(cached.stat().st_mtime).isoformat(
                        timespec="seconds")}})
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        address = self.upstream_api.rstrip("/") + "/" + suffix
        if parsed.query:
            address += "?" + parsed.query
        try:
            with urlopen(address, timeout=20) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except Exception as exc:
            return self._send(502, {"ok": False, "error": "public upstream unavailable",
                                    "detail": str(exc)})
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _member_pools(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        requested_date = str(query.get("date", [""])[0])
        member_id = self._active_member_id()
        private = {}
        if member_id and self._member_authorized(member_id) and requested_date:
            path = Path(self.members_root) / member_id / "facts" / requested_date / "pool.json"
            try:
                private = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                private = {}
        private_pools = private.get("pools") or {}
        # 历史选股完全以会员本地冻结池为准；命中时不再等待远端公共空池。
        if private_pools.get("alert") or private_pools.get("candidate"):
            return self._send(200, {"data": {"data_date": requested_date,
                                               "pools": private_pools},
                                    "meta": {"watchlist_scope": "member-local",
                                             "strategy_pool_scope": "member-local",
                                             "source": "member-local-archive"}})
        address = self.upstream_api.rstrip("/") + "/pools"
        if parsed.query:
            address += "?" + parsed.query
        try:
            with urlopen(address, timeout=20) as response:
                document = json.loads(response.read().decode("utf-8-sig"))
        except Exception as exc:
            document = {"data": {"data_date": requested_date, "pools": {}},
                        "meta": {"public_upstream": "unavailable", "detail": str(exc)}}
        if member_id and self._member_authorized(member_id):
            date_str = str(requested_date or
                           ((document.get("data") or {}).get("data_date") or ""))
            if not private or date_str != requested_date:
                path = Path(self.members_root) / member_id / "facts" / date_str / "pool.json"
                try:
                    private = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    private = {}
            pools = (document.setdefault("data", {}).setdefault("pools", {}))
            for name in ("limitup", "ladder", "alert", "candidate"):
                pools.setdefault(name, {})
            private_pools = private.get("pools") or {}
            for name in ("alert", "candidate", "watchlist"):
                if name in private_pools:
                    pools[name] = private_pools.get(name) or {}
            meta = document.setdefault("meta", {})
            meta["watchlist_scope"] = "member-local"
            meta["strategy_pool_scope"] = "member-local"
        return self._send(200, document)

    def _member_minute_volume(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        member_id = self._active_member_id()
        if not member_id or not self._member_authorized(member_id):
            return self._send(403, {"ok": False, "error": "会员授权无效"})
        try:
            min_ratio = max(0.0, float(query.get("ratio", [1.0])[0]))
        except (TypeError, ValueError):
            return self._send(400, {"ok": False, "error": "invalid ratio"})
        filter_name = str(query.get("filter", [""])[0])
        if filter_name and filter_name not in {"half", "near", "peak", "strong", "extreme"}:
            return self._send(400, {"ok": False, "error": "invalid filter"})
        selected_sid = str(query.get("stock", [""])[0]) or None
        source_query = {key: list(value) for key, value in query.items()}
        source_query["source"] = ["1"]
        requested_date = str(query.get("date", [""])[0])
        slim = _shared_web_document(self.shared_root, "stocks_slim.json")
        slim.update(_stock_metadata_from_documents(
            _shared_web_document(self.shared_root, f"day_{requested_date}.sector.json")
            if requested_date else {}))

        def fetch_source(stock=None):
            request_query = {key: list(value) for key, value in source_query.items()}
            if stock:
                request_query["stock"] = [stock]
            suffix = "/minute-volume?" + urlencode(request_query, doseq=True)
            last_error = None
            for upstream in dict.fromkeys((LOCAL_SERVER_API, self.upstream_api)):
                try:
                    with urlopen(upstream.rstrip("/") + suffix, timeout=30) as response:
                        source = expand_public_minute_source(
                            json.loads(response.read().decode("utf-8-sig")).get("data") or {})
                        metadata = dict(slim)
                        if not requested_date and source.get("data_date"):
                            metadata.update(_stock_metadata_from_documents(_shared_web_document(
                                self.shared_root, f'day_{source["data_date"]}.sector.json')))
                        for row in source.get("rows") or []:
                            master = metadata.get(row.get("stock_id")) or {}
                            row["name"] = str(master.get("n") or row.get("name") or row.get("stock_id"))
                            row.setdefault("sectors", list(master.get("s") or []))
                        return source
                except Exception as exc:
                    last_error = exc
            raise last_error or OSError("minute volume source unavailable")

        try:
            public_source = fetch_source(selected_sid)
        except Exception as exc:
            return self._send(502, {"ok": False, "error": "公共分钟量源不可用", "detail": str(exc)})
        date_str = str(query.get("date", [""])[0] or public_source.get("data_date") or "")
        try:
            config = load_member_config(member_id, self.members_root)
        except ValueError as exc:
            return self._send(400, {"ok": False, "error": str(exc)})
        stock_ids = [row.get("stock_id") for row in public_source.get("rows") or []
                     if row.get("stock_id")]
        member_root = Path(self.members_root) / member_id
        baseline = build_member_minute_baseline(config, date_str, stock_ids, member_root)
        pool_path = member_root / "facts" / date_str / "pool.json"
        try:
            pool = json.loads(pool_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pool = {}
        watchlist = ((pool.get("pools") or {}).get("watchlist") or {})
        preview = merge_member_minute_volume_source(
            public_source, baseline, [], min_ratio=min_ratio,
            selected_sid=selected_sid, watchlist=watchlist, filter_name=filter_name)
        detail_sid = ((preview.get("detail") or {}).get("stock_id"))
        if detail_sid and ((public_source.get("detail") or {}).get("stock_id") != detail_sid):
            try:
                public_source = fetch_source(detail_sid)
            except Exception:
                pass
        history = []
        if detail_sid:
            from services.collector.minute_volume_baseline import build_vipdoc_lc1_history
            history = build_vipdoc_lc1_history(config.get("vipdoc"), date_str, detail_sid, days=2)
        result = merge_member_minute_volume_source(
            public_source, baseline, history, min_ratio=min_ratio,
            selected_sid=detail_sid or selected_sid, watchlist=watchlist,
            filter_name=filter_name)
        return self._send(200, {"data": result, "meta": {
            "data_date": result.get("data_date"),
            "source": "member_lc1+public_minute_volume", "private": True}})

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        request_path = unquote(urlparse(self.path).path)
        if request_path in ("/", "/index.html"):
            return self._send_static("index.html")
        if request_path == "/member-guide.html":
            return self._send_static("member-guide.html")
        if request_path.startswith("/assets/"):
            return self._send_static(request_path.lstrip("/"))
        if request_path.startswith("/data/web/"):
            return self._send_public_cache(request_path.removeprefix("/data/"))
        if request_path == "/setup":
            return self._send_html(200, render_setup_page(self.data_root))
        if request_path == "/api/system/health":
            state_path = Path(self.shared_root) / "sync_state.json"
            sync_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
            return self._send(200, {"ok": True, "service": "jinshi-local-workbench",
                                    "version": HELPER_VERSION, "tabs": 7,
                                    "data_root": str(Path(self.data_root).resolve()),
                                    "sync": sync_state,
                                    "license": {key: value for key, value in
                                                load_license_cache(self.runtime_root).items()
                                                if key not in ("code", "device_fingerprint")}})
        if request_path == "/api/system/status":
            return self._send(200, build_runtime_status(
                self.data_root, self.shared_root, self.runtime_root, self.members_root))
        if request_path == "/api/system/update":
            parsed_upstream = urlparse(self.upstream_api)
            site_path = parsed_upstream.path.rstrip("/")
            if site_path.endswith("/api"):
                site_path = site_path[:-4]
            address = f"{parsed_upstream.scheme}://{parsed_upstream.netloc}{site_path}/downloads/member-workbench-latest.json"
            try:
                with urlopen(address, timeout=15) as response:
                    document = json.loads(response.read().decode("utf-8-sig"))
                return self._send(200, document)
            except Exception as exc:
                return self._send(502, {"ok": False, "error": "版本服务器连接失败", "detail": str(exc)})
        if self.path.startswith("/member"):
            member_id = parse_qs(urlparse(self.path).query).get("member_id", [""])[0]
            if member_id and not self._member_authorized(member_id):
                return self._send_html(403, render_member_page(
                    {"member_id": member_id}, error="云会员授权无效或已超过离线使用期限，请先在工作台会员中心重新校验。"))
            try:
                config = load_member_config(member_id, self.members_root) if member_id else {}
                return self._send_html(200, render_member_page(config, generation=load_generation_status(config) if config else {}))
            except ValueError as exc:
                return self._send_html(400, render_member_page({"member_id": member_id}, error=str(exc)))
        if self.path.startswith("/api/compat?"):
            query = parse_qs(urlparse(self.path).query)
            callback = query.get("callback", [""])[0]
            if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]{0,100}", callback):
                return self._send(400, {"ok": False, "error": "callback 不合法"})
            action = query.get("action", [""])[0]
            try:
                if action == "health":
                    body = {"ok": True, "service": "member-local", "private": True}
                elif action in ("realtime", "signal"):
                    member_id = query.get("member_id", [""])[0] or self._active_member_id()
                    if not self._member_authorized(member_id):
                        body = {"ok": False, "error": "会员授权无效"}
                        return self._send_script(200, callback, body)
                    data = load_member_realtime(member_id, self.members_root)
                    if data and action == "signal":
                        latest = data
                        data = {key: data.get(key) for key in
                                ("available", "member_id", "data_date", "ts", "quote_count")}
                        data["actionable_alerts"] = (latest.get("actionable_alerts") or [])[:30]
                        data["model_hits"] = (latest.get("model_hits") or [])[:500]
                        data["events"] = (latest.get("events") or [])[:200]
                        history_pools, history_summary = project_member_history_pools(
                            latest.get("pool") or {}, latest.get("data_date"))
                        data["history_pools"] = history_pools
                        data["history_pool_summary"] = history_summary
                    body = {"ok": bool(data), "data": data, "error": "本地策略结果尚未生成" if not data else ""}
                else:
                    body = {"ok": False, "error": "action 不合法"}
                return self._send_script(200, callback, body)
            except ValueError as exc:
                return self._send_script(200, callback, {"ok": False, "error": str(exc)})
        if self.path == "/api/health":
            state_path = Path(self.shared_root) / "sync_state.json"
            sync_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
            return self._send(200, {"ok": True, "service": "member-local", "version": HELPER_VERSION,
                                    "private": True, "sync": sync_state})
        if self.path == "/api/public/latest":
            path = Path(self.shared_root) / "realtime" / "latest.json"
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            return self._send(200 if data else 404, {"ok": bool(data), "data": data})
        if self.path.startswith("/api/member/config?"):
            try:
                member_id = parse_qs(urlparse(self.path).query).get("member_id", [""])[0]
                if not self._member_authorized(member_id):
                    return self._send(403, {"ok": False, "error": "会员授权无效"})
                return self._send(200, {"ok": True, "data": load_member_config(member_id, self.members_root)})
            except ValueError as exc:
                return self._send(400, {"ok": False, "error": str(exc)})
        if self.path.startswith("/api/member/realtime?"):
            try:
                member_id = parse_qs(urlparse(self.path).query).get("member_id", [""])[0]
                if not self._member_authorized(member_id):
                    return self._send(403, {"ok": False, "error": "会员授权无效"})
                data = load_member_realtime(member_id, self.members_root)
                return self._send(200 if data else 404, {"ok": bool(data), "data": data})
            except ValueError as exc:
                return self._send(400, {"ok": False, "error": str(exc)})
        if request_path == "/api/auction/status":
            member_id = self._active_member_id()
            if not member_id or not self._member_authorized(member_id):
                return self._send(403, {"ok": False, "error": "会员授权无效"})
            return self._send(200, {"ok": True,
                                    "data": self.auction_manager.status(member_id),
                                    "private": True})
        if request_path == "/api/auction/latest":
            member_id = self._active_member_id()
            if not member_id or not self._member_authorized(member_id):
                return self._send(403, {"ok": False, "error": "会员授权无效"})
            date_str = str(parse_qs(urlparse(self.path).query).get(
                "date", [datetime.now().date().isoformat()])[0])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                return self._send(400, {"ok": False, "error": "invalid date"})
            path = Path(self.members_root) / member_id / "facts" / date_str / "auction_radar.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return self._send(404, {"ok": False, "error": "本地竞价结果尚未生成"})
            return self._send(200, {"ok": True, "data": data, "private": True})
        if re.match(r"^/api/pools(?:\?|$)", self.path):
            return self._member_pools()
        if re.match(r"^/api/minute-volume(?:\?|$)", self.path):
            return self._member_minute_volume()
        if re.match(r"^/api/(health|days|day|intraday/latest|events|history|sectors/realtime|strategy/config)(?:\?|$)", self.path):
            return self._proxy_public_get()
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._write_authorized():
            return self._send(403, {"ok": False, "error": "local token required"})
        if self.path in ("/api/auction/start", "/api/auction/stop",
                         "/api/auction/test-connection"):
            member_id = self._active_member_id()
            if not member_id or not self._member_authorized(member_id):
                return self._send(403, {"ok": False, "error": "会员授权无效"})
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 65536)
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if self.path.endswith("/test-connection"):
                    result = self.auction_probe()
                elif self.path.endswith("/start"):
                    date_str = str(payload.get("date") or datetime.now().date().isoformat())
                    result = self.auction_manager.start(
                        member_id, self.members_root, date_str,
                        data_root=self.data_root, config_path=_bundled_strategy_config())
                else:
                    result = self.auction_manager.stop(member_id)
                return self._send(200, {"ok": True, "data": result, "private": True})
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                return self._send(400, {"ok": False, "error": str(exc)})
        if self.path == "/api/watchlist":
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 65536)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                member_id = self._active_member_id()
                if not member_id or not self._member_authorized(member_id):
                    return self._send(403, {"ok": False, "error": "会员授权无效"})
                sid = str(payload.get("stock_id") or "")
                action = str(payload.get("action") or "add")
                date_str = str(payload.get("date") or datetime.now().date().isoformat())
                source_date = str(payload.get("source_date") or date_str)
                if not re.fullmatch(r"[A-Z]{2}\d{6}", sid):
                    raise ValueError("invalid stock_id")
                if action not in ("add", "remove"):
                    raise ValueError("invalid action")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_date):
                    raise ValueError("invalid date")
                from services.collector.realtime_engine import update_watchlist
                facts = Path(self.members_root) / member_id / "facts"
                result = update_watchlist(str(facts), date_str, sid, action,
                                          note=str(payload.get("note") or "手动添加"),
                                          source_date=source_date)
                return self._send(200, {"ok": True, "data": result, "private": True})
            except (ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"ok": False, "error": str(exc)})
        if self.path == "/setup/save":
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            selected = form.get("data_root", [""])[0]
            try:
                saved = save_bootstrap(selected, self.bootstrap_path)
                local_paths(saved["data_root"], bootstrap_path=self.bootstrap_path)
                return self._send_html(200, render_setup_page(
                    saved["data_root"], message="保存成功，重启本地工作台后生效；旧目录未移动。"))
            except (ValueError, OSError) as exc:
                return self._send_html(400, render_setup_page(selected, error="保存失败：" + str(exc)))
        if re.fullmatch(r"/license-api/(activate|validate|trial/register)", self.path):
            action = self.path.removeprefix("/license-api/")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = refresh_cloud_license(action, payload, self.runtime_root, self.license_api)
                return self._send(200, result)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                return self._send(400, {"success": False, "message": str(exc)})
        if self.path in ("/member/save", "/member/generate"):
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            payload = {"member_id": form.get("member_id", [""])[0],
                       "vipdoc": form.get("vipdoc", [""])[0],
                       "tdx_root": form.get("tdx_root", [""])[0]}
            if not self._member_authorized(payload["member_id"]):
                return self._send_html(403, render_member_page(
                    payload, error="保存失败：云会员授权无效或已超过离线使用期限"))
            try:
                config = save_member_config(payload, self.members_root)
                if self.path == "/member/generate":
                    if not config["vipdoc_valid"]:
                        return self._send_html(400, render_member_page(config, error="生成失败：未找到 vipdoc/sh、sz 日线目录"))
                    generation = start_member_generation(config)
                    message = "配置已保存，会员 K 线已开始在后台生成"
                else:
                    generation = load_generation_status(config)
                    message = "保存成功，vipdoc 有效" if config["vipdoc_valid"] else "已保存，但未找到 sh/sz 日线目录"
                if not config["gbbq_valid"]:
                    message += "；未找到 gbbq 权息文件，将使用价格跳空回退复权"
                return self._send_html(200, render_member_page(config, message=message, generation=generation))
            except ValueError as exc:
                return self._send_html(400, render_member_page(payload, error="保存失败：" + str(exc)))
        if self.path not in ("/api/member/config", "/api/member/generate"):
            return self._send(404, {"ok": False, "error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not self._member_authorized(payload.get("member_id")):
                return self._send(403, {"ok": False, "error": "会员授权无效"})
            config = save_member_config(payload, self.members_root)
            generation = None
            if self.path == "/api/member/generate":
                if not config["vipdoc_valid"]:
                    return self._send(400, {"ok": False, "error": "未找到 vipdoc/sh、sz 日线目录",
                                            "data": config})
                generation = start_member_generation(config)
            response = {"ok": True, "data": config}
            if generation is not None:
                response["generation"] = generation
            self._send(200, response)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "error": str(exc)})

    def log_message(self, fmt, *args):
        return


def main(argv=None):
    worker_argv = list(sys.argv[1:] if argv is None else argv)
    if "--auction-worker" in worker_argv:
        worker_argv.remove("--auction-worker")
        from services.collector.auction_depth_shadow import main as auction_worker_main
        return auction_worker_main(worker_argv)
    parser = argparse.ArgumentParser(description="金十DSH 会员本地数据助手")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--data-root", default="", help="公共缓存、会员数据、日志和运行状态的统一根目录")
    parser.add_argument("--bootstrap-path", default="", help="数据根目录引导配置文件")
    parser.add_argument("--members-root", default="", help="兼容调试：显式覆盖会员目录")
    parser.add_argument("--server-api", default="", help="公共数据上游 API")
    parser.add_argument("--serve", action="store_true", help="直接运行本地服务（由安装后的 EXE/启动项使用）")
    args = parser.parse_args(argv)
    if getattr(sys, "frozen", False) and not args.serve:
        running_version = running_helper_version()
        already_installed = install_paths()["exe"].is_file()
        target = install_frozen_helper()
        if Path(sys.executable).resolve() != target.resolve():
            if running_version == HELPER_VERSION:
                show_installation_status(True)
                return 0
            if running_version:
                stop_older_helpers()
                time.sleep(1)
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([str(target), "--serve"], close_fds=True, creationflags=flags)
            show_installation_status(False)
            return 0
    bootstrap_path = Path(args.bootstrap_path).resolve() if args.bootstrap_path else default_bootstrap_path()
    paths = local_paths(args.data_root or None, bootstrap_path=bootstrap_path)
    MemberHandler.bootstrap_path = bootstrap_path
    MemberHandler.data_root = paths["root"]
    MemberHandler.members_root = Path(args.members_root).resolve() if args.members_root else paths["members"]
    MemberHandler.shared_root = paths["shared"]
    MemberHandler.runtime_root = paths["runtime"]
    MemberHandler.web_root = default_web_root()
    MemberHandler.upstream_api = args.server_api or os.environ.get("JINSHI_SERVER_API") or REMOTE_SERVER_API
    # Reserve the listener before starting workers: a duplicate launch cannot collect.
    server = ThreadingHTTPServer((args.host, args.port), MemberHandler, bind_and_activate=False)
    server.allow_reuse_address = False
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        server.server_bind()
        server.server_activate()
    except BaseException:
        server.server_close()
        raise
    start_public_sync(MemberHandler.shared_root, MemberHandler.upstream_api,
                      members_root=MemberHandler.members_root, runtime_root=MemberHandler.runtime_root)
    start_member_minute_archive_scheduler(MemberHandler.members_root, MemberHandler.runtime_root)
    if sys.stdout:
        print(f"[OK] 会员本地数据助手 http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
