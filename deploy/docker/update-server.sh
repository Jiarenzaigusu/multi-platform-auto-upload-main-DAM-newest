#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v docker >/dev/null 2>&1; then
  echo '请先安装 Docker Engine 和 Docker Compose 插件。' >&2
  exit 1
fi
docker compose version >/dev/null
if [ ! -f deploy/docker/docker.env ]; then
  (umask 077; cp deploy/docker/docker.env.example deploy/docker/docker.env)
  echo '已创建 deploy/docker/docker.env，请填写实际 MySQL 数据库名、账号、密码和端口，再运行本脚本。'
  exit 1
fi
if ! awk -F= '
  /^MPAU_MYSQL_(HOST|PORT|DATABASE|USER|PASSWORD)=/ {
    key=$1; value=substr($0,index($0,"=")+1); sub(/\r$/, "", value)
    if (value == "" || value ~ /数据库名|数据库用户|数据库密码|你的MySQL/) invalid=1
    seen[key]=1
  }
  END { exit (invalid || length(seen) != 5) }
' deploy/docker/docker.env; then
  echo 'MySQL 配置缺失或仍是占位值，请先填写 deploy/docker/docker.env。' >&2
  exit 1
fi
docker compose -f deploy/docker/docker-compose.yml config --quiet
# Existing accounts live in SQLite on the persistent volume, not in MySQL.
if docker container inspect mpau-web >/dev/null 2>&1; then
  current_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mpau/data"}}{{.Name}}{{end}}{{end}}' mpau-web)
  if [ "$current_volume" != 'mpau-data' ]; then
    echo '现有容器未使用预期 mpau-data 数据卷。请先保留并合并原挂载配置，脚本停止更新。' >&2
    exit 1
  fi
  docker exec mpau-web python -c 'import os; from pathlib import Path; assert Path(os.getenv("MPAU_DATA_DIR", "/var/lib/mpau/data")).resolve() == Path("/var/lib/mpau/data"), "原服务使用自定义数据目录，请先合并原配置"'
  backup_dir="backups/$(date +%Y%m%d-%H%M%S)-$$"
  (umask 077; mkdir -p "$backup_dir"; cp deploy/docker/docker.env "$backup_dir/docker.env")
  docker exec mpau-web python -c 'import sqlite3; from pathlib import Path; p=Path("/var/lib/mpau/data/system/auth.db"); assert p.is_file(), "未找到原账号库，停止更新"; src=sqlite3.connect(p.as_uri()+"?mode=ro", uri=True); dst=sqlite3.connect("/tmp/mpau-auth-pre-update.db"); src.backup(dst); assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"; print("原用户数：", dst.execute("SELECT COUNT(*) FROM users").fetchone()[0]); dst.close(); src.close()'
  docker cp mpau-web:/tmp/mpau-auth-pre-update.db "$backup_dir/auth.db"
  chmod 600 "$backup_dir/auth.db" "$backup_dir/docker.env"
  docker exec mpau-web rm -f /tmp/mpau-auth-pre-update.db
  echo "账号库及当前环境配置已备份到 $backup_dir；继续复用原 mpau-data 数据卷。"
else
  echo '未发现 mpau-web 容器。为防止误作首次部署，请确认原容器名与挂载位置后再更新。' >&2
  exit 1
fi
docker compose -f deploy/docker/docker-compose.yml up --build -d mpau-web
docker compose -f deploy/docker/docker-compose.yml exec -T mpau-web python -m webapp.mysql_demo
echo '更新完成，MySQL 连接验证通过。访问 http://175.27.255.46:8788'
