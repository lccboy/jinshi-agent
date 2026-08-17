# -*- coding: utf-8 -*-
"""交易日收盘全量冻结：KPL 板块/子板块/成分股 + 涨停原因 facts。"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path

from .normalize import normalize_limitup_multi


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_close_snapshot(date_str, output_dir, min_sectors=80):
    root = Path(output_dir)
    summary = _read(root / f"kpl_{date_str}.json")
    stocks = _read(root / f"kpl_{date_str}_stocks.json")
    sectors = summary.get("sectors", []) or []
    plate_ids = set((stocks.get("stocks", stocks) or {}).keys())
    main_ids = {str(row.get("id", "")) for row in sectors}
    report = {"data_date": date_str, "sector_count": len(sectors),
              "main_plate_count": len(main_ids.intersection(plate_ids)),
              "archived": bool(summary.get("archived"))}
    report["complete"] = (report["archived"] and report["sector_count"] >= min_sectors and
                          report["main_plate_count"] >= min_sectors)
    if not report["complete"]:
        raise RuntimeError(f"KPL 收盘快照不完整: {report}")
    return report


def build_limitup_fact(source):
    reasons = source.get("reasons", source) if isinstance(source, dict) else {}
    normalized_source = {"reasons": {}}
    for code, entry in reasons.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("sources"):
            normalized_source["reasons"][code] = entry
            continue
        kpl = dict(entry)
        kpl["source"] = "kpl"
        normalized_source["reasons"][code] = {
            "first_time": entry.get("first_time", ""), "seal_amount": entry.get("seal_amount", 0),
            "sources": {"kpl": kpl},
        }
    return normalize_limitup_multi(normalized_source)


def write_limitup_fact_once(date_str, limitup, data_root):
    path = Path(data_root) / "facts" / date_str / "limitup.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(limitup, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def load_collector(path):
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"KPL collector not found: {source}")
    if str(source.parent) not in sys.path:
        sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("jinshi_kpl_close_collector", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_close_archive(date_str, collector_path, output_dir, data_root, multi_reason=True):
    if date_str != dt.date.today().isoformat():
        raise ValueError("全量收盘采集只允许归档当天；历史日期请使用历史回补")
    module = load_collector(collector_path)
    module.OUTPUT_DIR = str(Path(output_dir).resolve())
    Path(module.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    module.collect_snapshot(full=True)
    if multi_reason and hasattr(module, "launch_multi_reason_supplement"):
        module.launch_multi_reason_supplement(date_str)
    report = validate_close_snapshot(date_str, output_dir)
    multi = Path(output_dir) / f"kpl_{date_str}_limitup_multi.json"
    single = Path(output_dir) / f"kpl_{date_str}_limitup.json"
    reason_path = multi if multi.exists() else single
    if not reason_path.exists():
        raise RuntimeError("KPL 收盘涨停原因文件缺失")
    limitup = build_limitup_fact(_read(reason_path))
    fact_path = write_limitup_fact_once(date_str, limitup, data_root)
    report.update({"limitup_count": len(limitup), "limitup_fact": str(fact_path),
                   "reason_source_file": str(reason_path)})
    run_path = Path(data_root) / "runs" / f"close_archive_{date_str}.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="15:30 KPL 题材与板块全量收盘归档")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--collector", required=True)
    ap.add_argument("--kpl-output", required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--no-multi-reason", action="store_true")
    args = ap.parse_args(argv)
    report = run_close_archive(args.date, args.collector, args.kpl_output, args.data,
                               multi_reason=not args.no_multi_reason)
    print(f"[OK] {args.date} 收盘全量归档源已冻结: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
