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
import tempfile

from .normalize import stock_id

# quotes 63 字段 → 页面展示列（DATA_MODEL §13.2）
QUOTES_KEEP = ("price", "change", "turnover", "volume", "volRatio", "mainNet",
               "circMarketCap", "totalMarketCap")
MIN_SECTOR_STRENGTH = 4000
MONEY_TOP_N = 30
STRATEGY_TOP_N = 20
WEB_ALERT_TOP_N = 30
WEB_CANDIDATE_TOP_N = 100


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
        {"id": sid, **{k: sec.get(k) for k in ("name", "strength", "change", "volume", "mainNet", "marketCap",
                                                   "rank", "limit_up_count", "up6_count", "stock_count",
                                                   "sub_sectors", "boom_reason") if k in sec}}
        for sid, sec in sorted(sectors_fact.items(), key=lambda kv: kv[1].get("strength", 0), reverse=True)
    ]

    limitup = facts.get("limitup") or {}
    stock_names = facts.get("stock_names") or {}
    view["limitup"] = [
        {"stock_id": sid, "name": stock_names.get(sid, sid),
         **{k: e[k] for k in ("reason", "boards", "concepts", "primary", "sourceCount",
                                               "first_time", "seal_amount") if k in e}}
        for sid, e in sorted(limitup.items(), key=lambda kv: _board_height(kv[1].get("boards")), reverse=True)
    ]
    limitup_ids = set(limitup)
    view["theme_limitup"] = {
        str(tid): sorted(limitup_ids.intersection(members or []))
        for tid, members in (facts.get("theme_stocks") or {}).items()
    }
    concept_limitup = {}
    for tid, theme in (facts.get("themes") or {}).items():
        entries = []
        for main in theme.get("tree", []) or []:
            main_members = set(main.get("st", []) or [])
            for sub in main.get("l2", []) or []:
                sub_hits = sorted(limitup_ids.intersection(sub.get("st", []) or []))
                main_members.update(sub.get("st", []) or [])
                if sub_hits:
                    entries.append({"level": 2, "parent": main.get("n1", ""),
                                    "name": sub.get("n2", ""), "stock_ids": sub_hits})
            main_hits = sorted(limitup_ids.intersection(main_members))
            if main_hits:
                entries.append({"level": 1, "name": main.get("n1", ""), "stock_ids": main_hits})
        entries.sort(key=lambda item: (-len(item["stock_ids"]), item["level"], item["name"]))
        concept_limitup[str(tid)] = entries
    view["theme_concept_limitup"] = concept_limitup

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
    web_pools = pools.get("pools", {})
    for key, limit in (("alert", WEB_ALERT_TOP_N), ("candidate", WEB_CANDIDATE_TOP_N)):
        ranked = sorted((web_pools.get(key) or {}).items(), key=lambda item: item[1].get("score", 0), reverse=True)
        web_pools[key] = dict(ranked[:limit])
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


