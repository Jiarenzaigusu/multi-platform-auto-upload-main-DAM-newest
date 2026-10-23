#!/usr/bin/env python3
"""MPAU 独立源码包升级工具（Ubuntu，Python >= 3.9，仅使用标准库）。

上传本文件及干净的源码 ZIP 到服务器，执行：
  python3 upgrade-from-zip.py /home/ubuntu/MPAU/新版代码.zip --check-only
  python3 upgrade-from-zip.py /home/ubuntu/MPAU/新版代码.zip

默认目录 /home/ubuntu/MPAU，可通过 --root 指定；只支持已有的 docker 项目、
mpau-web 服务、mpau-data 卷和宿主机 MySQL。需要 docker compose 和 mysqldump。
构建与空数据冒烟检查期间原服务运行；最终备份和切换期间短暂停服。

同步业务源码、锁文件、Dockerfile；保留服务器 Compose、docker.env、安装包及
其他本地文件。源码和运行镜像一起更新，避免下次 --build 又构建旧源码。
失败回退源码和镜像，不自动导入数据库或覆盖业务数据。应用自身的数据迁移
不在本工具的保证范围内，涉及迁移的版本应先在完整数据副本上验证。
备份含源码、配置、完整数据卷、MySQL 导出及旧镜像，必须保密。
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from uuid import uuid4
import zipfile


SOURCE_DIRS = ("webapp", "uploader", "utils", "local_agent")
SOURCE_FILES = ("pyproject.toml", "uv.lock", "README.zh-CN.md", ".dockerignore",
                "deploy/docker/Dockerfile")
PROTECTED = {"data", "runtime", "logs", "cookies", "secrets", "photos", "output",
             "outputs", "backups", "release", "node_modules", "dist", ".git",
             ".venv", "venv", ".corepack-cache", "__pycache__", ".pytest_cache"}
SMOKE = """
from fastapi.testclient import TestClient
from webapp.api.main import app
with TestClient(app, base_url='http://localhost:8788') as client:
    assert client.get('/api/health').status_code == 200
    assert client.get('/').status_code == 200
    assert (app.state.settings.frontend_dist_dir / 'index.html').is_file()
print('新镜像健康接口、首页及前端文件检查通过')
"""
DATA_CHECK = """
import json, sqlite3, tempfile, shutil, hashlib, sys
from pathlib import Path
root = Path(sys.argv[1])
p = root / 'system/auth.db'
assert p.is_file(), '原账号数据库不存在'
with tempfile.TemporaryDirectory() as tmp:
    target = Path(tmp) / 'auth.db'
    for suffix in ('', '-wal'):
        src = Path(str(p) + suffix)
        if src.is_file():
            shutil.copyfile(src, str(target) + suffix)
    with sqlite3.connect(target) as db:
        assert db.execute('PRAGMA quick_check').fetchall() == [('ok',)], '账号库损坏'
        ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
        columns = [r[1] for r in db.execute('PRAGMA table_info(users)')]
        assert "'viewer'" not in ddl, '存在 viewer 旧架构，需先单独验证迁移'
        assert {'brand_name', 'brand_key'} <= set(columns), '账号品牌字段需迁移'
        rows = db.execute('SELECT * FROM users ORDER BY id').fetchall()
        digest = hashlib.sha256(repr((columns, rows)).encode()).hexdigest()
active = 0
for p in (root / 'users').glob('*/runtime/state.json'):
    state = json.loads(p.read_text())
    active += sum(j.get('status') in ('running', 'cancelling')
                  for j in state.get('jobs', {}).values())
assert active == 0, '仍有运行或取消中的任务，停止升级'
print(json.dumps({'users': len(rows), 'users_sha256': digest}))
"""
MYSQL_CHECK = """
import os, json, pymysql
c = pymysql.connect(host=os.environ['MPAU_MYSQL_HOST'].strip(),
    port=int(os.getenv('MPAU_MYSQL_PORT') or '3306'),
    user=os.environ['MPAU_MYSQL_USER'].strip(),
    password=os.environ['MPAU_MYSQL_PASSWORD'],
    database=os.environ['MPAU_MYSQL_DATABASE'].strip(),
    connect_timeout=10, read_timeout=20, autocommit=True)
