#!/usr/bin/env bash
# 只读检查旧部署，不输出 .env 或容器环境，不停止服务，不修改文件。
set -eu
printf '\n--- System / disk ---\n'
uname -m
df -h / /www
printf '\n--- Docker ---\n'
docker --version
docker compose version
printf '\n--- Containers (including stopped ones) ---\n'
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
printf '\n--- Port owners ---\n'
ss -lntp | awk 'NR==1 || $4 ~ /:(80|443|8000|8001|18000)$/'
printf '\n--- Old directory names (no file contents) ---\n'
if [ -d /www/wwwroot/aliyun-deploy ]; then
    ls -la /www/wwwroot/aliyun-deploy
fi
printf '\n--- Old Compose container identity and data mounts ---\n'
for id in $(docker ps -aq --filter 'label=com.docker.compose.project.working_dir=/www/wwwroot/aliyun-deploy'); do
    docker inspect --format 'Name={{.Name}} Project={{index .Config.Labels "com.docker.compose.project"}} {{range .Mounts}}Mount[{{.Type}}]: {{.Source}} -> {{.Destination}}; {{end}}' "$id"
done
printf '\nCheck complete. No services or data were changed.\n'