def build_kpl_sector_views(daily, stocks_doc):
    """KPL 每日板块/成分文件 → Web 板块摘要与懒加载详情。字段名保持 DATA_MODEL §4.4 口径。"""
    sub_map = daily.get("sub") or daily.get("子板块映射") or {}
    source_sectors = daily.get("sectors") or daily.get("板块排行") or []
    rows_by_plate = stocks_doc.get("stocks", stocks_doc) or {}
    sectors = []
    aliases = {"id": "代码", "name": "名称", "strength": "强度", "change": "涨跌%",
               "volume": "成交额_亿", "mainNet": "主力净额_亿", "marketCap": "市值_亿",
               "rank": "排名", "zt": "涨停数", "up6": "大于6%", "n": "家数"}
    for raw in source_sectors:
        def val(key, default=0):
            return raw.get(key, raw.get(aliases[key], default))
        sid = str(val("id", ""))
        plate_rows = rows_by_plate.get(sid) or []
        changes = []
        for row in plate_rows:
            try:
                changes.append(float(row.get("change", row.get("涨跌幅%", -999))))
            except (TypeError, ValueError):
                continue
        has_zt = "zt" in raw or "涨停数" in raw
        has_up6 = "up6" in raw or "大于6%" in raw
        has_n = "n" in raw or "家数" in raw
        children = [{"id": str(x.get("id", x.get("代码", ""))),
                     "name": x.get("name", x.get("名称", "")),
                     "strength": x.get("strength", x.get("强度", 0))}
                    for x in sub_map.get(sid, [])]
        sectors.append({"id": sid, "name": val("name", sid), "strength": val("strength"),
                        "change": val("change"), "volume": val("volume"), "mainNet": val("mainNet"),
                        "marketCap": val("marketCap"), "rank": val("rank"),
                        "limit_up_count": val("zt") if has_zt else sum(1 for x in changes if x >= 9.8),
                        "up6_count": val("up6") if has_up6 else sum(1 for x in changes if 6 <= x < 9.8),
                        "stock_count": val("n") if has_n else len(plate_rows), "sub_sectors": children})
    sectors.sort(key=lambda x: (-float(x.get("strength") or 0), x["name"]))
    for rank, sector in enumerate(sectors, 1):
        sector["rank"] = rank

    plates = {}
    for pid, rows in rows_by_plate.items():
        normalized = []
        for row in rows or []:
            code = str(row.get("code", row.get("代码", "")))
            if not code:
                continue
            normalized.append({
                "stock_id": stock_id(code), "code": code, "name": row.get("name", row.get("名称", code)),
                "position": row.get("position", row.get("地位", "")),
                "change": row.get("change", row.get("涨跌幅%", 0)), "price": row.get("price", row.get("现价", 0)),
                "turnover": row.get("turnover", row.get("换手率%", 0)), "amount": row.get("volume", row.get("成交额", 0)),
                "main_net": row.get("mainNet", row.get("主力净额", 0)), "vol_ratio": row.get("volRatio", row.get("量比", 0)),
                "net_flow_ratio": row.get("netFlowRatio", row.get("净流占比", 0)),
                "boards": row.get("boards", row.get("连板", "")), "pe": row.get("pe1", row.get("市盈率1", "")),
                "circ_market_cap": row.get("circMarketCap", row.get("流通市值", 0)),
            })
        plates[str(pid)] = normalized
    return sectors, {"plates": plates}


def update_sector_trend(index, day_views):
    """把最近 10 个交易日的板块前十写入 index，供首屏一次请求展示。"""
    dates = sorted((d.get("date") for d in index.get("days", []) if d.get("date")), reverse=True)[:10]
    trend = []
    for date_str in dates:
        sectors = (day_views.get(date_str) or {}).get("sectors", [])[:10]
        trend.append({"date": date_str, "top": [
            {k: s.get(k) for k in ("id", "name", "rank", "strength", "limit_up_count")} for s in sectors
        ]})
    index["sector_trend"] = trend
    return index


def write_sector_view(date_str, detail, out_dir):
    raw = json.dumps({"date": date_str, **detail}, ensure_ascii=False).encode("utf-8")
    path = os.path.join(out_dir, f"day_{date_str}.sector.json")
    with open(path, "wb") as fh:
        fh.write(raw)
    with open(path + ".gz", "wb") as fh:
        fh.write(gzip.compress(raw, compresslevel=6))
    return [path, path + ".gz"]


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
        if rec.get("status") in ("source_missing", "invalid_instrument"):
            continue
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

