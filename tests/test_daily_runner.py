import datetime as dt
import json

from services.collector.daily_runner import (
    DailyRunStore, build_stage_commands, is_trading_day, run_command, run_stage, write_active_universe,
)


def test_is_trading_day_weekday_and_weekend():
    assert is_trading_day(dt.date(2026, 8, 17)) is True
    assert is_trading_day(dt.date(2026, 8, 16)) is False


def test_explicit_calendar_has_priority(tmp_path):
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({"trading_days": ["2026-08-16"], "holidays": ["2026-08-17"]}), encoding="utf-8")
    assert is_trading_day(dt.date(2026, 8, 16), calendar) is True
    assert is_trading_day(dt.date(2026, 8, 17), calendar) is False


def test_run_store_appends_attempts_and_skips_success(tmp_path):
    store = DailyRunStore(tmp_path / "daily_runs.json")
    calls = []

    def action():
        calls.append(1)
        return {"message": "ok"}

    first = run_stage(store, "2026-08-17", "premarket", action)
    second = run_stage(store, "2026-08-17", "premarket", action)
    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert len(calls) == 1
    saved = json.loads((tmp_path / "daily_runs.json").read_text(encoding="utf-8"))
    assert len(saved["runs"]["2026-08-17"]["premarket"]["attempts"]) == 1


def test_failed_stage_can_retry(tmp_path):
    store = DailyRunStore(tmp_path / "daily_runs.json")
    count = {"n": 0}

    def flaky():
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("temporary")
        return {"message": "recovered"}

    failed = run_stage(store, "2026-08-17", "archive", flaky)
    success = run_stage(store, "2026-08-17", "archive", flaky)
    assert failed["status"] == "failed" and "temporary" in failed["error"]
    assert success["status"] == "success"
    assert len(store.load()["runs"]["2026-08-17"]["archive"]["attempts"]) == 2


def test_force_repeats_successful_stage(tmp_path):
    store = DailyRunStore(tmp_path / "daily_runs.json")
    calls = []
    action = lambda: calls.append(1) or {}
    run_stage(store, "2026-08-17", "postmarket", action)
    result = run_stage(store, "2026-08-17", "postmarket", action, force=True)
    assert result["status"] == "success" and len(calls) == 2


def test_write_active_universe_filters_inactive_and_invalid(tmp_path):
    stocks = tmp_path / "stocks.json"
    stocks.write_text(json.dumps({
        "SH600000": {"code": "600000", "status": "active"},
        "BJ110075": {"code": "110075", "status": "invalid_instrument"},
        "SZ000001": {"code": "000001", "status": "source_missing"},
    }), encoding="utf-8")
    out = tmp_path / "universe.txt"
    assert write_active_universe(stocks, out) == 1
    assert out.read_text(encoding="utf-8").splitlines() == ["600000"]


def test_build_stage_commands_contains_real_pipeline(tmp_path):
    runtime = {"data_root": str(tmp_path / "data"), "vipdoc": "X:/vipdoc", "python": "python"}
    commands = build_stage_commands("2026-08-17", runtime)
    assert any("services.collector.master_collector" in cmd for cmd in commands["premarket"] for part in cmd)
    assert any("--realtime" in cmd for cmd in commands["intraday"])
    assert any("services.collector.strategy_engine" in cmd for cmd in commands["postmarket"] for part in cmd)
    assert "services.collector.close_archive" in commands["archive"][0]
    assert "--kpl-output" in commands["archive"][1]
    assert any("--stage-only" in cmd for cmd in commands["archive"])
    assert any("--promote" in cmd for cmd in commands["archive"])
    master = commands["premarket"][0]
    assert master[master.index("--date") + 1] == "2026-08-14"


def test_run_command_decodes_collector_output_as_utf8(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = "全量归档完成"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr("services.collector.daily_runner.subprocess.run", fake_run)
    result = run_command(["python", "collector.py"])
    assert captured["encoding"] == "utf-8" and captured["errors"] == "replace"
    assert "全量归档" in result["stdout"]
