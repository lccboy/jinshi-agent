# -*- coding: utf-8 -*-
"""V0.5 生产运维：备份、校验、隔离恢复与仓库密钥扫描。"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


DEFAULT_PATHS = ("data/normalized", "data/facts", "data/archive", "data/web", "data/runs", "config")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "data", "backups"}
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])-[-A-Za-z0-9_]{16,}\b"),
    re.compile(r"(?i)(?:api[_-]?key|api[_-]?token|password|secret)\s*[=:]\s*[\"']?([^\s\"']{12,})"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(root, paths):
    for relative in paths:
        source = root / relative
        if source.is_file():
            yield source, Path(relative)
        elif source.is_dir():
            for item in sorted(source.rglob("*")):
                if item.is_file():
                    yield item, item.relative_to(root)


def create_backup(root, backup_root, paths=DEFAULT_PATHS, keep=14):
    root, backup_root = Path(root).resolve(), Path(backup_root).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    temp = Path(tempfile.mkdtemp(prefix=f".{stamp}-", dir=backup_root))
    final = backup_root / stamp
    records = []
    try:
        for source, relative in _files(root, paths):
            target = temp / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            records.append({"path": relative.as_posix(), "size": target.stat().st_size,
                            "sha256": _sha256(target)})
        manifest = {"version": 1, "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "source_root": str(root), "paths": list(paths), "files": records}
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, final)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    backups = sorted((p for p in backup_root.iterdir() if p.is_dir() and not p.name.startswith(".")), reverse=True)
    for old in backups[max(1, keep):]:
        shutil.rmtree(old)
    return final


def verify_backup(backup):
    backup = Path(backup)
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    for rec in manifest.get("files", []):
        path = backup / "files" / rec["path"]
        if not path.is_file():
            errors.append({"path": rec["path"], "error": "missing"})
        elif path.stat().st_size != rec["size"] or _sha256(path) != rec["sha256"]:
            errors.append({"path": rec["path"], "error": "checksum"})
    return {"ok": not errors, "files": len(manifest.get("files", [])), "errors": errors}


def restore_backup(backup, target, dry_run=False):
    backup, target = Path(backup).resolve(), Path(target).resolve()
    result = verify_backup(backup)
    if not result["ok"]:
        raise ValueError("backup verification failed")
    if target.exists() and any(target.iterdir()):
        raise ValueError("restore target must be empty")
    if not dry_run:
        shutil.copytree(backup / "files", target, dirs_exist_ok=True)
    return result


def scan_secrets(root):
    root = Path(root).resolve()
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if "${" in line or "<REDACTED>" in line or "CHANGE_ME" in line:
                continue
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                findings.append({"path": path.relative_to(root).as_posix(), "line": line_no})
                break
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="V0.5 production operations")
    sub = ap.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--root", default=".")
    backup.add_argument("--out", default="backups")
    backup.add_argument("--keep", type=int, default=14)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("path")
    restore = sub.add_parser("restore")
    restore.add_argument("path")
    restore.add_argument("--target", required=True)
    restore.add_argument("--dry-run", action="store_true")
    scan = sub.add_parser("scan-secrets")
    scan.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.command == "backup":
        path = create_backup(args.root, args.out, keep=args.keep)
        print(path)
        return 0
    if args.command == "verify-backup":
        result = verify_backup(args.path)
    elif args.command == "restore":
        result = restore_backup(args.path, args.target, args.dry_run)
    else:
        result = {"ok": not (findings := scan_secrets(args.root)), "findings": findings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