with c, c.cursor() as q:
    q.execute('SELECT VERSION(), DATABASE()')
    version, name = q.fetchone()
    q.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'")
    engines = [r[0] for r in q.fetchall()]
    assert engines and all(e == 'InnoDB' for e in engines), '需要单独处理非 InnoDB 或空业务库'
    q.execute('SELECT COALESCE(SUM(DATA_LENGTH+INDEX_LENGTH),0) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
    size = int(q.fetchone()[0])
    print(json.dumps({'version': version, 'tables': len(engines), 'bytes': size}))
"""


class UpgradeError(Exception):
    pass


def require(ok, message):
    if not ok:
        raise UpgradeError(message)


def run(args, *, capture=False, data=None):
    # 不回显 inspect/config 的原文；它们含生产密码。
    p = subprocess.run([str(a) for a in args], input=data,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None, text=True)
    require(p.returncode == 0, f"命令失败：{args[0]} {args[1]}（退出码 {p.returncode}）")
    return p.stdout if capture else ""


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def protected(path):
    return (any(p in PROTECTED for p in path.parts)
            or (path.name.startswith(".env") and not path.name.endswith((".example", ".template")))
            or path.name.endswith((".env", ".db", ".sqlite", ".sqlite3", ".log")))


def check_zip(path):
    require(path.is_file(), "源码 ZIP 不存在")
    sidecar = Path(str(path) + ".sha256")
    if sidecar.is_file():
        words = sidecar.read_text().split()
        require(words and re.fullmatch(r"[0-9a-fA-F]{64}", words[0]), "SHA256 文件格式错误")
        require(digest(path) == words[0].lower(), "源码 ZIP 的 SHA256 校验失败")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        require(len(entries) <= 50000 and sum(e.file_size for e in entries) <= 2 * 1024**3,
                "ZIP 超过源码包大小限制")
        names = set()
        for e in entries:
            p = PurePosixPath(e.filename)
            mode = e.external_attr >> 16
            require(e.filename and not p.is_absolute() and ".." not in p.parts
                    and "\\" not in e.filename and ":" not in e.filename
                    and not any(ord(c) < 32 for c in e.filename)
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                    "ZIP 含不安全路径、链接或特殊文件")
            require(p.as_posix() not in names, "ZIP 含重复路径")
            names.add(p.as_posix())
        candidates = [n[:-len("pyproject.toml")] for n in names if n.endswith("pyproject.toml")
                      and n[:-len("pyproject.toml")] + "deploy/docker/Dockerfile" in names]
        require(len(candidates) == 1, "无法唯一识别源码包根目录")
        prefix = candidates[0]
        payload = {}
        for e in entries:
            if e.is_dir():
                continue
            require(e.filename.startswith(prefix), "ZIP 根目录外存在其他文件")
            rel = PurePosixPath(e.filename[len(prefix):])
            require(not protected(rel), f"源码包包含本地环境或数据：{rel}")
            payload[rel.as_posix()] = e.filename
        for n in SOURCE_FILES:
            require(n in payload, f"源码包缺少 {n}")
        for n in SOURCE_DIRS:
            require(f"{n}/__init__.py" in payload, f"源码包缺少 {n} Python 包")
        require(z.testzip() is None, "ZIP 内容损坏")
        if "PACKAGE-MANIFEST.sha256" in payload:
            manifest = z.read(payload["PACKAGE-MANIFEST.sha256"]).decode("utf-8")
            recorded = set()
            for line in manifest.splitlines():
                parts = line.split(None, 1)
                require(len(parts) == 2, "源码清单格式错误")
                sha, rel = parts
                rel = rel.lstrip("*")
                require(rel in payload and rel not in recorded, "源码清单条目无效")
                require(hashlib.sha256(z.read(payload[rel])).hexdigest() == sha,
                        f"源码清单校验失败：{rel}")
                recorded.add(rel)
            require(recorded == set(payload) - {"PACKAGE-MANIFEST.sha256"}, "源码清单不完整")
        return payload


def extract(path, payload, target):
    with zipfile.ZipFile(path) as z:
        for rel, member in payload.items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, p.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            p.chmod(0o755 if (z.getinfo(member).external_attr >> 16) & 0o111 else 0o644)


def remove_source(path):
    """只清理受管源码；遇到本地环境或数据时保留。"""
    if protected(path):
        return
    require(not path.is_symlink(), f"受管源码包含链接，需人工核对：{path}")
    if path.is_dir():
        for child in path.iterdir():
            remove_source(child)
        if not any(path.iterdir()):
            path.rmdir()
    else:
        path.unlink()


def sync_source(src, dst):
    require(not dst.is_symlink(), f"源码目标是链接：{dst}")
    if src.is_dir():
        if dst.exists() and not dst.is_dir():
            dst.unlink()
        dst.mkdir(parents=True, exist_ok=True)
        source_names = {p.name for p in src.iterdir()}
        for old in dst.iterdir():
            if old.name not in source_names:
                remove_source(old)
        for child in src.iterdir():
            sync_source(child, dst / child.name)
    else:
        if dst.is_dir():
            remove_source(dst)
            require(not dst.exists(), f"源码目标含本地数据，不能覆盖：{dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def fingerprint(apps):
    values = {}
    for rel in (*SOURCE_DIRS, *SOURCE_FILES, "deploy/docker/docker-compose.yml", "deploy/docker/docker.env",
                "deploy/docker/.env", ".env"):
        path = apps / rel
        items = sorted(path.rglob("*")) if path.is_dir() else [path]
        for p in items:
            if p.is_file() and (rel not in SOURCE_DIRS or not protected(p.relative_to(apps))):
                values[p.relative_to(apps).as_posix()] = digest(p)
    return values


def compressed_command(args, destination):
    """流式压缩，且同时检查导出进程退出码和 gzip 完整性。"""
    with tempfile.TemporaryFile() as errors:
        p = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=errors)
        try:
            with gzip.open(destination, "wb", compresslevel=1) as out:
                shutil.copyfileobj(p.stdout, out)
            require(p.wait() == 0, "备份导出失败；不会继续切换服务")
        finally:
            p.stdout.close()
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
    with gzip.open(destination, "rb") as f:
        while f.read(1024 * 1024):
            pass


def client_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'


class Upgrade:
    def __init__(self, args):
        self.args = args
        self.root = Path(args.root).expanduser().resolve()
        self.apps = self.root / "apps"
        self.compose_file = self.apps / "deploy/docker/docker-compose.yml"
        self.compose = ["docker", "compose", "--project-directory", self.compose_file.parent,
                        "-p", "docker", "-f", self.compose_file]
        self.session = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        self.new_tag = "mpau-web:release-" + self.session
        self.old_tag = "mpau-web:rollback-" + self.session
        self.backup = self.root / "backups" / ("upgrade-" + self.session)
        self.stage = self.root / "staging" / ("upgrade-" + self.session)
        self.stopped = False
        self.switch_attempted = False
        self.secret_file = None

    def inspect(self, *args):
        return json.loads(run(["docker", *args], capture=True))[0]

    def preflight(self):
        for tool in ("docker", "mysqldump"):
            require(shutil.which(tool), f"缺少命令：{tool}")
        require(self.apps.is_dir() and not self.apps.is_symlink(), "apps 必须是已有的真实目录")
        for directory in (self.root / "backups", self.root / "staging", self.compose_file.parent,
                          self.apps / "deploy"):
            require(not directory.is_symlink(), f"部署目录不能是符号链接：{directory}")
        self.original = self.inspect("inspect", "mpau-web")
        require(self.original["State"]["Running"], "原 mpau-web 未运行，停止升级")
        labels = self.original["Config"].get("Labels") or {}
        require(labels.get("com.docker.compose.project") == "docker"
                and labels.get("com.docker.compose.service") == "mpau-web", "原 Compose 项目或服务不匹配")
        self.old_image = self.original["Image"]
        self.old_env = dict(s.split("=", 1) for s in self.original["Config"]["Env"])
        require(self.old_env.get("MPAU_DATA_DIR", "/var/lib/mpau/data") == "/var/lib/mpau/data", "原数据目录不匹配")
        mounts = {m["Destination"]: m for m in self.original["Mounts"]}
        require(set(mounts) == {"/var/lib/mpau/data", "/var/lib/mpau/releases"}, "原容器有额外挂载，需人工核对")
        require(mounts["/var/lib/mpau/data"].get("Name") == "mpau-data", "原数据卷不是 mpau-data")
        installer = mounts["/var/lib/mpau/releases"]
        require(installer["Type"] == "bind" and not installer["RW"]
                and installer["Source"] == str(self.apps / "deploy/windows/output"), "安装包挂载不匹配")
        self.config = json.loads(run([*self.compose, "config", "--format", "json"], capture=True))
        service = self.config["services"]["mpau-web"]
        require(service["image"] == "mpau-web:local" and service.get("container_name") == "mpau-web", "部署镜像名或容器名不匹配")
        require(Path(service["build"]["context"]).resolve() == self.apps, "Compose 构建上下文未指向 apps")
        require(service["build"].get("dockerfile", "Dockerfile") == "deploy/docker/Dockerfile",
                "Compose 使用了不同的 Dockerfile，需人工核对")
        require("--wait-timeout" in run([*self.compose, "up", "--help"], capture=True), "Compose 版本不支持健康等待")
        self.check_config(service)
        self.initial_fingerprint = fingerprint(self.apps)
        stats = json.loads(run(["docker", "exec", "mpau-web", "python", "-c", DATA_CHECK,
                                "/var/lib/mpau/data"], capture=True))
        db = json.loads(run(["docker", "exec", "mpau-web", "python", "-c", MYSQL_CHECK], capture=True))
        require(str(db["version"]).startswith("5.7."), "本脚本面向当前 MySQL 5.7 部署，其他版本需先验证导出参数")
        self.payload = check_zip(Path(self.args.zip).expanduser().resolve())
        image_size = self.inspect("image", "inspect", self.old_image).get("Size", 0)
        source_size = sum(p.stat().st_size for p in self.apps.rglob("*")
                          if p.is_file() and not p.is_symlink())
        with zipfile.ZipFile(Path(self.args.zip).expanduser().resolve()) as z:
            unpacked_size = sum(p.file_size for p in z.infolist())
        required = max(2 * 1024**3, image_size * 2 + source_size * 2 + unpacked_size * 2 + db["bytes"] * 3)
        require(shutil.disk_usage(self.root).free >= required, "剩余空间不足以安全构建和备份，停止升级")
        print(f"预检通过：原用户 {stats['users']}，MySQL {db['version']}，业务表 {db['tables']}；源码 ZIP 校验通过。", flush=True)

    def check_config(self, service):
        declared = service.get("environment") or {}
        changed = [k for k, v in declared.items() if self.old_env.get(k) != str(v)]
        require(not changed, "Compose 与运行容器的环境配置不同，需先核对这些键：" + ", ".join(changed))
        volumes = service.get("volumes", [])
        expected = {"/var/lib/mpau/data", "/var/lib/mpau/releases"}
        require({v["target"] for v in volumes} == expected, "Compose 挂载目标不匹配")
        for v in volumes:
            if v["target"] == "/var/lib/mpau/data":
                name = self.config.get("volumes", {}).get(v["source"], {}).get("name", v["source"])
                require(v["type"] == "volume" and name == "mpau-data" and not v.get("read_only"), "Compose 将使用不同的数据卷")
            else:
                require(v["type"] == "bind" and v.get("read_only")
                        and v["source"] == str(self.apps / "deploy/windows/output"), "Compose 将改变安装包挂载")
        normal_ip = lambda ip: "" if ip in (None, "", "0.0.0.0") else ip
        proposed = {(f"{p['target']}/{p.get('protocol', 'tcp')}", str(p.get("published", "")), normal_ip(p.get("host_ip")))
                    for p in service.get("ports", [])}
        current = {(port, p["HostPort"], normal_ip(p.get("HostIp")))
                   for port, bindings in self.original["HostConfig"]["PortBindings"].items() for p in (bindings or [])}
        require(proposed == current, "Compose 将改变端口映射，停止升级")

    def prepare(self):
        self.backup.mkdir(parents=True, mode=0o700)
        self.stage.mkdir(parents=True, mode=0o700)
        unpacked = self.stage / "package"
        extract(Path(self.args.zip).expanduser().resolve(), self.payload, unpacked)
        prepared = self.stage / "next-apps"
        print("准备新版源码，保留原部署配置和安装包；原服务继续运行。", flush=True)
        shutil.copytree(self.apps, prepared, symlinks=True)
        for rel in (*SOURCE_DIRS, *SOURCE_FILES):
            sync_source(unpacked / rel, prepared / rel)
        # 强制排除本地环境及数据，不把保留的生产配置发给 Docker builder。
        with (prepared / ".dockerignore").open("a") as f:
            f.write("\n# upgrade-from-zip: always exclude server-local files\n"
                    "**/*.env\n**/.env\n.git\n.venv\ndata\nruntime\nlogs\nbackups\n"
                    "output\noutputs\nrelease\ndeploy/windows/output\n**/node_modules\n**/.corepack-cache\n")
        self.write_json("container-inspect.json", self.original)
        self.write_json("source-before.sha256.json", self.initial_fingerprint)
        self.write_json("release.json", {"old_image": self.old_image, "new_tag": self.new_tag,
                                        "zip_sha256": digest(Path(self.args.zip).expanduser().resolve())})
        run(["docker", "image", "tag", self.old_image, self.old_tag])
        print("保存旧镜像，原服务继续运行。", flush=True)
        compressed_command(["docker", "image", "save", self.old_tag], self.backup / "old-image.tar.gz")
        self.prepare_mysql_defaults()
        self.dump_mysql("mysql-schema-check.sql.gz", schema=True)
        print("构建新版镜像，原服务继续运行。", flush=True)
        build = ["docker", "build", "-t", self.new_tag, "-f", prepared / "deploy/docker/Dockerfile"]
        for key, value in (self.config["services"]["mpau-web"]["build"].get("args") or {}).items():
            if value is not None:
                build.extend(["--build-arg", f"{key}={value}"])
        run([*build, prepared])
        self.new_image = self.inspect("image", "inspect", self.new_tag)["Id"]
        env = dict(s.split("=", 1) for s in self.inspect("image", "inspect", self.new_image)["Config"].get("Env", []))
        env.update({k: str(v) for k, v in (self.config["services"]["mpau-web"].get("environment") or {}).items()})
        changed = [k for k in self.old_env if k.startswith("MPAU_") and env.get(k) != self.old_env[k]]
        require(not changed, "新镜像将改变 MPAU 环境配置，需先核对这些键：" + ", ".join(changed))
        run(["docker", "run", "--rm", "--network", "none", "--tmpfs",
             "/var/lib/mpau/data:uid=10001,gid=10001,mode=0700", "--entrypoint", "python",
             self.new_image, "-c", SMOKE])

    def write_json(self, name, value):
        (self.backup / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def prepare_mysql_defaults(self):
        values = {}
        for key in ("HOST", "USER", "PASSWORD", "DATABASE"):
            v = self.old_env.get("MPAU_MYSQL_" + key, "")
            require(bool(v), f"原 MySQL {key} 配置不完整")
            values[key.lower()] = v if key == "PASSWORD" else v.strip()
        require(not values["database"].startswith("-"), "MySQL 库名无效")
        # 使用容器内解析出的地址，与原应用实际连接目标保持一致。
        values["host"] = run(["docker", "exec", "mpau-web", "python", "-c",
                               "import socket,sys; print(socket.gethostbyname(sys.argv[1]))", values["host"]], capture=True).strip()
        values["port"] = int(self.old_env.get("MPAU_MYSQL_PORT") or "3306")
        self.database_name = values.pop("database")
        self.secret_file = self.backup / ".mysql-client.cnf"
        self.secret_file.write_text("[client]\nprotocol=tcp\n" + "".join(f"{k}={client_quote(v)}\n" for k, v in values.items()))
        self.secret_file.chmod(0o600)

    def dump_mysql(self, name, schema=False):
        command = ["mysqldump", f"--defaults-extra-file={self.secret_file}", "--single-transaction",
                   "--quick", "--no-tablespaces", "--set-gtid-purged=OFF", "--routines", "--events",
                   "--triggers", "--hex-blob"]
        if schema:
            command.append("--no-data")
        compressed_command([*command, "--databases", self.database_name], self.backup / name)

    def helper(self, code, *args, capture=True):
        return run(["docker", "run", "--rm", "--network", "none", "--user", "0:0",
                    "--mount", "type=volume,src=mpau-data,dst=/snapshot,readonly",
                    "--entrypoint", "python", self.old_image, "-c", code, *args], capture=capture)

    def cutover(self):
        require(fingerprint(self.apps) == self.initial_fingerprint, "构建期间原源码或配置被修改，请重新执行")
        current = self.inspect("inspect", "mpau-web")
        require(current["Id"] == self.original["Id"] and current["State"]["Running"], "构建期间原容器被更换或停止")
        require(json.loads(run([*self.compose, "config", "--format", "json"], capture=True)) == self.config,
                "构建期间 Compose 配置变化，停止升级")
        run(["docker", "exec", "mpau-web", "python", "-c", DATA_CHECK, "/var/lib/mpau/data"], capture=True)
        print("构建与预检完成。现在暂停 Web，备份完整数据卷和 MySQL，再切换。", flush=True)
        self.stopped = True
        run(["docker", "stop", "--time", "60", "mpau-web"])
        before = json.loads(self.helper(DATA_CHECK, "/snapshot"))
        self.write_json("accounts-before.json", before)
        command = ["docker", "run", "--rm", "--network", "none", "--user", "0:0",
                   "--mount", "type=volume,src=mpau-data,dst=/snapshot,readonly",
                   "--entrypoint", "python", self.old_image, "-c",
                   "import sys,tarfile\nwith tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as t: t.add('/snapshot',arcname='data')"]
        compressed_command(command, self.backup / "mpau-data.tar.gz")
        self.dump_mysql("mysql.sql.gz")
        checks = [p for p in self.backup.iterdir() if p.is_file() and p != self.secret_file]
        (self.backup / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in sorted(checks)))
        # 原源码整体留下；安装新版预备目录，确保普通 --build 也会使用新版源码。
        self.apps.rename(self.backup / "source-before")
        (self.stage / "next-apps").rename(self.apps)
        require(json.loads(run([*self.compose, "config", "--format", "json"], capture=True)) == self.config,
                "源码同步意外改变生产配置，停止切换")
        self.switch_attempted = True
        run(["docker", "image", "tag", self.new_image, "mpau-web:local"])
        run([*self.compose, "up", "-d", "--no-build", "--pull", "never", "--no-deps",
             "--wait", "--wait-timeout", str(self.args.timeout), "mpau-web"])
        current = self.inspect("inspect", "mpau-web")
        require(current["Image"] == self.new_image, "运行镜像与本次构建的镜像不一致")
        require(current["State"].get("Health", {}).get("Status") == "healthy", "新容器不健康")
        require(current["Mounts"] == self.original["Mounts"], "切换后挂载变化")
        # 只执行 SELECT；不登录、不触发品牌自动绑定等业务写入。
        run(["docker", "exec", "mpau-web", "python", "-c", MYSQL_CHECK], capture=True)
        self.write_json("success.json", {"image": self.new_image, "source_directory": str(self.apps)})
        self.stopped = False
        print(f"升级成功：{self.new_tag}\n运行镜像：{self.new_image}\n源码目录：{self.apps}\n完整备份：{self.backup}", flush=True)

    def recover(self):
        if not self.stopped:
            return
        print("升级失败，正在恢复原源码和旧镜像；不会自动覆盖数据库或用户数据。", file=sys.stderr, flush=True)
        if self.switch_attempted and run(["docker", "ps", "-q", "--filter", "name=^/mpau-web$"], capture=True).strip():
            run(["docker", "stop", "--time", "60", "mpau-web"], capture=True)
        # 依据实际目录恢复，也涵盖 rename 刚完成便收到中断信号的情况。
        if (self.backup / "source-before").exists():
            if self.apps.exists():
                self.apps.rename(self.stage / "failed-apps")
            (self.backup / "source-before").rename(self.apps)
        run(["docker", "image", "tag", self.old_image, "mpau-web:local"])
        run([*self.compose, "up", "-d", "--no-build", "--pull", "never", "--no-deps",
             "--wait", "--wait-timeout", str(self.args.timeout), "mpau-web"])
        self.stopped = False
        print("已恢复旧服务启动；请检查健康状态。失败时产生的数据变化没有被自动撤销。", file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("zip", help="干净的源码 ZIP（可包含一层项目目录）")
    parser.add_argument("--root", default="/home/ubuntu/MPAU", help="服务器 MPAU 根目录")
    parser.add_argument("--check-only", action="store_true", help="只校验包和服务器现状，不构建、备份、同步或重启")
    parser.add_argument("--timeout", type=int, default=180, help="切换健康检查超时秒数，默认 180")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("超时必须大于零")
    os.umask(0o077)
    upgrade = Upgrade(args)
    lock = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if not args.check_only:
            require(upgrade.root.is_dir(), "服务器根目录不存在")
            lock = (upgrade.root / ".mpau-upgrade.lock").open("a+")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UpgradeError("另一个升级进程正在运行")
        upgrade.preflight()
        if args.check_only:
            print("只检查模式结束：没有修改源码、镜像、容器或数据。")
            return 0
        upgrade.prepare()
        upgrade.cutover()
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print(f"升级停止：{error or '操作被中断'}", file=sys.stderr, flush=True)
        try:
            upgrade.recover()
        except (Exception, KeyboardInterrupt):
            print(f"自动回退未完成，请保留现场。备份目录：{upgrade.backup}", file=sys.stderr, flush=True)
        return 1
    finally:
        if upgrade.secret_file is not None:
            upgrade.secret_file.unlink(missing_ok=True)
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    sys.exit(main())
