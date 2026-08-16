# -*- coding: utf-8 -*-
"""归档 + Web 视图层（V0.1a 任务 6）

依据 `docs/DATA_MODEL.md` §13：
- 15:20 归档编排：读当日 facts → 生成 Web 视图层（字段裁剪 + 预排序 + 四维确认 + gzip 预压缩）→ intraday 移入 archive
- `data/web/day_<date>.json`（页面唯一数据源）+ `.gz`（nginx gzip_static 直出）+ `day_latest.json` + `index.json`（日期清单）
"""
import argparse
import gzip
import json
import os
import re
import shutil

# quotes 63 字段 → 页面展示列（DATA_MODEL §13.2）
QUOTES_KEEP = ("price", "change", "turnover", "volume", "volRatio", "mainNet",
               "circMarketCap", "totalMarketCap")
MIN_SECTOR_STRENGTH = 4000
MONEY_TOP_N = 30
STRATEGY_TOP_N = 20


# ---------------- 纯函数（TDD 覆盖） ----------------

def trim_quotes(full):
    """quotes 63 字段 → 页面 ~8 展示字段（剔除长文/人气/封单等）。"""
    return {k: full[k] for k in QUOTES_KEEP if k in full}


def _board_height(boards):
    """'4连板'/'3天2板'/'首板' → 数字高度（首板=1），用于排序。"""
    m = re.search(r"(\d+)", str(boards or ""))
    return int(m.group(1)) if m else 1


def compute_confirm(stock_sectors, sectors_fact, money_flow, leading_reason, min_strength=MIN_SECTOR_STRENGTH):
    """叠加确认层（STRATEGY_MODEL §8）：板块强度/资金流入/领涨原因 三维布尔。"""
    strength = max((sectors_fact[s].get("strength", 0) for s in stock_sectors if s in sectors_fact), default=0)
    has_money = any(money_flow[s].get("main", 0) > 0 for s in stock_sectors if s in money_flow)
    has_reason = any(str(leading_reason[s].get("reason", "") or "").strip() for s in stock_sectors if s in leading_reason)
    return {
        "sector_strength": bool(strength) and strength >= min_strength,
        "money_flow": has_money,
        "leading_reason": has_reason,
    }


def build_day_view(date_str, facts):
    """当日 facts → Web 视图（预排序 + 裁剪 + 四维确认）。

    facts 键：market/indexes/sectors/limitup/ladder/membership/strategy/money_flow/leading_reason/pool
    （均为解包后的直接 dict，缺省跳过）。
    """
    view = {"date": date_str, "market": dict(facts.get("market") or {}), "indexes": facts.get("indexes") or {}}

    sectors_fact = facts.get("sectors") or {}
    view["sectors"] = [
        {"id": sid, **{k: sec.get(k) for k in ("name", "strength", "change", "mainNet", "limit_up_count", "boom_reason") if k in sec}}
        for sid, sec in sorted(sectors_fact.items(), key=lambda kv: kv[1].get("strength", 0), reverse=True)
    ]

    limitup = facts.get("limitup") or {}
    view["limitup"] = [
        {"stock_id": sid, **{k: e[k] for k in ("reason", "boards", "concepts", "primary", "sourceCount",
                                               "first_time", "seal_amount") if k in e}}
        for sid, e in sorted(limitup.items(), key=lambda kv: _board_height(kv[1].get("boards")), reverse=True)
    ]

    view["ladder"] = facts.get("ladder") or {}

    # 盘中事件流（DATA_MODEL §4.12）：裁剪类型/字段，按时间倒序，供"实时信号"视图
    events = facts.get("events") or []
    view["events"] = [
        {k: e[k] for k in ("ts", "type", "stock_id", "score", "detail", "source") if k in e}
        for e in sorted(events, key=lambda ev: ev.get("ts", ""), reverse=True)[:200]
    ]

    money_flow = facts.get("money_flow") or {}
    view["money_flow"] = [
        {k: f[k] for k in ("name", "main", "main_pct", "rank_in") if k in f}
        for f in sorted(money_flow.values(), key=lambda f: f.get("main", 0), reverse=True)[:MONEY_TOP_N]
    ]

    leading = facts.get("leading_reason") or {}
    view["leading_reason"] = sorted(leading.values(), key=lambda r: r.get("limit_up_count", 0), reverse=True)

    strategy = facts.get("strategy") or {}
    view["strategy_top"] = [
        {"stock_id": sid, **{k: e[k] for k in ("score", "models", "buy_point", "target") if k in e}}
        for sid, e in sorted(strategy.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)[:STRATEGY_TOP_N]
    ]

    # 预警池 + 四维确认（需 membership 把股票 → 板块）
    membership = facts.get("membership") or {}
    pool = facts.get("pool") or {}
    pools = json.loads(json.dumps(pool))  # 深拷贝，避免改原 facts
    alert = pools.get("pools", {}).get("alert") or {}
    if alert:
        for sid, entry in alert.items():
            secs = [m["id"] for m in membership.get(sid, []) if m.get("type") == "sector"]
            confirm = compute_confirm(secs, sectors_fact, money_flow, leading)
            entry["confirm"] = confirm
            entry["stars"] = 4 if all(confirm.values()) else (3 if sum(confirm.values()) >= 2 else 2)
    view["pools"] = pools

    return view


