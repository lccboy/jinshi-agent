import json
import datetime
from pathlib import Path
import threading
import struct
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest
from urllib.error import HTTPError

import services.member_local_service as member_service
from services.member_local_service import (normalize_member_config, save_member_config,
                                           generate_member_klines,
                                           install_frozen_helper, install_paths,
                                           installation_status_message, MemberHandler,
                                           older_helper_image_names, startup_command,
                                           load_bootstrap, save_bootstrap, local_paths,
                                           member_calculation_revision,
                                           run_member_calculation_once,
                                           build_runtime_status, sync_poll_interval,
                                           materialize_member_strategy_archive)


def test_materialize_member_strategy_archive_uses_private_strategy_and_kline(tmp_path):
    member = tmp_path / "members" / "U100"
    facts = member / "facts" / "2026-09-01"
    kline = member / "kline"
    shared = tmp_path / "shared"
    facts.mkdir(parents=True)
    kline.mkdir()
    (shared / "legacy" / "web").mkdir(parents=True)
    (facts / "strategy.json").write_text(json.dumps({
        "SH600000": {"models": {"breakout": 88}, "score": 88, "stars": 3}
    }), encoding="utf-8")
    (facts / "pool.json").write_text(json.dumps({"data_date": "2026-09-01", "pools": {
        "alert": {"SH600000": {"score": 88}}, "candidate": {}
    }}), encoding="utf-8")
    (kline / "SH600000.json").write_text(json.dumps({"bars": [
        {"d": 20260831, "c": 10.0}, {"d": 20260901, "c": 10.5}
    ]}), encoding="utf-8")
    (shared / "legacy" / "web" / "stocks_slim.json").write_text(json.dumps({
        "SH600000": {"n": "浦发银行", "s": [], "t": []}
    }), encoding="utf-8")

    result = materialize_member_strategy_archive(
        {"member_id": "U100", "kline_dir": str(kline)}, "2026-09-01", shared)

    assert result["count"] == 1
    assert result["list"][0]["name"] == "浦发银行"
    assert result["list"][0]["price"] == 10.5
    saved = json.loads((member / "web" / "strategy_all_2026-09-01.json").read_text(encoding="utf-8"))
    assert saved["count"] == 1
    assert json.loads((member / "web" / "strategy_all.json").read_text(encoding="utf-8"))["date"] == "2026-09-01"


def test_member_strategy_web_route_prefers_authorized_private_archive(tmp_path):
    shared, members = tmp_path / "shared", tmp_path / "members"
    public_web = shared / "revisions" / "rev-1" / "web"
    private_web = members / "U100" / "web"
    public_web.mkdir(parents=True)
    private_web.mkdir(parents=True)
    (shared / "current.json").write_text(json.dumps({"revision": "rev-1"}), encoding="utf-8")
    (members / "U100" / "config.json").write_text(json.dumps({"member_id": "U100"}), encoding="utf-8")
    (public_web / "strategy_all_2026-09-01.json").write_text(
        json.dumps({"date": "2026-09-01", "count": 0, "list": []}), encoding="utf-8")
    (private_web / "strategy_all_2026-09-01.json").write_text(
        json.dumps({"date": "2026-09-01", "count": 1, "list": [{"stock_id": "SH600000"}]}),
        encoding="utf-8")
    old = (MemberHandler.shared_root, MemberHandler.members_root, MemberHandler.license_required)
    MemberHandler.shared_root, MemberHandler.members_root = shared, members
    MemberHandler.license_required = False
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/data/web/strategy_all_2026-09-01.json"
        ).read().decode("utf-8"))
        assert result["count"] == 1
        assert result["list"][0]["stock_id"] == "SH600000"
    finally:
        server.shutdown(); server.server_close()
        MemberHandler.shared_root, MemberHandler.members_root, MemberHandler.license_required = old


def test_sync_poll_interval_slows_down_after_close_without_hurting_trading():
    assert sync_poll_interval({"market_status": "trading"}, 15) == 15
    assert sync_poll_interval({"market_status": "preopen"}, 15) == 30
    assert sync_poll_interval({"market_status": "closed"}, 15) == 300
    assert sync_poll_interval({"market_status": "holiday"}, 15) == 300


def test_bootstrap_places_all_mutable_data_under_selected_root(tmp_path):
    bootstrap = tmp_path / "Local" / "JinshiDSH" / "bootstrap.json"
    selected = tmp_path / "H" / "JinshiDSHData"

    saved = save_bootstrap(selected, bootstrap)
    loaded = load_bootstrap(bootstrap)
    paths = local_paths(bootstrap_path=bootstrap)

    assert saved == loaded
    assert loaded["data_root"] == str(selected.resolve())
    assert paths == {
        "root": selected.resolve(),
        "shared": selected.resolve() / "shared",
        "members": selected.resolve() / "members",
        "runtime": selected.resolve() / "runtime",
        "logs": selected.resolve() / "logs",
        "backup": selected.resolve() / "backup",
    }
    assert all(path.is_dir() for path in paths.values())


def test_bootstrap_defaults_to_legacy_localappdata_root(tmp_path):
    bootstrap = tmp_path / "Local" / "JinshiDSH" / "bootstrap.json"

    paths = local_paths(local_appdata=tmp_path / "Local", bootstrap_path=bootstrap)

    assert paths["root"] == (tmp_path / "Local" / "JinshiDSH").resolve()
    assert paths["shared"] == paths["root"] / "shared"
    assert paths["members"] == paths["root"] / "members"


def test_local_service_hosts_complete_seven_tab_workbench():
    MemberHandler.web_root = Path(__file__).parents[1] / "apps" / "web"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        document = urlopen(base + "/").read().decode("utf-8")
        for view in ("signal", "auction", "theme", "sector", "leading", "strategy", "history"):
            assert f'data-view="{view}"' in document
        script = urlopen(base + "/assets/app.js").read().decode("utf-8")
        assert "mergeMemberLocalRealtime" in script
    finally:
        server.shutdown()
        server.server_close()


def test_local_static_server_rejects_path_traversal():
    MemberHandler.web_root = Path(__file__).parents[1] / "apps" / "web"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/assets/../../config/runtime.json")
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_local_system_health_reports_integrated_service_and_data_root(tmp_path):
    MemberHandler.data_root = tmp_path / "JinshiDSHData"
    MemberHandler.shared_root = MemberHandler.data_root / "shared"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/api/system/health"
        ).read().decode("utf-8"))
        assert payload["ok"] is True
        assert payload["service"] == "jinshi-local-workbench"
        assert payload["tabs"] == 7
        assert payload["data_root"] == str(MemberHandler.data_root.resolve())
    finally:
        server.shutdown()
        server.server_close()


