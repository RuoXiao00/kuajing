# 跨境阁：亚马逊跨境电商知识库与产品推荐

当前宝塔服务器 `8.138.30.176`：[直接上传压缩包和旧项目处理步骤](docs/baota-upload-steps.md)。用 `scripts/package_upload.py` 生成上传包；保留旧目录，新版单独部署。目前只有 IP，Pages/API 正式连接的域名步骤尚待完成。

本次部署方案：[GitHub Pages 前端 + Docker 云服务器后端操作流程](docs/github-pages-cloud-tutorial.md)。使用同一个域名下的 app / api 子域名，包含代码上传、Pages 自动发布、服务器配置、数据迁移与验收。

另一种方案：[前后端都放在 Docker 服务器](docs/github-docker-deployment-tutorial.md)。两套部署入口不要混用。

项目由 React/Vite 前端和统一 FastAPI 后端组成。知识库由 LangGraph 1.2.5 编排以下 RAG 流程：

1. 根据最近最多 10 条消息，把“日本站呢？”等追问改写成独立检索问题。
2. 从 Chroma 向量库召回 12 个候选知识块。
3. 使用 qwen3-rerank 精排并保留 5 个最相关知识块；精排不可用时自动退回向量顺序。
4. 使用 Qwen 仅依据检索资料回答，事实结论用 [资料 n] 标注来源。
5. 通过 SSE 将 token 实时发送到聊天页面。

问答的同步/异步入口共用一张图，无资料时由条件边返回资料不足，不调用回答模型。
上传和目录导入也共用入库图：准备文档 → 指纹 → 预检 → 按需切块 → 锁内确认并写入。
这是图编排的 RAG 工作流，不是自主规划 Agent。未启用 checkpointer，不需要 SQLite。

匿名聊天不会写入服务器数据库。会话由浏览器 localStorage 保存，刷新后仍可恢复；
conversation_id 只用于一次请求追踪。

## 开发者学习文档

- [代码实战教程（主要练习）](docs/zhishiku-code-tutorial.md)：14 课、带注释的离线 LangGraph 问答/入库/条件分支实例、SSE 和测试。
- [完整 RAG 开发者教程](docs/zhishiku-developer-tutorial.md)：从启动、Python、RAG、接口和 React，一直讲到测试、扩展与云部署。
- [快速代码学习指南](docs/zhishiku-learning-guide.md)：适合先建立阅读顺序和调用链。

建议先用快速指南定位入口，再按代码教程亲手运行，遇到原理问题查开发者教程；三份均已同步为 LangGraph 版本。

## 一、首次安装

在 PowerShell 中进入项目目录：

~~~powershell
cd C:\Users\ruoxiao\Desktop\kuajing
~~~

安装后端依赖：

~~~powershell
D:\python\python.exe -m pip install -r backend\requirements.txt
D:\python\python.exe -m pip check
~~~

安装前端依赖：

~~~powershell
npm install
~~~

## 二、环境配置

本机配置保存在项目根目录 .env，该文件已加入 .gitignore，不应提交或发送给别人。
可从 .env.example 了解全部配置项。

主要配置：

- DASHSCOPE_API_KEY：Qwen、Embedding 与 Rerank 共用的百炼密钥。
- QWEN_MODEL：正式回答模型，默认 qwen-max。
- QWEN_REWRITE_MODEL：多轮问题改写模型，默认 qwen-flash。
- DASHSCOPE_EMBEDDING_MODEL：入库和检索共同使用的向量模型。
- DASHSCOPE_RERANK_BASE_URL：包含 Workspace ID 的 compatible-api/v1 基础地址。
- ADMIN_USERNAME：管理员用户名。
- ADMIN_PASSWORD_HASH：bcrypt 密码哈希，不能填写明文密码。
- SESSION_SECRET：至少 32 字符，用于给管理员 Cookie 签名。
- FRONTEND_ORIGINS：允许访问 Cookie 接口的前端来源，禁止星号通配符。
- COOKIE_SECURE：本地 HTTP 为 false；公网 HTTPS 必须为 true。

修改 .env 后必须重启后端，已经导入 Chroma 后不能随意更换 Embedding 模型；
更换模型必须重新生成整个向量库。

## 三、启动项目

打开两个 PowerShell 窗口，并都进入项目根目录。

窗口一启动统一后端：

~~~powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -m backend.run_api
~~~

如果 PATH 中的 python 已经指向 D:\python\python.exe，也可以使用：

~~~powershell
npm run backend
~~~

窗口二启动前端：

~~~powershell
cd C:\Users\ruoxiao\Desktop\kuajing
npm run dev
~~~

启动后访问：

- 知识库聊天：http://localhost:5173/zhishiku
- 管理后台：http://localhost:5173/admin
- 产品推荐：http://localhost:5173/tuijian
- Swagger：http://127.0.0.1:8000/docs
- 知识库健康检查：http://127.0.0.1:8000/api/knowledge/health

