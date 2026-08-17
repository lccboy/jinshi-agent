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
           "strategy_top": [{"stock_id": "SZ300487", "score": 80, "models": {"breakout": 60}}],
           "pools": {"pools": {"alert": {"SZ300487": {"score": 80, "status": "active"}},
                               "candidate": {}, "limitup": {}, "ladder": {}, "watchlist": {}}},
           "events": [{"ts": "2026-08-14T10:00:00", "type": "signal_hit", "stock_id": "SZ300487", "score": 80}]}
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
        json.dump({"data_date": "2026-08-14", "pools": {
            "alert": {"SZ300487": {"score": 80, "model_hit": ["breakout"], "entry_time": "10:00:00"}},
            "limitup": {"SZ300487": {"entry_time": "10:00:00"},
                        "SH600001": {"entry_time": "10:01:00"}},
        }}, fh)
    with open(os.path.join(facts, "events.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_date": "2026-08-14", "events": [{"ts": "2026-08-14T10:00:00", "type": "signal_hit", "stock_id": "SZ300487"}]}, fh)
    with open(os.path.join(facts, "limitup.json"), "w", encoding="utf-8") as fh:
        json.dump({"SZ300487": {"reason": "存储", "boards": "首板"}}, fh)
    previous_facts = os.path.join(tmp_data, "facts", "2026-08-13")
    os.makedirs(previous_facts, exist_ok=True)
    with open(os.path.join(previous_facts, "limitup.json"), "w", encoding="utf-8") as fh:
        json.dump({"SH600001": {"reason": "机器人概念", "primary": "kpl", "sourceCount": 2,
                                  "sources": {"kpl": {"reason": "机器人概念"},
                                              "ths": {"reason": "自动化设备"}}}}, fh, ensure_ascii=False)
    intraday = os.path.join(tmp_data, "intraday", "2026-08-14")
    os.makedirs(intraday, exist_ok=True)
    with open(os.path.join(intraday, "snapshots.ndjson"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "2026-08-14 10:02:03", "phase": "continuous",
                             "stocks": {"SZ300487": {"price": 12.0, "change_pct": 9.98},
                                        "SH600001": {"price": 11.0, "change_pct": 10.0}}}) + "\n")
    normalized = os.path.join(tmp_data, "normalized")
    os.makedirs(normalized, exist_ok=True)
    with open(os.path.join(normalized, "stocks.json"), "w", encoding="utf-8") as fh:
        json.dump({"SZ300487": {"name": "蓝晓科技"}, "SH600001": {"name": "测试股份"}}, fh, ensure_ascii=False)
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


def test_intraday_latest(api):
    r = api.get("/intraday/latest")
    data = r["data"]
    assert r["meta"]["data_date"] == "2026-08-14"
    assert data["ts"] == "2026-08-14 10:02:03"
    assert data["available"] is True
    assert data["stocks"] == {}  # 轻量接口不下发 5000 只全市场明细
    assert data["quote_count"] == 2
    limitups = {item["stock_id"]: item for item in data["limitup"]}
    assert limitups["SZ300487"]["reason"] == "存储"
    assert limitups["SZ300487"]["reason_is_history"] is False
    assert limitups["SH600001"]["reason"] == "机器人概念"
    assert limitups["SH600001"]["reason_date"] == "2026-08-13"
    assert limitups["SH600001"]["reason_is_history"] is True
    assert limitups["SH600001"]["sourceCount"] == 2
    assert limitups["SH600001"]["sources"]["ths"]["reason"] == "自动化设备"
    assert data["model_hits"][0]["model_hit"] == ["breakout"]
    assert data["model_hits"][0]["model_names"] == ["②横盘突破"]
    assert data["model_hits"][0]["name"] == "蓝晓科技"
    assert data["model_hits"][0]["change_pct"] == 9.98
    assert data["model_hits"][0]["ts"] == "10:00:00"
    assert data["events"][0]["type"] == "signal_hit"


def test_agent_summary(api):
    # V0.4 Agent 聚合端点：一次返回当天信号摘要（涨停/策略/预警/事件/板块/资金流）
    r = api.get("/agent/summary?date=2026-08-14")
    data = r["data"]
    assert r["meta"]["data_date"] == "2026-08-14"
    assert data["limit_up_count"] == 73
    assert data["strategy_top"][0]["stock_id"] == "SZ300487"
    assert data["alert_count"] == 1
    assert data["event_counts"]["signal_hit"] == 1
    assert data["top_sectors"][0]["name"] == "芯片"
    assert data["top_money_flow"][0]["name"] == "通信"
    assert isinstance(data["stock_names"], dict)  # 无主数据时为空 dict，不报错


def test_agent_summary_default_latest(api):
    # 缺省 date → 最新交易日
    r = api.get("/agent/summary")
    assert r["meta"]["data_date"] == "2026-08-14"