def test_auction_control_api_is_member_local_authorized_and_sanitized(tmp_path, monkeypatch):
    class Manager:
        def status(self, member_id):
            assert member_id == "U100"
            return {"status": "running", "latency_ms": 18}

        def start(self, member_id, members_root, date_str, **kwargs):
            assert member_id == "U100"
            assert Path(members_root) == tmp_path / "members"
            return {"status": "running", "started_at": "2026-09-01T09:14:00+08:00"}

        def stop(self, member_id):
            return {"status": "stopped"}

    monkeypatch.setattr(MemberHandler, "_active_member_id", lambda self: "U100")
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U100")
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.shared_root = tmp_path / "shared"
    MemberHandler.local_token = "auction-token"
    MemberHandler.auction_manager = Manager()
    MemberHandler.auction_probe = staticmethod(lambda: {"status": "available", "source": "eltdx",
                                                         "latency_ms": 12, "server": "tdx-auto"})
    view = tmp_path / "members" / "U100" / "facts" / "2026-09-01"
    view.mkdir(parents=True)
    (view / "auction_radar.json").write_text(
        json.dumps({"schema_version": 3, "candidates": []}), encoding="utf-8")
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status = json.loads(urlopen(base + "/api/auction/status").read().decode("utf-8"))
        assert status == {"ok": True, "data": {"status": "running", "latency_ms": 18},
                          "private": True}
        request = Request(base + "/api/auction/start", data=b'{}', method="POST",
                          headers={"Content-Type": "application/json",
                                   "X-Jinshi-Local-Token": "auction-token"})
        started = json.loads(urlopen(request).read().decode("utf-8"))
        assert started["data"]["status"] == "running"
        assert started["private"] is True
        probe_request = Request(base + "/api/auction/test-connection", data=b'{}', method="POST",
                                headers={"Content-Type": "application/json",
                                         "X-Jinshi-Local-Token": "auction-token"})
        probe = json.loads(urlopen(probe_request).read().decode("utf-8"))
        assert probe["data"]["server"] == "tdx-auto"
        latest = json.loads(urlopen(
            base + "/api/auction/latest?date=2026-09-01").read().decode("utf-8"))
        assert latest["data"] == {"schema_version": 3, "candidates": []}
        assert latest["private"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_local_service_serves_promoted_public_web_cache(tmp_path):
    shared = tmp_path / "shared"
    revision = shared / "revisions" / "public-r1" / "web"
    revision.mkdir(parents=True)
    (revision / "index.json").write_text('{"days":[{"date":"2026-08-28"}]}', encoding="utf-8")
    (shared / "current.json").write_text(json.dumps({"revision": "public-r1"}), encoding="utf-8")
    MemberHandler.shared_root = shared
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/data/web/index.json"
        ).read().decode("utf-8"))
        assert payload["days"][0]["date"] == "2026-08-28"
    finally:
        server.shutdown()
        server.server_close()


def test_local_service_fetches_and_caches_web_file_for_legacy_server_manifest(tmp_path, monkeypatch):
    calls = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"days":[{"date":"2026-08-28"}]}'

    def upstream_open(url, timeout=0):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(member_service, "urlopen", upstream_open)
    MemberHandler.shared_root = tmp_path / "shared"
    MemberHandler.upstream_api = "http://server/dsh/api"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/data/web/index.json"
        ).read().decode("utf-8"))
        assert payload["days"][0]["date"] == "2026-08-28"
        assert calls == [("http://server/dsh/data/web/index.json", 20)]
        assert (tmp_path / "shared" / "legacy" / "web" / "index.json").is_file()
    finally:
        server.shutdown()
        server.server_close()


def test_local_service_uses_legacy_web_cache_when_upstream_is_offline(tmp_path, monkeypatch):
    cached = tmp_path / "shared" / "legacy" / "web" / "index.json"
    cached.parent.mkdir(parents=True)
    cached.write_text('{"days":[{"date":"2026-08-26"}]}', encoding="utf-8")

    def offline(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(member_service, "urlopen", offline)
    MemberHandler.shared_root = tmp_path / "shared"
    MemberHandler.upstream_api = "http://server/dsh/api"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/data/web/index.json"
        ).read().decode("utf-8"))
        assert payload["days"][0]["date"] == "2026-08-26"
    finally:
        server.shutdown()
        server.server_close()


def test_local_service_proxies_public_api_through_same_origin(monkeypatch):
    calls = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"data":{"available":true}}'

    def upstream_open(url, timeout=0):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(member_service, "urlopen", upstream_open)
    MemberHandler.upstream_api = "http://server/dsh/api"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/api/intraday/latest?cursor=c1"
        ).read().decode("utf-8"))
        assert payload["data"]["available"] is True
        assert calls == [("http://server/dsh/api/intraday/latest?cursor=c1", 20)]
    finally:
        server.shutdown()
        server.server_close()


