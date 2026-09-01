# -*- coding: utf-8 -*-
"""由只增不改的盘中累计量额快照生成自然分钟基线。"""
import argparse
from collections import Counter
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import struct


SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
LC1_RECORD = struct.Struct("<HHfffffII")
STOCK_ID_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")


def _parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI_TZ)
        except ValueError:
            pass
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed.replace(tzinfo=SHANGHAI_TZ) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _is_regular_session(value):
    clock = value.time()
    return (dt.time(9, 30) <= clock <= dt.time(11, 30) or
            dt.time(13, 0) <= clock <= dt.time(15, 0))


def _minute_end_label(value):
    # 09:30:00–09:30:59 的自然分钟 K 线结束于 09:31；边界末帧仍归前一分钟。
    if value.time() in (dt.time(11, 30), dt.time(15, 0)):
        return value.strftime("%H:%M")
    return (value + dt.timedelta(minutes=1)).strftime("%H:%M")


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def build_minute_baseline(snapshots, data_date, *, min_stock_minutes=200,
                          expected_minutes=240, min_coverage=0.95,
                          max_missing_minutes=5):
    """累计量额按自然分钟取末帧并差分；异常股票整只失效，绝不以零补缺。"""
    timelines = {}
    seen = set()
    invalid = set()
    latest_source_time = None

    for snapshot in snapshots:
        for stock_id, quote in (snapshot.get("stocks") or {}).items():
            seen.add(stock_id)
            volume = _number(quote.get("volume"))
            amount = _number(quote.get("amount"))
            source_time = _parse_time(quote.get("source_ts"))
            if volume is None or amount is None or source_time is None:
                invalid.add(stock_id)
                continue
            if source_time.date().isoformat() != data_date:
                invalid.add(stock_id)
                continue
            timelines.setdefault(stock_id, []).append((source_time, volume, amount))
            latest_source_time = max(latest_source_time, source_time) if latest_source_time else source_time

    stocks = {}
    observed_minutes = set()
    for stock_id, rows in timelines.items():
        if stock_id in invalid:
            continue
        # 输入本应按追加顺序单调；先检查，再做分钟聚合，不能排序掩盖源时间倒退。
        previous_time = None
        previous_volume = previous_amount = None
        for source_time, volume, amount in rows:
            if (previous_time is not None and
                    (source_time < previous_time or volume < previous_volume or amount < previous_amount)):
                invalid.add(stock_id)
                break
            previous_time, previous_volume, previous_amount = source_time, volume, amount
        if stock_id in invalid:
            continue

        preopen = [row for row in rows if row[0].time() < dt.time(9, 30)]
        if not preopen:
            invalid.add(stock_id)
            continue
        base_time, base_volume, base_amount = preopen[-1]
        by_minute = {}
        for source_time, volume, amount in rows:
            if _is_regular_session(source_time):
                by_minute[_minute_end_label(source_time)] = (source_time, volume, amount)
        if len(by_minute) < min_stock_minutes:
            invalid.add(stock_id)
            continue

        max_volume = max_amount = -1.0
        max_volume_time = max_amount_time = None
        prior_volume, prior_amount = base_volume, base_amount
        for label, (_, volume, amount) in by_minute.items():
            delta_volume, delta_amount = volume - prior_volume, amount - prior_amount
            if delta_volume < 0 or delta_amount < 0:
                invalid.add(stock_id)
                break
            if delta_volume > max_volume:
                max_volume, max_volume_time = delta_volume, label
            if delta_amount > max_amount:
                max_amount, max_amount_time = delta_amount, label
            prior_volume, prior_amount = volume, amount
        if stock_id in invalid:
            continue

        observed_minutes.update(by_minute)
        last = rows[-1]
        stocks[stock_id] = {
            "auction_volume": int(base_volume) if base_volume.is_integer() else base_volume,
            "auction_amount": int(base_amount) if base_amount.is_integer() else base_amount,
            "auction_source_ts": base_time.isoformat(timespec="seconds"),
            "max_1m_volume": int(max_volume) if max_volume.is_integer() else max_volume,
            "max_1m_volume_time": max_volume_time,
            "max_1m_amount": int(max_amount) if max_amount.is_integer() else max_amount,
            "max_1m_amount_time": max_amount_time,
            "day_volume": int(last[1]) if last[1].is_integer() else last[1],
            "day_amount": int(last[2]) if last[2].is_integer() else last[2],
        }

    total = len(seen)
    coverage = len(stocks) / total if total else 0.0
    missing_minutes = max(0, expected_minutes - len(observed_minutes))
    passed = bool(total and coverage >= min_coverage and missing_minutes <= max_missing_minutes)
    return {
        "data_date": data_date,
        "source": "tencent_intraday_snapshots",
        "source_updated_at": latest_source_time.isoformat(timespec="seconds") if latest_source_time else None,
        "quality": {
            "status": "pass" if passed else "fail",
            "coverage": round(coverage, 6),
            "missing_minutes": missing_minutes,
            "valid_stocks": len(stocks),
            "invalid_stocks": total - len(stocks),
        },
        "stocks": stocks,
    }


