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
import json
import os

from .master_collector import build_stock_record, write_sectors_json  # noqa: F401（复用产出工具）
from .normalize import stock_id

DEFAULT_SOURCE = r"H:\projects\金十AI题材库\.deploy_backups\pre_l2_sweep_20260813\all_themes_slim.json"


def parse_theme_dump(dump, updated_at=None):
    """题材库 dump → (themes, theme_stocks, stock_names)。

    - 概念树 `t[].n1` + `t[].l2[].n2` 展平为 sub_concepts
    - 成分 `s[].c`（6 位代码）→ stock_id；`s[].h` 均值作题材热度
    """
    updated_at = updated_at or datetime.date.today().strftime("%Y-%m-%d")
    themes, theme_stocks, stock_names = {}, {}, {}
    for tid, v in dump.items():
        sub = []
        for t in v.get("t") or []:
            if t.get("n1"):
                sub.append(t["n1"])
            for l2 in t.get("l2") or []:
                if l2.get("n2"):
                    sub.append(l2["n2"])
        members = v.get("s") or []
        hot = round(sum((m.get("h") or 0) for m in members) / len(members)) if members else 0
        themes[str(tid)] = {"theme_id": str(tid), "name": str(v.get("n", "")), "source": "题材库",
                            "sub_concepts": sub, "hot": hot, "stock_count": len(members),
                            "updated_at": updated_at}
        codes = []
        for m in members:
            c = str(m.get("c", "") or "").strip().zfill(6)
            if len(c) == 6 and c.isdigit():
                sid = stock_id(c)
                codes.append(sid)
                stock_names.setdefault(sid, str(m.get("n", "")))
        theme_stocks[str(tid)] = codes
    return themes, theme_stocks, stock_names


def merge_themes_into_master(stocks, themes, theme_stocks, stock_names, updated_at=None):
    """回写 stocks.json：补缺失个股（题材库成员）+ `current.themes` 去重。"""
    updated_at = updated_at or datetime.date.today().strftime("%Y-%m-%d")
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


def collect(source, out_dir):
    """题材库文件 → 三个产出。返回计数 dict。"""
    with open(source, encoding="utf-8") as fh:
        dump = json.load(fh)
    themes, theme_stocks, stock_names = parse_theme_dump(dump)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "themes.json"), "w", encoding="utf-8") as fh:
        json.dump(themes, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "theme_stocks.json"), "w", encoding="utf-8") as fh:
        json.dump(theme_stocks, fh, ensure_ascii=False, indent=2)

    stocks_path = os.path.join(out_dir, "stocks.json")
    stocks = {}
    if os.path.exists(stocks_path):
        with open(stocks_path, encoding="utf-8") as fh:
            stocks = json.load(fh)
    before = len(stocks)
    merge_themes_into_master(stocks, themes, theme_stocks, stock_names)
    with open(stocks_path, "w", encoding="utf-8") as fh:
        json.dump(stocks, fh, ensure_ascii=False, indent=2)

    return {"themes": len(themes), "theme_stocks": len(theme_stocks),
            "stocks_before": before, "stocks_after": len(stocks)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="题材字典采集（theme_collector）")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="题材库 all_themes_slim.json 路径")
    ap.add_argument("--out", default="data/normalized", help="输出目录（默认 data/normalized）")
    args = ap.parse_args(argv)
    if not os.path.exists(args.source):
        print(f"[ERROR] 题材库文件不存在: {args.source}")
        return 1
    report = collect(args.source, args.out)
    print(f"[OK] 题材={report['themes']} 题材成分索引={report['theme_stocks']} "
          f"个股 {report['stocks_before']} → {report['stocks_after']}（新增 {report['stocks_after'] - report['stocks_before']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
