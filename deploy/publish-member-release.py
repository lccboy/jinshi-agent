#!/usr/bin/env python3
"""定向发布会员下载包，不触碰服务器 data 和采集程序。"""
import argparse
import getpass
import hashlib
import posixpath
import time
import uuid
from pathlib import Path

import paramiko


FILES = (
    "index.html",
    "assets/app.css",
    "assets/app.js",
    "member-guide.html",
    "downloads/JinshiDSH-Workbench-1.0.41.zip",
    "downloads/JinshiDSH-Workbench-1.0.41.sha256.txt",
    "downloads/member-workbench-latest.json",
    "downloads/MEMBER-GUIDE.txt",
)


def digest_stream(stream):
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            return digest.hexdigest().upper()
        digest.update(chunk)


def ensure_remote_dir(sftp, path):
    current = ""
    for part in path.strip("/").split("/"):
        current += "/" + part
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def main():
    parser = argparse.ArgumentParser(description="发布金十DSH会员工作台下载文件")
    parser.add_argument("--host", default="114.132.236.131")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="Administrator")
    parser.add_argument("--root", default="/C:/nginx/html/DSH")
    parser.add_argument("--release", default="dist-member-release-1.0.41")
    args = parser.parse_args()

    release = Path(args.release).resolve()
    missing = [name for name in FILES if not (release / Path(name)).is_file()]
    if missing:
        raise SystemExit("发布目录缺少文件: " + ", ".join(missing))
    if args.root.replace("\\", "/").rstrip("/").lower() != "/c:/nginx/html/dsh":
        raise SystemExit("远程根目录必须是 C:\\nginx\\html\\DSH")

    password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=args.host, port=args.port, username=args.user, password=password,
                   timeout=20, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    uploaded = []
    try:
        for name in FILES:
            local = release / Path(name)
            remote = posixpath.join(args.root, name)
            ensure_remote_dir(sftp, posixpath.dirname(remote))
            try:
                sftp.stat(remote)
                backup = remote + ".bak." + stamp
                sftp.posix_rename(remote, backup)
            except OSError:
                backup = ""
            temporary = remote + ".upload." + uuid.uuid4().hex
            sftp.put(str(local), temporary)
            sftp.posix_rename(temporary, remote)
            with sftp.open(remote, "rb") as stream:
                remote_hash = digest_stream(stream)
            local_hash = hashlib.sha256(local.read_bytes()).hexdigest().upper()
            if remote_hash != local_hash:
                raise RuntimeError(f"远程校验失败: {name}")
            uploaded.append({"path": name, "size": local.stat().st_size,
                             "sha256": local_hash, "backup": backup})
            print(f"[OK] {name} ({local.stat().st_size} bytes, {local_hash})")
    finally:
        sftp.close()
        client.close()
    print(f"[DONE] 已发布 {len(uploaded)} 个文件到 C:\\nginx\\html\\DSH")


if __name__ == "__main__":
    main()
