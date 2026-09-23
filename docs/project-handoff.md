# 跨境阁项目交接：给新聊天中的 AI

## 2026-09-23 面试展示与自动连接（以此节为最新状态）

- 用户用途是面试项目，要求 Pages 优先真实后端，失败自动展示样例；不用等备案通过再改前端。默认 workflow mode=auto，API=https://api.qiyuange.online。
- `src/runtime.js` 在页面模块动态导入前检测健康状态（2.5 秒），验证 CORS 和 JSON；展示每分钟检测恢复，无交互时自动刷新，有交互时提示并在切页时切换。demo/live/auto 可以通过 Actions 选择，未来 push 默认为 auto 或仓库 PAGES_MODE。
- `src/demo/` 提供明确标注的人工商品、4 组 SSE 预置回答、4 张原创 SVG 插画；不上传参考图片，不调用收费接口。展示/真实本地存储分区；真实失败请求不会被样例伪装成成功。
- README 改为项目展示入口、截图、工程实现、运行与验收说明；原详细本机说明移至 `docs/local-development.md`。`docs/pages-auto-connect.md` 是本次自动连接配置入口。
- 真实服务器已 healthy，api 域名 HTTPS/反代本机验证通过，公网之前被 ICP 拦截；不要误判为容器未构建或域名尚未注册。域名是 qiyuange.online，前端 app 子域名仍待用户绑定 Pages。
- `deploy/enable-pages-origin.sh` 供用户在已有服务器执行一次，备份 env、设置 GitHub 与 app 的允许来源、重建容器读取 env，不重建镜像。当前没有服务器 shell 连接，不能声称该脚本已在服务器执行。
- Strict Cookie 跨站不能仅靠 CORS 修复；真实图片/管理页在 github.io 上提示访问 app.qiyuange.online，避免付费任务创建后读取失败。自定义域名按指南一次性配置后，Pages 仍然托管前端。
- 验证：47 项前端测试、lint、展示/自动/真实构建；`verify_demo.py` 离线 UI/分页/SSE/下载/移动/自动恢复，`verify_pages.py` 原有真实协议替身回归。截图不含用户资料或真实模型输出。

## 2026-09-23 宝塔直接上传与旧部署保留

- 最新验收：用户已粘贴真实服务器 env 并启动，`kuajing-next-api-1` 显示 `healthy`，绑定 `127.0.0.1:18000->8000/tcp`；服务器 curl 根接口返回跨境阁 API JSON。说明进程和根健康检查正常，不等于模型/爬虫/知识库/生图都通过真实业务验收。下一步前端仓库与 Pages、HTTPS 入口；只有 IP、没有域名，`FRONTEND_ORIGINS` 仍待配置。无需再构建/初始化后端，不输出真实 env。

- 用户反馈服务器四个凭据仍未填写，并要求直接提供现有配置。已获授权读取本机配置，生成私密 `deploy/backend.env`：百炼 Key 来自本机进程环境，其余沿用本机现有配置和管理员密码哈希，未在聊天输出凭据。Compose config -q、引号往返与打包排除检查通过；用户仍需将该文件内容粘贴到服务器同名文件后启动。`FRONTEND_ORIGINS` 暂空（用户没有域名），HTTPS 前端地址确定后再填写；不要把此真实 env 加进 GitHub 或上传包。

- 最新服务器结果：用户反馈 `exporting layers ... done`、`naming to docker.io/library/kuajing-next-api ... done`，镜像已构建成功，尚未提供容器启动结果。服务器采用了后续纯命令补丁（插入阿里云 apt 源、改为 only-shell），没有上传本机的三层/cache mount 版本，不能假定服务器构建缓存结构与本机完全一致。下一步检查 `deploy/backend.env` 是否仍为占位配置，再启动并验收 `127.0.0.1:18000`；不再让用户重复构建或下载。

- 构建进度：ECR 官方 Python 镜像在服务器已成功拉取；pip 换阿里云镜像后已进入 Playwright 系统依赖阶段，但 `deb.debian.org` 下载 97 MB 很慢。本机 Dockerfile 现已统一 ECR 基础镜像、阿里云 PyPI/Debian HTTPS 源，将 Python 包、系统依赖、浏览器拆成三层，并加 pip BuildKit 缓存。用户需要在宝塔只覆盖 `/www/kuajing-next/deploy/Dockerfile.api` 后重建，不用覆盖 env 或重传项目。旧组合 RUN 未完成，本次 Python 安装会重跑一次，之后完成的层可复用。
- 浏览器安装改为 `--only-shell chromium`：已确认生产爬虫 `headless=True`，在 chromium 配置下不传 channel，符合官方 headless shell 使用条件。依赖版本及爬虫业务逻辑不变。浏览器仍从官方源下载，不能保证云服务器所有网络阶段都快。服务器尚未完成镜像构建，也未启动新版后端；本机 Docker 引擎未开启，不能声称 Linux 镜像已实测运行。

- 用户后续说明 aliyun-deploy 是不再需要的另一个项目，已删除目录；服务器检查确认 0 容器，磁盘剩余 26 GB，Nginx 监听 80，Docker 26.1.4 / Compose 2.28.1。新版目录已由用户从 `/www/wwwroot/kuajing-next` 移动到 `/www/kuajing-next`。下一步初始化和构建。
- 宝塔 Compose 已去掉 2.30 才支持的 `format: raw`，改用标准 env_file，专用 env 示例改为单引号值保护 bcrypt 的 `$`。上传过旧包的服务器只需按教程 sed 删除 format 行；填哈希时需加单引号。其他 Pages/Caddy 方案仍沿用 raw，不混用模板。