def test_local_watchlist_is_member_private_and_overlays_public_pools(tmp_path, monkeypatch):
    public = {"data": {"data_date": "2026-08-29", "pools": {
        "alert": {"SH600000": {"score": 80}}, "candidate": {}, "limitup": {},
        "ladder": {}, "watchlist": {"SZ000001": {"note": "public-must-not-leak"}}
    }}, "meta": {"source": "engine"}}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return json.dumps(public).encode("utf-8")

    monkeypatch.setattr(member_service, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(MemberHandler, "_active_member_id", lambda self: "U100")
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U100")
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.upstream_api = "http://server/dsh/api"
    MemberHandler.local_token = "watch-token"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        request = Request(base + "/api/watchlist", data=json.dumps({
            "stock_id": "SH600000", "action": "add", "date": "2026-08-29",
            "source_date": "2026-08-28", "note": "实时信号加入"
        }).encode("utf-8"), headers={"Content-Type": "application/json",
                                    "X-Jinshi-Local-Token": "watch-token"})
        added = json.loads(urlopen(request).read().decode("utf-8"))
        private = tmp_path / "members" / "U100" / "facts" / "2026-08-29" / "pool.json"
        private_doc = json.loads(private.read_text(encoding="utf-8"))
        private_doc["pools"]["alert"] = {"SZ300001": {"score": 95}}
        private_doc["pools"]["candidate"] = {"SZ300002": {"score": 75}}
        private.write_text(json.dumps(private_doc), encoding="utf-8")
        pools = json.loads(urlopen(base + "/api/pools?date=2026-08-29").read().decode("utf-8"))

        assert added["data"]["selected"] is True
        assert set(pools["data"]["pools"]["watchlist"]) == {"SH600000"}
        assert pools["data"]["pools"]["alert"] == {"SZ300001": {"score": 95}}
        assert pools["data"]["pools"]["candidate"] == {"SZ300002": {"score": 75}}
        assert pools["meta"]["strategy_pool_scope"] == "member-local"
        assert private.is_file()
        assert not (tmp_path / "facts").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_member_strategy_pool_uses_local_archive_without_waiting_for_upstream(tmp_path, monkeypatch):
    monkeypatch.setattr(member_service, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("local strategy archive must not wait for public upstream")))
    monkeypatch.setattr(MemberHandler, "_active_member_id", lambda self: "U100")
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U100")
    MemberHandler.members_root = tmp_path / "members"
    private = tmp_path / "members" / "U100" / "facts" / "2026-09-01" / "pool.json"
    private.parent.mkdir(parents=True)
    private.write_text(json.dumps({"data_date": "2026-09-01", "pools": {
        "alert": {"SH600000": {"score": 90}}, "candidate": {"SZ300001": {"score": 75}}
    }}), encoding="utf-8")
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        document = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/api/pools?date=2026-09-01"
        ).read().decode("utf-8"))
        assert set(document["data"]["pools"]["alert"]) == {"SH600000"}
        assert document["meta"]["source"] == "member-local-archive"
    finally:
        server.shutdown()
        server.server_close()


def test_local_watchlist_remains_readable_when_public_day_is_not_archived(tmp_path, monkeypatch):
    monkeypatch.setattr(member_service, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("404")))
    monkeypatch.setattr(MemberHandler, "_active_member_id", lambda self: "U100")
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U100")
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.upstream_api = "http://server/dsh/api"
    private = tmp_path / "members" / "U100" / "facts" / "2026-08-29" / "pool.json"
    private.parent.mkdir(parents=True)
    private.write_text(json.dumps({"data_date": "2026-08-29", "pools": {
        "watchlist": {"SH600000": {"status": "active"}}
    }}), encoding="utf-8")
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        document = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/api/pools?date=2026-08-29"
        ).read().decode("utf-8"))
        assert set(document["data"]["pools"]["watchlist"]) == {"SH600000"}
        assert document["meta"]["public_upstream"] == "unavailable"
    finally:
        server.shutdown()
        server.server_close()


def test_local_service_serves_utf8_member_guide_page():
    MemberHandler.web_root = Path(__file__).parents[1] / "apps" / "web"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urlopen(f"http://127.0.0.1:{server.server_port}/member-guide.html")
        document = response.read().decode("utf-8")
        assert response.headers.get_content_charset() == "utf-8"
        assert "会员本地一体化工作台" in document
        assert "通达信日 K" in document
    finally:
        server.shutdown()
        server.server_close()


def test_sync_public_once_writes_shared_snapshot_atomically(tmp_path):
    payloads = {
        "/sync/manifest": {"data": {"cursor": "abc", "data_date": "2026-08-26"}},
        "/sync/latest": {"data": {"changed": True, "cursor": "abc", "data_date": "2026-08-26",
                                    "stocks": {"SH600000": {"price": 10.2}}}},
    }
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return json.dumps(self.payload).encode()
    def opener(url, timeout=0):
        path = "/sync/manifest" if url.endswith("/sync/manifest") else "/sync/latest"
        return Response(payloads[path])
    result = member_service.sync_public_once(tmp_path, "http://server/dsh/api", opener=opener)
    assert result["ok"] is True
    saved = json.loads((tmp_path / "realtime" / "latest.json").read_text(encoding="utf-8"))
    assert saved["stocks"]["SH600000"]["price"] == 10.2
    assert json.loads((tmp_path / "sync_state.json").read_text(encoding="utf-8"))["cursor"] == "abc"


def test_sync_public_once_verifies_and_promotes_versioned_public_files(tmp_path):
    body = b'{"days":[{"date":"2026-08-28"}]}'
    digest = __import__("hashlib").sha256(body).hexdigest()
    manifest = {"schema_version": "public-sync-v1", "active_trade_date": "2026-08-28",
                "market_status": "closed", "revision": "public-20260828-r1",
                "min_client_version": "1.0.0", "cursor": "c1", "complete": True,
                "datasets": {"auction": {"complete": True}, "strategy": {"complete": True},
                             "history": {"complete": True}},
                "history_archive": {"download_mode": "on_demand", "available_days": 12,
                                    "file_count": 30, "total_bytes": 123456}, "files": [{
                    "path": "web/index.json", "url": "../data/web/index.json",
                    "size": len(body), "sha256": digest, "required": True}]}

    class Response:
        def __init__(self, raw): self.raw = raw
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return self.raw

    static_downloads = []
    def opener(url, timeout=0):
        if url.endswith("/sync/manifest"):
            return Response(json.dumps({"data": manifest}).encode())
        if url.endswith("/data/web/index.json"):
            static_downloads.append(url)
            return Response(body)
        if "/sync/latest" in url:
            return Response(json.dumps({"data": {"changed": True, "cursor": "c1",
                "data_date": "2026-08-28", "stocks": {}}}).encode())
        return Response(json.dumps({"data": {"data_date": "2026-08-28"}}).encode())

    result = member_service.sync_public_once(tmp_path / "shared", "http://server/dsh/api", opener=opener)

    assert result["ok"] is True
    assert result["manifest_verified"] is True
    assert result["revision"] == "public-20260828-r1"
    assert result["complete"] is True
    assert result["datasets"]["strategy"]["complete"] is True
    assert result["history_archive"]["download_mode"] == "on_demand"
    assert result["history_archive"]["available_days"] == 12
    assert result["phase"] == "complete"
    assert result["sync_mode"] == "downloaded"
    assert result["file_count"] == 1
    assert (tmp_path / "shared" / "revisions" / "public-20260828-r1" / "web" / "index.json").read_bytes() == body

    second = member_service.sync_public_once(tmp_path / "shared", "http://server/dsh/api", opener=opener)

    assert second["sync_mode"] == "reused"
    assert static_downloads == ["http://server/dsh/data/web/index.json"]