def read_snapshots(path):
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_minute_baseline_once(document, data_root):
    path = Path(data_root) / "facts" / document["data_date"] / "minute_baseline.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def generate_minute_baseline(data_root, data_date, **kwargs):
    root = Path(data_root)
    candidates = [root / "intraday" / data_date / "snapshots.ndjson",
                  root / "archive" / data_date / "snapshots.ndjson"]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError(f"盘中快照缺失: {data_date}")
    document = build_minute_baseline(read_snapshots(source), data_date, **kwargs)
    return document, write_minute_baseline_once(document, root)


def _decode_lc1_date(value):
    year = int(value) // 2048 + 2004
    month_day = int(value) % 2048
    month, day = month_day // 100, month_day % 100
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _lc1_rows(path, max_records=600):
    """只读 LC1 尾部若干日；每条为通达信标准 32 字节分钟记录。"""
    path = Path(path)
    size = path.stat().st_size
    if size % LC1_RECORD.size:
        return []
    with path.open("rb") as handle:
        handle.seek(max(0, size - LC1_RECORD.size * int(max_records)))
        raw = handle.read()
    rows = []
    for offset in range(0, len(raw), LC1_RECORD.size):
        encoded_date, minute, op, high, low, close, amount, volume, _ = \
            LC1_RECORD.unpack_from(raw, offset)
        trade_date = _decode_lc1_date(encoded_date)
        if trade_date is None:
            continue
        rows.append({"date": trade_date, "minute": int(minute), "open": float(op),
                     "high": float(high), "low": float(low), "close": float(close),
                     "amount": float(amount), "volume": int(volume)})
    return rows


def _lc1_path(vipdoc, stock_id):
    matched = STOCK_ID_RE.fullmatch(str(stock_id or ""))
    if not matched:
        return None
    market, code = matched.groups()
    market = market.lower()
    return Path(vipdoc) / market / "minline" / f"{market}{code}.lc1"