- 最新纠正：用户只有 IP `8.138.30.176`，没有域名；前端目标仍是 GitHub Pages。截图显示 `/www/wwwroot/aliyun-deploy` 旧项目，含 `db`、`后端`、`.env`、旧 Compose。尚未连接服务器，未知旧容器名和数据库类型，不能删除/覆盖/盲目迁移。
- 新 `compose.baota.yaml` 是独立 `kuajing-next` 项目，仅 api 服务绑定宿主机 `127.0.0.1:18000`，用宝塔宿主 Nginx 做 HTTPS，不运行 Caddy、不抢 80/443。新目录 `/www/kuajing-next` 与旧版隔离。
- [baota-upload-steps.md](baota-upload-steps.md) 是当前入口，明确上传/解压、只读旧部署检查、env 填写、构建、可选本机 runtime 迁移、验收、旧版备份/切换/回退。域名缺失时只先完成本机验收和源码上传，不能把 HTTP IP 填进 Pages 地址变量。
- `scripts/package_upload.py` 生成带顶层目录的后端 ZIP 与 GitHub 源码 ZIP，排除秘密/运行数据/依赖，输出在已忽略的 `release/时间/`。真实 env 和当前数据库不自动打包；数据库迁移需要先停写再单独打包。
- `deploy/baota-inspect.sh` 只读容器/端口/旧挂载，不输出 env；`baota-init.sh` 仅在预定新目录初始化，不覆盖 env、不启动容器；`baota-proxy.conf` 提供 SSE/上传大小/协议头配置。

## 2026-09-23 GitHub Pages + Docker API 部署准备

- 用户确认已有域名，选定 `app.域名` 指向 GitHub Pages、`api.域名` 指向 Docker 云服务器；普通用户保持免登录。上一次未完成的短信登录已撤销，没有接入鉴权。
- 新教程 [github-pages-cloud-tutorial.md](github-pages-cloud-tutorial.md) 是本次操作入口，README 和旧教程均已注明区别。使用独立 `compose.pages.yaml`（api + Caddy gateway），复用后端 Dockerfile 和四个持久目录；不能和旧同源方案并行启动。
- `.github/workflows/pages.yml` 推送 main 后检查并发布前端，Actions 使用官方固定提交并已逐项验证存在；公开 `VITE_API_BASE_URL` 来自 Repository Variables，base 来自 configure-pages。没有模型密钥进入前端。
- Pages 构建使用 HashRouter，普通开发保持 BrowserRouter；头像和 favicon 遵守 Vite BASE_URL。没有改变后端业务逻辑、模型配置、真实 `.env` 或正式数据。
- `scripts/verify_pages.py` 在临时 HTTPS 双子域名和临时图片库中验证子路径、Hash 刷新、静态资源、Strict/HttpOnly/Secure Cookie、空提示词四图生成、跨域原图下载、刷新不重复生成与不同浏览器历史隔离。Coze 使用替身，已通过。
- lint、43 项前端测试、普通构建和 Pages 子路径构建通过；临时 Compose 配置验证仅两服务、四目录、API 不公开 8000、gateway 仅 80/443；Git 忽略规则和 Pages 地址校验通过。源码常见 Token 模式扫描未发现命中。
- Docker CLI 可用但引擎未启动，因此尚未构建/运行 Linux 容器；GitHub 尚未初始化/推送，未修改 DNS 或部署远端。用户需按教程填域名与服务器配置、迁移数据，完成服务器真实验收。

## 2026-09-22 图片页面紧凑布局

- 2026-09-23 最新定稿：上传按钮也移到底部，与生成类型、生成按钮同排；无参考图时不渲染空上传区或顶部计数栏，已选缩略图在提示词上方展示并可移除/折叠。产品模式直接选文件，组合模式用原生 popover 选择产品/模特/背景图，避免浮层被输入区裁切。仅产品图必填的规则不变。
- 最新空输入区高度：1440px 桌面约 136px，390/320px 手机约 146px。已用隔离浏览器验证上传文件选择器、菜单、预览位置、移除校验、同排按钮及四图生成替身全流程；lint/build 通过。下面各项为布局迭代历史，以本条为准。

- 2026-09-23 用户纠正：最终使用上下布局，参考图在上、提示词在下；“生成类型”选择框放在底部“生成 4 张”按钮左侧。已移除左右分栏，保留紧凑缩略图和缩小的结果预览。桌面/390px/320px 验证类型与发送同排、不溢出；lint/build 与生图替身浏览器验收通过。下面的左右排列/158px 仅为已被替换的中间版本。

- 用户要求降低生图输入区高度并略缩小结果预览。`Tupian.jsx` / CSS 将桌面参考图与提示词、操作区左右排列，压缩缩略图和留白，窄屏保持分行；参考图折叠后回收空间。
- 桌面 1440px 视口下默认输入框整体从约 284px 降至 158px，390px 手机约 261px 降至 212px。结果网格最大宽度 900px、手机最大 320px；放大弹层和原图下载尺寸不变。
- lint/build、生图替身浏览器验收通过；补验三种视口及五张参考图，生成按钮可见、折叠不丢文件。没有调用真实 Coze 或更改后端。

## 2026-09-22 推荐状态与来源悬浮面板

- `Tuijian.jsx` 将每日更新时间、状态、刷新展示与采样来源收进右上角“更新与来源”按钮，默认不展开，不再占用商品上方或下方的正文空间。
- 悬浮面板支持按钮切换、外部点击、关闭按钮、Esc、键盘焦点退出；长内容内部滚动，手机宽度自适应。展开不触发接口请求，刷新仍只读快照。
- lint/build 和隔离浏览器验证通过：商品布局不因展开而移动、桌面/手机边界、关闭方式、翻页及刷新保持类别。后端和业务数据未变。

## 2026-09-22 热门价格币种显示修复

- 只读当前快照确认：日本站实际 `price_display=¥...`，旧解析器留下 `currency=null`。前后端补充真实日本站 + ¥/￥ 的日元识别、新加坡站 $ 的 SGD 识别，明确币种优先；不按裸数字或伪造域名推断。
- `productPricing.js` 同时兼容已有缓存；`hasValidPrice` 要求有效金额和可识别币种，首屏/缓存/分页共同过滤无法确认币种的商品。页面不再显示“币种未确认”，汇率暂不可用时只显示一次明确原币价格。
- 43 项前端测试、19 项价格/浏览器恢复测试、34 项爬虫自测以及 lint/build 通过；隔离浏览器验证人民币换算、未知币种过滤和刷新缓存。测试使用固定汇率，不会拿测试汇率作为线上兜底。
- 前端修复对旧服务数据立即生效；后端解析改动需正常重启后加载，本次未操作运行中的后端或正式数据库。

## 2026-09-22 GitHub 与 Docker 部署教学