def test_local_update_check_uses_server_side_same_origin_proxy(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"version":"1.0.18","zip_url":"http://server/package.zip"}'

    calls = []
    monkeypatch.setattr(member_service, "urlopen", lambda url, timeout=0: calls.append((url, timeout)) or Response())
    MemberHandler.upstream_api = "http://server/dsh/api"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        document = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_port}/api/system/update"
        ).read().decode("utf-8"))
        assert document["version"] == "1.0.18"
        assert calls == [("http://server/dsh/downloads/member-workbench-latest.json", 15)]
    finally:
        server.shutdown()
        server.server_close()


def test_sync_public_best_available_prefers_local_api_without_calling_remote(tmp_path):
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return json.dumps(self.payload).encode()
    def opener(url, timeout=0):
        calls.append(url)
        assert url.startswith("http://127.0.0.1:8787/api/")
        if url.endswith("/sync/manifest"):
            return Response({"data": {"cursor": "local-cursor", "data_date": "2026-08-27"}})
        if "/sync/latest" in url:
            return Response({"data": {"changed": True, "cursor": "local-cursor",
                                      "data_date": "2026-08-27", "stocks": {}}})
        return Response({"data": {"data_date": "2026-08-27"}})

    result = member_service.sync_public_best_available(tmp_path, opener=opener)

    assert result["ok"] is True
    assert result["server_scope"] == "local"
    assert all("114.132.236.131" not in url for url in calls)


def test_sync_public_best_available_falls_back_to_remote_when_local_is_down(tmp_path):
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return json.dumps(self.payload).encode()
    def opener(url, timeout=0):
        calls.append(url)
        if url.startswith("http://127.0.0.1:8787/api/"):
            raise OSError("local api unavailable")
        if url.endswith("/sync/manifest"):
            return Response({"data": {"cursor": "remote-cursor", "data_date": "2026-08-27"}})
        if "/sync/latest" in url:
            return Response({"data": {"changed": True, "cursor": "remote-cursor",
                                      "data_date": "2026-08-27", "stocks": {}}})
        return Response({"data": {"data_date": "2026-08-27"}})

    result = member_service.sync_public_best_available(tmp_path, opener=opener)

    assert result["ok"] is True
    assert result["server_scope"] == "remote"
    assert any(url.startswith("http://127.0.0.1:8787/api/") for url in calls)
    assert any("114.132.236.131" in url for url in calls)


def test_member_realtime_result_combines_local_strategy_and_public_quotes(tmp_path, monkeypatch):
    member = tmp_path / "members" / "vip_001"
    kline = member / "kline"
    kline.mkdir(parents=True)
    (kline / "SH600000.json").write_text(json.dumps({"stock_id": "SH600000", "adjusted": "qfq",
        "bars": [{"d": 20260825, "o": 10, "h": 10.5, "l": 9.8, "c": 10, "v": 100, "amt": 1000}]}), encoding="utf-8")
    config = {"member_id": "vip_001", "kline_dir": str(kline)}
    shared = tmp_path / "shared"
    (shared / "realtime").mkdir(parents=True)
    (shared / "realtime" / "latest.json").write_text(json.dumps({"data_date": "2026-08-26",
        "ts": "2026-08-26 10:00:00", "stocks": {"SH600000": {"price": 10.8, "change_pct": 7,
        "vol_ratio": 2.2, "limit_up": 11}}}), encoding="utf-8")
    def fake_baseline(*_args, **_kwargs):
        day = member / "facts" / "2026-08-26"; day.mkdir(parents=True, exist_ok=True)
        (day / "strategy.json").write_text(json.dumps({"SH600000": {"models": {"breakout": 80},
            "score": 80, "buy_point": 10.5, "stop": 9.8, "stop_pct": 2, "rr": 3.5,
            "target": 12, "bp_pass": True, "stars": 4,
            "confirm": {"sector_strength": True, "money_flow": True, "leading_reason": True}}}), encoding="utf-8")
    monkeypatch.setattr(member_service, "_run_member_strategy_baseline", fake_baseline)
    result = member_service.calculate_member_realtime(config, shared)
    assert result["data_date"] == "2026-08-26"
    assert result["quote_count"] == 1
    assert result["model_hits"][0]["stock_id"] == "SH600000"
    assert result["model_hits"][0]["price"] == 10.8
    assert result["actionable_alerts"][0]["quality_score"] == 80
    assert result["actionable_alerts"][0]["confirm"]["money_flow"] is True
    assert (member / "realtime" / "latest.json").exists()


def test_member_strategy_baseline_rebuilds_empty_bootstrap_after_kline_generation(tmp_path, monkeypatch):
    member = tmp_path / "members" / "U100"
    kline = member / "kline"
    kline.mkdir(parents=True)
    (kline / "SH600000.json").write_text(json.dumps({"stock_id": "SH600000", "bars": [
        {"d": 20260827, "o": 10, "h": 11, "l": 9, "c": 10, "v": 1, "amt": 1}
    ]}), encoding="utf-8")
    day = member / "facts" / "2026-08-28"
    day.mkdir(parents=True)
    (day / "strategy.json").write_text("{}", encoding="utf-8")
    calls = []

    shared = tmp_path / "shared"
    (shared / "legacy" / "web").mkdir(parents=True)
    (shared / "legacy" / "web" / "stocks_slim.json").write_text(json.dumps({
        "SH600000": {"n": "浦发银行"}
    }), encoding="utf-8")

    (shared / "legacy" / "web" / "day_2026-08-28.json").write_text(json.dumps({
        "sectors": [{"id": "S1", "strength": 5000}],
        "money_flow": [{"id": "S1", "main": 1}],
        "leading_reason": [{"sector_ids": ["S1"], "reason": "测试"}]
    }), encoding="utf-8")

    def fake_run(date_str, kline_dir, out_root, config_path, universe=None, asof=None,
                 facts_override=None, membership_override=None):
        calls.append((date_str, kline_dir, out_root, config_path, universe, asof,
                      facts_override, membership_override))
        (day / "strategy.json").write_text(json.dumps({"SH600000": {"models": {"breakout": 80}}}),
                                            encoding="utf-8")
        return {"hits": 1}

    monkeypatch.setattr("services.collector.strategy_engine.run_strategy", fake_run)
    config = {"member_id": "U100", "kline_dir": str(kline)}

    member_service._run_member_strategy_baseline(config, "2026-08-28", member, shared)
    member_service._run_member_strategy_baseline(config, "2026-08-28", member, shared)

    assert len(calls) == 1
    marker = json.loads((day / "strategy.member-input.json").read_text(encoding="utf-8"))
    assert marker["kline_count"] == 1
    assert marker["asof"] == 20260827
    assert calls[0][4] == ["SH600000"]
    assert calls[0][6]["sectors"]["S1"]["strength"] == 5000
    assert calls[0][6]["money_flow"]["S1"]["main"] == 1
    assert calls[0][6]["leading_reason"]["S1"]["reason"] == "测试"
    assert calls[0][7] == {"SH600000": []}


