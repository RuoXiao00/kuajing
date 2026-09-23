# 这次怎么上传：宝塔后端 + GitHub Pages 前端

你的云服务器公网 IP：**8.138.30.176**。截图中的旧项目位于 `/www/wwwroot/aliyun-deploy`，里面有 `db`、`后端`、`.env` 和旧 Compose 文件。

你已确认**目前只有服务器 IP，没有域名**。现在可以完成上传、配置、构建及服务器本机验收（B～E）；F～G 的正式 Pages/API 连接要等获得可用域名后完成。当前方案不提供只凭 IP 就能完整打通 Pages 图片会话的承诺，也不将 HTTP IP 地址填进 Actions 变量。

**现在不删除、不覆盖旧目录，不停止整个 Docker 或宝塔 Nginx。** 新版放在 `/www/kuajing-next`，使用独立 Docker 项目名、独立数据目录和回环端口 18000，先验证新版再切换。

## A. 已整理好的两个压缩包

本机项目 `release` 下最新时间目录中有：

| 文件 | 上传到哪里 | 内容 |
| --- | --- | --- |
| `kuajing-backend.zip` | 宝塔文件管理的 `/www` 目录 | 新后端、Docker 配置、检查脚本、操作说明 |
| `kuajing-github-source.zip` | 解压到本机后，把里面源码上传 GitHub | 前端和后端源码、Pages 自动发布工作流、文档 |

两个包都**没有真实 `.env`、数据库、历史图片、node_modules**。GitHub 不会解压 zip 并运行其中的项目，不能把源码 zip 当作网站直接提交；后端 zip 则可以用宝塔“上传 → 解压”。

重新打包命令（本机 PowerShell）：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -B scripts\package_upload.py
```

## B. 宝塔：先上传、检查旧项目

1. 宝塔左侧 **文件**，地址栏输入 `/www`，回车。这里不是截图中的 `/www/wwwroot`。
2. 点击 **上传/下载 → 上传文件**，上传 `kuajing-backend.zip`。
3. 点压缩包右侧 **解压**，解压目标选 `/www`。压缩包本身带 `kuajing-next` 顶层文件夹。
4. 解压后应能看到 `/www/kuajing-next/compose.baota.yaml`。不要多套一层 `kuajing-next/kuajing-next`。
5. 如果 `/www/kuajing-next` 已存在，不选“覆盖全部”；先核对是否是之前已经启动的新版本。
6. 左侧打开 **终端**。以下 Linux 命令在宝塔终端运行，不是在 Windows PowerShell。

先执行只读检查：

```bash
cd /www/kuajing-next
bash deploy/baota-inspect.sh
```

它只显示系统、磁盘空间、Docker 版本、容器、监听端口、旧目录文件名及旧容器的数据挂载；不会读 `.env` 内容，不会停止或删除东西。可以将输出用于确认旧项目是什么、数据在哪里。

没有 Docker 命令时，先在宝塔 Docker 页面检查安装状态。**已有容器时不要重装 Docker。** 当前宝塔配置已适配你服务器的 Compose 2.28.1，无需为了这次部署升级 Docker。

你之前已上传的包带有 `format: raw`，需要在服务器执行一次以下修正；新下载的兼容包已修复，不必重新上传整个项目：

```bash
cd /www/kuajing-next
sed -i.bak '/^[[:space:]]*format: raw[[:space:]]*$/d' compose.baota.yaml
```

旧文件留在 `compose.baota.yaml.bak`。旧模板没有单引号，填写管理员密码哈希时务必按下面 C 的说明加单引号。

新包需要服务器自行下载 Python 镜像、依赖和 Chromium，构建和缓存也占磁盘。截图只有磁盘容量信息，不能据此判断可用空间，以上 `df -h` 才显示剩余量。

## C. 初始化新版、填配置、构建

通常宝塔终端是 root。不是 root 时在下面的 `bash deploy/baota-init.sh` 前加 `sudo`：

```bash
cd /www/kuajing-next
bash deploy/baota-init.sh
```

这一步创建新项目的 `deploy/backend.env` 和四个空数据目录，保留已有 env，不启动后端。用宝塔文件管理打开：

```text
/www/kuajing-next/deploy/backend.env
```

**填写真实配置**：百炼 API Key、原来的模型配置、Coze Token、工作流 ID、管理员用户名。可以在自己的本机 `.env` 中查看原值，手动填到此新文件；不要将密钥发到聊天或 GitHub，也不要把旧服务器 `.env` 整份覆盖过来，它的变量结构可能不同。

域名尚未确定时可以先构建；对外使用之前必须填写实际前端来源：

```dotenv
COOKIE_SECURE='true'
FRONTEND_ORIGINS='https://app.你的实际域名'
TRUST_PROXY_HEADERS='true'
AMAZON_FETCH_MODE='browser'
AMAZON_BROWSER_CHANNEL='chromium'
```

宝塔方案使用普通 env_file，按 `名称='值'` 填写，保留英文单引号，不在值后面加注释，不要 `source` 这个文件。尤其 `ADMIN_PASSWORD_HASH` 中的 `$` 需要单引号保护，避免被 Compose 当环境变量替换；其他方案的 raw 模板不能混用。新模板和原来的 `.env` 不共享，不会自动继承密钥。[Docker env_file 格式说明](https://docs.docker.com/reference/compose-file/services/#env_file)

构建新镜像：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml config -q
docker compose -f compose.baota.yaml build api
```

