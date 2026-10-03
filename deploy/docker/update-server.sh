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
docker compose -f deploy/docker/docker-compose.yml up --build -d mpau-web
docker compose -f deploy/docker/docker-compose.yml exec -T mpau-web python -m webapp.mysql_demo
echo '更新完成，MySQL 连接验证通过。访问 http://175.27.255.46:8788'