def test_member_calculation_revision_changes_with_public_and_kline_inputs(tmp_path, monkeypatch):
    member = tmp_path / "members" / "U100"
    kline = member / "kline"
    kline.mkdir(parents=True)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sync_state.json").write_text(json.dumps({"cursor": "c1", "revision": "p1",
        "data_date": "2026-08-28"}), encoding="utf-8")
    (member / "generation_status.json").write_text(json.dumps({"finished_at": "t1", "generated": 5000}), encoding="utf-8")
    config = {"member_id": "U100", "kline_dir": str(kline)}

    first = member_calculation_revision(config, shared)
    state = json.loads((shared / "sync_state.json").read_text(encoding="utf-8"))
    state["cursor"] = "c2"
    (shared / "sync_state.json").write_text(json.dumps(state), encoding="utf-8")
    second = member_calculation_revision(config, shared)

    assert first != second
    assert len(first) == 64 and len(second) == 64


def test_member_calculation_runs_once_per_revision_and_records_state(tmp_path):
    member = tmp_path / "members" / "U100"
    kline = member / "kline"
    kline.mkdir(parents=True)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "sync_state.json").write_text(json.dumps({"cursor": "c1", "revision": "p1",
        "data_date": "2026-08-28"}), encoding="utf-8")
    config = {"member_id": "U100", "kline_dir": str(kline)}
    calls = []

    def calculate(_config, _shared):
        calls.append(1)
        return {"quote_count": 5000, "model_hits": [1, 2], "actionable_alerts": [1]}

    first = run_member_calculation_once(config, shared, calculate_fn=calculate)
    second = run_member_calculation_once(config, shared, calculate_fn=calculate)

    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert len(calls) == 1
    state = json.loads((member / "runtime" / "calculation_state.json").read_text(encoding="utf-8"))
    assert state["quote_count"] == 5000
    assert state["model_count"] == 2
    assert state["actionable_count"] == 1


def test_member_auction_context_is_point_in_time_private_and_member_local(tmp_path):
    member = tmp_path / "members" / "vip_001"
    kline = member / "kline"
    kline.mkdir(parents=True)
    bars = []
    for index in range(1, 11):
        bars.append({"d": 20260700 + index, "o": 10, "h": 10.2, "l": 9.9,
                     "c": 10 + index * 0.02, "v": 100, "amt": 1000})
    bars.append({"d": 20260711, "o": 10.2, "h": 11.2, "l": 10.15, "c": 11.1, "v": 300, "amt": 3300})
    for day, close, volume in [(12, 10.95, 150), (13, 10.82, 130), (14, 10.9, 115),
                               (15, 10.98, 105), (16, 11.08, 95), (17, 11.14, 90)]:
        bars.append({"d": 20260700 + day, "o": close, "h": close + 0.05,
                     "l": close - 0.1, "c": close, "v": volume, "amt": volume * close})
    # 目标日及未来 K 线不得参与目标日前置形态。
    bars.append({"d": 20260826, "o": 20, "h": 22, "l": 19, "c": 22, "v": 9999, "amt": 1})
    (kline / "SH600001.json").write_text(json.dumps({
        "stock_id": "SH600001", "adjusted": "qfq", "bars": bars}), encoding="utf-8")
    config = {"member_id": "vip_001", "kline_dir": str(kline)}

    document, path = member_service.build_member_auction_context(config, "2026-08-26", member)

    assert path == member / "facts" / "2026-08-26" / "auction_context.json"
    assert document["private"] is True
    assert document["input_asof"] == 20260717
    assert document["stocks"]["SH600001"]["state"] == "near_breakout"
    assert str(tmp_path) not in json.dumps(document, ensure_ascii=False)


def test_member_auction_merge_adds_private_pattern_and_risk_without_mutating_public():
    public = {"phase": "auction", "config_version": "1.0", "candidates": [{
        "stock_id": "SH600001", "potential_grade": "A", "tradability": "wait"}]}
    context = {"stocks": {"SH600001": {"state": "near_breakout", "platform_upper": 11.2,
                                         "invalidation_price": 10.1}}}
    strategy = {"SH600001": {"models": {"breakout": 80}, "rr": 3.5, "stop": 10.0,
                               "buy_point": 10.6, "bp_pass": True}}
    merged = member_service.merge_member_auction_radar(public, context, strategy)
    row = merged["candidates"][0]
    assert merged["private"] is True and merged["local_merged"] is True
    assert row["local_pattern"]["state"] == "near_breakout"
    assert row["local_risk"] == {"rr": 3.5, "stop": 10.0, "buy_point": 10.6, "bp_pass": True}
    assert row["local_model_hit"] == ["breakout"]
    assert "local_pattern" not in public["candidates"][0]


def test_member_auction_merge_uses_private_lc1_baseline_to_promote_watch_candidate():
    public = {"phase": "auction", "config_version": "1.0", "candidates": [{
        "stock_id": "SH600001", "trajectory": "steady_strengthen",
        "potential_grade": "watch", "tradability": "wait",
        "auction_volume": 250, "auction_amount": 20_000_000, "final_gap": 0.05,
    }]}
    baseline = {
        "data_date": "2026-08-26", "source": "tdx_vipdoc_lc1", "private": True,
        "quality": {"status": "pass", "coverage": 1.0},
        "stocks": {"SH600001": {"max_1m_volume": 100, "max_1m_volume_time": "10:09",
                                    "day_amount": 100_000_000}},
    }
    config = {"trajectory": {"min_yesterday_max_1m_volume_ratio": 1.0,
                              "min_yesterday_amount_ratio": 0.03,
                              "min_auction_amount": 10_000_000,
                              "final_gap_min": 0.01, "final_gap_max": 0.07}}

    merged = member_service.merge_member_auction_radar(
        public, {"stocks": {}}, {}, minute_baseline=baseline,
        radar_config=config, target_date="2026-08-27",
    )

    row = merged["candidates"][0]
    assert row["auction_max_1m_volume_ratio"] == 2.5
    assert row["yesterday_max_1m_volume"] == 100
    assert row["yesterday_max_1m_volume_time"] == "10:09"
    assert row["potential_grade"] == "A"
    assert row["local_baseline"] is True
    assert "local_lc1_volume_gate" in row["evidence"]
    assert merged["baseline_source"] == "tdx_vipdoc_lc1"
    assert merged["baseline_source_date"] == "2026-08-26"


