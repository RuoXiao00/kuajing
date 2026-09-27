# Scrape.do 共享采集与宝塔更新

当前架构：GitHub Pages 只提供前端；云服务器通过 Scrape.do 获取 Amazon 数据，写入 SQLite；不同用户都读取同一份快照。浏览和刷新展示不会调用收费采集。

## 数据如何更新

- 热门产品：启动时检查当期数据；北京时间每天 05:00 开始下一期更新，按品类顺序处理。默认 9 个搜索品类、每个最多 3 张搜索页，保存本轮全部有效且去重的商品。这里的“全部”指本轮采样结果，并非 Amazon 全站商品。
- 页面：首次读取当前筛选的完整集合，下滑每次多展示 20 件。没有快照或后台尚未更新完时，只读接口最多自动查询 6 次；手动“刷新展示”同样只读。
- 共享持久化：`server-data/products/shared-products.sqlite3`，容器重建不会丢失。当天相同关键词、页码的成功结果在热门和推荐任务之间复用。
- 替换旧数据：各品类本期采集成功后事务替换旧集合；失败保留上一期并标记过期。当天失败最多尝试两次，间隔至少 15 分钟。后台不运行时不会更新，恢复运行后补当期。
- 每日推荐：商品搜索和 Amazon 榜单均使用 Scrape.do；Google 热搜仍使用原 RSS。推荐结果继续保存在 `server-data/recommendations`，由现有每日调度生成。已有当日成功推荐会保留至下一期，不会为了部署再付费生成一次。
- 预算：热门首次完整采样最多 27 次搜索请求；每日推荐有独立候选搜索和 3 个 Amazon 资料来源，会额外消耗额度。失败补试也可能产生请求。相同成功页面会复用；没有自动打开更高价格代理。实际计费以供应商响应和控制台为准。

后端配置（只放私有 `deploy/backend.env`）：

```dotenv
AMAZON_FETCH_MODE='scrape_do'
SCRAPE_DO_TOKEN='在服务器输入自己的令牌'
HOT_PRODUCTS_PAGES='3'
HOT_PRODUCTS_REFRESH_HOUR='5'
```

`HOT_PRODUCTS_PAGES` 允许 1..10。已有当日快照不会因调整页数被强制重新采集，新设置在下一期生效。保持单个 API 容器、单个 Uvicorn worker；不要同时运行多个共享数据库的采集服务。

## 现有宝塔服务器怎么更新

目标保持 `/www/kuajing-next`。不重装 Python、不重装系统、不重新申请 SSL。Docker 会构建新业务镜像并重建 API 容器；以后仅改业务代码时可复用依赖层。本次 Dockerfile 去掉了 Chromium 和浏览器系统依赖，首次构建可能重新下载 Python 依赖。

1. 本机项目根目录执行 `python -B scripts/package_upload.py`，找到输出目录里的 `kuajing-backend.zip`。上传到宝塔 **`/www`**，路径为 `/www/kuajing-backend.zip`。
2. 宝塔终端粘贴以下整段。压缩包解压到新的临时目录；脚本先备份旧配置和镜像，再覆盖必要后端代码。需要时会提示粘贴 Scrape.do 令牌，输入不会显示在终端中。

```bash
set -e
cd /www
test -f /www/kuajing-backend.zip
update_dir="$(mktemp -d /www/kuajing-update-XXXXXX)"
python3 -m zipfile -e /www/kuajing-backend.zip "$update_dir"
bash "$update_dir/kuajing-next/deploy/baota-update.sh" /www/kuajing-next
```

仅解压本项目打包器生成的上传包。不要把源码解压后直接覆盖整个旧目录；不要复制本机 `.env` 或数据库到服务器。

3. 检查。以下命令只读，不消耗 Scrape.do 额度：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml ps
curl -fsS http://127.0.0.1:18000/api/remen/health
curl -fsS 'http://127.0.0.1:18000/api/remen/products/snapshot?subCategory=all' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d.get("snapshot") or {}; print({"status":d.get("update_status"),"count":len(s.get("products",[])),"fetched_at":s.get("fetched_at"),"stale":s.get("is_stale")})'
docker compose -f compose.baota.yaml logs --since 10m --tail 100 api
```

`configured: true` 仅表示配置存在，不保证供应商额度充足。首次 `pending/updating`、数量 0 可等待几分钟再读；`ready` 有商品表示该品类成功。出现 `scrape_do_auth_or_credits` 检查令牌/额度；`scrape_do_upstream_error` 或 `scrape_do_timeout` 检查供应商状态和服务器访问 `api.scrape.do:443` 的网络。失败不退回已受限的直连爬虫。

4. 更新 GitHub Pages：在本机测试通过并提交后运行 `git push origin main`，等仓库 Actions 的 Pages 工作流成功。服务器代码上传和 GitHub 推送是两步，单纯提交不会自动更新服务器。建议先更新后端，再推前端，避免旧服务器只提供首屏快照。

## 旧文件、数据和回滚

- 保留 `server-data` 四个子目录、原 `deploy/backend.env` 中的其他设置、Compose 端口和宝塔 Nginx/SSL。不要执行 `docker compose down -v`，也不要清理数据卷。
- 旧版 `first-page.sqlite3` 即使仍在也不参与新流程，可以先留着，体积很小。新流程的数据库自动创建，无需手动建表。
- 备份位于脚本输出的 `/www/kuajing-backups/时间戳`，其中含密钥配置，勿上传 GitHub。旧镜像标记为 `kuajing-api-backup:时间戳`。确认更新稳定后，才按具体备份路径或镜像标签手动清理。
- 构建失败不会停止原容器；启动后的健康检查失败时脚本尝试恢复旧 env 和旧镜像。业务数据异常但健康检查通过时，需要人工查看上述快照状态，不能只凭容器 Healthy 判断采集成功。
- 如需人工回退，把下面备份路径换成脚本打印的实际值（不要把 `时间戳` 原样复制执行）：

```bash
cd /www/kuajing-next
backup_dir=/www/kuajing-backups/时间戳
test -f "$backup_dir/code-and-config.tar.gz"
tar -xzf "$backup_dir/code-and-config.tar.gz" -C /www/kuajing-next
docker compose -f compose.baota.yaml up -d --build --wait --wait-timeout 180 api
```

这个备份不含数据库，回退源码不会删除新旧业务数据。

## 官方接口依据

- [Scrape.do Amazon 结构化搜索接口](https://scrape.do/documentation/amazon-scraper-api/search/)
- [Scrape.do Amazon HTML 接口](https://scrape.do/documentation/amazon-scraper-api/raw-html/)
- [Scrape.do 请求费用](https://scrape.do/documentation/request-costs/)
- [Docker Compose 生产环境更新](https://docs.docker.com/compose/how-tos/production/)
