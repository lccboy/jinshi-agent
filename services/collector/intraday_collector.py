# -*- coding: utf-8 -*-
"""盘中快照采集器（V0.3 任务 3，盘中实时链路）

依据 `docs/DATA_MODEL.md` §5：
- 快照格式：`data/intraday/<日期>/snapshots.ndjson`，每行一个快照（追加写入，**只增不改**）
- 阶段节奏：竞价 09:15–09:30 每 3s（auction）、开盘 09:30–10:30 每 3s（open）、10:31–15:00 每 30s（tail）
- `meta.json`：当日采集节奏、起止状态
- 行情段（stocks）走腾讯全市场批量（quote_collector）；结构化段（板块/题材/连板）走 KPL（子集）
"""
import argparse
import datetime
import json
import os
import time

from .quote_collector import fetch_quotes

# 采集节奏（DATA_MODEL §5.1）
CADENCE = [
    ("09:15", "09:30", 3),   # 竞价 每 3 秒
    ("09:30", "10:30", 3),   # 开盘 每 3 秒
    ("10:31", "15:00", 30),  # 尾盘 每 30 秒
]
PHASES = {"auction": ("09:15", "09:30"), "open": ("09:30", "10:30"), "tail": ("10:31", "15:00")}


def cadence_for_time(hhmmss):
    """交易时钟 → (阶段, 秒间隔)；闭市/午休不发网络请求。"""
    seconds = _interval_seconds(hhmmss)
    if 9 * 3600 + 15 * 60 <= seconds < 9 * 3600 + 30 * 60:
        return "auction", 3
    if 9 * 3600 + 30 * 60 <= seconds < 10 * 3600 + 31 * 60:
        return "open", 3
    if 10 * 3600 + 31 * 60 <= seconds <= 11 * 3600 + 30 * 60:
        return "tail", 30
    if 11 * 3600 + 30 * 60 < seconds < 13 * 3600:
        return "lunch", None
    if 13 * 3600 <= seconds <= 15 * 3600:
        return "tail", 30
    return "closed", None


def phase_for_time(hhmmss):
    """时间 'HH:MM:SS' → 阶段（auction/open/tail）。"""
    t = str(hhmmss).replace(":", "")
    t = int(t[:4])  # HHMM
    if t < 930:
        return "auction"
    if t < 1031:
        return "open"
    return "tail"


def build_snapshot(ts, phase, indexes=None, sectors=None, themes=None,
                   ladder=None, abnormal=None, stocks=None):
    """组装 §5.2 快照结构。"""
    snap = {"ts": ts, "phase": phase}
    if indexes is not None:
        snap["indexes"] = indexes
    if sectors is not None:
        snap["sectors"] = sectors
    if themes is not None:
        snap["themes"] = themes
    if ladder is not None:
        snap["ladder"] = ladder
    if abnormal is not None:
        snap["abnormal"] = abnormal
    if stocks is not None:
        snap["stocks"] = stocks
    return snap