def build_detail_view(date_str, facts):
    """`day_<date>.detail.json`（懒加载）：涨停原因原文 + 4 源（页面弹窗按需拉取，DATA_MODEL §13.2）。"""
    limitup = facts.get("limitup") or {}
    return {"date": date_str, "limitup": {
        sid: {"reason": e.get("reason", ""), "detail": e.get("detail", ""), "primary": e.get("primary", ""),
              "sourceCount": e.get("sourceCount", 0), "sources": e.get("sources", {})}
        for sid, e in limitup.items()
    }}


def write_detail_view(date_str, detail, out_dir):
    """写 `day_<date>.detail.json` + `.gz`（懒加载）。"""
    raw = json.dumps(detail, ensure_ascii=False).encode("utf-8")
    path = os.path.join(out_dir, f"day_{date_str}.detail.json")
    with open(path, "wb") as fh:
        fh.write(raw)
    with open(path + ".gz", "wb") as fh:
        fh.write(gzip.compress(raw, compresslevel=6))
    return [path, path + ".gz"]


# ---------------- 写盘 ----------------

def build_stocks_slim(stocks):
    """5146 只 → {sid: {n 名称, s 板块ID[], t 题材ID[]}}：成分股展开用的体积裁剪（V0.3.0 UI）。"""
    slim = {}
    for sid, rec in stocks.items():
        cur = rec.get("current", {}) or {}
        slim[sid] = {"n": rec.get("name", sid), "s": list(cur.get("sectors", [])), "t": list(cur.get("themes", []))}
    return slim


def write_master_lib(norm_dir, web_dir):
    """主数据懒加载库 → data/web/：themes/theme_stocks/sectors 拷贝 + stocks_slim 生成，全部 .json + .gz。"""
    os.makedirs(web_dir, exist_ok=True)
    pairs = []
    for name in ("themes.json", "theme_stocks.json", "themes_tree.json", "sectors.json"):
        src = os.path.join(norm_dir, name)
        if not os.path.exists(src):
            continue
        with open(src, encoding="utf-8") as fh:
            content = json.load(fh)
        pairs.append((name, content))
    stocks_path = os.path.join(norm_dir, "stocks.json")
    if os.path.exists(stocks_path):
        with open(stocks_path, encoding="utf-8") as fh:
            pairs.append(("stocks_slim.json", build_stocks_slim(json.load(fh))))
    for name, content in pairs:
        raw = json.dumps(content, ensure_ascii=False).encode("utf-8")
        with open(os.path.join(web_dir, name), "wb") as fh:
            fh.write(raw)
        with open(os.path.join(web_dir, name + ".gz"), "wb") as fh:
            fh.write(gzip.compress(raw, compresslevel=6))
    return [p[0] for p in pairs]

