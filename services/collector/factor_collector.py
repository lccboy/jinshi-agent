# -*- coding: utf-8 -*-
"""板块因子采集（V0.1a 任务 5）

依据 `docs/DATA_MODEL.md`：
- §4.14 `money_flow.json`：东财板块资金流（push2delay.eastmoney.com clist，f62 主力净流入口径）
- §4.15 `leading_reason.json`：选股宝领涨原因（flash-api.xuangubao.cn surge_stock）
- §3.3 `sector_map.json`：KPL 801xxx ↔ 东财 BKxxxx ↔ 选股宝 plate_id 三套 ID 的跨源映射（名称匹配）

网络接口均公开（无需凭据）；测试走纯函数离线路径。
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

EM_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EM_FIELDS = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
EM_FS = "m:90+t:2+f:!2,m:90+t:1+f:!2"
XGB_URL = "https://flash-api.xuangubao.cn/api/surge_stock/plates"


# ---------------- 纯函数（TDD 覆盖） ----------------

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def map_em_flow(row):
    """东财 clist 行 → money_flow 板块记录（DATA_MODEL §4.14）。"""
    return {
        "em_code": str(row.get("f12", "")),
        "name": str(row.get("f14", "")),
        "price": _num(row.get("f2")),
        "pct": _num(row.get("f3")),
        "main": _num(row.get("f62")),
        "main_pct": _num(row.get("f184")),
        "super": _num(row.get("f66")),
        "super_pct": _num(row.get("f69")),
        "big": _num(row.get("f72")),
        "big_pct": _num(row.get("f75")),
        "mid": _num(row.get("f78")),
        "mid_pct": _num(row.get("f81")),
        "small": _num(row.get("f84")),
        "small_pct": _num(row.get("f87")),
    }


def map_leading_reason(plate):
    """选股宝 plate → leading_reason 板块记录（DATA_MODEL §4.15）。接口 key 为 `id`，兼容 `plate_id`。"""
    return {
        "xgb_id": str(plate.get("plate_id", plate.get("id", ""))),
        "name": str(plate.get("name", "")),
        "reason": str(plate.get("description", "") or ""),
        "limit_up_count": int(_num(plate.get("limit_up_count", 0))),
        "stocks": list(plate.get("stocks", []) or []),
    }


def _norm_name(name):
    text = str(name or "").strip()
    for suffix in ("概念", "板块"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def load_aliases(path):
    """加载 `config/sector_aliases.json`：{"em": {kpl名: em名}, "xgb": {kpl名: xgb名}}。"""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_sector_map(kpl_sectors, em_flows, leading_reasons, aliases=None):
    """名称匹配 + 别名表建立跨源映射。

    kpl_sectors: {kpl_id: {name}}；em_flows: [map_em_flow 记录]；leading_reasons: [map_leading_reason 记录]。
    aliases: load_aliases 输出（{"em": {...}, "xgb": {...}}），解析顺序 = 精确名 → 后缀归一 → 别名 → 未命中。
    返回 (mapping, report)：mapping[kpl_id] = {name, em_code, xgb_id}；report 含命中/未命中统计。
    """
    aliases = aliases or {}
    em_alias, xgb_alias = aliases.get("em", {}), aliases.get("xgb", {})

    by_em, by_em_alias = {}, {}
    for f in em_flows:
        by_em.setdefault(_norm_name(f["name"]), []).append(f["em_code"])
        for kpl_name, em_name in em_alias.items():
            if em_name == f["name"]:
                by_em_alias.setdefault(_norm_name(kpl_name), []).append(f["em_code"])
    by_xgb, by_xgb_alias = {}, {}
    for r in leading_reasons:
        by_xgb.setdefault(_norm_name(r["name"]), []).append(r["xgb_id"])
        for kpl_name, xgb_name in xgb_alias.items():
            if xgb_name == r["name"]:
                by_xgb_alias.setdefault(_norm_name(kpl_name), []).append(r["xgb_id"])

    mapping, report = {}, {"em_matched": 0, "em_unmatched": 0, "xgb_matched": 0, "xgb_unmatched": 0,
                           "em_alias_hit": 0, "xgb_alias_hit": 0}
    for kpl_id, sec in kpl_sectors.items():
        name = sec.get("name", "")
        key = _norm_name(name)
        em_hits = by_em.get(key) or by_em_alias.get(key) or [None]
        xgb_hits = by_xgb.get(key) or by_xgb_alias.get(key) or [None]
        em_code, xgb_id = em_hits[0], xgb_hits[0]
        if em_code and key not in by_em and em_code in by_em_alias.get(key, []):
            report["em_alias_hit"] += 1
        if xgb_id and key not in by_xgb and xgb_id in by_xgb_alias.get(key, []):
            report["xgb_alias_hit"] += 1
        mapping[kpl_id] = {"name": name, "em_code": em_code, "xgb_id": xgb_id}
        report["em_matched" if em_code else "em_unmatched"] += 1
        report["xgb_matched" if xgb_id else "xgb_unmatched"] += 1
    return mapping, report


def compute_ranks(flows):
    """按主力净流入降序计算 rank_in / main_pct_rank（DATA_MODEL §4.14 排名字段）。"""
    flows = list(flows)
    flows.sort(key=lambda f: f.get("main", 0), reverse=True)
    for i, f in enumerate(flows, start=1):
        f["rank_in"] = i
        f["main_pct_rank"] = i
    return flows


# ---------------- 网络采集（公开接口） ----------------

def _get_json(url, params=None, attempts=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # 限流/抖动重试
            last = exc
            import time
            time.sleep(0.5)
    raise last


def fetch_em_flows():
    """东财板块资金流：概念(t:2)+行业(t:1)分页拉全（每页 100，共 ~500+ 板块），按 em_code 去重。"""
    flows, seen = [], set()
    for fs in ("m:90+t:2+f:!2", "m:90+t:1+f:!2"):
        pn = 1
        while pn <= 12:
            data = _get_json(EM_URL, {"pn": str(pn), "pz": "100", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                                      "fid": "f62", "fs": fs, "fields": EM_FIELDS}).get("data") or {}
            diff = data.get("diff", []) or []
            if isinstance(diff, dict):
                diff = [diff[k] for k in sorted(diff, key=int)]
            if not diff:
                break
            for row in diff:
                rec = map_em_flow(row)
                if rec["em_code"] and rec["em_code"] not in seen:
                    seen.add(rec["em_code"])
                    flows.append(rec)
            pn += 1
    return flows


def fetch_leading_reasons():
    """选股宝领涨原因板块列表（surge_stock/plates，响应 `data.items`，key 为 `id`）。"""
    data = _get_json(XGB_URL, {"cache": "false"}).get("data") or {}
    plates = data.get("items", []) or []
    return [map_leading_reason(p) for p in plates]


# ---------------- 写盘 ----------------

def write_facts(date_str, flows, reasons, mapping, out_dir):
    """写 `facts/<date>/money_flow.json`、`leading_reason.json` + `normalized/sector_map.json`。"""
    facts_dir = os.path.join(out_dir, "facts", date_str)
    os.makedirs(facts_dir, exist_ok=True)

    by_em = {f["em_code"]: f for f in flows}
    by_xgb = {r["xgb_id"]: r for r in reasons}
    money_sectors = {}
    for kpl_id, m in mapping.items():
        flow = by_em.get(m["em_code"])
        if not flow:
            continue
        entry = {k: flow[k] for k in ("name", "main", "main_pct", "super", "super_pct", "big", "big_pct",
                                      "mid", "small")}
        entry["em_code"] = m["em_code"]
        entry["rank_in"], entry["main_pct_rank"] = 0, 0
        money_sectors[kpl_id] = entry
    compute_ranks(list(money_sectors.values()))  # 按主力净流入降序覆写排名字段

    with open(os.path.join(facts_dir, "money_flow.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": date_str, "sectors": money_sectors}, fh, ensure_ascii=False, indent=2)

    plates = {}
    for kpl_id, m in mapping.items():
        r = by_xgb.get(m["xgb_id"])
        if r:
            plates[r["xgb_id"]] = {"xgb_id": r["xgb_id"], "name": r["name"], "reason": r["reason"],
                                   "limit_up_count": r["limit_up_count"], "stocks": r["stocks"]}
    with open(os.path.join(facts_dir, "leading_reason.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": date_str, "plates": plates}, fh, ensure_ascii=False, indent=2)

    norm_dir = os.path.join(out_dir, "normalized")
    os.makedirs(norm_dir, exist_ok=True)
    with open(os.path.join(norm_dir, "sector_map.json"), "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)

    return len(money_sectors), len(plates)


# ---------------- CLI ----------------

def load_kpl_sectors(out_dir):
    path = os.path.join(out_dir, "normalized", "sectors.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="板块因子采集（factor_collector）")
    ap.add_argument("--date", default="", help="数据日期（默认取主数据 manifest 或今日）")
    ap.add_argument("--out", default="data", help="数据根目录（默认 data，facts/normalized 位于其下）")
    ap.add_argument("--sectors-json", help="KPL 板块字典路径（normalized/sectors.json），缺省读 --out/normalized")
    ap.add_argument("--aliases", default=os.path.join(os.path.dirname(__file__), "..", "..", "config", "sector_aliases.json"),
                    help="别名表路径（默认 config/sector_aliases.json）")
    args = ap.parse_args(argv)

    flows = fetch_em_flows()
    reasons = fetch_leading_reasons()
    print(f"[OK] 东财板块 {len(flows)} | 选股宝板块 {len(reasons)}")

    kpl_path = args.sectors_json or os.path.join(args.out, "normalized", "sectors.json")
    if not os.path.exists(kpl_path):
        print(f"[WARN] 未找到板块字典 {kpl_path}，跳过映射与写盘")
        return 1
    with open(kpl_path, encoding="utf-8") as fh:
        kpl_sectors = json.load(fh)

    mapping, report = build_sector_map(kpl_sectors, flows, reasons, load_aliases(args.aliases))
    print(f"[MAP] 东财命中 {report['em_matched']}/{len(kpl_sectors)}（别名 {report['em_alias_hit']}）"
          f" | 选股宝命中 {report['xgb_matched']}/{len(kpl_sectors)}（别名 {report['xgb_alias_hit']}）")
    if not args.date:
        args.date = json.load(open(os.path.join(args.out, "normalized", "..", "manifest.json"), encoding="utf-8")) \
            .get("stocks", {}).get("last_full", "")
    if not args.date:
        import datetime
        args.date = datetime.date.today().strftime("%Y-%m-%d")

    n_flow, n_reason = write_facts(args.date, flows, reasons, mapping, args.out)
    print(f"[DONE] facts/{args.date}/money_flow.json 板块数={n_flow} | leading_reason.json 板块数={n_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
