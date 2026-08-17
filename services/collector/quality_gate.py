# -*- coding: utf-8 -*-
"""V0.3 数据质量门禁：生成可机器判定的每日质量报告。"""
import argparse
import datetime as dt
import json
from pathlib import Path


DEFAULTS = {
    "min_sector_coverage": 0.90,
    "required_facts": ["meta", "limitup", "membership", "strategy", "events", "pool"],
}


def _read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _check(name, status, actual, expected, message):
    return {"name": name, "status": status, "actual": actual, "expected": expected, "message": message}


def evaluate_quality(data_root, date_str, config=None):
    root = Path(data_root)
    cfg = {**DEFAULTS, **(config or {})}
    checks = []
    stocks = _read(root / "normalized/stocks.json", {}) or {}
    active = [v for v in stocks.values() if v.get("status") not in ("source_missing", "invalid_instrument")]
    total = len(active)
    with_sectors = sum(bool(v.get("current", {}).get("sectors")) for v in active)
    coverage = with_sectors / total if total else 0.0
    checks.append(_check("master_sector_coverage",
                         "pass" if coverage >= cfg["min_sector_coverage"] else "fail",
                         round(coverage, 6), cfg["min_sector_coverage"], "主数据股票板块归属覆盖率"))
    industry_coverage = sum(bool(v.get("industry")) for v in active) / total if total else 0.0
    list_date_coverage = sum(bool(v.get("list_date")) for v in active) / total if total else 0.0
    checks.append(_check("industry_coverage", "pass" if industry_coverage >= 0.9 else "warn",
                         round(industry_coverage, 6), 0.9, "行业字段覆盖率"))
    checks.append(_check("list_date_coverage", "pass" if list_date_coverage >= 0.9 else "warn",
                         round(list_date_coverage, 6), 0.9, "上市日期覆盖率"))

    manifest = _read(root / "manifest.json", {}) or {}
    freshness = manifest.get("themes", {}).get("freshness", "missing")
    checks.append(_check("theme_freshness", "pass" if freshness == "fresh" else "warn",
                         freshness, "fresh", "题材源新鲜度"))

    missing, wrong_date = [], []
    for name in cfg["required_facts"]:
        path = root / "facts" / date_str / f"{name}.json"
        doc = _read(path)
        if doc is None:
            missing.append(name)
        elif isinstance(doc, dict) and doc.get("data_date") not in (None, date_str):
            wrong_date.append(name)
    facts_ok = not missing and not wrong_date
    checks.append(_check("required_facts", "pass" if facts_ok else "fail",
                         {"missing": missing, "wrong_date": wrong_date}, "all present", "必需日事实完整性"))

    web = _read(root / "web" / f"day_{date_str}.json")
    web_ok = isinstance(web, dict) and (web.get("data_date") or web.get("date")) == date_str
    checks.append(_check("web_day_view", "pass" if web_ok else "fail",
                         "valid" if web_ok else "missing_or_wrong_date", date_str, "Web 当日聚合视图"))

    statuses = {x["status"] for x in checks}
    status = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    return {"data_date": date_str, "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": status, "checks": checks}


def write_report(report, runs_dir):
    path = Path(runs_dir) / f"quality_{report['data_date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def promote_if_acceptable(report, web_dir):
    """仅在没有 fail 时发布 latest；warn 仍发布但保留质量报告供页面提示。"""
    if report.get("status") == "fail":
        return None
    from .archive_job import promote_day_view
    return Path(promote_day_view(report["data_date"], str(web_dir)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="V0.3 每日数据质量门禁")
    ap.add_argument("--date", required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--config", default="config/quality.json")
    ap.add_argument("--allow-warn", action="store_true", help="warn 返回成功；fail 始终返回失败")
    ap.add_argument("--promote", action="store_true", help="门禁无 fail 时原子更新 day_latest.json")
    args = ap.parse_args(argv)
    cfg = _read(args.config, {}) if Path(args.config).exists() else {}
    report = evaluate_quality(args.data, args.date, cfg)
    path = write_report(report, Path(args.data) / "runs")
    print(f"[{report['status'].upper()}] {args.date} quality -> {path}")
    for item in report["checks"]:
        print(f"  {item['status'].upper():4} {item['name']}: {item['actual']}")
    if args.promote:
        promoted = promote_if_acceptable(report, Path(args.data) / "web")
        print(f"[{'PUBLISHED' if promoted else 'WITHHELD'}] day_latest.json")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
