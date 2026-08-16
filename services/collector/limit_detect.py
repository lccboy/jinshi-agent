# -*- coding: utf-8 -*-
"""涨停检测（V0.3 任务 2，盘中实时链路）

依据 `docs/DATA_MODEL.md` §10：
- **腾讯涨停价字段优先**：现价 ≥ 涨停价 − 0.01 元容差 → 涨停（涨停价字段为 0 时规则推导兜底）
- **规则推导**：`涨停价 = round(昨收 × (1+limit) × 100) / 100`，阈值按板块与 ST 状态：

  | 板块 | 代码前缀 | 普通 | ST |
  |---|---|---|---|
  | 主板 | 60/00 | 10% | 5% |
  | 创业板 | 30 | 20% | 20% |
  | 科创板 | 68 | 20% | 20% |
  | 北交所 | 8/4/92 | 30% | 30% |

- 新股（名称含 N / 上市 ≤5 日）首日无限制，不判涨停
- **双源交叉验证**：KPL 有腾讯无 = 疑似炸板（kpl）；腾讯有 KPL 无 = KPL 缺失（tencent）；双源都有 = both
"""
import argparse
import json
import re


def limit_pct(code, is_st=False):
    """代码前缀 + ST → 涨停幅度（DATA_MODEL §10 表）。"""
    c = str(code)
    if is_st and c.startswith(("60", "00")):
        return 0.05
    if c.startswith(("30", "68")):
        return 0.20
    if c.startswith(("60", "00")):
        return 0.10
    return 0.30  # 北交所 8/4/92


def limit_price(prev_close, code, is_st=False):
    """规则推导涨停价：round(昨收 × (1+limit) × 100) / 100（分精度四舍五入）。"""
    return round(prev_close * (1 + limit_pct(code, is_st)) * 100) / 100.0


def is_new_stock(name="", list_date=None, today=None, days=5):
    """新股判定：名称含 N 前缀，或上市 ≤5 日（list_date 缺失时仅名称判定）。"""
    if str(name or "").strip().upper().startswith("N"):
        return True
    if list_date and today:
        try:
            from datetime import datetime
            d1 = datetime.strptime(str(list_date), "%Y-%m-%d")
            d2 = datetime.strptime(str(today), "%Y-%m-%d")
            return (d2 - d1).days <= days
        except (ValueError, TypeError):
            return False
    return False


def rule_limit_up(price, prev_close, code, is_st=False, is_new=False):
    """规则推导判定：现价 ≥ 涨停价 − 容差。新股返回 None（不判）。"""
    if is_new:
        return None
    if not prev_close or prev_close <= 0:
        return False
    return price >= limit_price(prev_close, code, is_st) - 0.01


def is_limit_up(price, prev_close, code, is_st=False, tencent_limit_up=None,
                tolerance=0.01, is_new=False):
    """涨停判定：腾讯涨停价字段优先，字段 0/缺失 → 规则推导兜底。"""
    if is_new:
        return False
    if tencent_limit_up:
        return price >= tencent_limit_up - tolerance
    result = rule_limit_up(price, prev_close, code, is_st=is_st)
    return bool(result)


def detect_from_quotes(quotes, name_of=None, list_date_of=None, today=None):
    """腾讯行情 dict → {stock_id: {is_limit_up, limit_price, detected_by}}。

    - name_of/list_date_of 可选：新股判定（主数据 stocks.json 提供）
    - 涨停价字段优先；字段 0 → 规则推导
    """
    out = {}
    for sid, q in quotes.items():
        code = q["code"]
        is_new = is_new_stock((name_of or {}).get(sid, ""),
                              (list_date_of or {}).get(sid), today)
        lp = q.get("limit_up") or limit_price(q["preclose"], code, q.get("is_st", False))
        hit = is_limit_up(q["price"], q["preclose"], code,
                          is_st=q.get("is_st", False),
                          tencent_limit_up=q.get("limit_up"),
                          is_new=is_new)
        out[sid] = {"is_limit_up": hit, "limit_price": lp,
                    "detected_by": "tencent" if hit else ""}
    return out


def cross_validate(kpl_set, tencent_set):
    """双源交叉验证 → {stock_id: detected_by}（kpl/tencent/both）。"""
    out = {}
    for sid in kpl_set:
        out[sid] = "both" if sid in tencent_set else "kpl"
    for sid in tencent_set:
        if sid not in out:
            out[sid] = "tencent"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="涨停检测（limit_detect）")
    ap.add_argument("--quotes", required=True, help="腾讯行情 JSON（quote_collector 输出）")
    ap.add_argument("--kpl", help="KPL 涨停池文件（每行一个 stock_id）")
    ap.add_argument("--out", help="输出 JSON 路径（缺省打印）")
    args = ap.parse_args(argv)

    with open(args.quotes, encoding="utf-8") as fh:
        quotes = json.load(fh)
    result = detect_from_quotes(quotes)
    hits = {sid for sid, r in result.items() if r["is_limit_up"]}
    print(f"[OK] 检测 {len(result)} 只，涨停 {len(hits)} 只")

    if args.kpl:
        with open(args.kpl, encoding="utf-8") as fh:
            kpl_set = {ln.strip() for ln in fh if ln.strip()}
        cross = cross_validate(kpl_set, hits)
        print(f"  双源交叉: both={sum(1 for v in cross.values() if v=='both')} "
              f"kpl_only={sum(1 for v in cross.values() if v=='kpl')} "
              f"tencent_only={sum(1 for v in cross.values() if v=='tencent')}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
