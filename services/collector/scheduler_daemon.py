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
    def state(stage):
        value = statuses.get(stage)
        return value if isinstance(value, dict) else {"status": value, "attempt_count": 0}

    def eligible(stage):
        value = state(stage)
        if value.get("status") == "success" or value.get("attempt_count", 0) >= 3:
            return False
        updated = value.get("updated_at")
        if value.get("status") == "failed" and updated:
            then = dt.datetime.fromisoformat(updated)
            compare_now = now if now.tzinfo else now.replace(tzinfo=then.tzinfo)
            if (compare_now - then).total_seconds() < 300:
                return False
        return True

    due = []
    if 9 * 60 <= minute and eligible("premarket"):
        due.append("premarket")
    if (9 * 60 + 14 <= minute <= 15 * 60 and
            state("premarket").get("status") == "success" and eligible("intraday")):
        due.append("intraday")
    if minute >= 15 * 60 + 10 and eligible("postmarket"):
        due.append("postmarket")
    if (minute >= 15 * 60 + 30 and state("postmarket").get("status") == "success" and
            eligible("archive")):
        due.append("archive")
    return due


def day_statuses(store, date_str):
    day = store.load().get("runs", {}).get(date_str, {})
    return {stage: {"status": day.get(stage, {}).get("status"),
                    "updated_at": day.get(stage, {}).get("updated_at"),
                    "attempt_count": len(day.get(stage, {}).get("attempts", []))}
            for stage in ("premarket", "intraday", "postmarket", "archive")}


RETRY_LIMIT = 3  # 与 due_stages 的 attempt_count 上限一致；达到后停止重试并升级告警


def pending_escalations(date_str, statuses, alerts_dir):
    """attempt_count 达到上限且仍失败、且当日未告警过的阶段 → 需升级告警。

    - 纯函数（TDD）：只返回清单，不写文件
    - 兼容历史脏数据（attempt_count 远超上限，如 08-17 的 592 次）同样触发
    """
    out = []
    for stage in ("premarket", "intraday", "postmarket", "archive"):
        raw = statuses.get(stage)
        value = raw if isinstance(raw, dict) else {"status": raw, "attempt_count": 0}
        if value.get("status") != "failed":
            continue
        if value.get("attempt_count", 0) < RETRY_LIMIT:
            continue
        alert_path = Path(alerts_dir) / f"{date_str}_{stage}.json"
        if alert_path.exists():
            continue
        out.append({"stage": stage, "attempts": value["attempt_count"],
                    "updated_at": value.get("updated_at"), "date": date_str})
    return out


def write_escalation(date_str, entry, alerts_dir, log_path=None):
    """写升级告警文件（幂等：已存在不覆盖）；返回写入路径或 None。"""
    alerts_dir = Path(alerts_dir)
    alerts_dir.mkdir(parents=True, exist_ok=True)
    alert_path = alerts_dir / f"{date_str}_{entry['stage']}.json"
    if alert_path.exists():
        return None
    doc = {"date": date_str, "stage": entry["stage"], "attempts": entry["attempts"],
           "last_failed_at": entry.get("updated_at"),
           "escalated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "message": f"{date_str} {entry['stage']} 阶段失败 {entry['attempts']} 次达到重试上限，已停止自动重试，需人工介入"}
    temp = alert_path.with_suffix(".tmp")
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, alert_path)
    line = f"[ESCALATE] {date_str} {entry['stage']}: {doc['message']}"
    if log_path:
        with Path(log_path).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    print(line, flush=True)
    return str(alert_path)


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
            # 失败升级告警：达到重试上限后停止盲重试，落盘 alerts/ 供人工/微信通知
            alerts_dir = root / "data" / "runs" / "alerts"
            for entry in pending_escalations(date_str, statuses, alerts_dir):
                write_escalation(date_str, entry, alerts_dir, log_path=log_path)
        write_state(state_path, children, now)
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