- 新教程 [github-docker-deployment-tutorial.md](github-docker-deployment-tutorial.md) 按 Windows 上传 GitHub、Ubuntu 安装 Docker、只读 Deploy Key、环境配置、数据迁移、SSH 隧道验收、域名 HTTPS、更新/备份/恢复/回退讲解；README 已加入口。
- 新增 `deploy/`、`compose.yaml` 和 `compose.https.yaml`。Python 3.13 + Chromium 后端单 worker；React 构建后由 Caddy 同源提供网页/API/SSE；默认只监听回环 8080，公网覆盖配置要求整站密码。四个 runtime 绑定到 `server-data`，不把密钥和正式数据库放入镜像。
- 新 `backend/requirements.txt` 复用知识库固定依赖，补齐推荐直接使用的 langchain、langchain-openai、openai、httpx、typing-extensions；README 安装入口已更新。
- 补齐 Git 和 Docker 忽略规则；未修改真实 `.env`、正式数据库、现有应用运行逻辑；未初始化本项目 Git、创建仓库、push 或部署到云端。
- 两套 Compose 解析、bcrypt `$` 保留、端口范围、四个持久目录和 Git 忽略/示例保留验证通过。Docker CLI 存在但 Linux 引擎未运行，尚未构建或运行容器；教程明确要求服务器侧真实验收，不要把配置通过误称为部署通过。

## 2026-09-22 热门页加载恢复与推荐计数

- 已真实复现美国搜索 URL 跳到 `www.amazon.co.jp`，旧版因此持续 `unexpected_redirect`，不是前端按钮失灵。仅热门服务的爬虫开启明确区域白名单（美/日/英/新加坡）；实际商品 URL 和币种随数据返回，页面及本地预览保留来源，不把日站商品链接硬改为美站。推荐爬虫的默认来源约束不变。
- 爬虫等待合法 ASIN 和非空标题/图片 alt，而非空容器；解析兼容空 h2 和两种容器混合布局。临时未就绪/超时最多在同一市场同一页恢复一次，继续遵守间隔、验证码停止及冷却。下一页的已校验链接跨 HTTP 请求短期复用，失败不前进游标。
- 推荐页改为下标加稳定类别标识定位，重复关键词不再拉回第一类。计数用独立 output 节点并禁止翻译改写，实测 1→10、上一类、刷新保持第 9 类以及重复关键词样例通过。
- 34 项爬虫自测、56 项热门/推荐测试、36 项前端测试及 lint/build 通过。真实独立爬虫连续取得第 2、3 页各 48 件原始商品（有效价格分别 22、36 件）。
- 隔离真实浏览器验收也已通过：首次加载 35 件有效价格商品，下滑自动增加到 55 件，第 1、2 页均 HTTP 200，全程未点击重试。
- 本次自动审批拒绝了停止/重启现有后端（仅返回 blocked by policy），没有绕过。正式后端需由用户在原终端 Ctrl+C 后执行 `python -m backend.run_api` 才能加载新爬虫。前端 Vite 已更新。可显式运行隔离真实滚动验收：`python -B -m backend.remen.tests.browser_live_smoke`，不写正式库、不停止原服务。

## 2026-09-22 最新补充：图片工作室

- 最新修正：生图只要求产品图，提示词和模特/背景图均可选。前端提交按钮与后端校验已同步放宽，need_what 仍由所选类型自动提供。按钮旁显示不可提交的原因。49 项图片测试、空提示词/仅产品图的七模式浏览器验收、lint/build 通过，后端已重新加载。

- `src/compoment/tupian/Tupian.jsx` 已实现聊天提示词、七种 Coze 意图、分类型参考图、四张大图、进度、历史、放大和下载；已移除前端硬编码令牌与错误的工作流调用。
- `backend/tupian/` 接入统一 8000 后端：后台执行 Coze 中国区工作流，独立 SQLite/本地原图存档，刷新不重复生成、重复提交保护、下载失败单独重试、会话隔离。中文教学注释与完整说明见 [image-studio.md](image-studio.md)。
- 已用用户新提供的令牌更新 `.env` 并重启统一后端，解决旧令牌 HTTP 401 / `700012006`。自制水瓶参考图真实验收：成功上传、运行工作流、返回 4 张图，并下载校验 4 张原图；产物只在系统临时目录，未写正式历史。工作流 ID 为 `7687948198364037155`，凭据不得写入前端、日志或文档。
- 27 项图片离线测试、整套后端 96 项、原有前端 34 项测试通过，lint/build 通过，隔离浏览器验证四图/刷新恢复/下载/手机布局。正式知识库未改。
- 按用户要求移除竞品分析导航、路由、组件及样式，未知/已移除的旧地址回到推荐首页。导航名称统一“知识库”，禁止浏览器自动翻译改写导航功能名；浏览器确认旧页面不再显示、知识库可正常进入，前端检查和构建通过。

更新时间：2026-09-19。项目根目录：`C:\Users\ruoxiao\Desktop\kuajing`。

本文是上下文交接，不是新的实施计划，也不是让你自动执行全部待办。先读本文，再按用户在新聊天中的具体请求工作。源码、运行状态可能继续变化，修改前仍需检查实际文件。

## 1. 先记住这几件事

- 用户正在学习 Python、FastAPI、React、RAG、LangGraph、Agent 和 MCP，目标是能独立写代码、理解调用链，并应对 Agent 应用开发实习面试。
- 用户特别重视**详细中文教学注释、能运行的代码示例、为什么这么写、怎么仿写**，不满意只有功能介绍或逐行翻译的说明。
- 项目已有可用的知识库全链路，不要当作空项目重做。问答、上传、批量导入已经恢复为真正的 LangGraph 编排，不要擅自换回手动串联函数。
- **正式知识库目前是 313 份文档、3023 个知识块**。本文生成时访问已有后端健康接口实际确认，不是照搬旧计划中的 307。
- 最近完成的是 `backend/test.py` 的独立 MCP 教学实验；它没有接入正式 RAG，也不是新增生产 Agent。
- 当前交接任务只新增本文，没有修改业务代码、`.env`、依赖、知识库数据或已有教程。

### 用户的修改边界与沟通偏好

