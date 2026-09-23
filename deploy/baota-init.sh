#!/usr/bin/env bash
# 只初始化当前新版本目录；不读取/复制旧项目的 .env 或 db，不启动收费任务。
set -eu
cd -- "$(dirname -- "$0")/.."
app_dir=$(pwd -P)
if [ "$(id -u)" -ne 0 ]; then
    printf 'Please run: sudo bash deploy/baota-init.sh\n' >&2
    exit 1
fi
if [ "$app_dir" != /www/kuajing-next ]; then
    printf 'Expected /www/kuajing-next; upload/extract the package to /www first.\n' >&2
    exit 1
fi
docker compose version
test -f compose.baota.yaml
umask 077
if [ ! -e deploy/backend.env ]; then
    cp deploy/backend.baota.env.example deploy/backend.env
    printf 'Created deploy/backend.env from template. Fill it using the panel editor.\n'
else
    printf 'Keeping your existing deploy/backend.env unchanged.\n'
fi
test ! -L deploy/backend.env
chmod 600 deploy/backend.env
# 只处理预定的新目录，拒绝符号链接，防止改到其他项目的数据权限。
for folder in server-data server-data/knowledge server-data/recommendations server-data/products server-data/images; do
    if [ -L "$folder" ]; then
        printf 'Refusing symlink: %s\n' "$folder" >&2
        exit 1
    fi
    mkdir -p -- "$folder"
    chown 10001:10001 "$folder"
    chmod 750 "$folder"
done
docker compose -f compose.baota.yaml config -q
printf 'Ready to configure/build. Old deployment untouched; no containers started.\n'
