# 从本机到服务器：GitHub 与 Docker 部署教学

> 2026-09-23：你当前选择的是 **GitHub Pages 前端 + Docker 后端**，请改按 [新版操作流程](github-pages-cloud-tutorial.md) 执行。本文保留为前后端同服务器方案的参考，不要与 `compose.pages.yaml` 同时启动。

这份教程针对当前“跨境阁”项目。你在 Windows 上写代码，把代码推到 GitHub，再让一台 Linux 服务器用 Docker 运行前后端。示例使用 **Ubuntu 24.04 LTS、单台服务器、一个后端进程**。

配套的 Dockerfile、Compose、Caddy 配置已放进项目。下面的命令由你按步骤执行；编写教程时没有替你创建 GitHub 仓库、上传代码或启动云服务器。

## 1. 先理解你要做的事情

| 名称 | 在本项目中负责什么 |
| --- | --- |
| Git | 在电脑上记录代码版本，方便比较和回退 |
| GitHub | 保存 Git 仓库，服务器从这里拉取代码 |
| 服务器 | 一台持续开机、能联网的电脑；关掉你自己的电脑后它仍可运行 |
| Dockerfile | 描述如何安装 Python/Node、依赖和浏览器，制作运行镜像 |
| 镜像 | 程序运行环境的模板 |
| 容器 | 用镜像启动的程序进程，可以停止和重建 |
| Docker Compose | 一起管理后端、前端服务、网络和数据目录 |
| Caddy | 提供前端网页，将 `/api/...` 转发给后端，并在配置域名后处理 HTTPS |

请求路径是：

```text
你的浏览器
    │ 打开网页或请求 /api/...
    ▼
服务器上的 Caddy（web 容器）
    ├─ 网页、JS、CSS → 构建好的 React 静态文件
    └─ /api/...     → api:8000 → FastAPI（api 容器）
                                     ├─ 通义模型 / Coze
                                     ├─ Playwright 浏览器抓商品
                                     └─ server-data 中的持久数据
```

**GitHub 不会自动运行这个 Python 后端。** `git push` 只上传代码；还需要服务器执行 `git pull` 和 Docker 构建/启动。这里先教手动部署，理解之后再考虑自动部署。

前端也放在同一台服务器，是为了让页面和 API 使用同一个域名。项目已有 Cookie 会话和同源 `/api` 请求，这样配置最直接。生产环境不使用 `npm run dev`，也不需要额外启动 8001。

## 2. 本次补好的部署文件

| 文件 | 作用 |
| --- | --- |
| `backend/requirements.txt` | 统一后端的依赖入口，补齐推荐模块直接使用的 LangChain/OpenAI 依赖 |
| `deploy/Dockerfile.api` | Python 3.13、全部后端依赖、Playwright Chromium、一个 Uvicorn worker |
| `deploy/Dockerfile.web` | 用 Node 构建网页，再由 Caddy 提供静态文件 |
| `compose.yaml` | 私下验收配置：服务器只监听 `127.0.0.1:8080`，API 不暴露宿主机端口 |
| `compose.https.yaml` | 有域名后覆盖配置，发布 80/443 端口 |
| `deploy/Caddyfile` | 本地隧道验收的反向代理和 React 路由回退 |
| `deploy/Caddyfile.https` | HTTPS、整站访问密码和同源 API 转发 |
| `deploy/backend.env.example` | 后端配置模板，不包含真实密钥 |
| `deploy/site.env.example` | 域名和整站访问密码哈希模板 |
| `.dockerignore` | 防止构建时把本机密钥和数据库打进镜像 |
| `.gitignore` | 防止把密钥、运行数据、缓存和原始知识资料提交到 Git |

不需要将电脑里的 `node_modules`、Python 安装目录或 Windows 浏览器上传。Docker 会在 Linux 中重新安装依赖和浏览器。

## 3. Windows：把项目上传到 GitHub

### 3.1 准备 Git 和 GitHub 登录

以下命令在**本机 PowerShell**执行：

```powershell
git --version
gh --version
```