Vite 会把 /api 和 /tuijian 代理到 127.0.0.1:8000。生产环境应让前端和 API
使用同一域名，并通过 HTTPS 访问，确保 SameSite=Strict 与 Secure Cookie 正常工作。

## 四、聊天和管理后台怎么使用

知识库页面：

- 点击左栏“知识库”按钮，可在按钮下方展开或收起会话列表。
- 点击左栏边缘的箭头可将整个导航收至左侧；手机端使用左上角菜单按钮打开抽屉。
- 点击“新建会话”创建独立对话，最多在当前浏览器保存 20 个会话。
- 每个会话最多持久化最近 30 轮；浏览器存储不可用时页面仍能继续聊天，并显示非阻断提示。
- Enter 发送，Shift+Enter 换行。
- 生成过程中点击方形按钮可停止请求。
- 回答下方“查看参考资料”会显示文件名、分类、日期和摘要。
- 请求失败后可点击“重新生成”，失败消息不会被提交为下一轮历史。

管理后台：

1. 打开 /admin 并使用管理员账号登录。
2. 进入“知识库管理”标签。
3. 可拖拽或多选 DOCX、PDF、TXT，单文件最大 25 MiB。
4. 分类可填写“税务要求”“亚马逊物流”等；不填时使用“未分类”。
5. 页面逐文件显示上传进度，以及“已入库、重复跳过、失败”结果。
6. 扫描版 PDF 没有文字层时会明确报错，当前系统不执行 OCR。

同一正文即使改名也会通过规范化正文 SHA-256 被识别为重复。去重信息直接查询
Chroma metadata，不使用容易和向量库失去同步的单独哈希文本文件。

## 五、主要接口

- POST /api/knowledge/chat/stream：SSE 流式问答，事件依次为 status、sources、
  token、done，异常时为 error。
- POST /api/knowledge/chat：一次性返回 answer、sources、rerank_used，适合 Swagger。
- GET /api/knowledge/health：返回文档数、知识块数和 Rerank 状态，不暴露路径或密钥。
- POST /api/admin/login：验证 bcrypt 密码并设置 8 小时 HttpOnly Cookie。
- GET /api/admin/session：检查管理员 Cookie。
- POST /api/admin/logout：删除管理员 Cookie。
- POST /api/admin/knowledge/files：multipart/form-data 单文件入库，字段为 file 和 category。
- GET /api/admin/knowledge/stats：返回唯一文档数、知识块数、分类数和最近上传结果。
- GET /api/recommendations/latest：读取最近发布的每日推荐及后台更新状态，不触发模型或抓取。
- GET /tuijian/agentcall：兼容旧地址，读取同一份每日推荐；非默认关键词返回 422。

### 每日推荐的运行方式

启动统一后端 `D:\python\python.exe -B -m backend.run_api` 后，服务在北京时间每天
05:00 开始生成推荐。第一次没有结果时会立即在后台生成；服务错过数天后恢复，只补
最近一期，不逐日追赶。需要电脑开机联网且后端保持运行，网页是否打开不影响生成。

商品来源直接复用 `backend/remen/pachon.py` 的本机爬虫，无需第三方商品接口或
单独启动 8001。十个类别串行抓取，每类最多两页、30 件候选，最终最多展示五件；
继承爬虫的请求间隔、验证码停止和冷却。默认浏览器模式需要已安装的 Playwright 和
Chrome，与独立热门爬虫的依赖相同。模型分析继续使用已有 Qwen 配置。

页面只读取保存结果，可见时每分钟检查一次；“刷新展示”不会生成新推荐。同一天会
看到同一期结果，这是每日快照的设计。分析结合近七天记录适度轮换，但不把缺少历史
证据的差异说成增长，也不把近月购买提示说成日销量。

选品采用证据先行的 LangGraph：`collect_market_evidence → start_analyze → collect_product_data → sum_up`。
第一步采集 Amazon 公开畅销/排名上升/新品榜和 Google 美国搜索热搜，并用本机
`pachon.AmazonCrawler.collect()` 串行采样商品。20个领域每日探索16个，同领域轮换关键词，
优先近期较少推荐的领域；每类最多两页、30件候选。模型必须等采集完成后，才能从
有实际商品的候选ID中选择最多10类。网页标题只是资料，不允许其中的指令改变模型任务。
公开榜单仅采带排名标记的商品卡片，排除导航/信用卡广告；抓取失败或返回200错误页会标记不可用，不会填造榜单结果。

此范围**不是全网覆盖，也不是跨平台销量调查**。Google 搜索热度只能辅助选题，
无关新闻不构成商品需求证据。页面展示来源、采集时间、采样数量及每类实际入选理由。
商品明细不经过 Scrape.do 或8001 HTTP服务；选题后直接复用候选池，避免重新抓相同商品。
按ASIN跨类别去重，每类保留热度前2件，再优先补3件近7天未推荐的商品；不足则按热度
补充并公开重复数量。分析中检测到把购买提示写成销量、或无依据的市场增长等常见越界表述时，
改为原始指标摘要并提示原因；这不等于对模型全部自然语言进行了事实核验。历史不足时不能声称增长，重复项不冒充新品。