def promote_day_view(date_str, out_dir):
    """质量门禁通过后，将已生成的历史日视图原子发布为 latest。"""
    source = os.path.join(out_dir, f"day_{date_str}.json")
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    with open(source, "rb") as fh:
        raw = fh.read()
    fd, temp_path = tempfile.mkstemp(prefix="day_latest_", suffix=".json", dir=out_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(temp_path, os.path.join(out_dir, "day_latest.json"))
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return os.path.join(out_dir, "day_latest.json")


def write_day_view(date_str, view, out_dir, publish_latest=True):
    """写 day_<date>.json + .gz + day_latest.json，更新 index.json 日期清单。"""
    os.makedirs(out_dir, exist_ok=True)
    raw = json.dumps(view, ensure_ascii=False).encode("utf-8")

    day_path = os.path.join(out_dir, f"day_{date_str}.json")
    with open(day_path, "wb") as fh:
        fh.write(raw)
    gz_path = day_path + ".gz"
    with open(gz_path, "wb") as fh:
        fh.write(gzip.compress(raw, compresslevel=6))

    latest_path = os.path.join(out_dir, "day_latest.json")
    if publish_latest:
        promote_day_view(date_str, out_dir)

    index_path = os.path.join(out_dir, "index.json")
    idx = {"days": []}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as fh:
            idx = json.load(fh)
    dates = {d["date"] for d in idx["days"]}
    if date_str not in dates:
        idx["days"].append({"date": date_str})
    idx["days"].sort(key=lambda d: d["date"], reverse=True)
    day_views = {date_str: view}
    for entry in idx["days"][:10]:
        d = entry["date"]
        if d in day_views:
            continue
        p = os.path.join(out_dir, f"day_{d}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                day_views[d] = json.load(fh)
    update_sector_trend(idx, day_views)
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, ensure_ascii=False, indent=2)

    return [day_path, gz_path, latest_path, index_path]


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


def archive_day(date_str, facts_dir, web_dir, intraday_dir, archive_dir, publish_latest=True, kpl_output=None):
    """归档编排：facts → 视图层（day + detail + 索引 + master lib）→ intraday 移入 archive。返回 (view, paths)。"""
    facts = read_facts(date_str, facts_dir)
    stocks_path = os.path.join(os.path.dirname(facts_dir), "normalized", "stocks.json")
    if os.path.exists(stocks_path):
        with open(stocks_path, encoding="utf-8") as fh:
            stocks = json.load(fh)
        facts["stock_names"] = {sid: rec.get("name", sid) for sid, rec in stocks.items()}
    theme_stocks_path = os.path.join(os.path.dirname(facts_dir), "normalized", "theme_stocks.json")
    if os.path.exists(theme_stocks_path):
        with open(theme_stocks_path, encoding="utf-8") as fh:
            facts["theme_stocks"] = json.load(fh)
    themes_path = os.path.join(os.path.dirname(facts_dir), "normalized", "themes.json")
    if os.path.exists(themes_path):
        with open(themes_path, encoding="utf-8") as fh:
            facts["themes"] = json.load(fh)
    sector_detail = None
    if kpl_output:
        daily_path = os.path.join(kpl_output, f"kpl_{date_str}.json")
        stocks_daily_path = os.path.join(kpl_output, f"kpl_{date_str}_stocks.json")
        if os.path.exists(daily_path):
            with open(daily_path, encoding="utf-8-sig") as fh:
                daily = json.load(fh)
            stocks_doc = {}
            if os.path.exists(stocks_daily_path):
                with open(stocks_daily_path, encoding="utf-8-sig") as fh:
                    stocks_doc = json.load(fh)
            kpl_sectors, sector_detail = build_kpl_sector_views(daily, stocks_doc)
            facts["sectors"] = {s["id"]: {k: v for k, v in s.items() if k != "id"} for s in kpl_sectors}
            # facts 只增不改：仅为缺失历史日补建规范板块事实，已有文件绝不覆盖。
            fact_sector_path = os.path.join(facts_dir, date_str, "sectors.json")
            if not os.path.exists(fact_sector_path):
                os.makedirs(os.path.dirname(fact_sector_path), exist_ok=True)
                with open(fact_sector_path, "w", encoding="utf-8") as fh:
                    json.dump({"data_date": date_str, "sectors": facts["sectors"]}, fh, ensure_ascii=False, indent=2)
    view = build_day_view(date_str, facts)
    paths = write_day_view(date_str, view, web_dir, publish_latest=publish_latest)
    paths += write_detail_view(date_str, build_detail_view(date_str, facts), web_dir)
    if sector_detail is not None:
        paths += write_sector_view(date_str, sector_detail, web_dir)
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
    ap.add_argument("--stage-only", action="store_true", help="只生成历史日视图，不更新 day_latest.json")
    ap.add_argument("--kpl-output", help="KPL 每日文件目录；用于补齐板块统计、子板块和成分股详情")
    args = ap.parse_args(argv)

    view, paths = archive_day(args.date, args.facts, args.web, args.intraday, args.archive,
                              publish_latest=not args.stage_only, kpl_output=args.kpl_output)
    print(f"[OK] {args.date} 视图层已生成: day_{args.date}.json + .gz")
    if args.verify:
        ok, report = verify_view(view, paths[0], paths[1])
        print(f"[VERIFY] {'PASS' if ok else 'FAIL'} raw={report['raw_kb']}KB gz={report['gz_kb']}KB "
              f"板块={report['sectors']} 涨停={report['limitup']}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
