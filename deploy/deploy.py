#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFTP deploy for 金十DSH to a Windows nginx web root."""

import os
import posixpath
import stat
import sys
import time
from pathlib import Path

import paramiko


def env(name, default=None):
    value = os.environ.get(name, "").strip()
    return value or default


def fail(message):
    print(f"[ERROR] {message}")
    sys.exit(1)


def windows_path(remote_dir):
    remote_dir = remote_dir.strip()
    if remote_dir.startswith("/"):
        remote_dir = remote_dir[1:]
    return remote_dir.replace("/", "\\")


def connect_sftp():
    host = env("DSH_SSH_HOST")
    port = int(env("DSH_SSH_PORT", "22"))
    user = env("DSH_SSH_USER", "Administrator")
    password = env("DSH_SSH_PASSWORD")
    key_path = env("DSH_SSH_KEY")

    if not host:
        fail("DSH_SSH_HOST is required")
    if not password and not key_path:
        fail("DSH_SSH_PASSWORD or DSH_SSH_KEY is required")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": user,
        "timeout": 20,
        "look_for_keys": False,
        "allow_agent": False,
    }

    if key_path:
        key_path = str(Path(key_path).expanduser())
        connect_kwargs["key_filename"] = key_path
    else:
        connect_kwargs["password"] = password

    try:
        client.connect(**connect_kwargs)
    except Exception as exc:
        fail(f"SSH connection failed: {exc}")

    return client, client.open_sftp()


def backup_remote(client, remote_dir):
    if env("DSH_BACKUP", "1") != "1":
        return

    win_dir = windows_path(remote_dir)
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{win_dir}.backup.{ts}"
    command = (
        "powershell -NoProfile -Command "
        f"\"if (Test-Path -LiteralPath '{win_dir}') "
        f"{{ Rename-Item -LiteralPath '{win_dir}' -NewName '{backup}' }}\""
    )

    try:
        _, stdout, stderr = client.exec_command(command, timeout=60)
        code = stdout.channel.recv_exit_status()
        if code != 0:
            detail = stderr.read().decode("utf-8", errors="ignore").strip()
            print(f"[WARN] Backup skipped or failed: {detail}")
        else:
            print(f"[OK] Existing remote directory backed up: {backup}")
    except Exception as exc:
        print(f"[WARN] Backup command failed: {exc}")


def ensure_remote_dir(sftp, remote_dir):
    current = ""
    for part in remote_dir.strip("/").split("/"):
        current += "/" + part
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def upload_tree(sftp, local_root, remote_root):
    count = 0
    local_root = Path(local_root)
    for local_path in sorted(local_root.rglob("*")):
        if not local_path.is_file():
            continue
        rel = local_path.relative_to(local_root).as_posix()
        remote_path = posixpath.join(remote_root, rel).replace("\\", "/")
        remote_parent = posixpath.dirname(remote_path)
        ensure_remote_dir(sftp, remote_parent)
        sftp.put(str(local_path), remote_path)
        count += 1
        print(f"[UPLOAD] {rel}")
    return count


def main():
    local_dist = env("DSH_LOCAL_DIST")
    remote_dir = env("DSH_REMOTE_DIR", "/C:/nginx/html/DSH")

    if not local_dist:
        fail("DSH_LOCAL_DIST is required")
    local_path = Path(local_dist)
    if not local_path.is_dir():
        fail(f"Local dist directory not found: {local_path}")
    if not any(local_path.rglob("*")):
        fail(f"Local dist directory is empty: {local_path}")

    client, sftp = connect_sftp()
    try:
        backup_remote(client, remote_dir)
        ensure_remote_dir(sftp, remote_dir)
        count = upload_tree(sftp, local_path, remote_dir)
        print(f"[DONE] Uploaded {count} files to {remote_dir}")
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