1. 用户说“只改这个文件”时就只能改该文件。以前对爬虫与 MCP 的要求都是单文件修改，不能顺手接前端、改入口、改 requirements 或重构目录。
2. 为修改部分补充大白话注释，解释：是什么、谁调用、什么时候执行、参数来源、返回值去向、为什么这样设计、以后怎么写。
3. 保留正确的原有代码和注释。纯注释任务不能暗中改变运行逻辑；修复/重构任务也不能扩大到无关功能。
4. 不修改 `.env`、密钥、模型配置、存储键或正式数据，除非用户本次明确要求。不要把凭据写进交接文档或聊天输出。
5. 旧的“允许导入 307 份资料到 DashScope”是已完成任务的授权，不是每次都可以重新入库、重复发送正文或清库。
6. 测试上传使用隔离存储；不要为了验收向正式库加入测试文件。独立浏览器测试曾获许可，但不要读取用户日常浏览器账号与历史。
7. 不要承诺“学习完就一定通过面试”“用了 LangGraph 就是自主 Agent”。需区分工作流编排、模型工具调用和自主决策能力。
8. 优先用实际代码和测试说明完成程度，不把“写了代码”“旧测试通过”“刚做过真实验收”混为一谈。

## 2. 环境与结构

- 操作系统：Windows，终端：PowerShell。
- 指定 Python：`D:\python\python.exe`。工具初始工作目录可能是 `D:\Pythonstd`，**那不是本项目根目录**。
- 前端：React 19、Vite 8、React Router，使用 `oxlint`。
- 知识库后端依赖以 `backend/zhishiku/requirements.txt` 为准：包含 `langgraph==1.2.5`、Chroma、LangChain、DashScope 等；FastAPI/Starlette 已固定兼容组合，不能只升级其中一个。
- MCP 教学沿用本机已有的官方 `mcp==1.27.0`，没有为本次教学升级或安装依赖。
- 根目录存在 `node_modules`、`dist`、`.env`。本次目录检查未见 `.git`，不要假定一定可以通过 Git 回滚。

```text
kuajing/
├─ README.md                         项目安装、启动、接口导航
├─ package.json / package-lock.json   前端依赖与 npm 命令
├─ vite.config.js                    开发代理
├─ .env / .env.example / .gitignore   私密配置、示例、忽略规则
├─ public/                           图片等静态资源
├─ 亚马逊知识大纲/                     原始知识文件
├─ amazon-outline-prescan.json       历史预扫描报告
├─ backend/
│  ├─ run_api.py                     统一后端启动、端口占用检查
│  ├─ app.py                         FastAPI 应用，挂载推荐与知识库/管理路由
│  ├─ _common.py                     配置要求、Embedding、聊天模型工厂
│  ├─ qwen_client.py                 Qwen 配置与客户端辅助代码
│  ├─ test.py                        独立 MCP 教学实验，不是生产入口
│  ├─ tuijian/
│  │  ├─ agent.py                    推荐 LangGraph、商品抓取、分析、接口
│  │  └─ tests/test_recommendations.py
│  ├─ remen/
│  │  └─ pachon.py                   独立亚马逊爬虫 + FastAPI + 内置自测
│  └─ zhishiku/
│     ├─ api.py                      问答 SSE/JSON、健康、管理员接口
│     ├─ zhishiku.py                 RagService、ServiceState、问答图
│     ├─ agent.py                    KnowledgeBaseService、IngestState、入库图
│     ├─ document_loader.py          DOCX/PDF/TXT 解析、规范化、切块
│     ├─ vector_stories.py           KnowledgeStore、Chroma、Embedding、锁内去重
│     ├─ reranker.py                 qwen3-rerank 请求与降级
│     ├─ auth.py                     bcrypt、签名 Cookie、认证与登录限流
│     ├─ config_data.py              配置、提示词与运行路径等
│     ├─ import_documents.py         预扫描、递归导入、JSON 报告
│     ├─ README.md / requirements.txt
│     ├─ tests/
│     │  ├─ test_documents_and_store.py
│     │  ├─ test_rag_and_api.py
│     │  └─ test_graphs.py
│     ├─ runtime/
│     │  ├─ chroma/                  正式持久化知识库，绝不能随便清理
│     │  ├─ amazon-outline-import-report.json
│     │  └─ import-入门指南.json       导入过程的历史阶段报告
│     └─ runtime-backup-20260911-132848/  历史旧库备份
├─ src/
│  ├─ main.jsx                       React 启动与 Provider 包裹
│  ├─ App.jsx / App.css              全局导航、会话子列表、折叠与移动抽屉
│  ├─ NavigationIcon.jsx             统一细线 SVG 图标
│  ├─ AppErrorBoundary.jsx           页面/消息渲染兜底
│  ├─ index.css
│  ├─ routers/index.jsx              URL 到页面的路由表
│  └─ compoment/                     注意：现有目录确实拼成 compoment
│     ├─ zhishiku/
│     │  ├─ Zhishiku.jsx / Zhishiku.css
│     │  ├─ KnowledgeConversationContext.jsx
│     │  ├─ knowledgeConversationStore.js / .test.js
│     │  ├─ AnswerMarkdown.jsx
│     │  ├─ streamingMarkdown.js / .test.js
│     │  ├─ tokenBuffer.js
│     │  ├─ chatAutoScroll.js / .test.js
│     │  └─ useChatAutoScroll.js
│     ├─ guanli/AdminDashboard.jsx / .css
│     ├─ tuijain/Tuijian.jsx / .css   注意：现有前端目录拼成 tuijain
│     ├─ remeng/Remeng.jsx / .css
│     ├─ jingpin/Jingpin.jsx / .css
│     ├─ tupian/Tupian.jsx / .css
│     └─ shezhi/Settings.jsx
└─ docs/
   ├─ project-handoff.md             本交接文件，不是第四份开发教程
   ├─ zhishiku-learning-guide.md     阅读导航与部分历史验收记录
   ├─ zhishiku-code-tutorial.md      14 课代码实战与练习
   ├─ zhishiku-developer-tutorial.md 原理、架构、接口、部署等详细解释
   └─ verification/                 2026-09-14 浏览器验收截图
```

## 3. 核心链路与不能破坏的约定

### 3.1 知识库问答

前端 `Zhishiku.jsx` 发送问题和最近历史 → `api.py` 校验/限流 → `RagService` 执行图：

