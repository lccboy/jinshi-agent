import json

from services.collector.quality_gate import evaluate_quality, promote_if_acceptable, write_report


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_kline(tmp_path, sids, last_d):
    for sid in sids:
        _write(tmp_path / f"kline/{sid}.json",
               {"stock_id": sid, "adjusted": "qfq",
                "bars": [{"d": last_d, "o": 100, "h": 100, "l": 100, "c": 100, "v": 1, "amt": 1.0}]})


def test_quality_gate_passes_complete_day(tmp_path):
    _write(tmp_path / "normalized/stocks.json", {
        "SH600000": {"current": {"sectors": ["880001"]}, "industry": "银行", "list_date": "1999-11-10"}
    })
    _write(tmp_path / "normalized/sectors.json", {"880001": {"type": "industry"}})
    _write(tmp_path / "manifest.json", {"themes": {"freshness": "fresh"}})
    for name in ("meta", "limitup", "membership", "strategy", "events", "pool"):
        _write(tmp_path / f"facts/2026-08-17/{name}.json", {"data_date": "2026-08-17"})
    _write(tmp_path / "web/day_2026-08-17.json", {"data_date": "2026-08-17"})
    _write_kline(tmp_path, ["SH600000", "SZ000001"], 20260817)
    report = evaluate_quality(tmp_path, "2026-08-17", {"min_sector_coverage": 0.9})
    assert report["status"] == "pass"
    assert not [x for x in report["checks"] if x["status"] == "fail"]


def test_quality_gate_detects_stale_and_missing_data(tmp_path):
    _write(tmp_path / "normalized/stocks.json", {
        "SH600000": {"current": {"sectors": []}},
        "SZ000001": {"current": {"sectors": ["880001"]}},
    })
    _write(tmp_path / "normalized/sectors.json", {"880001": {"type": "industry"}})
    _write(tmp_path / "manifest.json", {"themes": {"freshness": "stale"}})
    report = evaluate_quality(tmp_path, "2026-08-17", {"min_sector_coverage": 0.9})
    by_name = {x["name"]: x for x in report["checks"]}
    assert report["status"] == "fail"
    assert by_name["master_sector_coverage"]["status"] == "fail"
    assert by_name["theme_freshness"]["status"] == "warn"
    assert by_name["required_facts"]["status"] == "fail"


def test_quality_coverage_uses_active_master_only(tmp_path):
    _write(tmp_path / "normalized/stocks.json", {
        "SH600000": {"status": "active", "current": {"sectors": ["880001"]}},
        "SZ000001": {"status": "source_missing", "current": {"sectors": []}},
    })
    _write(tmp_path / "normalized/sectors.json", {"880001": {"type": "industry"}})
    report = evaluate_quality(tmp_path, "2026-08-17", {"min_sector_coverage": 0.9, "required_facts": []})
    check = {x["name"]: x for x in report["checks"]}["master_sector_coverage"]
    assert check["actual"] == 1.0


def test_write_report(tmp_path):
    report = {"data_date": "2026-08-17", "status": "warn", "checks": []}
    path = write_report(report, tmp_path / "runs")
    assert path.name == "quality_2026-08-17.json"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "warn"


def test_promote_only_when_report_has_no_fail(tmp_path):
    web = tmp_path / "web"
    _write(web / "day_2026-08-17.json", {"date": "2026-08-17"})
    assert promote_if_acceptable({"data_date": "2026-08-17", "status": "fail"}, web) is None
    assert not (web / "day_latest.json").exists()
    path = promote_if_acceptable({"data_date": "2026-08-17", "status": "warn"}, web)
    assert path.name == "day_latest.json"


def test_kline_freshness_pass(tmp_path):
    _write_kline(tmp_path, ["SH600000", "SZ000001", "BJ920000"], 20260817)
    report = evaluate_quality(tmp_path, "2026-08-17", {"min_sector_coverage": 0.9, "required_facts": []})
    check = {x["name"]: x for x in report["checks"]}["kline_freshness"]
    assert check["status"] == "pass"
    assert check["actual"]["current"] == 3


def test_kline_freshness_stale_fails(tmp_path):
    _write_kline(tmp_path, ["SH600000", "SZ000001"], 20260814)
    report = evaluate_quality(tmp_path, "2026-08-17", {"min_sector_coverage": 0.9, "required_facts": []})
    check = {x["name"]: x for x in report["checks"]}["kline_freshness"]
    assert check["status"] == "fail"