候选池和来源逐阶段存入任务检查点，补试复用成功采集；公开快照只携带选中商品和
证据说明，不包含候选池全集。既有已完成的一期不会因代码升级或刷新网页而重跑；
新流程在正常重启后的下一次到期任务生效。旧版未完成任务继续按原有结果恢复。

推荐单独保存在 `backend/tuijian/runtime/recommendations.sqlite3`，不写知识库。
后台任务和阶段检查点同样持久化，正常重启不重复生成已完成的一期。更新失败时保留
上期完整结果，15 分钟后只补试一次，优先复用已成功的阶段；第一次无历史时允许展示
部分结果。保留最近30天记录，长期故障时额外保留最后一份可展示快照。

当前调度器按**单个后端实例/单 worker**部署，不要为同一数据库启动多个调度器。
停止时等待正在执行的有限超时网络调用结束，再保存中断状态。日志记录更新周期、
次数、完成状态和耗时；接口提供 `generated_at`、`next_update_at`、`retry_at`、
`update_status`、`partial`、`is_stale`、`last_error`，用于区分新旧结果与更新失败。
独立验收可通过进程环境变量 `RECOMMENDATIONS_DB_PATH` 指向临时 SQLite；无需修改 `.env`。

聊天 JSON 示例：

~~~json
{
  "conversation_id": "018fd17f-6448-7c65-a90e-3f35e756bd61",
  "question": "日本站品牌备案需要什么材料？",
  "history": [
    {"role": "user", "content": "美国站品牌备案怎么办？"},
    {"role": "assistant", "content": "需要准备商标和品牌信息。"}
  ]
}
~~~

history 只允许 user 和 assistant，最多 10 条；question 最多 2,000 个字符。

## 六、批量导入与验证

仅预扫描，不调用外部模型、不写 Chroma：

~~~powershell
D:\python\python.exe -B -m backend.zhishiku.import_documents "亚马逊知识大纲" --dry-run
~~~

正式导入会把正文发送给 DashScope Embedding，并写入 runtime/chroma：

~~~powershell
D:\python\python.exe -B -m backend.zhishiku.import_documents "亚马逊知识大纲"
~~~

运行自动测试和前端检查：

~~~powershell
D:\python\python.exe -B -m pytest backend\zhishiku\tests -p no:cacheprovider -q
npm run test:frontend
npm run lint
npm run build
~~~

## 七、常见问题

如果出现端口 8000 被占用，先检查监听进程：

~~~powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
~~~

不要直接结束未知进程。backend.run_api 会识别已经运行的本项目后端，并避免重复启动。

健康检查显示 degraded 通常表示 Rerank 未配置或上次精排请求失败；此时聊天仍会使用
Chroma 向量排序。显示 unavailable 则检查 DASHSCOPE_API_KEY、runtime 写权限和
Chroma 文件是否完整。

FastAPI 与 Starlette 必须使用 requirements.txt 中的配套版本。若出现 Router 参数
不兼容，不要只升级其中一个包，应重新按 requirements.txt 安装。


## 热门产品动态首屏

热门页先展示浏览器或8001服务器保存的最近首屏，再请求实时第一页。服务器的只读接口
`GET /api/remen/products/snapshot?category=hot&subCategory=all` 不会等待爬虫；不再使用固定商品文件。
独立运行的8001服务每30分钟更新默认热门/全部品类首屏，抓取失败保留上次成功结果；
每个筛选的正常完整第一页响应也会更新独立 SQLite 快照。前端“重新加载”使用
`refresh=true` 忽略这一页的短期缓存，但仍遵守请求间隔和验证码冷却。
运行数据位于 `backend/remen/runtime/first-pages.sqlite3`，不写知识库或每日推荐数据库。
源站结果未变化时商品可能相同，页面始终显示实际抓取时间；服务停止期间无法定时更新。


### 2026-09-22 启动与浏览行为更新

热门、推荐、知识库现统一在8000：`D:\python\python.exe -B -m backend.run_api`。
前端热门请求使用同源 `/api/remen`，不再需要额外启动8001。上文的独立8001方式仅用于单独调试，
不要与统一后端同时执行默认首屏定时更新。默认首屏仍每30分钟更新，实际行情未变时可能保留相同商品。
热门页会把已经进入屏幕的卡片保存在本机7天内的浏览记录，下次优先展示未看商品，并接着读取上次成功响应的下一搜索页。
点击“更新并换一批”也继续发现后续候选；真实请求失败保留缓存，未知价格/币种和人民币换算逻辑不变。