```text
START → rewrite_question → retrieve_candidates → rerank_documents → prepare_context
                                                                          ├─ generate → END
                                                                          └─ insufficient_evidence → END
```

- 无历史不改写；改写失败回原问题。召回 12 条，精排保留 5 条；精排失败退回向量排序；无资料不调用回答模型。
- `ServiceState` 包含 question、history、retrieval_query、candidates、documents、context、sources、answer、rerank_used、status。每次请求独立，节点返回局部更新；不要给历史和候选列表随意加累加 reducer。
- 同步入口是 `ask()` → `graph.invoke()`。异步入口是 `astream_events()` → 同一图的 `graph.astream(custom + updates, version="v2")`。
- 不要重新使用旧的 `prepare()` + `stream_answer()` 手工串联问答方案。
- 公开接口：`POST /api/knowledge/chat`、`POST /api/knowledge/chat/stream`、`GET /api/knowledge/health`。
- 请求结构：conversation_id、question、history；问题最多 2000 字符，历史最多 10 条 user/assistant 消息。
- SSE 对外仍是 `status / sources / token / done / error`，增量为 `token` 事件中的 `{ "content": "..." }`。不把 LangGraph 内部完整状态或改写文本发给前端。
- sources 在答案前发送；done 的完整答案由同一批增量累积，不额外生成第二遍。
- 取消需关闭流并释放一次并发名额；页面停止接收不等于供应商立即停止计算或计费。
- 匿名历史只在浏览器保存，不使用 SQLite 聊天历史、不启用 checkpointer。
- 问答按 IP 限频且最多同时生成 2 个回答；生产多进程场景要另外考虑共享限流。

### 3.2 管理上传与批量导入

```text
上传 bytes 或预解析 ParsedDocument
→ prepare_document → fingerprint → check_duplicate
                                     ├─ 重复 ────────────────────┐
                                     └─ 不重复 → split_chunks ───┤
                                                                 ↓
                                                      persist_document → END
```

- `upload_file()` 与 `ingest_document()` 共用入库图；批量导入使用预解析入口，不能绕过图直接调用存储层。
- DOCX 保留段落/标题/表格顺序；PDF 读取文字层，不做 OCR；TXT 支持 UTF-8/BOM/GB18030。
- 规范化正文 SHA-256 去重；约 800 字符切块、120 字符重叠，保留标题/章节前缀；块 ID 确定性生成。
- Chroma metadata 是去重事实来源，不恢复独立 `content_hashes.txt`。图只做预检查，存储层必须锁内再次确认并写入；目前锁是单进程级别。
- 管理接口：`POST /api/admin/login`、`GET /api/admin/session`、`POST /api/admin/logout`、`POST /api/admin/knowledge/files`、`GET /api/admin/knowledge/stats`。
- 文件接口每个请求一个 file，可带 category；前端多选后逐文件发送；单文件上限 25 MiB。
- Cookie 为签名、HttpOnly、SameSite=Strict、8 小时；生产 HTTPS 要 Secure。管理员明文密码不在本文中，也不能从 bcrypt 哈希反推。初始用户名约定为 admin，当前凭据以实际配置为准；没有用户要求不要重置密码。

### 3.3 前端稳定性与当前 Markdown 实现

- Provider 提供共享会话，左栏和聊天页共用；切换/删除生成中的会话先停止旧请求，避免串会话。
- 会话键：`kuajing-knowledge-conversations-v2`；最多 20 个会话，每个持久化最近 60 条消息（约 30 轮）。导航偏好独立键：`kuajing-navigation-state-v1`。
- localStorage 读取清洗、防抖/体积裁剪、权限/容量异常保护、离开页面尽量即时保存都已有代码；不要因异常自动删除用户历史。
- 助手消息现在使用 `react-markdown + remark-gfm + remend@1.3.1`，包括流式、停止和部分失败内容；用户消息仍是纯文本。
- `streamingMarkdown.js` 只补全展示副本，不改原始答案/持久化历史；避免全局删除 `**`、`#` 等字符，代码块和转义符号必须保留。
- `tokenBuffer.js` 约 50ms 合并刷新，结束/停止/错误时立即补齐；`AnswerMarkdown` 使用 memo 和错误边界。
- 自动滚动只控制消息容器，用户上滑时暂停跟随，不要每个 token 重新 `scrollIntoView({behavior:'smooth'})`。
- 左栏已有 Claude 风格暖灰 `#F4F3EF`、深灰文字、细线 SVG。展开约 280px、折叠约 68px；≤680px 使用移动抽屉。
- 管理图表圆心已增加局部定位参照与明确居中规则，见 `AdminDashboard.css` 后段的 `.admin-page .donut`。

## 4. 其他模块目前做到哪里

| 模块 | 当前代码确认的状态 | 不要误认为已完成的部分 |
| --- | --- | --- |
| 知识库/管理 | 问答、引用、会话、停止、上传、认证、统计、LangGraph 两张图均存在；已有历史浏览器验收记录 | 不代表所有答案经过业务专家审核，也不是公网生产安全验收 |
| 推荐 | `backend/tuijian/agent.py` 保留 start_analyze → collect_product_data → sum_up 图和 GET `/tuijian/agentcall`；有输入精简、错误分类、有限重试、失败保留真实商品、前端重试 | 当前外部网络/供应商状态与真实完整十类别请求是否成功，本文没有重新验证 |
| 热门产品爬虫 | 单文件 `pachon.py` 已有真实抓取、浏览器/普通 HTTP 模式、分页、去重、缓存、限流、部分失败与自测 | 没有挂到统一 8000 应用；热门前端仍是静态卡片，没有接通爬虫 |
| 竞品分析 | 存在页面组件和筛选按钮，看到的商品/价格/销量是静态演示 | 没有确认真实竞品数据后端或分析闭环 |
| 图片生成 | 当前 `Tupian.jsx` 是布局占位 | 没有实现可验证的图片生成接口/模型链路 |
| 管理数据总览 | 有图表与统计卡片布局；知识库统计是独立真实接口 | 不要把无关商品/平台总览的静态数字说成真实电商运营数据 |
| MCP | 本地独立的可运行教学 Server + Client + 自测 | 没有生产鉴权、租户隔离、模型自主选择工具，也没有接入现有 Agent |

### 推荐服务补充

