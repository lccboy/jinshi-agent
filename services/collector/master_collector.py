# -*- coding: utf-8 -*-
"""主数据采集（V0.1a 任务 3）

依据 `docs/DATA_MODEL.md` §3.4：
- 主数据以开盘啦 API 为主源（`RealRankingInfo` 分页板块 + `ZhiShuStockList_W8` Type 0~19 合并成分股）
- 补充/推导：market/board 由代码前缀、is_st 由名称前缀、treeid/hexin 由 code、industry 取行业板块归属
- 增量：按 `data/manifest.json` 对比上次采集，只处理新增/变化；Token 过期需刷新（env KPL_TOKEN/KPL_USER_ID）

网络模式需要有效 KPL 凭据（env）；`--from-kpl` 离线模式读取现网 `kpl_<date>_stocks.json`
（含 code/name/_blockId 的真实成分股行），用于无凭据时的真实数据校验。
"""
import argparse
import concurrent.futures
import json
import os
import struct
import sys
import urllib.parse
import urllib.request
import time
from datetime import datetime

from .normalize import is_equity_code, sector_type, stock_id

# 常量（DATA_MODEL §9）
KPL_UA = "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)"
KPL_HQ_BASE = "https://apphwhq.longhuvip.com/w1/api/index.php"
KPL_HIS_BASE = "https://apphis.longhuvip.com/w1/api/index.php"
API_VERSION = "w44"


def derive_market_board(code):
    """代码前缀 → (市场, 板块)。60→沪主板、68→沪科创板、00→深主板、30→深创业板、其余→北交所。"""
    c = str(code).zfill(6)
    if c.startswith("68"):
        return "SH", "科创板"
    if c.startswith("60"):
        return "SH", "主板"
    if c.startswith("30"):
        return "SZ", "创业板"
    if c.startswith("00"):
        return "SZ", "主板"
    return "BJ", "北交所"


def is_st(name):
    return "st" in str(name).lower()


def merge_universe(rows):
    """成分股行（含 code/name/_blockId）→ {stock_id: {code, name, sectors:set}}，按 stock_id 去重合并板块。"""
    uni = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code", "")).strip().zfill(6)
        if not is_equity_code(code) or code == "000000":
            continue
        sid = stock_id(code)
        rec = uni.setdefault(sid, {"code": code, "name": str(r.get("name", "")), "sectors": set()})
        blk = r.get("_blockId")
        if blk:
            rec["sectors"].add(str(blk))
    return uni


def build_stock_record(code, name, sector_ids, updated_at, sectors=None):
    """universe 记录 → DATA_MODEL §3.1 完整主数据记录。"""
    code = str(code).zfill(6)
    market, board = derive_market_board(code)
    record = {
        "stock_id": stock_id(code),
        "code": code,
        "name": str(name),
        "market": market,
        "board": board,
        "treeid": code,
        "hexin": code,
        "is_st": is_st(name),
        "status": "active",
        "first_seen": updated_at,
        "last_seen": updated_at,
        "current": {
            "themes": [],
            "sectors": sorted(sector_ids),
            "updated_at": updated_at,
        },
        "updated_at": updated_at,
    }
    industry_names = [sectors[s]["name"] for s in sorted(sector_ids)
                      if sectors and s in sectors and sectors[s].get("type") == "industry"
                      and sectors[s].get("name")]
    if industry_names:
        record["industry"] = industry_names[0]
    return record


def build_records(universe, updated_at, sectors=None):
    return {sid: build_stock_record(v["code"], v["name"], v["sectors"], updated_at, sectors)
            for sid, v in universe.items()}


def diff_universe(prev, new):
    """prev: {sid: 完整记录}; new: {sid: universe记录} → 变更清单（新增/更名/ST/归属变化）。"""
    changes = {"added": [], "renamed": [], "st": [], "sectors": [],
               "removed": sorted(set(prev) - set(new))}
    for sid, rec in new.items():
        if sid not in prev:
            changes["added"].append(sid)
            continue
        p = prev[sid]
        if p.get("name") != rec["name"]:
            changes["renamed"].append(sid)
        if bool(p.get("is_st")) != bool(is_st(rec["name"])):
            changes["st"].append(sid)
        if set(p.get("current", {}).get("sectors", [])) != rec["sectors"]:
            changes["sectors"].append(sid)
    return changes


# ---------------- I/O（离线/增量） ----------------

