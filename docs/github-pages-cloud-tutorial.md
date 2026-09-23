# GitHub Pages 前端 + Docker 云服务器后端：操作流程

> 最新确认：服务器为 8.138.30.176，使用宝塔，且目前只有 IP、没有域名。请先按 [宝塔直接上传流程](baota-upload-steps.md) 上传和验收后端，使用 `compose.baota.yaml`。本文的域名连接部分作为后续步骤；下面“已有域名”是前一轮假设，已被新信息纠正。

本次采用你确认的方案：前后端源码放在同一个 GitHub 仓库；网页交给 GitHub Pages，Python 后端在云服务器的 Docker 中运行。你已有域名，因此用两个子域名。

本文的 `example.com`、`你的用户名`、`SERVER_IP` 都是占位符，操作前换成自己的。配置文件已经准备好；尚未替你购买服务器、修改 DNS、创建仓库、上传代码或上线。

准备阶段已通过前端检查、43 项测试、普通/Pages 构建、Compose 配置解析，以及隔离浏览器的跨域图片生成与下载验证。测试未调用真实 Coze。当前本机 Docker 引擎未运行，Linux 镜像构建和云端真实验收仍需按本文完成。

## 1. 最终会是什么样子

| 地址 / 位置 | 用途 |
| --- | --- |
| `github.com/你的用户名/kuajing` | 保存 `src` 前端和 `backend` 后端源码 |
| `https://app.example.com/#/tuijian` | 访客打开的页面，实际由 GitHub Pages 提供 |
| `https://api.example.com` | Docker 后端的 HTTPS 入口 |
| 云服务器 `~/kuajing/server-data` | 知识库、推荐快照、热门商品和生成原图 |

```text
本机修改 → git push → GitHub 仓库
                      ├─ Actions：构建 src → GitHub Pages → app.example.com
                      └─ 服务器 git pull → Docker 构建 backend → api.example.com

访客浏览器打开 app.example.com
    └─ 请求 api.example.com → Caddy HTTPS → FastAPI → 模型 / 爬虫 / 持久数据
```

GitHub Pages 只托管静态网页，不能运行 FastAPI 或 Docker。这里的“前端也上传 GitHub”是上传源代码，Actions 自动构建并发布 `dist`，不需要手动上传 `node_modules` 或 `dist`。[GitHub Pages 说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)

前后端子域名都使用 HTTPS。它们虽然是不同 origin，却属于同一个 site，能沿用当前安全 Cookie。请最终分享 `app.example.com` 地址：直接用 `你的用户名.github.io` 访问不同域名的 API 时，图片会话和管理员登录会受到跨站 Cookie 限制，单改 CORS 无法解决。[MDN 的同站与跨域说明](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Fetch_metadata)、[Cookie 与跨域请求](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)

## 2. 已准备的文件

| 文件 | 你需要知道的作用 |
| --- | --- |
| `.github/workflows/pages.yml` | 推送 main 后，检查、构建并发布前端；也能手动运行 |
| `vite.config.js`、`src/main.jsx` | 自动适配 Pages 路径，Pages 使用 HashRouter，刷新子页面不会 404 |
| `scripts/check-pages-config.mjs` | 发布前拦截未填写、HTTP 或 localhost 的 API 地址 |
| `compose.pages.yaml` | **本教程唯一使用的 Compose 入口**，只启动 api 和 gateway |
| `deploy/Dockerfile.api` | Python 3.13、依赖和 Chromium；后端只运行一个 worker |
| `deploy/Caddyfile.api` | 后端 HTTPS、反向代理和 SSE 实时转发 |
| `deploy/api.env.example` | API 域名示例 |
| `deploy/backend.env.example` | 后端密钥、模型、Cookie 和 CORS 示例 |

原来的 `compose.yaml` / `compose.https.yaml` 和 [旧教程](github-docker-deployment-tutorial.md) 是“前后端都放服务器”的另一套方案。**本次不要启动旧方案的 web 容器，也不要同时启动两套后端**，否则会端口冲突或重复运行每日推荐。

