"""复用云授权中心会员数据，为本地工作台提供在线校验与短期离线门禁。"""
import datetime
import json
import os
import re
import threading
from pathlib import Path
from urllib.request import Request, urlopen

_LICENSE_LOCK = threading.RLock()
_MAINTENANCE_THREAD = None


def _cache_path(runtime_root):
    return Path(runtime_root) / "license.json"


def load_license_cache(runtime_root):
    path = _cache_path(runtime_root)
    if not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        return document if isinstance(document, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_license_cache(runtime_root, document):
    path = _cache_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def refresh_cloud_license(action, payload, runtime_root, license_api, opener=urlopen, now=None):
    with _LICENSE_LOCK:
        return _refresh_cloud_license(action, payload, runtime_root, license_api, opener, now)


def _refresh_cloud_license(action, payload, runtime_root, license_api, opener=urlopen, now=None):
    if action not in ("activate", "validate", "trial/register"):
        raise ValueError("unsupported license action")
    payload = dict(payload or {})
    cached = load_license_cache(runtime_root)
    submitted_code = str(payload.get("code") or "").strip().upper()
    cached_code = str(cached.get("code") or "").strip().upper()
    # 8790 的私有缓存是本机授权真源。浏览器升级或换来源后无需再次持有密钥；
    # 同一码重复激活也必须沿用原设备绑定，不能让临时浏览器指纹制造“换设备”。
    if action == "validate" and not submitted_code and cached_code:
        payload["code"] = cached_code
        payload["device_fingerprint"] = cached.get("device_fingerprint")
        submitted_code = cached_code
    elif action == "activate" and submitted_code and submitted_code == cached_code:
        payload["device_fingerprint"] = cached.get("device_fingerprint")
    device = str(payload.get("device_fingerprint") or "").strip()
    if not device or not re.fullmatch(r"[A-Za-z0-9._-]{4,128}", device):
        raise ValueError("invalid device fingerprint")
    if action == "trial/register":
        name = str((payload or {}).get("name") or "").strip()[:40]
        phone = re.sub(r"\s+", "", str((payload or {}).get("phone") or ""))
        if not name or not re.fullmatch(r"1\d{10}", phone):
            raise ValueError("invalid trial registration")
        request_body = {"name": name, "phone": phone, "device_fingerprint": device}
        code = ""
    else:
        code = str(payload.get("code") or "").strip().upper()
        if not code or not re.fullmatch(r"[A-Za-z0-9-]{4,128}", code):
            raise ValueError("invalid license code")
        request_body = {"code": code, "device_fingerprint": device}
        if action == "activate" and payload.get("user_name"):
            request_body["user_name"] = str(payload["user_name"])[:80]
        if action == "activate" and payload.get("phone"):
            request_body["phone"] = str(payload["phone"])[:30]
    request = Request(license_api.rstrip("/") + "/" + action,
                      data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    with opener(request, timeout=15) as response:
        document = json.loads(response.read().decode("utf-8"))
    user = document.get("user") or {} if isinstance(document, dict) else {}
    if document.get("success") is True and user.get("id") and user.get("status") == "active":
        checked = now or datetime.datetime.now()
        cache = {"schema_version": "local-license-v1", "member_id": str(user["id"]),
                 "device_fingerprint": device, "code": code, "status": "active",
                 "plan": user.get("plan"), "expire_date": user.get("expire_date"),
                 "expire_timestamp": user.get("expire_timestamp"),
                 "remaining_days": user.get("remaining_days"),
                 "checked_at": checked.isoformat(timespec="seconds")}
        _save_license_cache(runtime_root, cache)
    elif document.get('success') is False and cached_code == code and cached.get('device_fingerprint') == device:
        # Explicit cloud rejection is not a network outage; do not continue offline use.
        _save_license_cache(runtime_root, {**cached, 'status': 'rejected'})
    return document


def refresh_cached_license_if_due(runtime_root, license_api, now=None, refresher=None):
    """Renew independently of market polling; never extend offline trust on failure."""
    if not _LICENSE_LOCK.acquire(blocking=False):
        return {'status': 'busy'}
    try:
        clock = now or datetime.datetime.now()
        cache = load_license_cache(runtime_root)
        if not cache.get('code') or not cache.get('device_fingerprint'):
            return {'status': 'not_configured'}
        try:
            age = (clock - datetime.datetime.fromisoformat(cache.get('checked_at') or '')).total_seconds()
            if 0 <= age < 6 * 3600 and license_allows_member(cache, cache.get('member_id'), cache.get('device_fingerprint'), now=clock):
                return {'status': 'fresh'}
        except (ValueError, TypeError):
            pass
        path = Path(runtime_root) / 'license_refresh.json'
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
            elapsed = (clock - datetime.datetime.fromisoformat(previous['attempted_at'])).total_seconds()
            if 0 <= elapsed < 300:
                return previous
        except (OSError, ValueError, KeyError, TypeError):
            pass
        state = {'attempted_at': clock.isoformat(timespec='seconds')}
        try:
            result = (refresher or refresh_cloud_license)('validate', {}, runtime_root, license_api, now=clock)
            state['status'] = 'success' if result.get('success') is True else 'rejected'
        except Exception as exc:
            state.update(status='network_error', error_type=type(exc).__name__)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        os.replace(temporary, path)
        return state
    finally:
        _LICENSE_LOCK.release()


def start_license_maintenance(runtime_root, license_api):
    global _MAINTENANCE_THREAD
    if _MAINTENANCE_THREAD and _MAINTENANCE_THREAD.is_alive():
        return _MAINTENANCE_THREAD
    def worker():
        import time
        while True:
            try:
                refresh_cached_license_if_due(runtime_root, license_api)
            except Exception:
                pass  # Storage failure does not terminate market collection.
            time.sleep(60)
    _MAINTENANCE_THREAD = threading.Thread(target=worker, name='member-license-maintenance', daemon=True)
    _MAINTENANCE_THREAD.start()
    return _MAINTENANCE_THREAD


def license_allows_member(cache, member_id, device_fingerprint, now=None, grace_hours=24):
    if not isinstance(cache, dict) or cache.get("status") != "active":
        return False
    if str(cache.get("member_id") or "") != str(member_id or ""):
        return False
    if str(cache.get("device_fingerprint") or "") != str(device_fingerprint or ""):
        return False
    try:
        checked = datetime.datetime.fromisoformat(str(cache.get("checked_at") or ""))
        current = now or datetime.datetime.now()
        if current < checked or current - checked > datetime.timedelta(hours=grace_hours):
            return False
        expires = float(cache.get("expire_timestamp") or 0)
        if expires <= current.timestamp():
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    return True