- 过去用户反馈“服务不可用”，已定位过汇总阶段 `APIConnectionError`；不是所有 502 都意味着密钥缺失。
- 当前代码把模型汇总输入限制为 24000 字符，保留标题/价格/评分/评论数/销量等分析字段，不把图片和商品长链接塞进汇总提示；页面仍拿原始商品字段。
- 连接超时 10 秒、读取超时 60 秒；只对指定临时异常最多额外重试一次，不自动重新抓取整批商品。
- 分析失败时明确标注 `analysis_status` 并保留商品，不能伪造成功分析。
- 推荐与热门爬虫不是同一服务：推荐有自己原有的抓取链路；热门爬虫按用户选择只做本机直连，不复用第三方抓取凭据。

### 热门爬虫补充

- 独立服务默认 `127.0.0.1:8001`，真正的路由前缀是 **`/api/remen`**，不是 `/remen`。
- GET `/api/remen/products`；GET `/api/remen/health` 只检查本地准备状态，不证明亚马逊当前可访问。
- 示例：`http://127.0.0.1:8001/api/remen/products?subCategory=shuma&limit=100&max_pages=10`。
- `limit` 默认 50、范围 1～200；`max_pages` 默认 5、范围 1～20；起始 `page` 范围 1～50。达到目标提前结束，不保证总能抓满。
- `category=hot|niche`；`period=current|day|15-days`；`keyword` 可覆盖默认分类词。分类键看文件开头表格，含 all/shuma/fuzhuan/jiaju/meir/muying/qimo/shipin/qita。
- 默认独立无头 Chrome，可配置普通 direct 模式；不读用户浏览器配置。不破解验证码、不轮换代理，受限时明确报错并冷却。
- 缓存约 5 分钟，真实页请求至少间隔 3 秒，批次串行翻页并复用一个浏览器；有软时间预算和部分结果。
- `sales` 是页面公开的近月购买提示，不是精确销量，更不是日销量；缺失为 null。day/15-days 不是真历史筛选，`period_applied=false`。hot/niche 是候选筛选规则，不是官方全站榜单。
- 如以后用户要求接入前端/统一入口，需要扩大到相关文件的明确任务范围；仅 include_router 还不够，需同时检查 crawler 依赖和 CrawlError 异常处理。

## 5. 最近完成的 MCP 教学任务

目标文件：`backend/test.py`。开始时为空，已完成；该次任务只修改了此文件。

- 用官方 SDK 1.27.0 的 `mcp.server.fastmcp.FastMCP`，不是独立的 `fastmcp` 包。文件标明了 SDK/协议版本边界，不要把新旧 SDK 示例直接混写。
- 第一层普通业务：`add_numbers`、内存合成资料检索、按白名单 ID 读资料；不访问正式知识库。
- 第二层 `build_server()`：登记 `add`、`search_demo_knowledge` 工具；固定资源 `demo://guide`、模板 `demo://documents/{document_id}`；提示词 `knowledge_answer`。
- 第三层真实客户端：`ClientSession` 完成初始化、发现和调用，不是直接调 Python 函数冒充 MCP。支持 stdio 与本机 Streamable HTTP。
- 工具参数有类型/范围约束，返回 Pydantic 结构化结果，处理 `isError`；stdout 不能被 stdio 服务端调试 print 污染。
- 第四层业务和协议自测：正常调用、参数缺失/越界/类型错误、零命中、资源/提示词错误、错误后恢复。
- 第五层 15 组面试问答与追问、30 秒介绍和“问题—做法—验证—边界”回答框架。
- 第六层带注释的 multiply 手写题参考、企业 RAG 接入设计练习、JSON-RPC 消息拆解、排错清单和学习自查标准。
- 模式：默认 `demo`、`self-test`、`config`、`serve`、`demo-http`。`config` 只打印常见宿主配置，不会修改客户端配置。
- 没有调用大模型，不需要密钥，不读 `.env`，不消耗模型额度。HTTP 仅监听回环地址，含 Host/Origin 检查，但没有企业鉴权；不能直接当公网生产 MCP 服务。
- 自测故意传入空提示词，SDK 会在 stderr 打印预期 ERROR 堆栈；最后“自测完成”且退出码 0 才表示通过。不要误把故意的负例日志当真实故障。

上一轮已实际验证：默认 demo、自测、config、真实本机 HTTP 工具/资源/提示词调用、不可信 Origin 返回 403、语法与导入不自动启动，以及注释中 multiply 参考的登记/计算/非法参数处理。临时 HTTP 进程测试后已关闭，没有停止正式 8000 后端。

## 6. 数据、备份与验证证据

### 生成本交接文件时的只读检查

已有 `http://127.0.0.1:8000/api/knowledge/health` 返回 HTTP 200：

```json
{
  "status": "ok",
  "document_count": 313,
  "chunk_count": 3023,
  "rerank": {
    "enabled": true,
    "available": true,
    "degraded": false,
    "model": "qwen3-rerank",
    "reason": null
  }
}
```

这是当时服务的报告，不是刚做了一次真实 Rerank 探测。该次对 8001 的连接失败，不能据此认定爬虫坏了；它是需要另行启动的服务。

### 历史导入与验收

- 原始大纲扫描：377 个 DOCX、307 份唯一正文、67 个重复、3 个损坏文件。
- `runtime/amazon-outline-import-report.json` 的最终快照为 307 文档/2998 块。该报告是幂等复核运行：indexed=0、duplicate=307、error=0、chunks_written_this_run=0，不表示第一次没有导入。
- 当前 313/3023 与上述初始报告属于不同时间点。新增 6 文档/25 块的具体来源本次没有审计，不能猜测成测试数据，也不能为了凑回 307 而删除。
- `runtime/import-入门指南.json` 是较早阶段报告，不是完整知识库最终统计。
- 历史旧库备份目录仍存在：`backend/zhishiku/runtime-backup-20260911-132848`。未验证本次恢复演练，不要随意覆盖现有 runtime。
- `docs/zhishiku-learning-guide.md` 第十三、十四节保存 2026-09-14 验收记录：真实长回答、追问、来源、停止刷新、会话隔离、存储异常、侧栏/手机抽屉、隔离上传、401 等，以及抖动专项检查。
- 当时记录后端 28 项测试通过，滚动专项之后前端 14 项通过，lint/build 通过。后来新增 Markdown/推荐测试，所以**这些不是当前最新测试总数**。
- 爬虫先前会话记录为 31 项离线自测通过，真实抓取曾取得 50 个不同商品；本次交接没有重新向亚马逊发抓取请求，不能承诺当前同样成功。
- 本次只核对结构、源码、报告和已有健康接口；没有重新运行全套回归、生产构建、推荐完整十类别请求、真实问答或上传测试。

