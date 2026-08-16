# -*- coding: utf-8 -*-
"""日K同步（V0.1a 任务 4）

依据 `docs/DATA_MODEL.md` §12：
- 读取通达信 vipdoc `.day`：每根 32 字节 = date/o/h/l/c（各 int32，价格×100）+ amt（float32）+ vol（int32）+ reserved
- 前复权：gbbq 权息事件（pytdx 可用时）；缺失回退价格跳空推断——**只调整 OHLC，量/额不变**
- 输出 `data/kline/<stock_id>.json`：`{stock_id, adjusted: "qfq", bars:[{d,o,h,l,c,v,amt}]}`

口径要点（与参考 `tdx_tri_screener.py` + `tdx_gbbq.py` 逐位一致）：
- `.day` 解析保持 **o/h/l/c 为 int×100**，复权因子在整数分上计算（逐分取整对低价股除权比值影响显著），
  最后在输出层 `to_kline_bars` 转为元——这是与通达信显示价对账一致的唯一路径。
"""
import argparse
import bisect
import json
import os
import struct

from .normalize import stock_id

DAY_RECORD = struct.Struct("<IIIIIfII")  # date,o,h,l,c,amt(float),vol,reserved = 32B
DAY_RECORD_SIZE = DAY_RECORD.size


def parse_day_file(path):
    """`.day` 二进制 → [{d,o,h,l,c,v,amt}]；**o/h/l/c 为 int×100 原始值**，amt(元)浮点，v(股)int。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return []
    bars = []
    for i in range(0, len(raw) - DAY_RECORD_SIZE + 1, DAY_RECORD_SIZE):
        dt, o, h, l, c, amt, vol, _ = DAY_RECORD.unpack_from(raw, i)
        bars.append({"d": dt, "o": o, "h": h, "l": l, "c": c, "v": vol, "amt": amt})
    return bars


_GBBQ_CACHE = None


def _load_gbbq():
    """加载 gbbq 权息事件（category=1 真实除权除息）。结果模块级缓存，避免逐股重复解析。"""
    global _GBBQ_CACHE
    if _GBBQ_CACHE is not None:
        return _GBBQ_CACHE
    try:
        from pytdx.reader.gbbq_reader import GbbqReader  # 可选依赖
    except Exception:
        _GBBQ_CACHE = (False, {})
        return _GBBQ_CACHE

    # 候选根目录：env TDX_ROOT 优先，其次本机已知通达信安装
    roots = [os.environ.get("TDX_ROOT", "")]
    roots += [r"H:\MPV1.240322\Tdx MPV V1.24++", r"D:\new_tdx64"]
    candidates = []
    for root in roots:
        if not root:
            continue
        candidates += [
            os.path.join(root, "T0002", "hq_cache", "gbbq"),
            os.path.join(root, "T0002", "hq_cache", "gbbq.dat"),
        ]
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if not path:
        _GBBQ_CACHE = (False, {})
        return _GBBQ_CACHE
    try:
        frame = GbbqReader().get_df(path)
    except Exception:
        _GBBQ_CACHE = (False, {})
        return _GBBQ_CACHE

    events = {}
    for row in frame.itertuples(index=False):
        if float(getattr(row, "category", 0) or 0) != 1:
            continue
        code = "".join(ch for ch in str(getattr(row, "code", "")) if ch.isdigit())[:6]
        if not code:
            continue
        date_val = getattr(row, "datetime", None)
        date_int = None
        if date_val is not None:
            digits = "".join(ch for ch in str(date_val) if ch.isdigit())
            if len(digits) >= 8:
                date_int = int(digits[:8])
        if date_int is None:
            continue
        events.setdefault(code, []).append((
            date_int,
            float(getattr(row, "hongli_panqianliutong", 0) or 0),
            float(getattr(row, "peigujia_qianzongguben", 0) or 0),
            float(getattr(row, "songgu_qianzongguben", 0) or 0),
            float(getattr(row, "peigu_houzongguben", 0) or 0),
        ))
    for values in events.values():
        values.sort(key=lambda item: item[0])
    _GBBQ_CACHE = (True, events)
    return _GBBQ_CACHE


def _gbbq_adjust(bars, events):
    """按真实权息事件计算前复权因子，只调整 OHLC（口径同 tdx_gbbq._gbbq_adjust，输入为 int×100）。"""
    dates = [b["d"] for b in bars]
    factors = [1.0] * len(bars)
    latest = dates[-1]
    for event_date, cash10, rights_price, bonus10, rights10 in events:
        if event_date > latest:
            continue
        idx = bisect.bisect_left(dates, event_date) - 1
        if idx < 0:
            continue
        prev_close = bars[idx]["c"]
        if prev_close <= 0:
            continue
        denominator = 1.0 + bonus10 / 10.0 + rights10 / 10.0
        if denominator <= 0:
            continue
        ex_reference = (prev_close - cash10 / 10.0 + rights_price * rights10 / 10.0) / denominator
        ratio = ex_reference / prev_close
        if not (0.05 < ratio < 2.0):
            continue
        for i in range(idx + 1):
            factors[i] *= ratio
    out = []
    for i, b in enumerate(bars):
        nb = dict(b)
        for key in ("o", "h", "l", "c"):
            nb[key] *= factors[i]
        out.append(nb)
    return out


def _fallback_adjust(bars, code):
    """价格跳空推断复权（gbbq 不可用时），只调整 OHLC（口径同 tdx_gbbq._fallback_adjust）。"""
    limit = 0.215 if str(code).startswith(("300", "301", "302", "688")) else 0.115
    out = [dict(b) for b in bars]
    for i in range(len(out) - 1, 0, -1):
        close_prev, close_now = out[i - 1]["c"], out[i]["c"]
        if close_prev <= 0:
            continue
        ratio = close_now / close_prev
        if abs(ratio - 1.0) > limit:
            for key in ("o", "h", "l", "c"):
                out[i - 1][key] *= ratio
    return out


def adjust_bars(bars, code):
    """前复权入口（输入 int×100 原始 bars）：gbbq 可用走真实权息，否则回退跳空推断。"""
    loaded, events = _load_gbbq()
    if not loaded:
        return _fallback_adjust(bars, code)
    return _gbbq_adjust(bars, events.get(str(code), ()))


def to_kline_bars(adjusted_bars):
    """int×100 复权结果 → DATA_MODEL §12 输出形态（价格转元）。"""
    return [
        {"d": b["d"], "o": b["o"] / 100.0, "h": b["h"] / 100.0, "l": b["l"] / 100.0,
         "c": b["c"] / 100.0, "v": b["v"], "amt": b["amt"]}
        for b in adjusted_bars
    ]


def write_kline_json(sid, bars, out_dir):
    """按 DATA_MODEL §12 写出 `data/kline/<stock_id>.json`（bars 为元价格形态）。"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{sid}.json")
    doc = {"stock_id": sid, "adjusted": "qfq", "bars": bars}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    return path