## 3. 本机：把源码上传到 GitHub

以下在 Windows PowerShell 操作：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
git --version
```

没有 Git 时先安装 Git for Windows，再重新打开终端。到 [GitHub 新建仓库](https://github.com/new)，仓库名填 `kuajing`。使用 GitHub Free 时选 Public 才能使用 Pages；私有仓库的 Pages 可用性取决于账户套餐。不要勾选自动创建 README、License 或 `.gitignore`，本机已有文件。

当前目录尚未初始化 Git；首次执行：

```powershell
git init -b main
git config user.name "你的名字"
git config user.email "你的GitHub提交邮箱"
git check-ignore .env deploy/backend.env deploy/api.env backend/zhishiku/runtime/chroma/chroma.sqlite3 server-data/images/example.png
git add .
git diff --cached --stat
git diff --cached --name-only
```

检查列表应包含 `src`、`backend`、`.github`、`deploy`、`docs` 和依赖清单；不能有 `.env`、真实配置、runtime 数据库、原图、备份或原始知识资料。`.gitignore` 已排除这些内容。已被旧仓库跟踪的秘密不会被 `.gitignore` 自动移除，需要另外处理；不要使用 `git add -f`。

确认后上传：

```powershell
git commit -m "Prepare GitHub Pages and Docker API deployment"
git remote add origin https://github.com/你的用户名/kuajing.git
git push -u origin main
```

Git 提示登录时用 GitHub 的浏览器认证；不要把百炼或 Coze Token 当 GitHub 密码。已有 origin 就先看 `git remote -v`，不要重复添加或强推。以后修改用 `git add` → `git commit` → `git push`。

初次 push 时 Pages 还没配置，Actions 可能失败；完成下一节后手动重新运行即可。

## 4. GitHub 和域名：配置前端地址

### 4.1 先绑定 Pages 域名

进入 GitHub 仓库 → **Settings → Pages**：

1. Build and deployment 的 Source 选择 **GitHub Actions**。
2. Custom domain 填 `app.example.com`，Save。
3. 到域名 DNS 控制台添加下表记录。
4. 等 DNS 检查和证书签发完成，再启用 **Enforce HTTPS**。

| 记录类型 | 主机记录 | 记录值 |
| --- | --- | --- |
| CNAME | `app` | `你的用户名.github.io` |
| A | `api` | `SERVER_IP`，云服务器公网 IPv4 |

CNAME 不带 `https://`、不带仓库名或斜杠。`app` 不指向服务器 IP，因为前端在 Pages；`api` 不指向 GitHub。没有部署 IPv6 时不要保留错误的 AAAA 记录。先在 GitHub 绑定再设置 DNS，官方还支持通过 TXT 记录验证域名所有权。[GitHub 自定义子域名步骤](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

本机可检查解析：

```powershell
nslookup app.example.com
nslookup api.example.com
```

### 4.2 填写公开的后端地址

GitHub 仓库 → **Settings → Secrets and variables → Actions → Variables → New repository variable**：

```text
Name:  VITE_API_BASE_URL
Value: https://api.example.com
```

这是公开地址，不是密钥；不追加 `/api`。所有模型密钥都留在服务器，**不能放进 `VITE_` 变量**。