### 云端数据注意

知识库在 `backend/zhishiku/runtime/chroma`，不是在 Git 或模型供应商那里自动保存的一份可用副本。只上传源码不会带上本地向量库。未来部署需要规划一致性备份/迁移、持久化磁盘和匹配的 Embedding 配置；不要在运行中随意搬 SQLite/Chroma 文件，也不要为回答部署问题直接执行重建入库。

## 7. 明确尚未完成或需要重新确认的事项

以下是交接提醒，**不是新 AI 可以不经用户请求立即执行的工作清单**。

1. **热门前端尚未接爬虫**：`Remeng.jsx` 仍是固定图片和“价格232/销量232”，统一 `app.py` 只挂推荐与知识库。单文件爬虫已完成，不等于该页面已联调。
2. **MCP 尚未接入生产 Agent**：目前是完整教学实验。若用户下一步要求接 LangGraph，先确定只暴露检索还是完整问答、身份权限、调用费用与允许改哪些文件。
3. **教程中的流式 Markdown 说明落后**：
   - learning-guide 的“前端状态与 SSE”仍写生成中纯文本。
   - developer-tutorial 的 11 节附近仍写完成后再切 Markdown。
   - code-tutorial 的 7.4 节标题与相关示例仍是“生成中纯文本，完成后 Markdown”。
   - 这些与当前 `AnswerMarkdown.jsx`、`streamingMarkdown.js`、`tokenBuffer.js` 不一致。若获准同步文档，应保留有日期的历史验收事实，同时明确当前实现已更新。
4. **README 代理描述过宽**：README 写代理 `/tuijian`，实际 `vite.config.js` 只代理 `/tuijian/agentcall`；这是为了避免推荐页面刷新被误转发到后端。不要照旧文字把代理范围改大。
5. **推荐真实全链路需按新需求复验**：代码里已有汇总输入精简和错误修复，测试文件也存在，但本次未确认当前十类别真实请求的完整成功记录；不能把降级保留商品当成供应商连接问题彻底消失。
6. **最新视觉改动缺少本次浏览器复验**：图表局部定位、流式 Markdown、暖灰侧栏均已看到实际代码；2026-09-14 截图属于此前阶段，不能代替这些最新改动的动态验收。
7. **其他页面不是全功能成品**：竞品分析、图片生成和无关静态总览不要宣称已实现完整业务。
8. **未实施公网生产方案**：没有在本次完成 HTTPS/反代部署、跨实例写入协调、共享限流、多租户权限、生产 MCP OAuth 或完整监控告警。
9. **管理员明文密码不在这份交接中**：不要猜测还是 admin/admin123；需要帮助登录时先按实际任务核对配置或征得同意后走重置流程。

## 8. 启动与检查命令

以下是供下个 AI 和用户按需要执行的命令，不表示生成本文时执行过它们。

### 正式前后端

```powershell
# 两个 PowerShell 窗口都先进入项目根目录
cd C:\Users\ruoxiao\Desktop\kuajing

# 窗口一
D:\python\python.exe -m backend.run_api

# 窗口二
npm run dev
```

- 知识库：`http://localhost:5173/zhishiku`
- 管理：`http://localhost:5173/admin`
- 推荐：`http://localhost:5173/tuijian`
- 热门页面：`http://localhost:5173/remeng`，当前还未接真实抓取。
- Swagger：`http://127.0.0.1:8000/docs`
- `npm run backend` 使用 PATH 中的 python，不一定是 D 盘解释器，优先上面的明确命令。
- Vite 代理 `/api` 和 `/tuijian/agentcall` 到 8000；爬虫目前在 8001，不会自动被这套代理接通。

### 独立热门爬虫

```powershell
D:\python\python.exe -B -m backend.remen.pachon
# 离线自测，不需要真实抓取
D:\python\python.exe -B -m backend.remen.pachon --self-test
```

### MCP 教学

```powershell
# 自动启动并清理自己的 stdio 子进程，不需要另开服务端
D:\python\python.exe -B backend\test.py
D:\python\python.exe -B backend\test.py self-test
D:\python\python.exe -B backend\test.py config

# HTTP 教学才使用两个终端；默认 8012，不与正式后端冲突
D:\python\python.exe -B backend\test.py serve --transport streamable-http --port 8012
D:\python\python.exe -B backend\test.py demo-http --port 8012
```

### 回归测试（修改相应功能后再运行）

```powershell
D:\python\python.exe -B -m pytest backend\zhishiku\tests backend\tuijian\tests -p no:cacheprovider -q
npm run test:frontend
npm run lint
npm run build
```

先阅读测试依赖替身与隔离机制，不要把真实收费请求加进默认单测。`npm run build` 会更新 dist；`-B` 和 `-p no:cacheprovider` 用于避免不必要的 Python 字节码/pytest 项目缓存写入。

依赖已安装，不要为“继续”自动重装或升级。换电脑时按 README 和 requirements 安装；MCP、Playwright 等教学/独立服务依赖要分别检查，不能假定全部已写入知识库 requirements。

## 9. 新 AI 接手时建议怎么做

1. 先复述当前用户要继续的具体模块和允许修改的文件，不要把历史长计划全部重新执行。
2. 根据任务只读相关入口：知识库看 api.py/zhishiku.py/agent.py；前端看 main.jsx/App.jsx/对应组件；MCP 看 test.py；爬虫看 pachon.py。
3. 优先检查现有状态和测试，不假设旧服务还运行，也不要杀未知端口进程。
4. 如果用户在学习，按“最小示例 → 运行命令 → 预期输出 → 调用过程 → 改写练习 → 测试”来讲。
5. 如果用户继续问 MCP，教学基础已经写完，可帮助他亲手做 multiply 练习或模拟面试，而不是再次覆盖成一个只有加法的极简示例。
6. 交付时分别写清改动、实际测试、没验证的外部依赖和剩余边界，继续保持只改任务相关文件。

