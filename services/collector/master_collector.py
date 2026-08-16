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
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

from .normalize import stock_id

# 常量（DATA_MODEL §9）
KPL_UA = "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)"
KPL_BASE = "https://apphwshhq.longhuvip.com/w1/api/index.php"
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
        if not code or code == "000000":
            continue
        sid = stock_id(code)
        rec = uni.setdefault(sid, {"code": code, "name": str(r.get("name", "")), "sectors": set()})
        blk = r.get("_blockId")
        if blk:
            rec["sectors"].add(str(blk))
    return uni


def build_stock_record(code, name, sector_ids, updated_at):
    """universe 记录 → DATA_MODEL §3.1 完整主数据记录。"""
    code = str(code).zfill(6)
    market, board = derive_market_board(code)
    return {
        "stock_id": stock_id(code),
        "code": code,
        "name": str(name),
        "market": market,
        "board": board,
        "treeid": code,
        "hexin": code,
        "is_st": is_st(name),
        "current": {
            "themes": [],
            "sectors": sorted(sector_ids),
            "updated_at": updated_at,
        },
        "updated_at": updated_at,
    }


def build_records(universe, updated_at):
    return {sid: build_stock_record(v["code"], v["name"], v["sectors"], updated_at) for sid, v in universe.items()}


def diff_universe(prev, new):
    """prev: {sid: 完整记录}; new: {sid: universe记录} → 变更清单（新增/更名/ST/归属变化）。"""
    changes = {"added": [], "renamed": [], "st": [], "sectors": []}
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

def _request(params):
    params.setdefault("PhoneOSNew", "1")
    params.setdefault("apiv", API_VERSION)
    params["UserID"] = os.environ.get("KPL_USER_ID", "")
    params["Token"] = os.environ.get("KPL_TOKEN", "")
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(KPL_BASE, data=body, headers={"User-Agent": KPL_UA, "Connection": "Keep-Alive"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_plates():
    """RealRankingInfo 动态分页 → [{id, name}]。"""
    plates = []
    page = 0
    while page < 20:
        data = _request({"Order": "1", "a": "RealRankingInfo", "st": "30", "c": "ZhiShuRanking",
                         "Index": str(page), "Type": "1", "ZSType": "7"})
        rows = data.get("list", []) or []
        if not rows:
            break
        for item in rows:
            if len(item) >= 2:
                plates.append({"id": str(item[0]), "name": str(item[1])})
        page += 1
    return plates


def fetch_stocks(plate_id, date_str):
    """ZhiShuStockList_W8：Type 0~19 遍历合并去重（DATA_MODEL §9.7），每行含 code/name/_blockId。"""
    rows = []
    seen = set()
    for t in range(20):
        data = _request({"Order": "1", "a": "ZhiShuStockList_W8", "st": "30", "c": "ZhiShuRanking",
                         "Type": str(t), "PlateID": plate_id, "Date": date_str, "IsKZZType": "0",
                         "TSZB_Type": "0", "filterType": "0", "TSZB": "0"})
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

def collect_from_rows(rows, out_dir, updated_at=None, mode="full"):
    updated_at = updated_at or datetime.now().strftime("%Y-%m-%d")
    universe = merge_universe(rows)
    if mode == "incr":
        prev = load_existing(out_dir)
        changes = diff_universe(prev, universe)
        records = dict(prev)
        records.update(build_records(universe, updated_at))
    else:
        changes = {}
        records = build_records(universe, updated_at)
    write_normalized(records, out_dir)
    update_manifest(out_dir, "last_incr" if mode == "incr" else "last_full", updated_at)
    return len(universe), changes


def verify(records):
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
    report = {"stocks": len(records), "sectors": sorted({s for r in records.values() for s in r["current"]["sectors"]}),
              "errors": errors[:10], "error_count": len(errors)}
    return ok, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="主数据采集（master_collector）")
    ap.add_argument("--from-kpl", help="离线：读取现网 kpl_<date>_stocks.json（无需凭据）")
    ap.add_argument("--full", action="store_true", help="网络：全量采集（需 KPL_TOKEN/KPL_USER_ID）")
    ap.add_argument("--incr", action="store_true", help="网络：增量采集（按 manifest 对比）")
    ap.add_argument("--out", default="data/normalized", help="输出目录（默认 data/normalized）")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--verify", action="store_true", help="采集后校验并输出统计")
    args = ap.parse_args(argv)

    if args.from_kpl:
        rows, fetched_at = read_kpl_stocks_file(args.from_kpl)
        count, changes = collect_from_rows(rows, args.out, mode="incr" if args.incr else "full")
    elif args.full or args.incr:
        if not os.environ.get("KPL_TOKEN"):
            print("[ERROR] 网络模式需要 KPL_TOKEN / KPL_USER_ID（env），无凭据请用 --from-kpl 离线校验")
            return 1
        date_str = args.date
        plates = fetch_plates()
        rows = []
        for p in plates:
            rows.extend(fetch_stocks(p["id"], date_str))
        count, changes = collect_from_rows(rows, args.out, mode="incr" if args.incr else "full")
    else:
        ap.print_help()
        return 1

    print(f"[OK] universe: {count} 只股票")
    if changes:
        print(f"[CHANGES] added={len(changes.get('added', []))} renamed={len(changes.get('renamed', []))} "
              f"st={len(changes.get('st', []))} sectors={len(changes.get('sectors', []))}")

    if args.verify:
        ok, report = verify(load_existing(args.out))
        print(f"[VERIFY] {'PASS' if ok else 'FAIL'} 股票数={report['stocks']} 板块数={len(report['sectors'])} "
              f"错误数={report['error_count']}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
