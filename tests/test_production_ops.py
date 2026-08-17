import json
from pathlib import Path

from services.collector.production_ops import create_backup, restore_backup, scan_secrets, verify_backup


def test_backup_verify_and_restore(tmp_path):
    root = tmp_path / "project"
    (root / "data" / "normalized").mkdir(parents=True)
    (root / "data" / "normalized" / "stocks.json").write_text('{"ok": 1}', encoding="utf-8")
    backup = create_backup(root, tmp_path / "backups", paths=["data/normalized"])
    assert verify_backup(backup)["ok"] is True
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    assert (restored / "data" / "normalized" / "stocks.json").read_text(encoding="utf-8") == '{"ok": 1}'


def test_verify_detects_corruption(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "value.txt").write_text("good", encoding="utf-8")
    backup = create_backup(root, tmp_path / "backups", paths=["value.txt"])
    (backup / "files" / "value.txt").write_text("bad", encoding="utf-8")
    assert verify_backup(backup)["ok"] is False


def test_secret_scan_flags_real_value_and_allows_placeholder(tmp_path):
    fake_secret = "sk-" + "live-12345678901234567890"
    (tmp_path / "bad.json").write_text(json.dumps({"api_token": fake_secret}), encoding="utf-8")
    (tmp_path / "ok.env.example").write_text("API_TOKEN=${API_TOKEN}\n", encoding="utf-8")
    findings = scan_secrets(tmp_path)
    assert [item["path"] for item in findings] == ["bad.json"]