@pytest.mark.parametrize("baseline", [
    {"data_date": "2026-08-27", "source": "tdx_vipdoc_lc1", "private": True,
     "quality": {"status": "pass"}, "stocks": {"SH600001": {"max_1m_volume": 100}}},
    {"data_date": "2026-08-26", "source": "tdx_vipdoc_lc1", "private": True,
     "quality": {"status": "fail"}, "stocks": {"SH600001": {"max_1m_volume": 100}}},
])
def test_member_auction_merge_fails_closed_for_invalid_local_baseline(baseline):
    public = {"candidates": [{"stock_id": "SH600001", "trajectory": "steady_strengthen",
                              "potential_grade": "watch", "auction_volume": 250}]}
    merged = member_service.merge_member_auction_radar(
        public, {"stocks": {}}, {}, minute_baseline=baseline,
        radar_config={"trajectory": {"min_yesterday_max_1m_volume_ratio": 1.0}},
        target_date="2026-08-27",
    )
    row = merged["candidates"][0]
    assert row["potential_grade"] == "watch"
    assert row.get("local_baseline") is not True
    assert "local_minute_baseline_invalid" in row["failed_evidence"]


def test_member_minute_volume_uses_private_lc1_baseline_and_history():
    public = {"available": True, "data_date": "2026-08-31", "minute": "14:31", "rows": [{
        "stock_id": "SH600001", "name": "甲公司", "minute_volume": 250,
        "minute_amount": 5000, "price": 10.5, "change_pct": 5.0,
        "price_volume_type": "上涨放量", "sectors": ["S1"],
    }], "detail": {"stock_id": "SH600001", "current_series": [
        {"minute": "14:30", "volume": 100, "price": 10.0},
        {"minute": "14:31", "volume": 250, "price": 10.5},
    ]}}
    baseline = {"data_date": "2026-08-28", "source": "tdx_vipdoc_lc1", "private": True,
                "quality": {"status": "pass", "coverage": .98, "valid_stocks": 1},
                "stocks": {"SH600001": {"max_1m_volume": 100, "max_1m_amount": 2000}}}
    history = [{"date": "2026-08-28", "series": [{"minute": "14:31", "volume": 80}]},
               {"date": "2026-08-27", "series": [{"minute": "14:31", "volume": 90}]}]
    result = member_service.merge_member_minute_volume_source(
        public, baseline, history, min_ratio=1.5, selected_sid="SH600001",
        watchlist={"SH600001": {"status": "active"}})
    assert result["available"] is True and result["private"] is True
    assert result["rows"][0]["volume_ratio"] == 2.5
    assert result["rows"][0]["selected"] is True
    assert [day["date"] for day in result["detail"]["volume_days"]] == [
        "2026-08-31", "2026-08-28", "2026-08-27"]
    assert result["baseline_source"] == "tdx_vipdoc_lc1"


def test_member_expands_compact_public_minute_source_before_local_merge():
    public = {"available": True, "schema_version": "minute-source-v2",
              "data_date": "2026-08-31", "minute": "14:31",
              "fields": ["stock_id", "volume", "amount", "price", "change_pct"],
              "rows": [["SH600001", 250, 5000, 10.5, 5.0]]}
    expanded = member_service.expand_public_minute_source(public)
    assert expanded["rows"] == [{"stock_id": "SH600001", "minute_volume": 250,
                                  "minute_amount": 5000, "price": 10.5,
                                  "change_pct": 5.0, "minute": "14:31"}]


def test_member_minute_volume_is_comparable_when_current_minute_has_no_peak_breaks():
    result = member_service.merge_member_minute_volume_source(
        {"available": True, "data_date": "2026-08-31", "rows": [{
            "stock_id": "SH600001", "minute_volume": 50, "minute_amount": 1000,
            "sectors": []}]},
        {"data_date": "2026-08-28", "source": "tdx_vipdoc_lc1", "private": True,
         "quality": {"status": "pass"},
         "stocks": {"SH600001": {"max_1m_volume": 100}}},
        [], min_ratio=1.0)
    assert result["available"] is True
    assert result["rows"] == []
    assert result["quality"]["status"] == "pass"


def test_monitoring_dashboard_summarizes_public_and_private_results(tmp_path):
    member = tmp_path / "members" / "vip_001"
    (member / "facts" / "2026-08-26").mkdir(parents=True)
    (member / "realtime").mkdir(parents=True)
    (member / "facts" / "2026-08-26" / "strategy.json").write_text(json.dumps({
        "SH600000": {"score": 88, "models": {"breakout": 88}}
    }), encoding="utf-8")
    (member / "realtime" / "latest.json").write_text(json.dumps({"data_date": "2026-08-26",
        "ts": "2026-08-26 14:59:00", "quote_count": 5000, "model_hits": [{"stock_id": "SH600000"}],
        "actionable_alerts": [{"stock_id": "SH600000"}], "events": [{"type": "signal_hit"}]}), encoding="utf-8")
    shared = tmp_path / "shared"; (shared / "public").mkdir(parents=True)
    (shared / "sync_state.json").write_text(json.dumps({"ok": True, "cursor": "c1"}), encoding="utf-8")
    (shared / "public" / "latest.json").write_text(json.dumps({"data_date": "2026-08-26",
        "limitup": [{"stock_id": "SZ000001"}], "actionable_alerts": [{"stock_id": "SZ000002"}],
        "events": [{"type": "limitup"}, {"type": "broken"}]}), encoding="utf-8")
    config = {"member_id": "vip_001", "kline_dir": str(member / "kline")}
    dashboard = member_service.monitoring_dashboard(config, shared)
    assert dashboard["monitoring"] is True
    assert dashboard["baseline_count"] == 1
    assert dashboard["public"]["limitup_count"] == 1
    assert dashboard["local"]["actionable_count"] == 1


