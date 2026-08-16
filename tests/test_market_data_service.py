# V0.2 任务 1-2：market_data_service 测试（in-process 起服务，TDD）
import json
import os
import threading
import urllib.request

import pytest


def make_client(tmp_data, tmp_path):
    """临时数据目录 + in-process 服务 → (client, stop)。"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from services.market_data_service import make_server

    # 构造临时数据：index + day + facts（strategy/pool/events/limitup）+ kline
    web = os.path.join(tmp_data, "web")
    os.makedirs(web, exist_ok=True)
    day = {"date": "2026-08-14", "market": {"limit_up": 73}, "sectors": [{"id": "801001", "name": "芯片", "strength": 5000}],
           "limitup": [{"stock_id": "SZ300487", "reason": "存储", "boards": "首板", "concepts": ["存储"],
                        "primary": "kpl", "sourceCount": 4}],
           "money_flow": [{"name": "通信", "main": 100}], "leading_reason": [{"name": "存储", "reason": "x"}],
           "strategy_top": [{"stock_id": "SZ300487", "score": 80, "models": {"breakout": 60}}], "pools": {}}
    with open(os.path.join(web, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"days": [{"date": "2026-08-14"}]}, fh)
    for name, content in (("day_2026-08-14.json", day), ("day_latest.json", day)):
        with open(os.path.join(web, name), "w", encoding="utf-8") as fh:
            json.dump(content, fh, ensure_ascii=False)

    facts = os.path.join(tmp_data, "facts", "2026-08-14")
    os.makedirs(facts, exist_ok=True)
    with open(os.path.join(facts, "strategy.json"), "w", encoding="utf-8") as fh:
        json.dump({"SZ300487": {"run_id": "r1", "models": {"breakout": 60}, "score": 80}}, fh)
    with open(os.path.join(facts, "pool.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": "2026-08-14", "pools": {"alert": {"SZ300487": {"score": 80}}}}, fh)
    with open(os.path.join(facts, "events.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": "2026-08-14", "events": [{"ts": "2026-08-14T10:00:00", "type": "signal_hit", "stock_id": "SZ300487"}]}, fh)
    with open(os.path.join(facts, "limitup.json"), "w", encoding="utf-8") as fh:
        json.dump({"SZ300487": {"reason": "存储", "boards": "首板"}}, fh)
    kline = os.path.join(tmp_data, "kline")
    os.makedirs(kline, exist_ok=True)
    with open(os.path.join(kline, "SZ300487.json"), "w", encoding="utf-8") as fh:
        json.dump({"stock_id": "SZ300487", "adjusted": "qfq", "bars": [{"d": 20260814, "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100, "amt": 1000}]}, fh)

    server = make_server(tmp_data, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}/api"

    class Client:
        def get(self, path):
            with urllib.request.urlopen(base + path, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        def raw(self, path):
            try:
                with urllib.request.urlopen(base + path, timeout=10) as resp:
                    return resp.status, resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8")

    def stop():
        server.shutdown()
    return Client(), stop


@pytest.fixture()
def api(tmp_path):
    client, stop = make_client(str(tmp_path / "data"), tmp_path)
    yield client
    stop()


def test_health(api):
    r = api.get("/health")
    assert r["status"] == "ok"


def test_days(api):
    r = api.get("/days")
    assert r["data"]["days"][0]["date"] == "2026-08-14"


def test_day_latest(api):
    r = api.get("/day")
    assert r["data"]["date"] == "2026-08-14"
    assert "sectors" in r["data"]


def test_day_meta(api):
    r = api.get("/day?date=2026-08-14")
    assert r["meta"]["data_date"] == "2026-08-14"
    assert "source" in r["meta"] and "fetched_at" in r["meta"]


def test_day_missing_date_404(api):
    status, body = api.raw("/day?date=1999-01-01")
    assert status == 404


def test_strategies(api):
    r = api.get("/strategies?date=2026-08-14")
    assert r["data"]["SZ300487"]["score"] == 80


def test_pools(api):
    r = api.get("/pools?date=2026-08-14")
    assert "alert" in r["data"]["pools"]


def test_events(api):
    r = api.get("/events?date=2026-08-14&type=signal_hit")
    assert r["data"]["events"][0]["type"] == "signal_hit"


def test_limitups(api):
    r = api.get("/limitups?date=2026-08-14")
    assert r["data"]["SZ300487"]["reason"] == "存储"


def test_kline(api):
    r = api.get("/kline/SZ300487")
    assert r["data"]["adjusted"] == "qfq"
    assert r["data"]["bars"][-1]["c"] == 10.5


def test_history_timeline(api):
    r = api.get("/history?stock=SZ300487")
    days = r["data"]["timeline"]
    assert len(days) == 1
    d = days[0]
    assert d["date"] == "2026-08-14"
    assert d["strategy"]["score"] == 80
    assert d["pool"]["alert"] is True
    assert d["limitup"]["reason"] == "存储"
    assert d["events"][0]["type"] == "signal_hit"


def test_intraday_latest_missing(api):
    # 临时数据无 intraday 目录 → 200 空
    r = api.get("/intraday/latest")
    assert "data" in r
