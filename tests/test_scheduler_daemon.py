import datetime as dt

from services.collector.scheduler_daemon import due_stages, rotate_log, service_specs


def at(value):
    return dt.datetime.fromisoformat(f"2026-08-17T{value}:00")


def test_due_stages_obey_market_windows():
    assert due_stages(at("08:59"), {}) == []
    assert due_stages(at("09:00"), {}) == ["premarket"]
    assert due_stages(at("09:14"), {"premarket": "success"}) == ["intraday"]
    assert "intraday" not in due_stages(at("15:01"), {"premarket": "success"})


def test_due_stages_retry_failed_and_skip_success():
    statuses = {"premarket": "success", "intraday": "success", "postmarket": "failed"}
    assert due_stages(at("15:29"), statuses) == ["postmarket"]
    assert due_stages(at("15:30"), statuses) == ["postmarket"]
    statuses.update(postmarket="success", archive="success")
    assert due_stages(at("15:30"), statuses) == []


def test_archive_starts_at_1530_after_postmarket_and_retries_are_bounded():
    assert due_stages(at("15:29"), {"postmarket": "success"}) == ["premarket"]
    states = {"premarket": "success", "postmarket": "success"}
    assert due_stages(at("15:30"), states) == ["archive"]
    states["archive"] = {"status": "failed", "attempt_count": 1,
                         "updated_at": "2026-08-17T15:29:00+08:00"}
    assert due_stages(at("15:30"), states) == []
    states["archive"]["updated_at"] = "2026-08-17T15:24:00+08:00"
    assert due_stages(at("15:30"), states) == ["archive"]
    states["archive"]["attempt_count"] = 3
    assert due_stages(at("16:00"), states) == []


def test_intraday_waits_for_premarket():
    assert "intraday" not in due_stages(at("10:00"), {"premarket": "failed"})


def test_rotate_log_keeps_bounded_generations(tmp_path):
    log = tmp_path / "scheduler.log"
    log.write_text("12345", encoding="utf-8")
    rotate_log(log, max_bytes=4, keep=2)
    assert not log.exists()
    assert (tmp_path / "scheduler.log.1").read_text(encoding="utf-8") == "12345"


def test_service_specs_bind_api_to_loopback(tmp_path):
    specs = service_specs(tmp_path, {"python": "python", "data_root": "data", "nginx_dir": "C:/nginx"})
    api = specs["api"]
    assert api["command"][-4:] == ["--host", "127.0.0.1", "--port", "8787"]
    assert specs["nginx"]["health"].endswith("/DSH/")
