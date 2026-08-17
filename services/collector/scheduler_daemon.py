# -*- coding: utf-8 -*-
"""无需管理员权限的 V0.3 用户态调度守护进程。"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .daily_runner import DailyRunStore, is_trading_day


def due_stages(now, statuses):
    """返回当前应启动且尚未成功的阶段；盘中采集绝不在收盘后补跑。"""
    minute = now.hour * 60 + now.minute
    due = []
    if 9 * 60 <= minute and statuses.get("premarket") != "success":
        due.append("premarket")
    if (9 * 60 + 14 <= minute <= 15 * 60 and
            statuses.get("premarket") == "success" and statuses.get("intraday") != "success"):
        due.append("intraday")
    if minute >= 15 * 60 + 10 and statuses.get("postmarket") != "success":
        due.append("postmarket")
    if minute >= 15 * 60 + 20 and statuses.get("archive") != "success":
        due.append("archive")
    return due


def day_statuses(store, date_str):
    return {stage: store.latest_status(date_str, stage)
            for stage in ("premarket", "intraday", "postmarket", "archive")}


def rotate_log(path, max_bytes=10 * 1024 * 1024, keep=5):
    path = Path(path)
    if not path.exists() or path.stat().st_size <= max_bytes:
        return
    oldest = path.with_name(path.name + f".{keep}")
    if oldest.exists():
        oldest.unlink()
    for index in range(keep - 1, 0, -1):
        source = path.with_name(path.name + f".{index}")
        if source.exists():
            os.replace(source, path.with_name(path.name + f".{index + 1}"))
    os.replace(path, path.with_name(path.name + ".1"))


def service_specs(root, runtime):
    nginx = Path(runtime.get("nginx_dir", r"C:\nginx"))
    return {
        "api": {"health": "http://127.0.0.1:8787/api/health", "cwd": str(root),
                "command": [runtime.get("python") or sys.executable, "services/market_data_service.py",
                            "--data", runtime.get("data_root", "data"), "--host", "127.0.0.1", "--port", "8787"]},
        "nginx": {"health": "http://127.0.0.1:8088/DSH/", "cwd": str(nginx),
                  "command": [str(nginx / "nginx.exe"), "-p", str(nginx), "-c", "conf/nginx.conf"]},
    }


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def write_state(path, children, now):
    doc = {"pid": os.getpid(), "updated_at": now.astimezone().isoformat(timespec="seconds"),
           "children": {stage: proc.pid for stage, proc in children.items() if proc.poll() is None}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="V0.3 用户态每日调度守护进程")
    ap.add_argument("--runtime", default="config/runtime.json")
    ap.add_argument("--calendar", default="config/trading_calendar.json")
    ap.add_argument("--runs", default="data/runs/daily_runs.json")
    ap.add_argument("--state", default="data/runs/scheduler_state.json")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    store = DailyRunStore(root / args.runs)
    state_path = root / args.state
    log_path = root / "data" / "runs" / "logs" / "daily_runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    children = {}
    while True:
        now = dt.datetime.now().astimezone()
        date_str = now.date().isoformat()
        children = {stage: proc for stage, proc in children.items() if proc.poll() is None}
        for name, spec in service_specs(root, json.loads((root / args.runtime).read_text(encoding="utf-8"))).items():
            if not healthy(spec["health"]) and name not in children:
                service_log = root / "data" / "runs" / "logs" / f"{name}.watchdog.log"
                rotate_log(service_log)
                with service_log.open("a", encoding="utf-8") as log:
                    children[name] = subprocess.Popen(spec["command"], cwd=spec["cwd"], stdout=log,
                                                      stderr=subprocess.STDOUT)
        if is_trading_day(now.date(), root / args.calendar):
            statuses = day_statuses(store, date_str)
            for stage in due_stages(now, statuses):
                if stage in children:
                    continue
                command = [sys.executable, "-m", "services.collector.daily_runner", "--phase", stage,
                           "--runtime", args.runtime]
                rotate_log(log_path)
                with log_path.open("a", encoding="utf-8") as log:
                    children[stage] = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        write_state(state_path, children, now)
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
