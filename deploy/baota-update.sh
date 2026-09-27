#!/usr/bin/env bash
# 从独立解压目录更新宝塔现有项目。密钥及四个数据挂载目录均在原位置保留。
set -Eeuo pipefail
umask 077
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
target_dir="$(realpath -e -- "${1:-/www/kuajing-next}")"
if [[ "$target_dir" == / || "$target_dir" == /www || "$target_dir" == "$source_dir" ]]; then
  echo 'Run this script from a separately extracted update package.' >&2
  exit 1
fi
for required in compose.baota.yaml deploy/backend.env backend/app.py; do
  test -f "$target_dir/$required" || { echo "Missing target file: $required" >&2; exit 1; }
done
test -f "$source_dir/backend/remen/scrape_do.py"
command -v python3 >/dev/null
command -v docker >/dev/null
cd -- "$target_dir"
docker compose -f compose.baota.yaml config -q

stamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="$(dirname -- "$target_dir")/kuajing-backups/$stamp"
mkdir -p -- "$backup_dir"
chmod 700 "$backup_dir"
# 备份旧代码和配置，不复制正在写入的数据库。备份包含私密 env，权限限制为本人。
tar --exclude='*/runtime*' --exclude='*/__pycache__' --exclude='*.pyc' \
  -czf "$backup_dir/code-and-config.tar.gz" backend deploy/Dockerfile.api deploy/backend.env compose.baota.yaml .dockerignore
cp -p deploy/backend.env "$backup_dir/backend.env"
container="$(docker compose -f compose.baota.yaml ps -q api)"
old_image=''
if [[ -n "$container" ]]; then
  old_image="$(docker inspect --format '{{.Image}}' "$container")"
  docker tag "$old_image" "kuajing-api-backup:$stamp"
fi

# 新令牌不进入终端历史或日志；回车可沿用服务器上已存在的令牌。
read -r -s -p 'Scrape.do token (Enter keeps existing token): ' SCRAPE_DO_NEW_TOKEN
printf '\n'
export SCRAPE_DO_NEW_TOKEN
python3 - <<'PY'
import os, re
from pathlib import Path
p = Path('deploy/backend.env')
text = p.read_text(encoding='utf-8-sig')
token = os.environ.get('SCRAPE_DO_NEW_TOKEN', '').strip()
current = re.search(r'^\s*SCRAPE_DO_TOKEN\s*=\s*(.*?)\s*$', text, re.M)
if not token:
    token = current[1].strip("\"'") if current else ''
if not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', token) or token.startswith('replace-'):
    raise SystemExit('A valid Scrape.do token is required; configuration was not changed.')
updates = {'SCRAPE_DO_TOKEN': token, 'AMAZON_FETCH_MODE': 'scrape_do'}
for key, value in [('HOT_PRODUCTS_PAGES', '3'), ('HOT_PRODUCTS_REFRESH_HOUR', '5')]:
    if not re.search(r'^\s*'+key+r'\s*=', text, re.M):
        updates[key] = value
for key, value in updates.items():
    text = re.sub(r'^\s*'+key+r'\s*=.*(?:\n|$)', '', text, flags=re.M)
    text = text.rstrip() + '\n' + key + "='" + value + "'\n"
temp = p.with_suffix('.env.update-tmp')
temp.write_text(text, encoding='utf-8')
temp.chmod(0o600)
temp.replace(p)
print('Private configuration updated; token is not displayed.')
PY
unset SCRAPE_DO_NEW_TOKEN

python3 - "$source_dir" "$target_dir" <<'PY'
import os, shutil, sys
from pathlib import Path
source, target = map(Path, sys.argv[1:])
# 不替换服务器的 compose / backend.env，不触碰 runtime、server-data 和 Nginx。
for current, directories, files in os.walk(source/'backend'):
    directories[:] = [d for d in directories if not d.startswith('runtime') and d not in ('__pycache__', 'tests')]
    for name in files:
        path = Path(current)/name
        if path.suffix not in ('.py', '.txt', '.json') or path.name == '.env' or path.is_symlink():
            continue
        relative = path.relative_to(source)
        if relative.as_posix() == 'backend/test.py':
            continue
        destination = target/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
for relative in ('deploy/Dockerfile.api', '.dockerignore'):
    shutil.copyfile(source/relative, target/relative)
PY

docker compose -f compose.baota.yaml config -q
echo "Backup: $backup_dir"
echo 'Building API image; the existing container keeps serving during the build.'
if ! docker compose -f compose.baota.yaml build api; then
  cp -p "$backup_dir/backend.env" deploy/backend.env
  echo 'Build failed. Existing container was not stopped; env restored. Fix the build error and rerun.' >&2
  exit 1
fi
if ! docker compose -f compose.baota.yaml up -d --no-build --wait --wait-timeout 180 api; then
  echo 'New container failed health check. Restoring previous configuration and image.' >&2
  if [[ -n "$old_image" ]]; then
    cp -p "$backup_dir/backend.env" deploy/backend.env
    printf 'services:\n  api:\n    image: kuajing-api-backup:%s\n' "$stamp" > "$backup_dir/rollback.yaml"
    docker compose -f compose.baota.yaml -f "$backup_dir/rollback.yaml" up -d --no-build --wait --wait-timeout 180 api
  fi
  exit 1
fi
docker compose -f compose.baota.yaml ps
curl -fsS --max-time 15 http://127.0.0.1:18000/api/remen/health
printf '\n'
echo 'API updated. First daily collection runs in the background; health does not mean data is ready yet.'
echo 'Inspect: docker compose -f compose.baota.yaml logs --since 10m --tail 100 api'
echo 'Do not remove server-data or run docker compose down -v.'