def test_runtime_status_requires_fresh_sync_valid_license_and_successful_calculation(tmp_path):
    data_root = tmp_path / "data"
    shared, runtime, members = data_root / "shared", data_root / "runtime", data_root / "members"
    shared.mkdir(parents=True); runtime.mkdir(); members.mkdir()
    now = datetime.datetime(2026, 8, 28, 10, 0, 30)
    (shared / "sync_state.json").write_text(json.dumps({"ok": True, "data_date": "2026-08-28",
        "synced_at": "2026-08-28T10:00:00", "revision": "p1", "cursor": "c1",
        "manifest_verified": True, "complete": True, "datasets": {"auction": {"complete": True},
        "strategy": {"complete": True}, "history": {"complete": True}}}), encoding="utf-8")
    (runtime / "license.json").write_text(json.dumps({"member_id": "U100", "device_fingerprint": "DEV-1",
        "status": "active", "checked_at": "2026-08-28T09:00:00", "expire_timestamp": 1798761600}), encoding="utf-8")
    state = members / "U100" / "runtime" / "calculation_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"status": "success", "quote_count": 5000, "model_count": 20,
        "finished_at": "2026-08-28T10:00:05", "revision": "calc1"}), encoding="utf-8")

    status = build_runtime_status(data_root, shared, runtime, members, now=now)

    assert status["monitoring"] is True
    assert status["sync"]["fresh"] is True
    assert status["license"]["valid"] is True
    assert status["calculation"]["status"] == "success"
    assert status["calculation"]["quote_count"] == 5000


def test_runtime_status_reports_stale_sync_instead_of_monitoring(tmp_path):
    root = tmp_path / "data"
    shared, runtime, members = root / "shared", root / "runtime", root / "members"
    shared.mkdir(parents=True); runtime.mkdir(); members.mkdir()
    (shared / "sync_state.json").write_text(json.dumps({"ok": True,
        "synced_at": "2026-08-28T09:50:00"}), encoding="utf-8")
    status = build_runtime_status(root, shared, runtime, members,
                                  now=datetime.datetime(2026, 8, 28, 10, 0, 0))
    assert status["monitoring"] is False
    assert status["sync"]["fresh"] is False


def test_runtime_status_uses_closed_market_polling_window_for_freshness(tmp_path):
    root = tmp_path / "data"
    shared, runtime, members = root / "shared", root / "runtime", root / "members"
    shared.mkdir(parents=True); runtime.mkdir(); members.mkdir()
    (shared / "sync_state.json").write_text(json.dumps({"ok": True, "market_status": "closed",
        "synced_at": "2026-08-28T15:30:00"}), encoding="utf-8")

    fresh = build_runtime_status(root, shared, runtime, members,
                                 now=datetime.datetime(2026, 8, 28, 15, 35, 0))
    stale = build_runtime_status(root, shared, runtime, members,
                                 now=datetime.datetime(2026, 8, 28, 15, 41, 1))

    assert fresh["sync"]["fresh"] is True
    assert fresh["sync"]["freshness_limit_seconds"] == 660
    assert stale["sync"]["fresh"] is False


def test_normalize_member_config_keeps_private_paths_under_member_root(tmp_path):
    tdx_root = tmp_path / "tdx"
    vipdoc = tdx_root / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True)
    (tdx_root / "T0002" / "hq_cache").mkdir(parents=True)
    (tdx_root / "T0002" / "hq_cache" / "gbbq").write_bytes(b"")
    cfg = normalize_member_config({"member_id": "vip_001", "vipdoc": str(vipdoc),
                                   "tdx_root": str(tdx_root)}, tmp_path / "members")
    assert cfg["member_id"] == "vip_001"
    assert cfg["vipdoc"] == str(vipdoc.resolve())
    assert cfg["kline_dir"] == str((tmp_path / "members" / "vip_001" / "kline").resolve())
    assert cfg["vipdoc_valid"] is True
    assert cfg["tdx_root"] == str(tdx_root.resolve())
    assert cfg["gbbq_path"].endswith("T0002\\hq_cache\\gbbq") or cfg["gbbq_path"].endswith("T0002/hq_cache/gbbq")
    assert cfg["gbbq_valid"] is True


def test_normalize_member_config_rejects_unsafe_member_id(tmp_path):
    with pytest.raises(ValueError):
        normalize_member_config({"member_id": "../other", "vipdoc": "C:/tdx/vipdoc"}, tmp_path)


def test_save_member_config_is_member_scoped(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True)
    result = save_member_config({"member_id": "member_a", "vipdoc": str(vipdoc)}, tmp_path / "members")
    path = tmp_path / "members" / "member_a" / "config.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["member_id"] == "member_a"
    assert result["kline_dir"].endswith("member_a\\kline") or result["kline_dir"].endswith("member_a/kline")


def test_frozen_helper_installs_only_in_current_user_directories(tmp_path):
    paths = install_paths(local_appdata=tmp_path / "Local", appdata=tmp_path / "Roaming")
    assert paths["exe"] == tmp_path / "Local" / "JinshiDSH" / "bin" / "JinshiDSH-MemberHelper-1.0.27.exe"
    assert "Startup" in str(paths["startup"])
    command = startup_command(paths["exe"])
    assert str(paths["exe"]) in command
    assert "--serve" in command


def test_install_reuses_running_target_when_windows_denies_replacement(tmp_path, monkeypatch):
    source = tmp_path / "download.exe"
    source.write_bytes(b"new helper")
    target = tmp_path / "Local" / "JinshiDSH" / "bin" / "JinshiDSH-MemberHelper-1.0.27.exe"
    startup = tmp_path / "Roaming" / "Startup" / "JinshiDSH-MemberHelper.cmd"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"running helper")
    monkeypatch.setattr(member_service, "install_paths", lambda: {"exe": target, "startup": startup})
    monkeypatch.setattr(member_service.os, "replace", lambda *_: (_ for _ in ()).throw(PermissionError(5, "拒绝访问")))

    installed = install_frozen_helper(source)

    assert installed == target
    assert target.read_bytes() == b"running helper"
    assert not Path(str(target).replace(".exe", ".tmp.exe")).exists()
    assert startup.exists()


def test_installation_status_message_distinguishes_first_install_and_running():
    assert "安装成功" in installation_status_message(False)
    assert "助手已运行" in installation_status_message(True)


def test_upgrade_knows_only_older_versioned_helper_process_names():
    names = older_helper_image_names()
    assert "JinshiDSH-MemberHelper-1.0.0.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.4.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.5.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.6.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.7.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.8.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.9.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.10.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.11.exe" in names
    assert "JinshiDSH-MemberHelper-1.0.27.exe" not in names


