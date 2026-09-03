import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path


def test_core_intraday_route_does_not_build_auction_payload(monkeypatch):
    import services.market_data_service as service

    calls = []

    def fake_latest(cursor=None, include_auction=True):
        calls.append((cursor, include_auction))
        return {"available": True, "data_date": "2026-09-03"}

    monkeypatch.setattr(service, "intraday_latest", fake_latest)
    payload, status = service.handle_api(
        "/api/intraday/latest", {"cursor": ["c1"], "scope": ["core"]})

    assert status == 200
    assert payload["data"]["available"] is True
    assert calls == [("c1", False)]


def test_intraday_latest_can_omit_auction_payload(monkeypatch):
    import services.market_data_service as service

    source = ("2026-09-03", None, Path("unused.ndjson"), None)
    monkeypatch.setattr(service, "latest_snapshot_source", lambda: source)
    monkeypatch.setattr(service, "read_last_ndjson_record", lambda _path: {
        "ts": "2026-09-03 10:00:00", "phase": "trading", "stocks": {}})
    monkeypatch.setattr(service, "load_json", lambda *_parts: {})
    monkeypatch.setattr(service, "build_event_view", lambda *args: []) if hasattr(service, "build_event_view") else None
    monkeypatch.setattr(service, "compute_sector_strength", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "rank_actionable_alerts", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "realtime_money_flow", lambda: ([], ""))
    monkeypatch.setattr(service, "realtime_leading_reasons", lambda: ([], ""))
    monkeypatch.setattr(service, "realtime_expected_leaders", lambda **kwargs: ([], ""))
    monkeypatch.setattr(service, "build_auction_radar_payload",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("auction built")))

    result = service.intraday_latest(include_auction=False)

    assert "auction_radar" not in result


def test_member_json_transport_gzips_large_payload_and_supports_etag():
    from services.member_local_service import encode_json_transport

    body = {"data": {"rows": ["实时数据"] * 2000}}
    raw, headers = encode_json_transport(body, "gzip")

    assert headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(raw).decode("utf-8")) == body
    assert headers["ETag"].startswith('"')
    again, again_headers = encode_json_transport(body, "gzip")
    assert again == raw
    assert again_headers["ETag"] == headers["ETag"]


def test_member_calculation_throttles_changed_cursor_within_minimum_interval(tmp_path):
    from services.member_local_service import run_member_calculation_once

    member = tmp_path / "members" / "U100"
    kline = member / "kline"
    kline.mkdir(parents=True)
    shared = tmp_path / "shared"
    shared.mkdir()
    state = {"cursor": "c1", "revision": "p1", "data_date": "2026-09-03"}
    (shared / "sync_state.json").write_text(json.dumps(state), encoding="utf-8")
    config = {"member_id": "U100", "kline_dir": str(kline)}
    calls = []
    start = datetime(2026, 9, 3, 10, 0, 0)

    def calculate(*_args):
        calls.append(1)
        return {"quote_count": 1, "model_hits": [], "actionable_alerts": []}

    assert run_member_calculation_once(config, shared, calculate_fn=calculate, now=start)["status"] == "success"
    state["cursor"] = "c2"
    (shared / "sync_state.json").write_text(json.dumps(state), encoding="utf-8")
    skipped = run_member_calculation_once(
        config, shared, calculate_fn=calculate, now=start + timedelta(seconds=20), min_interval_seconds=60)

    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "minimum interval"
    assert len(calls) == 1


def test_frontend_reuses_one_core_intraday_request_path():
    js = (Path(__file__).parents[1] / "apps" / "web" / "assets" / "app.js").read_text(
        encoding="utf-8")

    assert "function fetchIntradayCore()" in js
    assert js.count("fetchJSON('api/intraday/latest?scope=core'") == 1
    assert js.count("fetchIntradayCore()") >= 5
