# -*- coding: utf-8 -*-
"""腾讯实时行情采集（V0.3 任务 1，盘中实时链路）

依据 `docs/DATA_MODEL.md` §9.11/9.12（qt.gtimg.cn 批量）+ §4.1（quotes 字段）：
- HTTP GET `http://qt.gtimg.cn/q=sh600000,sz000001,...` 批量返回，单请求数百只、毫秒级
- 88 字段 ~ 分隔（索引见模块常量）：现价[3]/昨收[4]/今开[5]/量[6]/时间戳[30]/涨跌[31]/涨跌%[32]/
  最高[33]/最低[34]/额[35 第3段]/换手[38]/PE[39]/流通市值[44]/总市值[45]/PB[46]/涨停价[47]/跌停价[48]/量比[49]
- 涨停价/跌停价字段为 0（新股/停牌）时保留 0，由 `limit_detect` 规则推导兜底（§10）
"""
import argparse
import json
import time
import urllib.request

from .normalize import stock_id

QUOTE_BASE = "http://qt.gtimg.cn/q="
BATCH_SIZE = 500          # 单请求股票数上限（实测数百只毫秒级）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 88 字段关键索引（腾讯布局，稳定）
I_NAME, I_CODE, I_PRICE, I_PRECLOSE, I_OPEN = 1, 2, 3, 4, 5
I_VOLUME, I_TIME, I_CHANGE, I_CHG_PCT = 6, 30, 31, 32
I_HIGH, I_LOW, I_AMOUNT_PART = 33, 34, 35
I_TURNOVER, I_PE = 38, 39
I_FLOAT_MKTCAP, I_MKTCAP, I_PB = 44, 45, 46
I_LIMIT_UP, I_LIMIT_DOWN, I_VOL_RATIO = 47, 48, 49


def normalize_tencent_code(code):
    """腾讯 6 位代码 → stock_id（市场前缀，全系统唯一 join 键）。"""
    return stock_id(code)


def _f(parts, idx):
    """字段安全取 float；空/异常 → 0.0。"""
    try:
        v = parts[idx]
        return float(v) if v not in ("", None) else 0.0
    except (IndexError, ValueError, TypeError):
        return 0.0


def _amount_from_part(part35):
    """[35] `price/vol(手)/amount(元)` → 成交额（元）。"""
    try:
        return float(part35.split("/")[2])
    except (IndexError, ValueError, AttributeError):
        return 0.0


def parse_quote_line(line):
    """单行 `v_sh600000="1~...~"` → {stock_id, code, name, price, ...}。

    非行情行（空/无 `="`）返回 None；涨停价等缺失字段保留 0（规则兜底见 limit_detect）。
    """
    line = (line or "").strip()
    if not line or '="' not in line:
        return None
    body = line.split('="', 1)[1].rstrip('";')
    parts = body.split("~")
    if len(parts) < 50:
        return None
    code = str(parts[I_CODE]).strip()
    if not code or not code.isdigit():
        return None
    return {
        "stock_id": stock_id(code),
        "code": code,
        "name": str(parts[I_NAME]).strip(),
        "price": _f(parts, I_PRICE),
        "preclose": _f(parts, I_PRECLOSE),
        "open": _f(parts, I_OPEN),
        "high": _f(parts, I_HIGH),
        "low": _f(parts, I_LOW),
        "change": _f(parts, I_CHANGE),
        "change_pct": _f(parts, I_CHG_PCT),
        "volume": _f(parts, I_VOLUME),          # 手
        "amount": _amount_from_part(parts[I_AMOUNT_PART]),  # 元
        "turnover": _f(parts, I_TURNOVER),      # %
        "pe": _f(parts, I_PE),
        "mktcap": _f(parts, I_MKTCAP),          # 总市值（亿）
        "float_mktcap": _f(parts, I_FLOAT_MKTCAP),
        "pb": _f(parts, I_PB),
        "limit_up": _f(parts, I_LIMIT_UP),      # 0 = 需规则兜底
        "limit_down": _f(parts, I_LIMIT_DOWN),
        "vol_ratio": _f(parts, I_VOL_RATIO),
        "timestamp": str(parts[I_TIME]).strip(),
    }


def parse_quote_response(text):
    """批量响应 → {stock_id: quote}（`;`/换行分隔多行）。"""
    out = {}
    for line in (text or "").replace(";", "\n").split("\n"):
        q = parse_quote_line(line)
        if q:
            out[q["stock_id"]] = q
    return out


def fetch_quotes(codes, base=QUOTE_BASE, batch=BATCH_SIZE, retries=2, timeout=8):
    """批量拉取行情：codes（6 位或 stock_id）→ {stock_id: quote}。

    - 自动按代码前缀转 `sh600000/sz000001/...` 腾讯格式
    - 分批请求（默认 500/批），失败重试 retries 次，单批失败不拖垮整体
    """
    tencent_codes = []
    for c in codes:
        c = str(c).strip()
        if len(c) == 8 and c[:2] in ("SH", "SZ", "BJ"):
            c = c[2:]
        if not c.isdigit() or len(c) != 6:
            continue
        market = "sh" if c.startswith(("60", "68")) else ("sz" if c.startswith(("00", "30")) else "bj")
        tencent_codes.append(market + c)
    if not tencent_codes:
        return {}

    quotes = {}
    for i in range(0, len(tencent_codes), batch):
        chunk = tencent_codes[i:i + batch]
        url = base + ",".join(chunk)
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                raw = urllib.request.urlopen(req, timeout=timeout).read().decode("gbk", errors="replace")
                quotes.update(parse_quote_response(raw))
                break
            except Exception:
                if attempt >= retries:
                    break
                time.sleep(0.5)
    return quotes


def main(argv=None):
    ap = argparse.ArgumentParser(description="腾讯实时行情采集（quote_collector）")
    ap.add_argument("--codes", help="逗号分隔代码（6 位或 SH600000 形态）")
    ap.add_argument("--universe-file", help="每行一个代码的文件")
    ap.add_argument("--out", help="输出 JSON 路径（缺省只打印）")
    ap.add_argument("--limit", type=int, default=0, help="上限（0=全部）")
    args = ap.parse_args(argv)

    codes = []
    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as fh:
            codes = [ln.strip() for ln in fh if ln.strip()]
    elif args.codes:
        codes = args.codes.split(",")
    if args.limit:
        codes = codes[: args.limit]

    quotes = fetch_quotes(codes)
    print(f"[OK] 拉取 {len(quotes)} 只行情")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(quotes, fh, ensure_ascii=False, indent=2)
    else:
        for sid, q in list(quotes.items())[:10]:
            print(f"  {sid} {q['name']} 现价={q['price']} 涨停价={q['limit_up']} 量比={q['vol_ratio']}")
    return 0 if quotes else 1


if __name__ == "__main__":
    raise SystemExit(main())