def build_vipdoc_lc1_baseline(vipdoc, target_date, stock_ids, *,
                               expected_minutes=240, min_coverage=0.95):
    """从会员本地 LC1 生成目标日前最近完整交易日基线。

    LC1 本身已经是自然分钟增量，不得再按累计量差分。股票集合必须由调用方
    显式传入，以免指数、基金和退市遗留文件混入覆盖率。
    """
    target = dt.date.fromisoformat(str(target_date))
    universe = list(dict.fromkeys(str(sid) for sid in (stock_ids or [])
                                  if STOCK_ID_RE.fullmatch(str(sid))))
    rows_by_stock = {}
    latest_complete_dates = Counter()
    latest_mtime = None
    for stock_id in universe:
        path = _lc1_path(vipdoc, stock_id)
        if path is None or not path.is_file():
            continue
        modified = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=SHANGHAI_TZ)
        latest_mtime = max(latest_mtime, modified) if latest_mtime else modified
        by_date = {}
        for row in _lc1_rows(path):
            if row["date"] < target:
                by_date.setdefault(row["date"], []).append(row)
        rows_by_stock[stock_id] = by_date
        complete = [day for day, rows in by_date.items()
                    if len(rows) == int(expected_minutes) and
                    len({row["minute"] for row in rows}) == int(expected_minutes)]
        if complete:
            latest_complete_dates[max(complete)] += 1

    source_date = None
    if latest_complete_dates:
        # 以覆盖股票数最多的完整日期为准；同覆盖数取最近日期。
        source_date = max(latest_complete_dates, key=lambda day: (latest_complete_dates[day], day))

    stocks = {}
    observed_minutes = set()
    if source_date:
        for stock_id in universe:
            rows = (rows_by_stock.get(stock_id) or {}).get(source_date) or []
            minutes = {row["minute"] for row in rows}
            if len(rows) != int(expected_minutes) or len(minutes) != int(expected_minutes):
                continue
            if int(expected_minutes) == 240 and (min(minutes) != 9 * 60 + 31 or max(minutes) != 15 * 60):
                continue
            max_volume = max(rows, key=lambda row: row["volume"])
            max_amount = max(rows, key=lambda row: row["amount"])
            stocks[stock_id] = {
                "max_1m_volume": max_volume["volume"],
                "max_1m_volume_time": f'{max_volume["minute"] // 60:02d}:{max_volume["minute"] % 60:02d}',
                "max_1m_amount": max_amount["amount"],
                "max_1m_amount_time": f'{max_amount["minute"] // 60:02d}:{max_amount["minute"] % 60:02d}',
                "day_volume": sum(row["volume"] for row in rows),
                "day_amount": sum(row["amount"] for row in rows),
                "bar_count": len(rows),
            }
            observed_minutes.update(minutes)

    total = len(universe)
    coverage = len(stocks) / total if total else 0.0
    missing_minutes = max(0, int(expected_minutes) - len(observed_minutes))
    passed = bool(source_date and total and coverage >= float(min_coverage) and not missing_minutes)
    return {
        "data_date": source_date.isoformat() if source_date else None,
        "source": "tdx_vipdoc_lc1",
        "source_updated_at": latest_mtime.isoformat(timespec="seconds") if latest_mtime else None,
        "private": True,
        "quality": {
            "status": "pass" if passed else "fail",
            "coverage": round(coverage, 6),
            "missing_minutes": missing_minutes,
            "valid_stocks": len(stocks),
            "invalid_stocks": total - len(stocks),
        },
        "stocks": stocks,
    }


def build_vipdoc_lc1_history(vipdoc, target_date, stock_id, *, days=2,
                             expected_minutes=240):
    """读取单只股票目标日前最近若干个完整 LC1 交易日，供本地三日对比。"""
    target = dt.date.fromisoformat(str(target_date))
    path = _lc1_path(vipdoc, stock_id)
    if path is None or not path.is_file():
        return []
    by_date = {}
    max_records = max(600, (int(days) + 3) * int(expected_minutes))
    for row in _lc1_rows(path, max_records=max_records):
        if row["date"] < target:
            by_date.setdefault(row["date"], []).append(row)
    result = []
    for day in sorted(by_date, reverse=True):
        rows = sorted(by_date[day], key=lambda item: item["minute"])
        minutes = {row["minute"] for row in rows}
        if len(rows) != int(expected_minutes) or len(minutes) != int(expected_minutes):
            continue
        if int(expected_minutes) == 240 and (min(minutes) != 9 * 60 + 31 or max(minutes) != 15 * 60):
            continue
        result.append({"date": day.isoformat(), "series": [{
            "minute": f'{row["minute"] // 60:02d}:{row["minute"] % 60:02d}',
            "volume": row["volume"], "amount": row["amount"], "price": row["close"],
        } for row in rows]})
        if len(result) >= int(days):
            break
    return result


def generate_vipdoc_lc1_baseline(vipdoc, target_date, stock_ids, member_root, **kwargs):
    document = build_vipdoc_lc1_baseline(vipdoc, target_date, stock_ids, **kwargs)
    if not document.get("data_date"):
        raise ValueError(f"{target_date} 之前没有完整 LC1 分钟基线")
    return document, write_minute_baseline_once(document, Path(member_root))