构建不调用模型、不启动定时推荐。管理员密码哈希和会话密钥可以通过构建好的镜像生成：

如果旧包构建很慢（pip 只有几十 KB/s，或 `deb.debian.org` 下载 97 MB 系统依赖耗时十几分钟），按以下步骤更新构建文件：

1. 在原构建终端按 `Ctrl+C`，等回到命令提示符。
2. 宝塔文件管理打开 `/www/kuajing-next/deploy`，上传本机项目的 `deploy/Dockerfile.api`，覆盖同名文件即可。不需要重传整个压缩包，也不覆盖 `backend.env`。
3. 回到宝塔终端执行：

```bash
cd /www/kuajing-next
docker compose --progress plain -f compose.baota.yaml build api
```

新版 Dockerfile 使用服务器已成功拉取的 ECR 官方 Python 镜像；Python 包和容器内 Debian 系统依赖改走阿里云 HTTPS 镜像，后者日志应出现 `https://mirrors.aliyun.com/debian`。宿主机仍是 Alibaba Linux，不需要改宿主机的软件源。Python 固定依赖版本保持不变，24 个直接依赖的版本已核对存在。[阿里云 PyPI 镜像](https://developer.aliyun.com/mirror/pypi)、[Debian 镜像](https://developer.aliyun.com/mirror/debian)

Python 包、系统依赖、浏览器分为三个镜像层，Python 下载增加 BuildKit 缓存。旧文件把三步连在一起，当前步骤没有完成，所以本次换文件后 Python 安装仍会重跑一次；之后相同配置重试可以复用已经完成的层。不要加 `--no-cache`，也不要为提速清理 Docker 构建缓存。

当前爬虫以 headless 模式启动且不传 Chromium channel 参数，所以仅安装 `--only-shell chromium`，减少无用浏览器下载。浏览器文件仍使用官方源，其速度取决于服务器网络；实际速度以构建日志为准。[Playwright 安装说明](https://playwright.dev/python/docs/browsers#chromium-headless-shell)

镜像构建完成后，再生成管理员配置：

```bash
docker compose -f compose.baota.yaml run --rm --no-deps api python -c 'import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass("Admin password: ").encode(), bcrypt.gensalt()).decode())'
docker compose -f compose.baota.yaml run --rm --no-deps api python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

把两条输出分别填入新 `backend.env` 的 `ADMIN_PASSWORD_HASH`、`SESSION_SECRET`。输入密码不回显是正常的；这些输出自己保存，不贴出来。

## D. 旧项目和旧数据怎么处理

截图只能确认有一个叫 `db` 的目录，**不能判断它属于哪个数据库、是否还有 Docker 数据卷，也不能直接认定能迁入当前 Chroma**。先看 B 中的容器挂载输出。

| 旧内容 | 处理方式 |
| --- | --- |
| `aliyun-deploy` 整个目录 | 先原样保留，作为旧版回退来源 |
| `.env` | 原地保留；新版本单独填写配置，不提交 GitHub |
| `db`、运行数据目录、Docker volumes | 确认实际用途和挂载后做一致性备份，不能先删 |
| 旧容器 | 新版验证通过且准备切换时，只停止确认属于旧项目的容器 |
| `default`、宝塔自身目录、其他网站 | 不修改、不删除 |

**新项目不使用旧项目的 db，也不会覆盖它。** 你有两个数据起点：

1. 使用当前电脑上已经修好的项目数据：按下面方式单独迁移整个 runtime，通常更贴近现在的页面。
2. 使用旧服务器的数据：先核对数据库类型、版本、集合名和挂载位置，再确定映射。拿到检查输出之前，不写自动迁移命令。

### D1. 迁移当前电脑的数据（可选，想保留现有知识库时需要）

先在电脑运行后端的原终端按 `Ctrl+C`，等待正常退出，确保没有其他爬虫/导入进程写库。然后在本机 PowerShell：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
$runtimePackage = Join-Path $env:TEMP 'kuajing-runtime.tar.gz'
tar -czf $runtimePackage backend/zhishiku/runtime backend/tuijian/runtime backend/remen/runtime backend/tupian/runtime
Write-Output $runtimePackage
```

如果某个目录不存在，从命令里去掉该目录。将生成的 tar.gz 用宝塔上传到 **`/www/kuajing-next`**，不要上传 GitHub。此包包含私人数据，不能放到网站公开目录。

在宝塔终端操作，**只适用于新后端尚未启动、四个目标目录为空时**：

```bash
cd /www/kuajing-next
find server-data -mindepth 2 -maxdepth 2 -print
```

有输出表示已有内容，先不要执行下面的复制；否则：

```bash
mkdir -p import-runtime
tar -xzf kuajing-runtime.tar.gz -C import-runtime
cp -a import-runtime/backend/zhishiku/runtime/. server-data/knowledge/
cp -a import-runtime/backend/tuijian/runtime/. server-data/recommendations/
cp -a import-runtime/backend/remen/runtime/. server-data/products/
cp -a import-runtime/backend/tupian/runtime/. server-data/images/
chown -R 10001:10001 server-data
```

未打包的模块跳过对应 `cp`。迁移后核对知识库数量并真实检索；不要更改 Embedding 模型/集合名称。换域名后浏览器问答历史不会自动迁移，旧 Cookie 所属图片也不会自动显示给新的浏览器会话。

不迁移也能启动，但知识库为空，需要到 `/#/admin` 重新上传资料。没有推荐快照时，启动会自动生成一期并使用模型额度。

### D2. 停旧版和备份：等切换时再做

先确认旧容器名称、项目标签和挂载范围，不能执行 `docker stop $(docker ps -q)` 这类停止全部容器的命令。

下面的 `旧后端容器名` 必须换成 B 中确认过的真实名称，**不是现在直接照抄执行**：

```bash
docker stop 旧后端容器名
```

待所有写入旧数据的进程停止后，备份旧目录到非公开目录：

```bash
umask 077
mkdir -p /www/backup/kuajing
backup_stamp=$(date +%Y%m%d-%H%M%S)
tar -czf "/www/backup/kuajing/aliyun-deploy-$backup_stamp.tar.gz" -C /www/wwwroot aliyun-deploy
```

若检查发现数据在旧目录之外或 Docker named volume 中，上述压缩包**不包含那些数据**，需要按实际挂载单独备份，不能把它当成完整数据库备份。保留容器、卷和目录；不要执行 `down -v`、`docker system prune --volumes` 或删除 `db`。

## E. 先在服务器本机启动并验收

在宝塔终端：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml up -d
docker compose -f compose.baota.yaml ps
docker compose -f compose.baota.yaml logs --tail=80 api
curl -f http://127.0.0.1:18000/
curl -f http://127.0.0.1:18000/api/knowledge/health
```

根接口返回 JSON 说明进程可响应；健康接口用来核对知识库。若端口被占用，先定位占用者，不直接杀进程；需要改端口时 Compose 和宝塔反向代理目标要一起改。

这时服务只监听 `127.0.0.1:18000`，外网访问 `8.138.30.176:18000` 失败是预期结果。**不要在阿里云安全组开放 18000/8000/8001，也不要修改绑定为 0.0.0.0。** 对外访问交给宝塔 HTTPS 反向代理。

## F. 宝塔反向代理与域名

此步待域名准备好后执行。前端仍由 GitHub Pages 托管，只是绑定自定义域名：

| 地址 | DNS |
| --- | --- |
| `app.你的域名`（仍托管在 GitHub Pages） | CNAME → `你的GitHub用户名.github.io` |
| `api.你的域名` | A → `8.138.30.176` |

`https://你的用户名.github.io/kuajing/` 不能直接请求普通 HTTP IP 后端；图片历史和管理员会话又依赖 Cookie，不同站点组合会遇到浏览器限制。**绑定前端自定义域名不等于把前端移到服务器**，Pages 仍负责网页。只有 IP 而没有可用域名时，先完成 E 的本机验收，对外完整使用还未准备完成。

宝塔 **网站 → 添加站点**，填 `api.你的域名`。选择纯静态或不启用 PHP，不创建数据库。网站根目录选择新建的空站点目录，例如 `/www/wwwroot/kuajing-api-site`，**不要指向后端源码 `/www/kuajing-next`**。

如果该 API 域名已有站点，不再添加同名站点：先保存现有代理设置，完成 E 后再修改目标。其他网站保持原样。

在 API 站点设置里：

1. **SSL**：申请/部署该 API 域名的有效证书，成功后开启强制 HTTPS。不要只给“宝塔面板登录地址”装证书。
2. **反向代理 → 添加反向代理**：名称 `kuajing-next`，目录 `/`，目标 URL `http://127.0.0.1:18000`，发送域名 `$host`，关闭缓存。
3. 打开该条反向代理的配置，将原 `location / { ... }` 替换成包内 `deploy/baota-proxy.conf`。不要覆盖完整 SSL server 配置，不要保留两个相同 location。
4. 保存并让宝塔检测/重载 Nginx。该配置包含 SSE 不缓存、上传大小、长请求超时及真实协议转发。

宝塔官方操作参考：[反向代理](https://docs.bt.cn/user-guide/site/php/site-config/reverse-proxy)、[网站 SSL](https://docs.bt.cn/user-guide/site/php/site-config/ssl)。这里使用宝塔宿主机 Nginx；如果你的实际部署是 Docker 内的 Nginx，需要根据检查结果调整网络，容器内 127.0.0.1 并不是宿主机。

访问 `https://api.你的域名/` 应返回后端 JSON。阿里云安全组为网站放行 80/443，保留原来的宝塔/SSH 管理规则，不停止当前 Nginx，不另开 Caddy 抢端口。

## G. 前端源码上传 GitHub，启用 Pages

解压 `kuajing-github-source.zip`。里面的 `kuajing-source` 是完整、已排除密钥的源码目录，**不要把 zip 文件本身当成源码仓库**。GitHub 网页上传也必须上传解压后的文件并保留 `.github/workflows/pages.yml`；用 Git 更可靠：

```powershell
# 把路径替换成你解压后 kuajing-source 的实际位置。
cd C:\你的解压位置\kuajing-source
git init -b main
git config user.name "你的名字"
git config user.email "你的提交邮箱"
git add .
git status --short
git commit -m "Deploy frontend and backend"
git remote add origin https://github.com/你的用户名/kuajing.git
git push -u origin main
```

上面用于 GitHub 新建的空仓库。已有仓库不要重新覆盖或强推，直接在原本本机仓库更新即可。GitHub Free 的 Pages 通常使用 Public 仓库，私有仓库请核对账户套餐。

仓库设置按顺序配置：

**上传源码现在可以做；下面的自动发布配置待域名就绪后完成。** 初次推送触发的 workflow 如果因为 Pages 或 HTTPS API 尚未配置而失败，不代表代码上传失败；配置完成后重新运行即可。

1. **Settings → Pages → Source：GitHub Actions**。
2. **Custom domain：`app.你的域名`**，对应 CNAME 生效后开启 Enforce HTTPS。
3. **Settings → Secrets and variables → Actions → Variables** 新增 `VITE_API_BASE_URL`，值为 `https://api.你的域名`，不带 `/api`。
4. **Actions → Publish frontend to GitHub Pages → Run workflow**。

成功后分享 `https://app.你的域名`。路由会显示 `/#/tuijian`，刷新不会 404。完整说明见 [Pages 教程](github-pages-cloud-tutorial.md)，但后端命令以本篇 `compose.baota.yaml` 为准。

## H. 切换成功后、出问题回退

新版推荐、热门滚动、知识问答、生图和下载都验收通过后，停止明确属于旧项目的应用容器，旧目录和数据仍保留一段时间。旧 Nginx 若也服务其他站点，不要一起停止。新项目名是 `kuajing-next`，不要误停它。

回退：宝塔反向代理目标改回之前记录的旧地址，恢复旧应用容器（`docker start 旧容器名`）；若新旧前端 API 地址不同，也恢复 GitHub 的 `VITE_API_BASE_URL` 并重新发布前端。新版数据与旧库独立，不会自动合并。

新版本日常命令：

```bash
cd /www/kuajing-next
docker compose -f compose.baota.yaml logs -f --tail=100 api
# Ctrl+C 只退出看日志。
docker compose -f compose.baota.yaml stop
docker compose -f compose.baota.yaml up -d
```

后续更新源码时，只更新代码，不覆盖真实 `deploy/backend.env` 或 `server-data`，然后 `docker compose -f compose.baota.yaml up -d --build`。本包不包含登录门槛，公开问答/生图使用的是你的供应商额度。

当前准备工作的边界：打包和 Compose 配置可在本机验证；尚未连接或修改 8.138.30.176，也未获知旧数据库结构。第一次应先完成 B 的只读检查，再决定旧服务停止和数据迁移范围。
