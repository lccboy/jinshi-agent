# -*- coding: utf-8 -*-
"""按日归属 membership（V0.2.3，DATA_MODEL §4.5）

产出 `data/facts/<date>/membership.json`——"当天该股属于哪些板块/子板块/题材、地位、板块内排名"：
- 板块归属+排名：`stocks.json.current.sectors` × `kpl_<date>_stocks.json` 板块内源顺序（强度序）→ rank
- 地位：rank 分位 → 龙头（前 5%）/ 中军（前 20%）/ 跟风
- 题材归属：`stocks.json.current.themes` × `themes.json` → theme 条目（position=None）
- 子板块：`sectors.json.parent_id` 非空 → type=subsector
"""
import argparse
import datetime
import json
import os

from .normalize import stock_id

LEADER_PCT = 0.05   # 板块内前 5% → 龙头
MIDDLE_PCT = 0.20   # 前 20% → 中军


def position_by_rank(rank, size):
    """板块内排名 → 地位：龙一恒为龙头；其余按分位（前 5% 龙头 / 前 20% 中军 / 跟风）。"""
    import math
    if rank <= 0 or size <= 0:
        return "跟风"
    if rank == 1 or rank <= math.ceil(size * LEADER_PCT):
        return "龙头"
    if rank <= math.ceil(size * MIDDLE_PCT):
        return "中军"
    return "跟风"


def load_plate_orders(kpl_stocks_path):
    """kpl_<date>_stocks.json（{板块ID: [成分股行]}）→ {板块ID: [stock_id 有序]}，保持源顺序（板块内强度序）。"""
    with open(kpl_stocks_path, encoding="utf-8") as fh:
        data = json.load(fh)
    orders = {}
    for pid, rows in (data.get("stocks") or {}).items():
        orders[str(pid)] = [stock_id(str(r["code"])) for r in (rows or []) if r.get("code")]
    return orders


def build_membership(stocks, sectors, themes, plate_orders):
    """主数据 + 板块序 → {stock_id: [{type, id, name, parent_id?, position, rank}]}（DATA_MODEL §4.5）。"""
    out = {}
    for sid, rec in stocks.items():
        cur = rec.get("current", {}) or {}
        entries = []
        for sec_id in cur.get("sectors", []):
            sec = sectors.get(sec_id, {})
            order = plate_orders.get(sec_id) or []
            rank = order.index(sid) + 1 if sid in order else 0
            parent = sec.get("parent_id")
            entries.append({
                "type": "subsector" if parent else "sector",
                "id": sec_id,
                "name": sec.get("name", sec_id),
                "parent_id": parent,
                "position": position_by_rank(rank, len(order)),
                "rank": rank,
            })
        for tid in cur.get("themes", []):
            entries.append({
                "type": "theme", "id": tid, "name": themes.get(tid, {}).get("name", tid),
                "position": None, "rank": 0,
            })
        if entries:
            out[sid] = entries
    return out


def collect(date_str, kpl_stocks_path, normalized_dir, out_root):
    with open(os.path.join(normalized_dir, "stocks.json"), encoding="utf-8") as fh:
        stocks = json.load(fh)
    with open(os.path.join(normalized_dir, "sectors.json"), encoding="utf-8") as fh:
        sectors = json.load(fh)
    with open(os.path.join(normalized_dir, "themes.json"), encoding="utf-8") as fh:
        themes = json.load(fh)
    orders = load_plate_orders(kpl_stocks_path)
    membership = build_membership(stocks, sectors, themes, orders)

    day_dir = os.path.join(out_root, "facts", date_str)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, "membership.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(membership, fh, ensure_ascii=False, indent=2)
    n_sector = sum(1 for entries in membership.values() for e in entries if e["type"] != "theme")
    n_theme = sum(1 for entries in membership.values() for e in entries if e["type"] == "theme")
    return {"stocks": len(membership), "sector_entries": n_sector, "theme_entries": n_theme, "path": path}


def main(argv=None):
    ap = argparse.ArgumentParser(description="按日归属 membership（membership_collector）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--kpl-stocks", required=True, help="kpl_<date>_stocks.json（板块内强度序）")
    ap.add_argument("--normalized", default="data/normalized", help="主数据目录（默认 data/normalized）")
    ap.add_argument("--out", default="data", help="数据根目录（默认 data）")
    args = ap.parse_args(argv)
    report = collect(args.date, args.kpl_stocks, args.normalized, args.out)
    print(f"[OK] {args.date} membership：个股 {report['stocks']} | 板块/子板块条目 {report['sector_entries']} | 题材条目 {report['theme_entries']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