如果提示找不到命令，可使用 Windows 的 winget 安装对应工具，再重新打开 PowerShell：

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
```

登录 GitHub：

```powershell
gh auth login
gh auth setup-git
```

按提示选择 GitHub.com、HTTPS、浏览器登录，使用你自己的 GitHub 账号。GitHub 登录凭据与 Coze/百炼 Token 完全不同。

### 3.2 创建一个空仓库

打开 [GitHub 新建仓库页面](https://github.com/new)：

1. Repository name 填 `kuajing`。
2. 初次学习建议选 **Private**，确认代码和资料可以公开后再调整。
3. 不勾选生成 README、`.gitignore` 或 License，因为本机已经有项目文件。
4. 创建后记住地址，例如 `https://github.com/你的用户名/kuajing.git`。

将已有项目推入空仓库的步骤依据 [GitHub 官方说明](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

### 3.3 初始化并检查要上传的内容

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
git init -b main
git config user.name "你的名字"
git config user.email "你的GitHub邮箱或GitHub提供的noreply邮箱"
git status --short
```

`user.name`/`user.email` 是提交作者信息，不是登录账号密码。已有 Git 仓库时不用再次初始化，先看 `git status` 和当前分支。

检查忽略规则：

```powershell
git check-ignore .env backend/zhishiku/runtime/chroma/chroma.sqlite3 deploy/backend.env server-data/images/example.png
```

正常应显示这些路径，表示它们不会被首次 `git add .` 添加。仓库保存源码；`.env.example` 和 `*.env.example` 只是配置模板，可以上传。

本项目的真实 `.env` 包含模型和工作流凭据，知识库 runtime 也包含实际数据。**不要使用 `git add -f` 强行添加这些文件。** 原始知识大纲和验证截图也已默认忽略；后面通过 SSH 单独迁移数据。

```powershell
git add .
git diff --cached --stat
git diff --cached --name-only
git diff --cached
```

先在本机检查暂存内容，再提交。应看到 `src`、`backend` 源码、`docs`、`deploy`、Compose、依赖清单等；不应看到真实密钥、运行数据库、生成图片、备份或 `node_modules`。不要把带私密内容的检查输出粘贴到公开聊天或 issue。

`.gitignore` 只阻止尚未跟踪的文件；如果旧仓库已经跟踪了 `.env`，新增忽略规则不会清除 Git 历史。已泄露的凭据要先在供应商处撤销/轮换，再按 [GitHub 敏感信息清理指南](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)处理历史。

### 3.4 第一次推送

把下方地址换成自己的仓库：

```powershell
git commit -m "Initial project and Docker deployment"
git remote add origin https://github.com/你的用户名/kuajing.git
git remote -v
git push -u origin main
```

`commit` 生成本地版本；`push` 把版本传到 GitHub。`-u` 记录默认远程分支，下次可以直接 `git push`。

如果提示 `remote origin already exists`，先用 `git remote -v` 检查现有地址；仅在地址确实错误时用 `git remote set-url origin 新地址`。遇到远程已有提交，不要为了省事直接强推；先确认是不是创建仓库时勾选了 README。

## 4. 准备 Linux 服务器

教程假设你有一台 Ubuntu 24.04 LTS、x86_64 的服务器和可以 sudo 的普通用户，例如 `ubuntu`。下面出现的 `SERVER_IP`、`你的用户名`、`app.example.com` 都要替换成自己的值。

资源先按测试项目估算：**2 核/4 GB 可以作为起点，浏览器和构建同时运行时可能需要更多内存；4 核/8 GB 更宽裕**。这是本项目的起步估算，不是压测承诺。图片原图持续保存会占磁盘，需要监控磁盘并备份。

服务器需能访问 GitHub、Docker 镜像仓库、PyPI、npm、Playwright 下载站、百炼、Coze 和商品网页。**电脑能访问，不代表云服务器也能访问；Docker 不会解决源站限流或验证码。** 先用现有或短期测试机器确认网络，再决定长期使用。

### 4.1 SSH 连接

本机 PowerShell：

```powershell
ssh ubuntu@SERVER_IP
```

如果云平台给了私钥文件：

```powershell
ssh -i C:\Users\ruoxiao\.ssh\你的服务器私钥 ubuntu@SERVER_IP
```

首次连接时，将 SSH 指纹与云控制台提供的指纹核对。连接后终端通常变为 `ubuntu@...`，后面的 Bash 命令是在服务器执行。

初次验收只需要开放 SSH 端口 22（尽量限制自己的 IP）。不用开放 8000、8001、5173、8080。有域名上线时再开放 80/443。

### 4.2 安装 Docker Engine 与 Compose

下面适用于**新 Ubuntu 服务器**。如果已有 Docker，先执行 `docker version` 和 `docker compose version`，不要直接覆盖已有服务环境。

按 [Docker 官方 Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)添加官方软件源：

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

看到 hello-world 成功信息说明 Docker 能拉取并运行容器。这里统一使用 `sudo docker`，不用为教程把普通用户加入具有高权限的 docker 组。

Compose 需要 **2.30.0 或更新版本**，以支持配置文件使用的 `env_file.format: raw`；当前 5.x 版本也满足。不要使用老的 `docker-compose` v1 命令。[格式依据](https://docs.docker.com/reference/compose-file/services/#env_file)

## 5. 让服务器取得 GitHub 代码

### 5.1 公共仓库

```bash
git clone https://github.com/你的用户名/kuajing.git
cd kuajing
```

### 5.2 私有仓库：给服务器一把只读 Deploy Key

这是服务器独立的 GitHub 密钥，不需要复制你个人电脑的私钥。以下在服务器执行：

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "kuajing-server-readonly" -f ~/.ssh/kuajing_github
cat ~/.ssh/kuajing_github.pub
```

已有同名密钥时不要覆盖。把 `.pub` 的公钥内容添加到 GitHub 仓库 → Settings → Deploy keys → Add deploy key，**不勾选 Allow write access**。

用 `nano ~/.ssh/config` 添加下面一段；若文件已有配置，只追加，不覆盖：

```sshconfig
Host github-kuajing
    HostName github.com
    User git
    IdentityFile ~/.ssh/kuajing_github
    IdentitiesOnly yes
```

```bash
chmod 600 ~/.ssh/config
ssh -T git@github-kuajing
git clone git@github-kuajing:你的用户名/kuajing.git
cd kuajing
```

首次 SSH 连接 GitHub 时核对 [GitHub 官方 SSH 指纹](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)。认证测试提示成功但“不提供 shell”是正常的；Deploy Key 用途见 [官方说明](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)。

## 6. 配置后端与持久化目录

以下都在**服务器的 kuajing 项目根目录**执行。

```bash
cp -n deploy/backend.env.example deploy/backend.env
chmod 600 deploy/backend.env
mkdir -p server-data/knowledge server-data/recommendations server-data/products server-data/images
sudo chown -R 10001:10001 server-data
nano deploy/backend.env
```

首次复制用 `-n` 防止覆盖已经填写的文件。`10001` 是 Dockerfile 中运行后端的用户 UID；目录权限不匹配会出现数据库只读或图片无法保存。

按模板填写这些值：

| 配置 | 你要填写什么 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 自己的百炼密钥 |
| `QWEN_MODEL` 等模型配置 | 与目前本机正在使用的模型保持一致 |
| `DASHSCOPE_RERANK_BASE_URL` | 自己的 Workspace 兼容接口地址，带 `/compatible-api/v1` |
| `ADMIN_USERNAME` | 知识库管理员用户名 |
| `ADMIN_PASSWORD_HASH` | bcrypt 哈希，下面演示生成 |
| `SESSION_SECRET` | 长随机字符串 |
| `COZE_API_TOKEN` | 能访问该工作流和上传图片的 Coze Token |
| `COZE_WORKFLOW_ID` | 当前模板保留项目工作流 ID；确认工作流已发布并有 API 权限 |
| `COOKIE_SECURE` | SSH 隧道 HTTP 验收阶段 `false`；域名 HTTPS 阶段 `true` |
| `FRONTEND_ORIGINS` | 验收先保持模板；上线改成实际 `https://域名`，不带路径和末尾斜杠 |
| `AMAZON_BROWSER_CHANNEL` | 容器中保持 `chromium`，不要照抄 Windows 的 `chrome` |

模板使用 Compose 的 raw 格式：每行 `名称=值`，**不要给值套引号，不要在值后面追加注释**。bcrypt 的 `$` 会原样传入。不要 `source deploy/backend.env`；这是配置文件，不是 Shell 脚本。

不要把密钥设成 `VITE_...`，这种前端变量会进入浏览器下载的 JS。服务器不需要复制本机根目录 `.env`；部署专用配置由 `env_file` 注入容器环境。

### 6.1 先构建镜像，再生成管理员配置

```bash
sudo docker compose build
```

第一次要安装 Python/Node 依赖和 Chromium，耗时取决于网络。**build 不会启动推荐任务，也不会调用收费模型。**

用构建好的后端镜像生成密码哈希，不启动 FastAPI、不加载调度器：

```bash
sudo docker compose run --rm --no-deps api python -c 'import bcrypt,getpass; p=getpass.getpass("Admin password: ").encode(); assert 12 <= len(p) <= 72, "Use 12-72 UTF-8 bytes"; print(bcrypt.hashpw(p,bcrypt.gensalt()).decode())'
sudo docker compose run --rm --no-deps api python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

第一条输入密码时不回显；复制输出哈希填入 `ADMIN_PASSWORD_HASH`。第二条输出填入 `SESSION_SECRET`，妥善保管，不提交到 Git。

如果 `build` 提示某个固定依赖无法下载，先确认 PyPI 镜像源和网络，不要把所有版本号都删掉。现有版本以本机已安装组合为基础，Linux 镜像仍需要在你的服务器实际构建验收。

## 7. 要不要搬运本机已有的数据？

**只克隆代码，知识库会是空的。** 当前本机的知识库、推荐快照、热门首屏和生成图片都不在 GitHub 中。

| 本机目录 | 服务器目录 | 保存内容 |
| --- | --- | --- |
| `backend/zhishiku/runtime` | `server-data/knowledge` | Chroma 向量库与相关文件 |
| `backend/tuijian/runtime` | `server-data/recommendations` | 每日推荐快照、任务状态与检查点 |
| `backend/remen/runtime` | `server-data/products` | 热门商品首屏缓存 |
| `backend/tupian/runtime` | `server-data/images` | 生图任务数据库、参考图和已下载原图 |

### 7.1 不迁移：从空数据开始

可直接进入下一节。之后在管理页面上传知识资料，重新入库会调用 Embedding 并产生相应费用。没有推荐历史时，**后端首次启动会自动生成一次推荐**；这可能调用模型和爬虫，并不是网页触发。

### 7.2 迁移：停写后复制完整 runtime

先在本机停止统一后端（原终端 `Ctrl+C`），等待退出，确保没有其他爬虫/导入进程还在写数据库。不要在 SQLite/Chroma 正在写入时只复制一个 `.sqlite3` 文件。

本机 PowerShell，打包到系统临时目录，避免误加进 Git：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
$migrationFile = Join-Path $env:TEMP 'kuajing-runtime.tar.gz'
tar -czf $migrationFile backend/zhishiku/runtime backend/tuijian/runtime backend/remen/runtime backend/tupian/runtime
scp $migrationFile ubuntu@SERVER_IP:~/kuajing-runtime.tar.gz
```

若某模块从未使用、没有 runtime 目录，从命令中去掉对应项。若使用 SSH 私钥，给 `scp` 添加与 `ssh` 相同的 `-i 私钥路径`。

下面在服务器执行，**仅适用于首次部署、server-data 四个目录尚为空**。已有数据的服务器先做下一节介绍的备份，不直接覆盖旧库：

```bash
cd ~/kuajing
sudo docker compose stop
mkdir -p ~/kuajing-import
tar -xzf ~/kuajing-runtime.tar.gz -C ~/kuajing-import
sudo cp -a ~/kuajing-import/backend/zhishiku/runtime/. server-data/knowledge/
sudo cp -a ~/kuajing-import/backend/tuijian/runtime/. server-data/recommendations/
sudo cp -a ~/kuajing-import/backend/remen/runtime/. server-data/products/
sudo cp -a ~/kuajing-import/backend/tupian/runtime/. server-data/images/
sudo chown -R 10001:10001 server-data
```

向量库迁移后保持 Embedding 模型和集合名称一致，不能只换模型名就继续使用旧向量。Windows 到 Linux 的 Chroma 文件迁移需做实际检索验收；若兼容性有问题，保留原始备份，在新目录重新入库，别删本机正式库。

文件搬到服务器，不等于网页会自动显示本机全部历史：**设置和问答历史保存在浏览器；生图历史按浏览器 Cookie 区分**。换域名会得到新的浏览器存储空间和图片会话，即使原图已迁移，新会话也不会自动列出旧会话的作品。迁移前先保存你需要的原图；跨域历史迁移需要另外实现导出/导入功能。

## 8. 第一次启动：先通过 SSH 隧道验收

服务器：

```bash
sudo docker compose config -q
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 api
curl -f http://127.0.0.1:8080/api/knowledge/health
```

`config -q` 只验证配置，不打印展开后的密钥。不要把 `docker compose config` 的完整输出随便贴出来。

`up -d` 在后台启动。Compose 会等待 API 基本健康后启动 web；根路径健康检查只确认 API 能响应，**不代表模型、数据库检索和爬虫都正常**。第一次初始化期间请查看日志及页面状态。

本机再开一个 PowerShell 窗口，保持此连接：

```powershell
ssh -N -L 8080:127.0.0.1:8080 ubuntu@SERVER_IP
```

浏览器访问 **http://localhost:8080**。隧道把电脑 8080 转发到服务器的回环地址；终端没有文字、一直停在那里是正常的，`Ctrl+C` 只关闭隧道，服务器容器继续运行。

验收时依次检查：

1. 首页和设置页能打开，直接刷新 `/remeng`、`/tupian` 不出现 404。
2. `/api/knowledge/health` 返回 JSON；迁移过数据时核对文档/知识块数量，并做一次真实检索。
3. 管理员可以登录，Cookie 不会因为来源或 HTTPS 配置错误而丢失。
4. 热门产品能展示、下滑继续加载；服务器源站限制如实显示，不能把构建成功当作抓取成功。
5. 推荐页只读取已保存结果；首次尚无结果时等待后台生成。保留日志确认定时任务只启动一份。
6. 生图先确认历史页能打开，再按需上传一张产品图做一次真实生成并下载原图；这一步会使用 Coze 配额。

只检查容器内浏览器是否能启动，不访问商品网页、不调用模型，可以执行：

```bash
sudo docker compose exec api python -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); print(b.version); b.close(); p.stop()'
```

Playwright 需要浏览器二进制和系统依赖，不是 `pip install playwright` 就完成；Dockerfile 已使用安装命令处理。[Playwright 容器文档](https://playwright.dev/python/docs/docker)

## 9. 有域名后：开启 HTTPS 与整站访问密码

如果只给自己使用，可以一直使用 SSH 隧道，不必立即配置域名。需要让别人通过网址访问时，再做本节。

当前项目的管理员登录只保护知识库管理操作，**没有完整的普通用户注册、额度和收费权限系统**。图片会话 Cookie 也不是收费权限校验。因此提供的公网配置对整站加一道访问密码，避免模型和生图接口直接向所有访客开放。

### 9.1 配置域名与端口

1. 在域名服务商配置 `app.你的域名` 的 A 记录，指向服务器公网 IPv4。
2. 没有配置 IPv6 时不要留下错误的 AAAA 记录。
3. 云安全组开放 TCP 80、443；保留自己的 SSH 访问。
4. 确保服务器这两个端口未被其他服务占用。

示例使用 `app.example.com`，请换成自己的域名。Caddy 在满足域名解析和端口可达条件时自动申请和续期证书。[Caddy HTTPS 文档](https://caddyserver.com/docs/automatic-https)

### 9.2 生成整站访问密码哈希

服务器：

```bash
cp -n deploy/site.env.example deploy/site.env
chmod 600 deploy/site.env
sudo docker compose run --rm --no-deps web caddy hash-password
nano deploy/site.env
```

输入你要给访客使用的访问密码，把生成的哈希填入 `SITE_PASSWORD_HASH`，并填写：

```dotenv
SITE_ADDRESS=app.你的真实域名
SITE_USER=viewer
SITE_PASSWORD_HASH=这里填刚生成的完整哈希
```

不要填明文密码，也不要给哈希套引号。Caddy 的 [basic_auth](https://caddyserver.com/docs/caddyfile/directives/basic_auth)使用密码哈希。

然后修改 `deploy/backend.env` 中两行：

```dotenv
COOKIE_SECURE=true
FRONTEND_ORIGINS=https://app.你的真实域名
```

### 9.3 启用公网覆盖配置

```bash
sudo docker compose -f compose.yaml -f compose.https.yaml config -q
sudo docker compose -f compose.yaml -f compose.https.yaml up -d --force-recreate
sudo docker compose -f compose.yaml -f compose.https.yaml logs --tail=100 web
```

浏览器访问 `https://app.你的真实域名`，先输入整站用户名和密码，再使用应用。知识库管理员登录仍然是另一套账号。

此后管理正式部署时，**始终带上这两个 `-f` 参数**。只执行默认 `docker compose up -d` 可能把 web 切回隧道验收配置。覆盖配置会保留 127.0.0.1:8080 的绑定，但它使用的已是域名配置，日常直接使用 HTTPS 域名。

前端保持同源 `/api`；不设置 `VITE_API_BASE_URL=http://127.0.0.1:8000`。用户浏览器中的 `127.0.0.1` 是用户自己的电脑，不是你的云服务器。

API 8000 不发布到宿主机，Caddy 清洗转发 IP 并传递 HTTPS 协议信息。不要另行开放 8000 绕过访问密码。Docker 发布端口与 UFW 存在特殊交互，不能只凭 UFW 状态推断端口未公开，按 [Docker 的防火墙说明](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations)和云安全组一起检查。

## 10. 以后改完代码，如何更新服务器？

### 10.1 本机保存并推送

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
git status
git add src backend docs deploy compose.yaml compose.https.yaml package.json package-lock.json .gitignore .dockerignore README.md
git diff --cached --stat
git diff --cached
git commit -m "Describe the change"
git push
```

只提交你确认过的改动。GitHub 更新完成后，服务器不会自动更新。

### 10.2 服务器拉取并重建

正式 HTTPS 部署：

```bash
cd ~/kuajing
git rev-parse HEAD
git pull --ff-only
sudo docker compose -f compose.yaml -f compose.https.yaml build
sudo docker compose -f compose.yaml -f compose.https.yaml up -d
sudo docker compose -f compose.yaml -f compose.https.yaml ps
```

更新前记下旧提交号，并按下一节备份。`--ff-only` 在服务器代码分叉时停止，不偷偷合并；一般只在本机改源码，在服务器改被忽略的配置文件。

`build` 失败时先修复构建，旧容器通常仍在运行；不要先 `down`。这套单实例方案更新会有短暂中断，不是零停机部署。更新前尽量等正在执行的生图/推荐任务结束。

只修改 `deploy/backend.env` 时，不用重新 build，但要重新创建 API：

```bash
sudo docker compose -f compose.yaml -f compose.https.yaml up -d --force-recreate api
```

`restart` 只重启原容器，不会重新读取新的 `env_file` 来创建环境。

## 11. 数据备份、恢复与代码回退

### 11.1 备份

下面为正式 HTTPS 部署；隧道阶段去掉 `-f compose.yaml -f compose.https.yaml` 即可。先等任务结束，再停写、备份，最后启动：

```bash
cd ~/kuajing
mkdir -p backups
chmod 700 backups
sudo docker compose -f compose.yaml -f compose.https.yaml stop api
sudo tar -czf "backups/data-$(date +%Y%m%d-%H%M%S).tar.gz" server-data
sudo chmod 600 backups/*.tar.gz
sudo docker compose -f compose.yaml -f compose.https.yaml start api
```

备份文件应另存到服务器之外的安全位置；只留同一块磁盘上，无法应对服务器损坏。`deploy/backend.env`、`deploy/site.env` 也需要另外安全保管，不进 Git。

容器重建不会清空 `server-data`，因为它是宿主机绑定目录。不要为“重装”删除这个目录。Caddy 证书保存在 Docker 命名卷中，日常也不要执行 `down -v`。

### 11.2 恢复数据

先确认备份来源可信、压缩包内是 `server-data/...`：

```bash
sudo tar -tzf backups/你选中的备份.tar.gz | head
```

停止写入，保留现有目录，再解压恢复，避免新旧数据库文件混放：

```bash
sudo docker compose -f compose.yaml -f compose.https.yaml stop api
sudo mv server-data "backups/server-data-before-restore-$(date +%Y%m%d-%H%M%S)"
sudo tar -xzf backups/你选中的备份.tar.gz
sudo chown -R 10001:10001 server-data
sudo docker compose -f compose.yaml -f compose.https.yaml up -d --force-recreate api
```

恢复后重新核对健康状态、知识库数量、检索、推荐和图片下载。不要在恢复过程中再次触发导入任务。

### 11.3 回退代码

如果新版本有问题，而你已经记下上一个可用提交号：

```bash
git switch --detach 上一个可用提交号
sudo docker compose -f compose.yaml -f compose.https.yaml build
sudo docker compose -f compose.yaml -f compose.https.yaml up -d
```

修复版本推到 GitHub 后，再 `git switch main`、`git pull --ff-only` 并重建。代码回退不会自动回退数据库；涉及存储结构改动时，要确认代码与备份的数据版本匹配。不要用 `git reset --hard` 清掉自己还没保存的修改。

## 12. 常用运维命令

以下使用正式 HTTPS 配置：

```bash
# 看容器状态
sudo docker compose -f compose.yaml -f compose.https.yaml ps

# 跟踪后端日志，Ctrl+C 只结束看日志，不停止服务
sudo docker compose -f compose.yaml -f compose.https.yaml logs -f --tail=100 api

# 看资源使用；Ctrl+C 退出
sudo docker stats

# 看磁盘剩余空间
df -h
sudo du -sh server-data/*

# 暂停整套应用
sudo docker compose -f compose.yaml -f compose.https.yaml stop

# 恢复已有容器
sudo docker compose -f compose.yaml -f compose.https.yaml start
```

Compose 配置了 `restart: unless-stopped`：Docker 服务随服务器启动时，未被手动停止的容器会恢复运行。你主动执行 `stop` 后，需要自己 `start`。这与关掉 SSH 窗口不同，退出 SSH 不会停止 `up -d` 启动的容器。

每日推荐仍按**北京时间 05:00**开始生成；第一次没有历史会初始化，错过更新时恢复运行后补最新一期。首次启动和后续定时任务可能产生模型费用。不要增加 Uvicorn workers，也不要执行 `--scale api=2`；当前调度与 SQLite 设计按单实例运行。

## 13. 常见问题怎么查

| 现象 | 优先检查 |
| --- | --- |
| `docker compose` 不存在 | 安装的是旧版工具还是缺少 compose-plugin |
| `format: raw` 不支持 | Compose 至少 2.30.0 |
| 镜像拉取或 pip/npm 下载失败 | 服务器出网、DNS、仓库连通性；不是业务代码一定有问题 |
| API 一直 unhealthy | 看 api 日志、依赖、配置、数据目录权限和可用内存 |
| `browser_unavailable` | Chromium 是否安装、channel 是否为 chromium；执行第 8 节浏览器自检 |
| 商品验证码、403、空结果 | 云服务器访问被源站限制；保留冷却和失败状态，不循环重试冲击源站 |
| 网页能开，但 API 502 | api 容器是否健康，Caddy 是否在同一 Compose 网络 |
| 刷新某个前端路径 404 | 是否使用了带 `try_files ... /index.html` 的 Caddy 配置 |
| 问答一直等到最后才显示 | 反向代理有没有缓冲 SSE；配置已设置 `flush_interval -1` |
| 生图或管理接口 403 | `FRONTEND_ORIGINS` 的协议、域名、端口是否与地址栏一致 |
| 登录后又显示未登录 | HTTP 阶段是否错误开启 Secure；HTTPS 代理是否传递协议头；Cookie 是否被浏览器拦截 |
| 管理员密码一直不对 | 是否填了 bcrypt 哈希、是否套了引号或被 `$` 插值；这里 raw 文件不应加引号 |
| 知识库数量为 0 | 只拉了源码，没有迁移 runtime 或重新入库 |
| 换域名后历史/设置消失 | 浏览器 localStorage/Cookie 按来源隔离，参见第 7 节 |
| 每天重复调用推荐多次 | 检查是否启动了多个后端实例、多个 worker，或本机与云端同时运行 |
| HTTPS 申请失败 | 域名 DNS、80/443、错误的 AAAA 记录、端口冲突和 web 日志 |
| 更新 env 后没变化 | 用 `up -d --force-recreate api`，不是只执行 `restart` |

Caddy 的流式代理配置依据 [reverse_proxy 官方文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。

## 14. 当前验证范围

编写时已检查项目真实入口、数据目录、浏览器渠道、Cookie 和依赖，并对两套 Compose 配置进行了本地解析校验。新增配置不会修改现有本机 `.env` 或正式数据。

**本机 Docker Desktop 的 Linux 引擎没有运行，因此尚未实际构建/启动这套容器；也未连接任何云服务器。** 文中区分了配置验证与真实部署验收。按第 6–9 节完成镜像构建、浏览器自检、数据迁移和真实功能验收后，才能确认你的服务器适合持续运行本项目。