def sync_stock(code, market, vipdoc_root, out_dir):
    """同步单只：读 .day → 前复权 → 转元 → 写 kline JSON。返回 (sid, 根数)。"""
    sid = stock_id(code)
    path = os.path.join(vipdoc_root, market, "lday", f"{market}{code}.day")
    raw = parse_day_file(path)
    if not raw:
        return sid, 0
    adjusted = adjust_bars(raw, code)
    write_kline_json(sid, to_kline_bars(adjusted), out_dir)
    return sid, len(adjusted)


def main(argv=None):
    ap = argparse.ArgumentParser(description="日K同步（kline_sync）")
    ap.add_argument("--vipdoc", required=True, help="通达信 vipdoc 根目录（如 H:\\MPV1.240322\\Tdx MPV V1.24++\\vipdoc）")
    ap.add_argument("--out", default="data/kline", help="输出目录（默认 data/kline）")
    ap.add_argument("--code", help="6 位代码（如 600000）")
    ap.add_argument("--market", default="sh", choices=["sh", "sz", "bj"], help="市场目录（默认 sh）")
    ap.add_argument("--universe-file", help="批量：每行一个 6 位代码（自动按代码前缀选市场）")
    ap.add_argument("--limit", type=int, default=0, help="批量上限（0=全部）")
    args = ap.parse_args(argv)

    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as fh:
            codes = [ln.strip() for ln in fh if ln.strip()]
        if args.limit:
            codes = codes[: args.limit]
        done, failed = 0, []
        for code in codes:
            market = "sh" if code.startswith(("60", "68")) else ("sz" if code.startswith(("00", "30")) else "bj")
            sid, n = sync_stock(code, market, args.vipdoc, args.out)
            if n:
                done += 1
            else:
                failed.append(code)
        print(f"[OK] 批量同步 {done}/{len(codes)} 只；失败 {len(failed)}: {failed[:10]}")
        return 0 if not failed else 2

    if args.code:
        sid, n = sync_stock(args.code, args.market, args.vipdoc, args.out)
        print(f"[OK] {sid}: {n} 根K线 → {os.path.join(args.out, sid + '.json')}")
        return 0 if n else 1
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
