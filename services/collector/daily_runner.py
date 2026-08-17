# -*- coding: utf-8 -*-
"""V0.3 每日总控：交易日判断、阶段幂等、失败重试与运行清单。"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .normalize import is_equity_code


STAGES = ("premarket", "intraday", "postmarket", "archive")


def is_trading_day(day, calendar_path=None):
    """显式日历优先；缺失时仅以周一至周五作为保守降级。"""
    if isinstance(day, str):
        day = dt.date.fromisoformat(day)
    if calendar_path and Path(calendar_path).is_file():
        data = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
        value = day.isoformat()
        if value in set(data.get("trading_days", [])):
            return True
        if value in set(data.get("holidays", [])):
            return False
    return day.weekday() < 5


class DailyRunStore:
    def __init__(self, path="data/runs/daily_runs.json"):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {"version": 1, "runs": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="daily_runs_", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def latest_status(self, date_str, stage):
        attempts = self.load().get("runs", {}).get(date_str, {}).get(stage, {}).get("attempts", [])
        return attempts[-1].get("status") if attempts else None

    def append(self, date_str, stage, attempt):
        data = self.load()
        bucket = data.setdefault("runs", {}).setdefault(date_str, {}).setdefault(stage, {"attempts": []})
        bucket["attempts"].append(attempt)
        bucket["status"] = attempt["status"]
        bucket["updated_at"] = attempt["finished_at"]
        self.save(data)


def _now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run_stage(store, date_str, stage, action, force=False):
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if not force and store.latest_status(date_str, stage) == "success":
        return {"date": date_str, "stage": stage, "status": "skipped", "reason": "already_successful"}
    started = _now()
    try:
        detail = action() or {}
        attempt = {"started_at": started, "finished_at": _now(), "status": "success", "detail": detail}
    except Exception as exc:  # 阶段失败必须落清单，下一次调用可重试
        attempt = {"started_at": started, "finished_at": _now(), "status": "failed",
                   "error": f"{type(exc).__name__}: {exc}"}
    store.append(date_str, stage, attempt)
    return {"date": date_str, "stage": stage, **attempt}


def run_command(command, cwd=None, timeout=3600, dry_run=False):
    """执行阶段子命令并返回可序列化结果；非零退出触发阶段失败。"""
    if dry_run:
        return {"command": command, "dry_run": True}
    proc = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout)
    detail = {"command": command, "returncode": proc.returncode,
              "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
    if proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-1000:]}")
    return detail


def write_active_universe(stocks_path, out_path):
    stocks = json.loads(Path(stocks_path).read_text(encoding="utf-8"))
    codes = sorted({str(rec.get("code") or sid[2:]).zfill(6) for sid, rec in stocks.items()
                    if rec.get("status") not in ("source_missing", "invalid_instrument")
                    and is_equity_code(rec.get("code") or sid[2:])})
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(code + "\n" for code in codes), encoding="utf-8")
    return len(codes)


def load_runtime(path="config/runtime.json"):
    data = {}
    if Path(path).is_file():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.setdefault("python", sys.executable)
    data.setdefault("data_root", "data")
    data.setdefault("vipdoc", "")
    data.setdefault("kpl_output", r"H:\projects\kpl\output")
    data.setdefault("kpl_collector", r"H:\projects\kpl\collect_live.py")
    return data


def previous_weekday(date_str):
    day = dt.date.fromisoformat(date_str) - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day.isoformat()


def build_stage_commands(date_str, runtime):
    py = runtime.get("python") or sys.executable
    data = runtime.get("data_root", "data")
    norm = os.path.join(data, "normalized")
    runs = os.path.join(data, "runs")
    universe = os.path.join(runs, "universe_active.txt")
    vipdoc = runtime.get("vipdoc", "")
    kpl_stocks = os.path.join(runtime.get("kpl_output", ""), f"kpl_{date_str}_stocks.json")
    master_date = previous_weekday(date_str)
    membership = [py, "-m", "services.collector.membership_collector", "--date", date_str,
                  "--normalized", norm, "--out", data]
    if os.path.isfile(kpl_stocks):
        membership += ["--kpl-stocks", kpl_stocks]
    return {
        "premarket": [
            [py, "-m", "services.collector.master_collector", "--incr", "--date", master_date,
             "--out", norm, "--workers", "10", "--verify"],
            [py, "-m", "services.collector.theme_collector", "--out", norm],
            [py, "-m", "services.collector.master_collector", "--backfill-vipdoc", vipdoc,
             "--out", norm, "--verify"],
        ],
        "intraday": [[py, "-m", "services.collector.intraday_collector", "--date", date_str,
                      "--intraday", os.path.join(data, "intraday"), "--universe-file", universe,
                      "--realtime", "--facts", os.path.join(data, "facts"),
                      "--kline", os.path.join(data, "kline")]],
        "postmarket": [
            [py, "-m", "services.collector.kline_sync", "--vipdoc", vipdoc,
             "--stocks-json", os.path.join(norm, "stocks.json"), "--out", os.path.join(data, "kline")],
            [py, "-m", "services.collector.factor_collector", "--date", date_str, "--out", data],
            membership,
            [py, "-m", "services.collector.strategy_engine", "--date", date_str,
             "--kline", os.path.join(data, "kline"), "--out", data, "--config", "config/strategy.json"],
        ],
        "archive": [
            [py, "-m", "services.collector.close_archive", "--date", date_str,
             "--collector", runtime.get("kpl_collector", r"H:\projects\kpl\collect_live.py"),
             "--kpl-output", runtime.get("kpl_output", r"H:\projects\kpl\output"),
             "--data", data],
            [py, "-m", "services.collector.archive_job", "--date", date_str,
             "--facts", os.path.join(data, "facts"), "--web", os.path.join(data, "web"),
             "--intraday", os.path.join(data, "intraday"), "--archive", os.path.join(data, "archive"),
             "--verify", "--stage-only", "--kpl-output", runtime.get("kpl_output", r"H:\projects\kpl\output")],
            [py, "-m", "services.collector.quality_gate", "--date", date_str, "--data", data, "--promote"],
        ],
    }


def write_fact_meta(data_root, date_str, stage="postmarket"):
    root = Path(data_root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8")) if (root / "manifest.json").exists() else {}
    day = root / "facts" / date_str
    day.mkdir(parents=True, exist_ok=True)
    doc = {"data_date": date_str, "fetched_at": _now(), "stage": stage,
           "sources": {k: v for k, v in manifest.items() if k in ("stocks", "themes", "sectors")}}
    (day / "meta.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def execute_stage(date_str, stage, runtime, root, dry_run=False):
    data = runtime.get("data_root", "data")
    norm = os.path.join(data, "normalized", "stocks.json")
    universe = os.path.join(data, "runs", "universe_active.txt")
    commands = build_stage_commands(date_str, runtime)[stage]
    details = []
    for command in commands:
        details.append(run_command(command, cwd=root, timeout=8 * 3600, dry_run=dry_run))
        if stage == "premarket" and not dry_run and os.path.isfile(norm):
            write_active_universe(norm, universe)
    if stage == "postmarket" and not dry_run:
        write_fact_meta(data, date_str)
    return {"commands": details}


def main(argv=None):
    ap = argparse.ArgumentParser(description="V0.3 每日运行总控")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--phase", choices=(*STAGES, "all"), default="all")
    ap.add_argument("--calendar", default="config/trading_calendar.json")
    ap.add_argument("--runs", default="data/runs/daily_runs.json")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--runtime", default="config/runtime.json")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.date)
    if not is_trading_day(day, args.calendar):
        print(f"[SKIP] {args.date} 非交易日")
        return 0
    stages = STAGES if args.phase == "all" else (args.phase,)
    store = DailyRunStore(args.runs)
    runtime = load_runtime(args.runtime)
    root = str(Path(__file__).resolve().parents[2])
    failed = False
    dependencies = {"intraday": "premarket", "archive": "postmarket"}
    for stage in stages:
        dependency = dependencies.get(stage)
        if dependency and store.latest_status(args.date, dependency) != "success":
            action = lambda dep=dependency: (_ for _ in ()).throw(RuntimeError(f"dependency not successful: {dep}"))
        else:
            action = lambda s=stage: execute_stage(args.date, s, runtime, root, args.dry_run)
        result = run_stage(store, args.date, stage,
                           action, args.force)
        print(f"[{result['status'].upper()}] {args.date} {stage}")
        failed |= result["status"] == "failed"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
