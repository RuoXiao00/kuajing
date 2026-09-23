#!/usr/bin/env bash
# 在已部署的宝塔项目中执行一次；只增补来源和 HTTPS Cookie，不打印其他配置。
set -eu
cd /www/kuajing-next
test -f deploy/backend.env
test ! -L deploy/backend.env
umask 077
cp -p deploy/backend.env "deploy/backend.env.backup-$(date +%Y%m%d-%H%M%S)"
chmod 600 deploy/backend.env
# 明确允许自己的 Pages 来源；来源不含 /kuajing 路径，不能使用星号。
sed -i '/^[[:space:]]*FRONTEND_ORIGINS=/d; /^[[:space:]]*COOKIE_SECURE=/d' deploy/backend.env
printf '\nFRONTEND_ORIGINS=https://ruoxiao00.github.io,https://app.qiyuange.online\nCOOKIE_SECURE=true\n' >> deploy/backend.env
docker compose -f compose.baota.yaml config -q
# restart 不会重新载入 env_file，必须让 Compose 重建容器；不重新下载或构建镜像。
docker compose -f compose.baota.yaml up -d --no-build --wait --wait-timeout 180
curl --fail --max-time 10 -sS -o /dev/null http://127.0.0.1:18000/api/knowledge/health
printf '\nPages origins configured; API healthy. No credentials were displayed.\n'
