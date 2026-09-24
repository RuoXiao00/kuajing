#!/usr/bin/env bash
# 迁移已生成的向量库，不调用 Embedding。上传包与运行数据均不得提交 Git。
set -euo pipefail
cd /www/kuajing-next
archive=/www/kuajing-next/knowledge-data.tar.gz
expected=${1:?Usage: bash deploy/import-knowledge.sh SHA256}
[[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { echo 'Invalid SHA256'; exit 1; }
test -f "$archive"
test ! -L server-data
test ! -L server-data/knowledge
printf '%s  %s\n' "$expected" "$archive" | sha256sum --check --status
# 先校验和解包到独立暂存目录，完成后才停止服务、替换挂载目录。
if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo 'Unsafe archive paths'; exit 1
fi
if tar -tzf "$archive" | grep -Ev '^chroma(/|$)' >/dev/null; then
    echo 'Archive must contain only chroma/'; exit 1
fi
stage=$(mktemp -d /www/kuajing-next/server-data/knowledge-import.XXXXXX)
tar --no-same-owner -xzf "$archive" -C "$stage"
test -f "$stage/chroma/chroma.sqlite3"
if find "$stage" -type l -print -quit | grep -q .; then
    echo 'Symlinks are not allowed'; exit 1
fi
chown -R 10001:10001 "$stage"
chmod 750 "$stage"
backup="/www/kuajing-next/server-data/knowledge-backup-$(date +%Y%m%d-%H%M%S)-$$"
docker compose -f compose.baota.yaml stop api
if [ -d server-data/knowledge ]; then mv server-data/knowledge "$backup"; fi
mv "$stage" server-data/knowledge
# bind mount 的宿主目录换了，必须重建容器，不能只 start 旧容器。
if ! docker compose -f compose.baota.yaml up -d --no-build --force-recreate --wait --wait-timeout 180; then
    echo "Startup failed. Previous data retained at: $backup"
    exit 1
fi
printf 'Previous knowledge preserved at: %s\n' "$backup"
curl --fail --max-time 30 -sS http://127.0.0.1:18000/api/knowledge/health
printf '\nCheck document/chunk counts, then verify a real question in the browser.\n'
