import json
from pathlib import Path


def test_validate_without_browser_secret_reuses_private_cached_license(tmp_path):
    from services.local_license import refresh_cloud_license

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "license.json").write_text(json.dumps({
        "code": "AK-AAAA-BBBB-CCCC-D",
        "device_fingerprint": "DEV-STABLE-DEVICE",
    }), encoding="utf-8")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self):
            return json.dumps({"success": True, "message": "校验通过", "user": {
                "id": "U100", "status": "active", "plan": "member",
                "expire_date": "2026-12-31", "remaining_days": 100,
            }}).encode("utf-8")

    def opener(request, timeout=0):
        captured.update(json.loads(request.data.decode("utf-8")))
        return Response()

    result = refresh_cloud_license("validate", {}, runtime, "http://license/api", opener=opener)

    assert result["success"] is True
    assert captured == {"code": "AK-AAAA-BBBB-CCCC-D",
                        "device_fingerprint": "DEV-STABLE-DEVICE"}


def test_repeat_activation_of_cached_code_keeps_original_device_binding(tmp_path):
    from services.local_license import refresh_cloud_license

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "license.json").write_text(json.dumps({
        "code": "AK-AAAA-BBBB-CCCC-D", "device_fingerprint": "DEV-ORIGINAL",
    }), encoding="utf-8")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self):
            return json.dumps({"success": True, "user": {
                "id": "U100", "status": "active", "plan": "member",
                "expire_date": "2026-12-31", "remaining_days": 100,
            }}).encode("utf-8")

    def opener(request, timeout=0):
        captured.update(json.loads(request.data.decode("utf-8")))
        return Response()

    refresh_cloud_license("activate", {
        "code": "AK-AAAA-BBBB-CCCC-D", "device_fingerprint": "DEV-BROWSER-NEW",
    }, runtime, "http://license/api", opener=opener)

    assert captured["device_fingerprint"] == "DEV-ORIGINAL"


def test_local_member_ui_restores_server_side_license_and_does_not_store_code():
    js = (Path(__file__).parents[1] / "apps" / "web" / "assets" / "app.js").read_text(
        encoding="utf-8")
    load = js[js.index("function loadMemberLicense()"):
              js.index("function openMemberCenter()")]
    persist = js[js.index("function persistMemberLicense"):
                 js.index("function activateMemberLicense")]

    assert "fetchJSON('/api/system/status', 'no-store')" in load
    assert "doc.license" in load
    assert "memberIsLocalWorkbench() ? '' : code" in persist
    assert "licenseJSON('/validate', memberIsLocalWorkbench() ? {}" in js
