# -*- coding: utf-8 -*-
"""题材字典采集（V0.2.2 任务 2）

依据 `docs/DATA_MODEL.md` §3.2：题材是动态概念，题材 ID 需稳定。
- 输入：题材库 `all_themes_slim.json`（{题材ID: {n 名称, l 层级, t 概念树, s 成分股[{c 代码, n 名称, h 热度, tg 标签}]}}）
- 输出：
  - `data/normalized/themes.json`：题材字典（name/sub_concepts/hot/stock_count/source/updated_at）
  - `data/normalized/theme_stocks.json`：{theme_id: [stock_id]}（题材→成分股索引，UI 展开用）
  - 回写 `data/normalized/stocks.json`：补缺失个股 + `current.themes` 去重回写
"""
import argparse
import datetime
import hashlib
import json
import os

from .master_collector import build_stock_record, write_sectors_json  # noqa: F401（复用产出工具）
from .normalize import is_equity_code, stock_id

DEFAULT_SOURCE_ROOT = r"H:\projects\金十AI题材库"


def discover_theme_source(root=DEFAULT_SOURCE_ROOT):
    """选择题材库当前产物；备份目录只允许显式通过 --source 使用。"""
    path = os.path.abspath(os.path.join(root, "all_themes_slim.json"))
    return path if os.path.isfile(path) else ""


def _source_meta(source, collected_at=None):
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(source)).astimezone()
    collected = collected_at or datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with open(source, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    today = datetime.datetime.now().astimezone().date()
    return {
        "source": "theme_repo",
        "source_path": os.path.abspath(source),
        "source_updated_at": mtime.isoformat(timespec="seconds"),
        "collected_at": collected,
        "source_hash": digest,
        "freshness": "fresh" if (today - mtime.date()).days <= 1 else "stale",
    }


def parse_theme_dump(dump, updated_at=None):
    """题材库 dump → (themes, theme_stocks, stock_names)。

    - 概念树 `t[].n1` + `t[].l2[].n2` 展平为 sub_concepts，并保留完整树（tree: [{n1, st, l2:[{n2, st}]}]）
    - 成分 `s[].c`（6 位代码）→ stock_id；`s[].h` 均值作题材热度
    """
    updated_at = updated_at or datetime.date.today().strftime("%Y-%m-%d")
    themes, theme_stocks, stock_names = {}, {}, {}
    for tid, v in dump.items():
        sub, tree = [], []
        for t in v.get("t") or []:
            if t.get("n1"):
                sub.append(t["n1"])
            l2 = []
            for x in t.get("l2") or []:
                if x.get("n2"):
                    sub.append(x["n2"])
                l2.append({"n2": x.get("n2", ""), "st": _codes(x.get("st"))})
            tree.append({"n1": t.get("n1", ""), "st": _codes(t.get("st")), "l2": l2})
        members = v.get("s") or []
        hot = round(sum((m.get("h") or 0) for m in members) / len(members)) if members else 0
        themes[str(tid)] = {"theme_id": str(tid), "name": str(v.get("n", "")), "source": "题材库",
                            "sub_concepts": sub, "hot": hot, "stock_count": len(members),
                            "tree": tree, "updated_at": updated_at}
        codes = []
        for m in members:
            c = str(m.get("c", "") or "").strip().zfill(6)
            if is_equity_code(c):
                sid = stock_id(c)
                codes.append(sid)
                stock_names.setdefault(sid, str(m.get("n", "")))
        theme_stocks[str(tid)] = codes
    return themes, theme_stocks, stock_names


def _codes(rows):
    """概念成分行 [{c, r}] → [stock_id]。"""
    out = []
    for m in rows or []:
        c = str(m.get("c", "") or "").strip().zfill(6)
        if is_equity_code(c):
            out.append(stock_id(c))
    return out


def merge_themes_into_master(stocks, themes, theme_stocks, stock_names, updated_at=None):
    """回写 stocks.json：补缺失个股（题材库成员）+ `current.themes` 去重。"""
    updated_at = updated_at or datetime.date.today().strftime("%Y-%m-%d")
    # 题材源对 current.themes 拥有字段所有权：先清空再按最新索引重建，避免退出题材后残留。
    for rec in stocks.values():
        rec.setdefault("current", {})["themes"] = []
    for tid, codes in theme_stocks.items():
        for sid in codes:
            rec = stocks.get(sid)
            if rec is None:
                rec = build_stock_record(sid[2:], stock_names.get(sid, sid[2:]), set(), updated_at)
                stocks[sid] = rec
            cur = rec.setdefault("current", {})
            cur.setdefault("themes", [])
            if tid not in cur["themes"]:
                cur["themes"].append(tid)
            cur["updated_at"] = updated_at
            rec["updated_at"] = updated_at
    return stocks


def collect(source, out_dir, collected_at=None):
    """题材库文件 → 三个产出。返回计数 dict。"""
    meta = _source_meta(source, collected_at)
    with open(source, encoding="utf-8") as fh:
        dump = json.load(fh)
    themes, theme_stocks, stock_names = parse_theme_dump(dump, meta["source_updated_at"][:10])

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "themes.json"), "w", encoding="utf-8") as fh:
        json.dump(themes, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "theme_stocks.json"), "w", encoding="utf-8") as fh:
        json.dump(theme_stocks, fh, ensure_ascii=False, indent=2)
    # 概念层级树（主概念 n1 → 细分概念 n2 → 成分股），供"概念层级表格"渲染
    with open(os.path.join(out_dir, "themes_tree.json"), "w", encoding="utf-8") as fh:
        json.dump({tid: {"name": t["name"], "tree": t["tree"]} for tid, t in themes.items()},
                  fh, ensure_ascii=False, indent=2)

    stocks_path = os.path.join(out_dir, "stocks.json")
    stocks = {}
    if os.path.exists(stocks_path):
        with open(stocks_path, encoding="utf-8") as fh:
            stocks = json.load(fh)
    before = len(stocks)
    merge_themes_into_master(stocks, themes, theme_stocks, stock_names)
    with open(stocks_path, "w", encoding="utf-8") as fh:
        json.dump(stocks, fh, ensure_ascii=False, indent=2)

    manifest_path = os.path.abspath(os.path.join(out_dir, "..", "manifest.json"))
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    meta["count"] = len(themes)
    manifest["themes"] = meta
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    return {"themes": len(themes), "theme_stocks": len(theme_stocks), "freshness": meta["freshness"],
            "stocks_before": before, "stocks_after": len(stocks)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="题材字典采集（theme_collector）")
    ap.add_argument("--source", default="", help="题材库 all_themes_slim.json 路径（默认自动选择当前产物）")
    ap.add_argument("--out", default="data/normalized", help="输出目录（默认 data/normalized）")
    args = ap.parse_args(argv)
    source = args.source or discover_theme_source()
    if not source or not os.path.exists(source):
        print(f"[ERROR] 题材库当前文件不存在: {source or DEFAULT_SOURCE_ROOT}")
        return 1
    report = collect(source, args.out)
    print(f"[OK] 题材={report['themes']} 题材成分索引={report['theme_stocks']} "
          f"个股 {report['stocks_before']} → {report['stocks_after']}（新增 {report['stocks_after'] - report['stocks_before']}）"
          f" freshness={report['freshness']} source={source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