def archive_vipdoc_lc1_day(vipdoc, data_date, stock_ids, member_root, *,
                            expected_minutes=240, min_coverage=0.95):
    """把指定交易日 LC1 写入会员独立归档；完成归档只读且可校验。"""
    day = dt.date.fromisoformat(str(data_date))
    universe = list(dict.fromkeys(str(sid) for sid in (stock_ids or [])
                                  if STOCK_ID_RE.fullmatch(str(sid))))
    records, stocks, observed = [], {}, set()
    for stock_id in universe:
        path = _lc1_path(vipdoc, stock_id)
        if path is None or not path.is_file():
            continue
        rows = [row for row in _lc1_rows(path, max_records=max(600, expected_minutes * 3))
                if row["date"] == day]
        minutes = {row["minute"] for row in rows}
        if len(rows) != int(expected_minutes) or len(minutes) != int(expected_minutes):
            continue
        if int(expected_minutes) == 240 and (min(minutes) != 571 or max(minutes) != 900):
            continue
        rows.sort(key=lambda row: row["minute"])
        observed.update(minutes)
        max_volume = max(rows, key=lambda row: row["volume"])
        max_amount = max(rows, key=lambda row: row["amount"])
        stocks[stock_id] = {
            "max_1m_volume": max_volume["volume"],
            "max_1m_volume_time": f'{max_volume["minute"] // 60:02d}:{max_volume["minute"] % 60:02d}',
            "max_1m_amount": max_amount["amount"],
            "max_1m_amount_time": f'{max_amount["minute"] // 60:02d}:{max_amount["minute"] % 60:02d}',
            "day_volume": sum(row["volume"] for row in rows),
            "day_amount": sum(row["amount"] for row in rows), "bar_count": len(rows),
        }
        records.extend({"stock_id": stock_id,
                        "minute": f'{row["minute"] // 60:02d}:{row["minute"] % 60:02d}',
                        "volume": row["volume"], "amount": row["amount"],
                        "price": row["close"]} for row in rows)
    coverage = len(stocks) / len(universe) if universe else 0.0
    missing = max(0, int(expected_minutes) - len(observed))
    status = "complete" if universe and coverage >= float(min_coverage) and not missing else "incomplete"
    raw = b"".join((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                   for row in records)
    digest = hashlib.sha256(raw).hexdigest()
    archive_dir = Path(member_root) / "archive" / day.isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_path = archive_dir / "minute_volume.ndjson.gz"
    manifest_path = archive_dir / "minute_manifest.json"
    if manifest_path.is_file():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("status") == "complete":
            if old.get("sha256") != digest:
                quarantine = archive_dir / f"minute_volume.divergent-{digest[:12]}.ndjson.gz"
                with quarantine.open("wb") as raw_handle:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle:
                        handle.write(raw)
                return old, manifest_path
            return old, manifest_path
    temp = data_path.with_suffix(data_path.suffix + ".tmp")
    with temp.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle:
            handle.write(raw)
    os.replace(temp, data_path)
    events_path = archive_dir / "minute_events.ndjson.gz"
    if not events_path.exists():
        event_temp = events_path.with_suffix(events_path.suffix + ".tmp")
        with event_temp.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0):
                pass
        os.replace(event_temp, events_path)
    baseline = {"data_date": day.isoformat(), "source": "tdx_vipdoc_lc1", "private": True,
                "quality": {"status": "pass" if status == "complete" else "fail",
                            "coverage": round(coverage, 6), "missing_minutes": missing,
                            "valid_stocks": len(stocks), "invalid_stocks": len(universe) - len(stocks)},
                "stocks": stocks}
    write_minute_baseline_once(baseline, Path(member_root))
    manifest = {"schema_version": 1, "data_date": day.isoformat(), "source": "tdx_vipdoc_lc1",
                "private": True, "status": status, "expected_minutes": int(expected_minutes),
                "valid_stocks": len(stocks), "universe_stocks": len(universe),
                "coverage": round(coverage, 6), "record_count": len(records),
                "volume_unit": "tdx_lc1_volume", "sha256": digest,
                "file": data_path.name,
                "generated_at": dt.datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")}
    temp_manifest = manifest_path.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_manifest, manifest_path)
    return manifest, manifest_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成自然分钟成交量/额基线")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data", default="data")
    args = parser.parse_args(argv)
    document, path = generate_minute_baseline(args.data, args.date)
    print(f"[{document['quality']['status'].upper()}] {args.date} minute baseline -> {path}")
    return 0 if document["quality"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
