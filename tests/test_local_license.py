import datetime
import json

from services.local_license import (license_allows_member, load_license_cache,
                                    refresh_cloud_license)


class Response:
    def __init__(self, document):
        self.document = document
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self): return json.dumps(self.document).encode("utf-8")


def test_refresh_cloud_license_uses_existing_validate_contract_and_caches_member(tmp_path):
    calls = []
    cloud = {"success": True, "message": "校验通过", "user": {
        "id": "U100", "status": "active", "plan": "year",
        "expire_timestamp": 1798761600, "remaining_days": 100,
        "code": "AK-TEST", "name": "会员"}}

    def opener(request, timeout=0):
        calls.append((request.full_url, json.loads(request.data), timeout))
        return Response(cloud)

    result = refresh_cloud_license("validate", {"code": "ak-test", "device_fingerprint": "DEV-1"},
                                   tmp_path, "http://server:18908/api", opener=opener,
                                   now=datetime.datetime(2026, 8, 28, 9, 0, 0))

    assert result == cloud
    assert calls == [("http://server:18908/api/validate",
                      {"code": "AK-TEST", "device_fingerprint": "DEV-1"}, 15)]
    cache = load_license_cache(tmp_path)
    assert cache["member_id"] == "U100"
    assert cache["device_fingerprint"] == "DEV-1"
    assert cache["checked_at"] == "2026-08-28T09:00:00"
    assert cache["code"] == "AK-TEST"


def test_invalid_cloud_response_does_not_overwrite_previous_valid_cache(tmp_path):
    valid = {"success": True, "user": {"id": "U100", "status": "active",
        "expire_timestamp": 1798761600, "code": "AK-TEST"}}
    refresh_cloud_license("validate", {"code": "AK-TEST", "device_fingerprint": "DEV-1"},
                          tmp_path, "http://server/api", opener=lambda *_args, **_kwargs: Response(valid),
                          now=datetime.datetime(2026, 8, 28, 9, 0, 0))
    denied = {"success": False, "message": "账号已停用"}
    result = refresh_cloud_license("validate", {"code": "AK-TEST", "device_fingerprint": "DEV-1"},
                                   tmp_path, "http://server/api",
                                   opener=lambda *_args, **_kwargs: Response(denied),
                                   now=datetime.datetime(2026, 8, 28, 10, 0, 0))
    assert result == denied
    assert load_license_cache(tmp_path)["checked_at"] == "2026-08-28T09:00:00"
    cache = load_license_cache(tmp_path)
    assert not license_allows_member(cache, 'U100', 'DEV-1', now=datetime.datetime(2026,8,28,10))


def test_offline_license_gate_requires_same_member_device_fresh_check_and_unexpired_user():
    cache = {"member_id": "U100", "device_fingerprint": "DEV-1", "status": "active",
             "checked_at": "2026-08-28T09:00:00", "expire_timestamp": 1798761600}
    now = datetime.datetime(2026, 8, 28, 20, 0, 0)
    assert license_allows_member(cache, "U100", "DEV-1", now=now, grace_hours=24) is True
    assert license_allows_member(cache, "U200", "DEV-1", now=now, grace_hours=24) is False
    assert license_allows_member(cache, "U100", "DEV-X", now=now, grace_hours=24) is False
    assert license_allows_member(cache, "U100", "DEV-1",
                                 now=datetime.datetime(2026, 8, 29, 10, 0, 1), grace_hours=24) is False