def write_day_view(date_str, view, out_dir):
    """写 day_<date>.json + .gz + day_latest.json，更新 index.json 日期清单。"""
    os.makedirs(out_dir, exist_ok=True)
    raw = json.dumps(view, ensure_ascii=False).encode("utf-8")

    day_path = os.path.join(out_dir, f"day_{date_str}.json")
    with open(day_path, "wb") as fh:
        fh.write(raw)
    gz_path = day_path + ".gz"
    with open(gz_path, "wb") as fh:
        fh.write(gzip.compress(raw, compresslevel=6))

    with open(os.path.join(out_dir, "day_latest.json"), "wb") as fh:
        fh.write(raw)

    index_path = os.path.join(out_dir, "index.json")
    idx = {"days": []}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as fh:
            idx = json.load(fh)
    dates = {d["date"] for d in idx["days"]}
    if date_str not in dates:
        idx["days"].append({"date": date_str})
    idx["days"].sort(key=lambda d: d["date"], reverse=True)
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=2)

    return [day_path, gz_path, os.path.join(out_dir, "day_latest.json"), index_path]


# ---------------- 归档编排 ----------------

FACT_FILES = ("market", "indexes", "sectors", "limitup", "ladder", "membership", "strategy",
              "money_flow", "leading_reason", "pool", "events")


def read_facts(date_str, facts_dir):
    """读 data/facts/<date>/*.json → 解包为 build_day_view 的直接 dict。

    facts 文件形态：纯 dict（market/indexes/ladder/pool）或 {data_date, sectors/plates/...} 包装。
    """
    day_dir = os.path.join(facts_dir, date_str)
    facts = {}
    for name in FACT_FILES:
        path = os.path.join(day_dir, f"{name}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if name in ("sectors", "money_flow"):
            facts[name] = doc.get("sectors", doc)
        elif name == "leading_reason":
            facts[name] = doc.get("plates", doc)
        elif name == "indexes":
            facts[name] = doc.get("indexes", doc)
        elif name == "events":
            facts[name] = doc.get("events", [])   # 事件流为列表
        else:
            facts[name] = doc
    return facts


def archive_day(date_str, facts_dir, web_dir, intraday_dir, archive_dir):
    """归档编排：facts → 视图层（day + detail + 索引 + master lib）→ intraday 移入 archive。返回 (view, paths)。"""
    facts = read_facts(date_str, facts_dir)
    view = build_day_view(date_str, facts)
    paths = write_day_view(date_str, view, web_dir)
    paths += write_detail_view(date_str, build_detail_view(date_str, facts), web_dir)
    paths += [os.path.join(web_dir, n) for n in
              write_master_lib(os.path.join(os.path.dirname(facts_dir), "normalized"), web_dir)]

    src = os.path.join(intraday_dir, date_str)
    if os.path.isdir(src):
        os.makedirs(archive_dir, exist_ok=True)
        dst = os.path.join(archive_dir, date_str)
        shutil.move(src, dst)

    return view, paths


def verify_view(view, day_path, gz_path):
    raw_size = os.path.getsize(day_path)
    gz_size = os.path.getsize(gz_path)
    ok = raw_size <= 200 * 1024 and gz_size <= 80 * 1024
    report = {"date": view["date"], "raw_kb": round(raw_size / 1024, 1), "gz_kb": round(gz_size / 1024, 1),
              "sectors": len(view["sectors"]), "limitup": len(view["limitup"]), "ok": ok}
    return ok, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="归档 + Web 视图层（archive_job）")
    ap.add_argument("--date", required=True, help="数据日期 YYYY-MM-DD")
    ap.add_argument("--facts", default="data/facts", help="facts 根目录（默认 data/facts）")
    ap.add_argument("--web", default="data/web", help="Web 视图层输出（默认 data/web）")
    ap.add_argument("--intraday", default="data/intraday", help="盘中快照目录（默认 data/intraday）")
    ap.add_argument("--archive", default="data/archive", help="归档目录（默认 data/archive）")
    ap.add_argument("--verify", action="store_true", help="输出体积校验（≤200KB raw / ≤80KB gz）")
    args = ap.parse_args(argv)

    view, paths = archive_day(args.date, args.facts, args.web, args.intraday, args.archive)
    print(f"[OK] {args.date} 视图层已生成: day_{args.date}.json + .gz")
    if args.verify:
        ok, report = verify_view(view, paths[0], paths[1])
        print(f"[VERIFY] {'PASS' if ok else 'FAIL'} raw={report['raw_kb']}KB gz={report['gz_kb']}KB "
              f"板块={report['sectors']} 涨停={report['limitup']}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