路由模式和资源 base 已由 Actions 设置。自定义域名自动使用 `/`，默认项目地址使用 `/kuajing/`，不需要改源码里的仓库名。[Vite Pages 构建说明](https://vite.dev/guide/static-deploy)

打开仓库 **Actions → Publish frontend to GitHub Pages → Run workflow → main**。成功后打开 `https://app.example.com/#/settings`；此时如果后端还没部署，设置和页面布局可查看，数据功能要等后端启动。

以后推送 main 会自动更新前端。**修改 Repository Variable 或 Pages 自定义域名后，也需要重新 Run workflow**，因为 API 地址和资源路径是在构建时写入 JS 的。

## 5. 云服务器：安装 Docker

以下以 Ubuntu 24.04 LTS、x86_64、单台服务器为操作示例。服务器必须能访问模型、Coze、商品源站和镜像/依赖仓库；不能仅凭地区保证爬虫可用。已有服务器先检查系统和资源，再安装，不覆盖已有业务。

在云安全组开放 TCP **80、443**，SSH **22** 尽量只允许自己的 IP。**不用开放 8000、8001、5173**。如果已有服务占用 80/443，需要先安排网关入口。

本机连接：

```powershell
ssh ubuntu@SERVER_IP
# 如果云平台要求私钥：ssh -i C:\Users\ruoxiao\.ssh\你的私钥 ubuntu@SERVER_IP
```

用户名按云平台实际提供的填写，不一定是 ubuntu。下面的 Bash 都在服务器执行。已有 Docker 可跳过安装，先看 `sudo docker version`、`sudo docker compose version`。新服务器按 [Docker 官方 Ubuntu 文档](https://docs.docker.com/engine/install/ubuntu/)安装：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Compose 需要 2.30.0 或更新版本，支持 `env_file.format: raw`，这样 bcrypt 哈希中的 `$` 才能原样传入。不使用旧的 `docker-compose` v1。

## 6. 服务器：拉代码、填写后端配置

```bash
cd ~
git clone https://github.com/你的用户名/kuajing.git
cd kuajing
cp -n deploy/backend.env.example deploy/backend.env
cp -n deploy/api.env.example deploy/api.env
chmod 600 deploy/backend.env deploy/api.env
mkdir -p server-data/knowledge server-data/recommendations server-data/products server-data/images
sudo chown -R 10001:10001 server-data
nano deploy/api.env
```

私有仓库使用只读 Deploy Key，步骤见 [旧教程第 5.2 节](github-docker-deployment-tutorial.md#52-私有仓库给服务器一把只读-deploy-key)。

`deploy/api.env` 填：

```dotenv
API_DOMAIN=api.example.com
```

再执行 `nano deploy/backend.env`。用本机当前有效的后端配置填写模型与 Coze 部分，保留原模型设置；另外修改：

```dotenv
COOKIE_SECURE=true
FRONTEND_ORIGINS=https://app.example.com
TRUST_PROXY_HEADERS=true
AMAZON_FETCH_MODE=browser
AMAZON_BROWSER_CHANNEL=chromium
TZ=Asia/Shanghai
```

`FRONTEND_ORIGINS` 是网页 origin，不带 `/#/tuijian` 或 `/kuajing/`，不能填 `*`。不要把整个本机 `.env` 上传到仓库。配置按 `名称=值` 填写，不加引号，不在值后追加注释，也不要用 `source` 执行这些文件。

必填项的来源：

| 配置项 | 来源 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 你自己的百炼密钥 |
| `QWEN_MODEL`、`QWEN_REWRITE_MODEL`、`DASHSCOPE_EMBEDDING_MODEL` | 与本机正在使用的配置保持一致 |
| `DASHSCOPE_RERANK_BASE_URL` | 自己的 Workspace 兼容地址 |
| `COZE_API_TOKEN`、`COZE_WORKFLOW_ID` | 已发布的 Coze 工作流及有相应权限的 Token |
| `ADMIN_USERNAME` | 仅知识库管理使用的账号名 |
| `ADMIN_PASSWORD_HASH`、`SESSION_SECRET` | 下一步生成 |

构建后端镜像，不会启动推荐任务：

```bash
sudo docker compose -f compose.pages.yaml config -q
sudo docker compose -f compose.pages.yaml build api
sudo docker compose -f compose.pages.yaml run --rm --no-deps api python -c 'import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass("Admin password: ").encode(), bcrypt.gensalt()).decode())'
sudo docker compose -f compose.pages.yaml run --rm --no-deps api python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

把前一条输出填入 `ADMIN_PASSWORD_HASH`，后一条填入 `SESSION_SECRET`。输入密码时不回显是正常的。不要分享输出；管理员权限只用于资料管理，普通访客无需登录。

## 7. 首次启动前：迁移现有数据

**GitHub 只有源码，没有你本机知识库和图片。** 建议先迁移再启动，避免把空库误认为原有内容丢失。

| 本机目录 | 服务器目录 |
| --- | --- |
| `backend/zhishiku/runtime` | `server-data/knowledge` |
| `backend/tuijian/runtime` | `server-data/recommendations` |
| `backend/remen/runtime` | `server-data/products` |
| `backend/tupian/runtime` | `server-data/images` |

先在本机后端原终端 `Ctrl+C` 等待退出，确保没有其他进程写这些库。在本机 PowerShell 打包到临时目录，经 SSH 传输：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
$migrationFile = Join-Path $env:TEMP 'kuajing-runtime.tar.gz'
tar -czf $migrationFile backend/zhishiku/runtime backend/tuijian/runtime backend/remen/runtime backend/tupian/runtime
scp $migrationFile ubuntu@SERVER_IP:~/kuajing-runtime.tar.gz
```

没有的 runtime 从打包命令中去掉；使用私钥时 `scp` 也添加 `-i`。数据库必须停写后复制完整目录，不能只拿一个 SQLite 文件。

服务器操作，**只适用于首次迁入、目标四个目录为空**；已有数据先备份，不直接合并覆盖：

```bash
cd ~/kuajing
mkdir -p ~/kuajing-import
tar -xzf ~/kuajing-runtime.tar.gz -C ~/kuajing-import
sudo cp -a ~/kuajing-import/backend/zhishiku/runtime/. server-data/knowledge/
sudo cp -a ~/kuajing-import/backend/tuijian/runtime/. server-data/recommendations/
sudo cp -a ~/kuajing-import/backend/remen/runtime/. server-data/products/
sudo cp -a ~/kuajing-import/backend/tupian/runtime/. server-data/images/
sudo chown -R 10001:10001 server-data
```

没有迁移的模块跳过对应 `cp`。向量模型和集合配置必须保持一致；Windows → Linux 迁移后仍需真实问答验收。不迁移时，可在 `https://app.example.com/#/admin` 登录后重新上传知识资料，重新入库会调用 Embedding。

设置、问答历史在浏览器 localStorage，换域名后是新的存储空间；生成图片按浏览器 Cookie 分组，搬运文件不会把旧会话自动认领给新访客。迁移前先下载自己需要的旧作品。服务器上的“原图本地保存”指保存到服务器持久目录，访客点击保存原图才下载到自己的电脑。

## 8. 启动后端、验收前后端连接

确认 `api` A 记录已解析到服务器、80/443 可达，再启动：

```bash
cd ~/kuajing
sudo docker compose -f compose.pages.yaml config -q
sudo docker compose -f compose.pages.yaml up -d
sudo docker compose -f compose.pages.yaml ps
sudo docker compose -f compose.pages.yaml logs --tail=80 api gateway
curl -f https://api.example.com/
curl -f https://api.example.com/api/knowledge/health
```

Caddy 会申请并续期 HTTPS 证书；首次签发可能需要等待 DNS 生效，失败看 gateway 日志，不要反复删除证书卷。[Caddy 自动 HTTPS 条件](https://caddyserver.com/docs/automatic-https)

可验证跨域预检，返回应包含精确前端来源和允许凭据：

```bash
curl -i -X OPTIONS https://api.example.com/api/images/jobs \
  -H 'Origin: https://app.example.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

预期：`access-control-allow-origin: https://app.example.com` 和 `access-control-allow-credentials: true`。`curl` 通过不代表浏览器 Cookie 一定通过，继续做网页验收：

1. 打开 `https://app.example.com/#/tuijian`，刷新页面、切换类别，头像和静态资源没有 404。
2. 推荐页显示已保存结果；后台常驻在北京时间 05:00 更新，没有历史时启动自动生成。不要开多个 worker 或多套后端。
3. 热门页能加载并向下分页。云服务器 IP 的抓取结果需要实际验证。
4. 知识库健康信息有资料数量，真实提问能逐段显示回答。
5. 图片页上传产品图、提示词留空也能生成；刷新保留当前浏览器历史，点保存原图确实下载文件。
6. 管理员登录、统计和上传正常；手机访问也检查一次。

本配置保持你要求的**普通用户免登录**，没有加入短信或整站访问密码。公网访客使用问答和生图会消耗你配置的模型额度；CORS 只约束浏览器跨域读取，不是用户授权机制。

后台 `restart: unless-stopped` 会在正常重启后恢复服务。首次没有推荐快照时可能需要较久初始化；健康检查成功只说明进程能响应，不代表模型、爬虫和资料库都通过验收。

## 9. 以后如何更新、停止、备份

### 改完代码后

本机：

```powershell
git add .
git commit -m "Update application"
git push
```

前端会自动发布。后端需要你在服务器更新，GitHub Actions 不会替你 SSH 或启动容器：

```bash
cd ~/kuajing
git pull --ff-only
sudo docker compose -f compose.pages.yaml up -d --build
sudo docker compose -f compose.pages.yaml ps
```

数据保存在绑定目录中，重建容器不会清空它们。修改后端 env 后同样执行 `up -d` 重建相关容器；仅 `restart` 不会载入新的 Compose 环境变量。修改 `deploy/api.env` 后可用 `up -d --force-recreate gateway`。

### 看日志、停止、恢复

```bash
sudo docker compose -f compose.pages.yaml logs -f --tail=100 api
# 日志界面 Ctrl+C 只退出查看，不会关后端。
sudo docker compose -f compose.pages.yaml stop
sudo docker compose -f compose.pages.yaml up -d
```

不要随便执行 `down -v` 或删除 `server-data`。停止后端期间前端页面仍在 Pages 上，但数据接口不可用。

### 一致性备份

在服务器项目根目录，短暂停写后打包，再恢复；备份路径在仓库外：

```bash
cd ~/kuajing
mkdir -p ~/kuajing-backups
chmod 700 ~/kuajing-backups
sudo docker compose -f compose.pages.yaml stop api
sudo tar -czf "$HOME/kuajing-backups/data-$(date +%Y%m%d-%H%M%S).tar.gz" server-data
sudo docker compose -f compose.pages.yaml up -d
```

把备份再复制到另一台机器；后端 env 和域名配置也单独妥善备份。恢复时先停 api，将旧 `server-data` 保留为备份，用确认过的备份恢复到空目录、归属设为 UID 10001 后再启动，不要直接叠加不同时间的数据库。

## 10. 常见问题对照

| 现象 | 检查 |
| --- | --- |
| Pages Actions 红色，提示 API 地址 | Repository Variables 中是否配置 HTTPS `VITE_API_BASE_URL`；之后重新运行 workflow |
| Pages 报权限或不存在 | Settings → Pages 是否选择 GitHub Actions；仓库/账户是否支持 Pages |
| 头像或脚本 404 | 重新发布，让 configure-pages 读取当前自定义域名；不要手改生成后的 dist |
| 刷新子页面 404 | 使用 `/#/tupian` 等发布后的 Hash 地址，不用旧 `/tupian` 书签 |
| CORS 报错 | 后端 FRONTEND_ORIGINS 是否精确等于浏览器地址栏 origin；更新 env 后重建 api |
| 生图提示初始化会话或管理员反复掉登录 | 必须从 app 自定义域名访问，同一个根域名下的 api，双方 HTTPS；不使用 github.io 与独立 API 域名组合 |
| 后端证书失败 | api DNS、80/443、安全组、已有端口占用及 gateway 日志 |
| 镜像构建失败 | 先定位失败的 pip/apt/浏览器下载步骤和网络，不要直接删除所有依赖版本号 |
| API 健康但知识库没内容 | 是否迁移了完整 knowledge runtime，或是否已上传资料入库 |
| 数据库只读 / 原图无法保存 | `server-data` 目录是否归 UID 10001 所有、磁盘是否已满 |
| 推荐或抓取失败 | 查看实际失败状态；服务器必须能连通相应供应商，前端部署成功不代表这些外部服务正常 |

完成后的日常入口只有两个：访客打开 `https://app.example.com`，你通过 SSH 管理 `compose.pages.yaml`。无需让自己的电脑一直开机。