def test_jsonp_fallback_is_read_only_and_cannot_save_member_config(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True)
    MemberHandler.members_root = tmp_path / "members"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/compat"
    try:
        health = urlopen(base + "?callback=cb&action=health").read().decode("utf-8")
        assert health.startswith("cb(") and '"ok": true' in health
        from urllib.parse import quote
        denied = urlopen(base + "?callback=cb&action=save&member_id=vip_001&vipdoc=" + quote(str(vipdoc))).read().decode("utf-8")
        assert '"ok": false' in denied
        assert not (tmp_path / "members" / "vip_001" / "config.json").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_jsonp_realtime_uses_active_local_member_when_browser_has_no_member_id(tmp_path, monkeypatch):
    monkeypatch.setattr(MemberHandler, "_active_member_id", lambda self: "U100")
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U100")
    MemberHandler.members_root = tmp_path / "members"
    member = tmp_path / "members" / "U100"
    (member / "kline").mkdir(parents=True)
    (member / "config.json").write_text(json.dumps({"member_id": "U100",
        "kline_dir": str(member / "kline")}), encoding="utf-8")
    realtime = tmp_path / "members" / "U100" / "realtime" / "latest.json"
    realtime.parent.mkdir(parents=True)
    realtime.write_text(json.dumps({"available": True, "data_date": "2026-09-01",
                                    "actionable_alerts": [{"stock_id": "SH600000"}]}), encoding="utf-8")
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = urlopen(f"http://127.0.0.1:{server.server_port}/api/compat?callback=cb&action=signal").read().decode("utf-8")
        assert '"ok": true' in body
        assert '"stock_id": "SH600000"' in body
        assert '"auction_radar"' not in body
    finally:
        server.shutdown()
        server.server_close()


def test_local_member_page_saves_without_cross_origin_fetch(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True)
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.license_required = False
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = urlencode({"member_id": "vip_001", "vipdoc": str(vipdoc)}).encode()
        response = urlopen(Request(f"http://127.0.0.1:{server.server_port}/member/save", data=payload,
                                   headers={"X-Jinshi-Local-Token": MemberHandler.local_token}))
        html = response.read().decode("utf-8")
        assert "保存成功，vipdoc 有效" in html
        assert "本地日 K 配置" in html
        assert "通达信根目录（复权权息数据）" in html
        assert "保存配置并生成会员 K 线" in html
        assert "监控运行状态" in html
        assert "公共信号" in html
        assert "策略基线" in html
        assert "本地可买预警" in html
        assert (tmp_path / "members" / "vip_001" / "config.json").exists()
    finally:
        MemberHandler.license_required = True
        server.shutdown()
        server.server_close()


def test_member_config_read_is_blocked_without_valid_cloud_license(tmp_path):
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.runtime_root = tmp_path / "runtime"
    MemberHandler.license_required = True
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/api/member/config?member_id=U100")
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_local_write_api_rejects_missing_token(tmp_path):
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.local_token = "test-local-token"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f"http://127.0.0.1:{server.server_port}/api/member/config",
                          data=json.dumps({"member_id": "vip_001", "vipdoc": "D:/tdx/vipdoc"}).encode(),
                          headers={"Content-Type": "application/json"})
        with pytest.raises(HTTPError) as exc:
            urlopen(request)
        assert exc.value.code == 403
        assert not (tmp_path / "members" / "vip_001" / "config.json").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_member_generate_json_endpoint_saves_config_and_starts_generation(tmp_path, monkeypatch):
    vipdoc = tmp_path / "tdx" / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True)
    MemberHandler.members_root = tmp_path / "members"
    MemberHandler.local_token = "generate-token"
    monkeypatch.setattr(MemberHandler, "_member_authorized", lambda self, value: value == "U-GENERATE")
    calls = []
    monkeypatch.setattr(member_service, "start_member_generation",
                        lambda config: calls.append(config) or {"state": "running"})
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f"http://127.0.0.1:{server.server_port}/api/member/generate",
                          data=json.dumps({"member_id": "U-GENERATE", "vipdoc": str(vipdoc),
                                           "tdx_root": str(vipdoc.parent)}).encode(),
                          headers={"Content-Type": "application/json",
                                   "X-Jinshi-Local-Token": "generate-token"})
        document = json.loads(urlopen(request).read().decode("utf-8"))
        assert document["ok"] is True
        assert document["data"]["vipdoc_valid"] is True
        assert document["generation"]["state"] == "running"
        assert calls[0]["member_id"] == "U-GENERATE"
    finally:
        server.shutdown()
        server.server_close()


def test_setup_page_saves_selected_data_root_without_moving_legacy_data(tmp_path):
    legacy = tmp_path / "Local" / "JinshiDSH"
    legacy.mkdir(parents=True)
    legacy_marker = legacy / "members" / "old-member" / "config.json"
    legacy_marker.parent.mkdir(parents=True)
    legacy_marker.write_text('{"member_id":"old-member"}', encoding="utf-8")
    selected = tmp_path / "H" / "JinshiDSHData"
    MemberHandler.bootstrap_path = legacy / "bootstrap.json"
    MemberHandler.data_root = legacy
    MemberHandler.local_token = "setup-token"
    server = member_service.ThreadingHTTPServer(("127.0.0.1", 0), MemberHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        page = urlopen(base + "/setup").read().decode("utf-8")
        assert "数据根目录" in page
        payload = urlencode({"data_root": str(selected)}).encode()
        response = urlopen(Request(base + "/setup/save", data=payload,
                                   headers={"X-Jinshi-Local-Token": "setup-token"}))
        saved_page = response.read().decode("utf-8")
        assert "重启本地工作台后生效" in saved_page
        assert load_bootstrap(MemberHandler.bootstrap_path)["data_root"] == str(selected.resolve())
        assert legacy_marker.is_file()
        assert (selected / "shared").is_dir()
        assert (selected / "members").is_dir()
    finally:
        server.shutdown()
        server.server_close()


def test_generate_member_klines_scans_vipdoc_and_writes_qfq_json(tmp_path):
    vipdoc = tmp_path / "tdx" / "vipdoc"
    lday = vipdoc / "sh" / "lday"
    lday.mkdir(parents=True)
    record = struct.Struct("<IIIIIfII")
    (lday / "sh600000.day").write_bytes(
        record.pack(20260825, 1000, 1100, 900, 1050, 12345.0, 6789, 0)
    )
    cfg = normalize_member_config({"member_id": "vip_001", "vipdoc": str(vipdoc),
                                   "tdx_root": str(tmp_path / "tdx")}, tmp_path / "members")

    result = generate_member_klines(cfg)

    assert result["generated"] == 1
    output = json.loads((Path(cfg["kline_dir"]) / "SH600000.json").read_text(encoding="utf-8"))
    assert output["stock_id"] == "SH600000"
    assert output["adjusted"] == "qfq"
    assert output["bars"][-1]["d"] == 20260825