def read_kpl_stocks_file(path):
    """读取现网 `kpl_<date>_stocks.json`（{t, stocks:{板块ID:[{code,name,_blockId,...}]}}）→ rows（展平）。"""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    stocks = data.get("stocks", [])
    rows = []
    if isinstance(stocks, dict):  # {板块ID: [成分股行, ...]}
        for plate_id, items in stocks.items():
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                item = dict(item)
                item.setdefault("_blockId", plate_id)
                rows.append(item)
    elif isinstance(stocks, list):  # 兼容平铺形态
        rows = [r for r in stocks if isinstance(r, dict)]
    return rows, data.get("t", "")


def write_normalized(records, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "stocks.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
    return path


def load_existing(out_dir):
    path = os.path.join(out_dir, "stocks.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def update_manifest(out_dir, key, value):
    path = os.path.join(out_dir, "..", "manifest.json")
    manifest = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    manifest.setdefault("stocks", {})[key] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return path


# ---------------- 网络采集（KPL API，需有效凭据） ----------------

def _request(params, base=KPL_HQ_BASE, attempts=3):
    params.setdefault("PhoneOSNew", "1")
    params.setdefault("apiv", API_VERSION)
    if os.environ.get("KPL_USER_ID"):
        params["UserID"] = os.environ["KPL_USER_ID"]
    if os.environ.get("KPL_TOKEN"):
        params["Token"] = os.environ["KPL_TOKEN"]
    url = base + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": KPL_UA, "Connection": "Keep-Alive"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"KPL request failed after {attempts} attempts: {last}")


def fetch_plates():
    """RealRankingInfo 动态分页：ZSType=7 综合/概念 + ZSType=4 完整行业。"""
    plates = []
    seen = set()
    for zstype, forced_type in (("7", None), ("4", "industry")):
        offset = 0
        while offset < 600:
            data = _request({"Order": "1", "a": "RealRankingInfo", "st": "30", "c": "ZhiShuRanking",
                             "Index": str(offset), "Type": "1", "ZSType": zstype})
            rows = data.get("list", []) or []
            if not rows:
                break
            for item in rows:
                if len(item) >= 2:
                    sid = str(item[0])
                    if sid not in seen:
                        seen.add(sid)
                        plates.append({"id": sid, "name": str(item[1]),
                                       "type": forced_type or sector_type(sid), "zstype": zstype})
            offset += 30
    return plates


def fetch_stocks(plate_id, date_str):
    """ZhiShuStockList_W8：Type 0~19 遍历合并去重（DATA_MODEL §9.7），每行含 code/name/_blockId。"""
    rows = []
    seen = set()
    for t in range(20):
        data = _request({"Order": "1", "a": "ZhiShuStockList_W8", "st": "30", "c": "ZhiShuRanking",
                         "Type": str(t), "PlateID": plate_id, "Date": date_str, "IsKZZType": "0",
                         "TSZB_Type": "0", "filterType": "0", "TSZB": "0", "old": "1"}, base=KPL_HIS_BASE)
        for item in data.get("list", []) or []:
            if len(item) < 2:
                continue
            code = str(item[0])
            if code in seen:
                continue
            seen.add(code)
            rows.append({"code": code, "name": str(item[1]), "_blockId": plate_id})
    return rows


# ---------------- 编排 ----------------

def collect_from_rows(rows, out_dir, updated_at=None, mode="full", sectors=None):
    updated_at = updated_at or datetime.now().strftime("%Y-%m-%d")
    universe = merge_universe(rows)
    if mode == "incr":
        prev = load_existing(out_dir)
        previous_active = sum(rec.get("status") not in ("source_missing", "invalid_instrument")
                              for rec in prev.values())
        minimum = max(1, int(previous_active * 0.8))
        if previous_active and len(universe) < minimum:
            raise ValueError(f"主源股票池异常: incoming={len(universe)} previous_active={previous_active} minimum={minimum}")
        changes = diff_universe(prev, universe)
        records = dict(prev)
        for sid, item in universe.items():
            incoming = build_stock_record(item["code"], item["name"], item["sectors"], updated_at, sectors)
            if sid not in records:
                incoming["source_status"] = {"kpl": "active"}
                records[sid] = incoming
                continue
            rec = records[sid]
            old_name = rec.get("name", "")
            if old_name and old_name != item["name"]:
                history = rec.setdefault("name_history", [])
                if not history or history[-1].get("name") != old_name:
                    history.append({"name": old_name, "ended_at": updated_at})
            # KPL 只更新其权威字段，保留 themes/list_date/跨源元数据等补充字段。
            rec.update({k: incoming[k] for k in ("stock_id", "code", "name", "market", "board",
                                                  "treeid", "hexin", "is_st")})
            cur = rec.setdefault("current", {})
            cur["sectors"] = incoming["current"]["sectors"]
            cur.setdefault("themes", [])
            cur["updated_at"] = updated_at
            rec["updated_at"] = updated_at
            rec["status"] = "active"
            rec.setdefault("first_seen", updated_at)
            rec["last_seen"] = updated_at
            if incoming.get("industry"):
                rec["industry"] = incoming["industry"]
            rec.setdefault("source_status", {})["kpl"] = "active"
        for sid in changes["removed"]:
            records[sid].setdefault("source_status", {})["kpl"] = "missing"
            records[sid]["status"] = "source_missing"
    else:
        changes = {}
        records = build_records(universe, updated_at, sectors)
    write_normalized(records, out_dir)
    update_manifest(out_dir, "last_incr" if mode == "incr" else "last_full", updated_at)
    return len(universe), changes


def verify(records, sectors=None):
    """校验：数量 + 字段形状。返回 (ok, report)。"""
    errors = []
    for sid, rec in records.items():
        if rec.get("stock_id") != sid:
            errors.append(f"{sid}: stock_id 不一致")
        if not rec.get("code") or not rec.get("name"):
            errors.append(f"{sid}: code/name 缺失")
        if rec.get("market") not in ("SH", "SZ", "BJ"):
            errors.append(f"{sid}: market 非法")
        if not isinstance(rec.get("is_st"), bool):
            errors.append(f"{sid}: is_st 非 bool")
    ok = not errors
    active = [r for r in records.values() if r.get("status") not in ("source_missing", "invalid_instrument")]
    all_sector_ids = sorted({s for r in active for s in r.get("current", {}).get("sectors", [])})
    total = len(active)
    no_sectors = sum(not r.get("current", {}).get("sectors") for r in active)
    sector_types = {}
    for value in (sectors or {}).values():
        kind = value.get("type", "unknown")
        sector_types[kind] = sector_types.get(kind, 0) + 1
    report = {"stocks": total, "sectors": all_sector_ids,
              "stocks_without_sectors": no_sectors,
              "master_records": len(records),
              "source_missing": len(records) - total,
              "stocks_without_industry": sum(not r.get("industry") for r in active),
              "stocks_without_list_date": sum(not r.get("list_date") for r in active),
              "sector_coverage": round((total - no_sectors) / total, 6) if total else 0.0,
              "sector_types": sector_types,
              "errors": errors[:10], "error_count": len(errors)}
    return ok, report


def build_sectors_from_daily(daily):
    """kpl_<date>.json（sectors + sub）→ `normalized/sectors.json` 板块/子板块字典（DATA_MODEL §3.3）。

    - `sectors` 列表 → level 1（parent_id=None）
    - `sub` 映射 → level 2（parent_id=父板块）
    - `type`（concept/industry）按板块 ID 前缀（normalize.sector_type）
    """
    secs = {}
    for s in daily.get("sectors", []):
        sid = str(s["id"])
        secs[sid] = {"sector_id": sid, "name": s["name"], "parent_id": None, "level": 1,
                     "type": sector_type(sid), "source": "kpl"}
    for pid, subs in (daily.get("sub") or {}).items():
        for s in subs:
            sid = str(s["id"])
            secs.setdefault(sid, {"sector_id": sid, "name": s["name"], "parent_id": str(pid), "level": 2,
                                  "type": sector_type(sid), "source": "kpl"})
    return secs


def write_sectors_json(secs, out_dir):
    path = os.path.join(out_dir, "sectors.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(secs, fh, ensure_ascii=False, indent=2)
    return path


def load_sectors(out_dir):
    path = os.path.join(out_dir, "sectors.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def backfill_list_dates_from_vipdoc(records, vipdoc_root):
    """读取 TDX `.day` 首条记录日期回填上市日期；不解析价格、不推测缺失值。"""
    report = {"updated": 0, "missing": 0, "invalid": 0}
    for sid, rec in records.items():
        if not is_equity_code(rec.get("code", sid[2:])):
            rec["status"] = "invalid_instrument"
            rec.setdefault("source_status", {})["kpl"] = "invalid_instrument"
            report["invalid"] += 1
            continue
        kpl_status = rec.get("source_status", {}).get("kpl")
        if kpl_status == "missing":
            rec["status"] = "source_missing"
        elif kpl_status == "active":
            rec["status"] = "active"
        market = sid[:2].lower()
        code = sid[2:]
        path = os.path.join(vipdoc_root, market, "lday", f"{market}{code}.day")
        if not os.path.isfile(path):
            report["missing"] += 1
            continue
        try:
            with open(path, "rb") as fh:
                raw = fh.read(4)
            value = struct.unpack("<I", raw)[0]
            date = datetime.strptime(str(value), "%Y%m%d").date().isoformat()
        except (OSError, struct.error, ValueError):
            report["invalid"] += 1
            continue
        rec["list_date"] = date
        rec.setdefault("sources", {})["listing"] = {
            "source": "tdx_vipdoc", "source_path": os.path.abspath(path), "data_as_of": date
        }
        report["updated"] += 1
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="主数据采集（master_collector）")
    ap.add_argument("--from-kpl", help="离线：读取现网 kpl_<date>_stocks.json（无需凭据）")
    ap.add_argument("--kpl-daily", help="离线：读取 kpl_<date>.json → 生成 normalized/sectors.json 板块字典")
    ap.add_argument("--full", action="store_true", help="网络：全量采集（需 KPL_TOKEN/KPL_USER_ID）")
    ap.add_argument("--incr", action="store_true", help="网络：增量采集（按 manifest 对比）")
    ap.add_argument("--out", default="data/normalized", help="输出目录（默认 data/normalized）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--verify", action="store_true", help="采集后校验并输出统计")
    ap.add_argument("--backfill-vipdoc", help="从 TDX vipdoc `.day` 首条记录回填 list_date")
    ap.add_argument("--workers", type=int, default=10, help="网络全量采集并发板块数（默认 10）")
    args = ap.parse_args(argv)

    if args.backfill_vipdoc:
        records = load_existing(args.out)
        if not records:
            print(f"[ERROR] 未找到主数据: {os.path.join(args.out, 'stocks.json')}")
            return 1
        report = backfill_list_dates_from_vipdoc(records, args.backfill_vipdoc)
        write_normalized(records, args.out)
        print(f"[OK] list_date 回填={report['updated']} 缺文件={report['missing']} 无效={report['invalid']}")
        if args.verify:
            ok, quality = verify(records, load_sectors(args.out))
            print(f"[VERIFY] {'PASS' if ok else 'FAIL'} list_date缺失={quality['stocks_without_list_date']}")
            return 0 if ok else 1
        return 0

    if args.kpl_daily:
        with open(args.kpl_daily, encoding="utf-8") as fh:
            daily = json.load(fh)
        secs = build_sectors_from_daily(daily)
        path = write_sectors_json(secs, args.out)
        lvl1 = sum(1 for v in secs.values() if v["level"] == 1)
        lvl2 = sum(1 for v in secs.values() if v["level"] == 2)
        print(f"[OK] 板块字典 {len(secs)} 个（level1={lvl1} level2={lvl2}）→ {path}")
        return 0

    if args.from_kpl:
        rows, fetched_at = read_kpl_stocks_file(args.from_kpl)
        count, changes = collect_from_rows(rows, args.out, mode="incr" if args.incr else "full",
                                           sectors=load_sectors(args.out))
    elif args.full or args.incr:
        date_str = args.date
        plates = fetch_plates()
        # 保留 SonPlate_Info 已采集的二级板块，仅刷新本次 RealRankingInfo 一级字典。
        sector_defs = load_sectors(args.out)
        sector_defs.update({p["id"]: {"sector_id": p["id"], "name": p["name"], "parent_id": None,
                                       "level": 1, "type": p["type"], "source": "kpl"} for p in plates})
        write_sectors_json(sector_defs, args.out)
        rows, failed = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = {executor.submit(fetch_stocks, p["id"], date_str): p for p in plates}
            for future in concurrent.futures.as_completed(futures):
                plate = futures[future]
                try:
                    rows.extend(future.result())
                except Exception as exc:
                    failed.append((plate["id"], str(exc)))
        if failed:
            print(f"[ERROR] 板块成分采集失败 {len(failed)}/{len(plates)}: {failed[:10]}")
            return 1
        count, changes = collect_from_rows(rows, args.out, mode="incr" if args.incr else "full",
                                           sectors=sector_defs)
    else:
        ap.print_help()
        return 1

    print(f"[OK] universe: {count} 只股票")
    if changes:
        print(f"[CHANGES] added={len(changes.get('added', []))} renamed={len(changes.get('renamed', []))} "
              f"st={len(changes.get('st', []))} sectors={len(changes.get('sectors', []))}")

    if args.verify:
        ok, report = verify(load_existing(args.out), load_sectors(args.out))
        print(f"[VERIFY] {'PASS' if ok else 'FAIL'} 股票数={report['stocks']} 板块数={len(report['sectors'])} "
              f"板块覆盖={report['sector_coverage']:.1%} 无行业={report['stocks_without_industry']} "
              f"无上市日期={report['stocks_without_list_date']} 错误数={report['error_count']}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