本文无需重复粘贴全部长聊天；新 AI 阅读此文件，再读取用户新任务所涉及的代码即可。

## 2026-09-22 基础设置页面

- `src/compoment/shezhi/Settings.jsx` 提供昵称、默认首页、侧栏展开、热门产品自动加载及恢复默认设置；补充中文注释和手机布局。昵称会立即同步到导航底部。
- `PreferencesContext.jsx` 统一管理页面偏好；`preferences.js` 校验昵称、路由和布尔值，用独立 `kuajing-preferences-v1` 浏览器存储键持久化，兼容旧侧栏状态。跨标签页同步；存储不可用时仍在当前页面生效并明确提示保存失败。
- 根路径通过 `routers/DefaultHome.jsx` 跳转所选首页，刷新明确的页面地址仍停留原页。热门页只在开启自动加载时监听滚动，关闭后保留首屏请求和“继续加载”按钮。
- 恢复默认只重置上述偏好，不清除商品浏览记录、聊天或生成图片；没有新增后端接口或修改业务数据库。
- 验证：前端 40 项测试、lint 和构建通过。`D:\python\python.exe -B scripts/verify_settings.py` 使用隔离浏览器和模拟接口，验证保存/刷新、默认首页、侧栏、自动/手动分页、跨标签页同步、重置、存储禁用及手机布局；不会请求真实模型或爬虫。


## 2026-09-21 每日推荐补充：证据先于模型判断

- `backend/tuijian/evidence.py`：固定公开来源采集、错误页检测、来源状态，以及20领域中每天16领域的探索轮换。
- `agent.py`：先抓候选池再调用模型；模型只能选已有 candidate_id；商品继续走本机 pachon，候选池复用、跨类 ASIN 去重、2件热度保留+3件近期未推荐优先。
- 这不是全网数据服务。来源仅Amazon美国站采样/公开榜单和Google美国搜索热搜；热搜不是销量，失败来源如实显示。
- `Tuijian.jsx` 显示证据覆盖范围、采集时间、入选理由和近7天重复数量。每日05:00、只读快照、失败保留旧数据和一次补试仍有效。
- 新增 `test_evidence.py` 覆盖采集先于模型、禁止凭空品类、来源失败、历史轮换、检查点恢复和去重；推荐测试默认阻断真实 requests。
- 已完成的当日期号不能因为升级重跑。正常重启后新流程用于下一期；不要为验收清理正式数据库或启动第二个正式调度器。


## 2026-09-21 热门产品动态首屏（替代固定预存文件）

- 用户明确不接受每次都从同一份固定商品开始。已删除 `hotProductsSeed.json` 和前端静态导入。
- `backend/remen/first_page.py` 在独立 `backend/remen/runtime/first-pages.sqlite3` 保存共享首屏；`GET /api/remen/products/snapshot` 只读磁盘并返回 no-store，不触发抓取。
- 8001服务生命周期启动默认热门/全部品类更新器，启动时无快照或超过30分钟则抓取；之后每分钟检查，达到30分钟更新。失败保留旧结果并至少等5分钟再试。定时任务和前台请求共用同一爬虫，仍遵守并发、间隔及验证码冷却。
- 每个默认关键词筛选的完整第一页（page=1、limit=200、max_pages=1）请求成功后也会保存。其它筛选不定时预抓；自定义关键词、空页、部分失败、后续页不覆盖默认首屏；旧时间响应不能倒灌。
- `Remeng.jsx` 同步显示本地快照，并行读服务器快照和实时第一页；较新的共享快照能更新新访客首屏，晚到的旧快照不能覆盖实时数据。首次浏览仅等快速快照读取，不等爬虫；全新部署无任何快照时才需首次抓取。
- “重新加载”发送 refresh=true 失效所请求页的五分钟缓存，仍受冷却与限流约束。实时成功后替换预览，滚动追加/去重、筛选隔离和人民币换算沿用原流程。
- 43项推荐/共享首屏测试、34项爬虫自测、31项前端测试以及lint/build通过。浏览器验证了共享首屏、实时替换、分页追加、旧快照晚到和主动刷新参数。
- 8001爬虫已重启加载该版本；默认首屏保存过真实48件商品。8000推荐/知识库服务未操作。正常源站数据可能保留部分相同商品；数据更新时间与商品是否全部更换不是同一个概念。


## 2026-09-22 统一商品服务、已浏览轮换和推荐错误分类

- 热门页原来硬编码8001，用户仅启动8000就断连。`backend/app.py` 现在在同一个生命周期启动热门快照更新器，挂载 `/api/remen/*` 和爬虫错误处理。前端使用同源API；用户只需启动 `python -m backend.run_api`，不要同时启动独立8001更新同一库。
- 用户明确选择“每次进入优先展示上次没看过的商品”。新增 `productDiscovery.js`：只有进入可视区域的卡片才计为看过，本地记录7天/最多600件，按筛选隔离。首屏先按进入前的历史优先展示未看商品；实际请求接着上次成功结果的next_page，后续仍顺序分页。末页回到1，不把换序说成市场更新。存储禁用时正常降级。
- “更新并换一批”继续请求新一页并设置refresh=true，仍受间隔/冷却限制。浏览记录不发送给后端或模型。
- 推荐9月22日首次失败的检查点表明16类全部 `browser_unavailable`，不是AI JSON失败。新增 ProductEvidenceError，浏览器不可用时停止重复启动，对旧失败记录也按检查点纠正页面说明；后续仍按原15分钟补试一次。
- 历史快照只读展示时也过滤常见“销量/增长”越界文案，返回presentation_version让前端更新旧内容，不改原始数据库快照、不调用模型。

- 真实恢复验收：2026-09-22 07:38 自动补试，07:41:23 成功发布当天10类/50件商品；采样12个有数据领域，失败记录已清除。热门页通过同源8000真实取得48件商品，不再请求8001；新访客浏览器回归验证再次进入请求页序1→2，“更新并换一批”请求3，旧已看卡片后移。
- 验证：推荐/热门47项测试、知识库28项测试、爬虫34项自测、前端34项测试通过，lint/build通过。继续保持正式知识库不变。