def append_snapshot(day_dir, snapshot):
    """追加一行快照到 `day_dir/snapshots.ndjson`（只增不改；目录自动创建）。"""
    os.makedirs(day_dir, exist_ok=True)
    line = json.dumps(snapshot, ensure_ascii=False)
    with open(os.path.join(day_dir, "snapshots.ndjson"), "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return os.path.join(day_dir, "snapshots.ndjson")


def read_snapshots(day_dir):
    """读回快照列表（末行容错：坏行跳过）。"""
    path = os.path.join(day_dir, "snapshots.ndjson")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_meta(day_dir, date_str, cadence="3s", status="running", extra=None):
    """写 `meta.json`（当日采集节奏、起止状态）。"""
    os.makedirs(day_dir, exist_ok=True)
    meta = {"date": date_str, "cadence": cadence, "status": status,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if extra:
        meta.update(extra)
    path = os.path.join(day_dir, "meta.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return path


def _interval_seconds(hhmmss):
    """'HH:MM:SS' → 当日秒数。"""
    h, m, s = (int(x) for x in str(hhmmss).split(":"))
    return h * 3600 + m * 60 + s


def collect_once(codes, watch_codes=None, phase="open", include_quotes=False):
    """单次采集：腾讯全市场行情 → 快照（结构化段预留 KPL 挂点）。

    codes: 全市场/子集股票代码列表；watch_codes: 盘中关注池（涨停池/候选池成分）。
    返回 build_snapshot 快照（含 stocks 行情段）。
    """
    if not codes:
        raise RuntimeError("股票池为空，拒绝启动腾讯实时行情采集")
    quotes = fetch_quotes(codes)
    if not quotes:
        raise RuntimeError("腾讯行情返回空，拒绝写入伪实时快照")
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stocks = {sid: {"price": q["price"], "change": q["change"],
                    "change_pct": q["change_pct"], "volRatio": q["vol_ratio"],
                    "limit_up": q["limit_up"], "preclose": q["preclose"]}
              for sid, q in quotes.items()}
    snapshot = build_snapshot(ts, phase, stocks=stocks)
    return (snapshot, quotes) if include_quotes else snapshot


def make_realtime_handler(facts_dir, date_str, kline_dir, stocks_path,
                          scan_fn=None):
    """构造每帧处理器：全市场涨停检测 + 昨日冻结模型命中。"""
    from .realtime_engine import load_frozen_context, scan_snapshot
    frozen, source_date = load_frozen_context(facts_dir, date_str, kline_dir)
    instruments = {}
    if stocks_path and os.path.isfile(stocks_path):
        with open(stocks_path, encoding="utf-8") as fh:
            instruments = json.load(fh)
    scanner = scan_fn or scan_snapshot
    previous = {}

    def on_quotes(quotes):
        scanner(facts_dir, date_str, frozen, quotes, previous, instruments=instruments)
        previous.clear()
        previous.update(quotes)

    return on_quotes, frozen, source_date


def run_loop(intraday_root, date_str, codes, interval=3, phase="open", max_snapshots=0, dry=False):
    """采集循环：每 interval 秒 append 一次快照；max_snapshots 上限（0=无限）。"""
    day_dir = os.path.join(intraday_root, date_str)
    os.makedirs(day_dir, exist_ok=True)
    write_meta(day_dir, date_str, cadence=f"{interval}s", status="running")
    count = 0
    while not max_snapshots or count < max_snapshots:
        snap = collect_once(codes, phase=phase)
        append_snapshot(day_dir, snap)
        count += 1
        if max_snapshots and count >= max_snapshots:
            break
        time.sleep(interval)
    write_meta(day_dir, date_str, cadence=f"{interval}s", status="done")
    return count


def run_market_session(intraday_root, date_str, codes, now_fn=datetime.datetime.now,
                       sleep_fn=time.sleep, collect_fn=collect_once, on_quotes=None,
                       max_consecutive_errors=10):
    """按真实交易时钟无人值守采集；午休暂停，15:00 后自动结束，网络异常退避。"""
    day_dir = os.path.join(intraday_root, date_str)
    now = now_fn()
    write_meta(day_dir, date_str, cadence="dynamic", status="running",
               extra={"started_at": now.strftime("%Y-%m-%d %H:%M:%S"), "errors": 0})
    count = errors = consecutive_errors = 0
    while True:
        hhmmss = now.strftime("%H:%M:%S")
        phase, interval = cadence_for_time(hhmmss)
        seconds = _interval_seconds(hhmmss)
        if seconds > 15 * 3600:
            break
        if interval is None:
            sleep_fn(30 if phase == "lunch" else 1)
            now = now_fn()
            continue
        try:
            result = collect_fn(codes, phase=phase)
            if isinstance(result, tuple):
                snap, quotes = result
                if on_quotes:
                    on_quotes(quotes)
            else:
                snap = result
            append_snapshot(day_dir, snap)
            count += 1
            consecutive_errors = 0
            sleep_fn(interval)
        except Exception as exc:
            errors += 1
            consecutive_errors += 1
            write_meta(day_dir, date_str, cadence="dynamic", status="degraded",
                       extra={"snapshots": count, "errors": errors, "last_error": f"{type(exc).__name__}: {exc}"})
            if consecutive_errors >= max_consecutive_errors:
                write_meta(day_dir, date_str, cadence="dynamic", status="failed",
                           extra={"snapshots": count, "errors": errors, "last_error": str(exc)})
                raise
            sleep_fn(min(60, 2 ** consecutive_errors))
        now = now_fn()
    write_meta(day_dir, date_str, cadence="dynamic", status="done",
               extra={"snapshots": count, "errors": errors, "finished_at": now.strftime("%Y-%m-%d %H:%M:%S")})
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(description="盘中快照采集（intraday_collector）")
    ap.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"), help="数据日期")
    ap.add_argument("--intraday", default="data/intraday", help="盘中目录（默认 data/intraday）")
    ap.add_argument("--codes", help="逗号分隔代码（缺省读 --universe-file）")
    ap.add_argument("--universe-file", help="每行一个代码的文件")
    ap.add_argument("--once", action="store_true", help="只采一次（调试）")
    ap.add_argument("--interval", type=int, default=3, help="采集间隔秒（默认 3）")
    ap.add_argument("--max-snapshots", type=int, default=0, help="快照上限（0=无限）")
    ap.add_argument("--realtime", action="store_true", help="每帧同步运行事件引擎并维护预警池")
    ap.add_argument("--facts", default="data/facts", help="实时事件 facts 根目录")
    ap.add_argument("--kline", default="data/kline", help="日K目录（冻结上下文）")
    args = ap.parse_args(argv)

    codes = []
    if args.universe_file:
        with open(args.universe_file, encoding="utf-8") as fh:
            codes = [ln.strip() for ln in fh if ln.strip()]
    elif args.codes:
        codes = args.codes.split(",")

    if args.once:
        snap = collect_once(codes)
        day_dir = os.path.join(args.intraday, args.date)
        path = append_snapshot(day_dir, snap)
        print(f"[OK] 单次快照 → {path}（{len(snap.get('stocks', {}))} 只）")
        return 0

    if args.max_snapshots:
        n = run_loop(args.intraday, args.date, codes, interval=args.interval,
                     max_snapshots=args.max_snapshots)
    else:
        collect_fn, on_quotes = collect_once, None
        if args.realtime:
            stocks_path = os.path.join(os.path.dirname(args.facts), "normalized", "stocks.json")
            on_quotes, frozen, source_date = make_realtime_handler(
                args.facts, args.date, args.kline, stocks_path)

            def collect_fn(codes, phase="open"):
                return collect_once(codes, phase=phase, include_quotes=True)

            print(f"[READY] 腾讯全市场涨停检测；模型冻结日={source_date or '无'} 股票={len(frozen)}")
        n = run_market_session(args.intraday, args.date, codes, collect_fn=collect_fn, on_quotes=on_quotes)
    print(f"[OK] 采集完成 {n} 个快照 → {os.path.join(args.intraday, args.date)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
