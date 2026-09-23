# 跨境电商知识库代码学习指南

源码内的注释解释局部设计，本文件负责把 Python、FastAPI、React 与 LangGraph RAG 串成完整运行流程。

学习三份文档的顺序：先用本指南定位入口，再按 `zhishiku-code-tutorial.md` 运行带注释的练习；遇到概念或接口细节查 `zhishiku-developer-tutorial.md`。三份已经同步为 LangGraph 编排版，不是互相替代的不同项目版本。

## 一、先分清定义与运行

- Python 第一次 `import` 模块时执行顶层语句，建立函数、类并创建模块级单例。
- `class` 是类型模板；执行 `ClassName()` 才运行 `__init__`。
- `def` 只定义函数；被其他代码调用后才执行函数体。
- FastAPI 装饰器在启动时登记路由；接口函数等请求命中后才执行。
- 包含 `yield` 的函数是生成器，由调用方逐次推进；`async def` 中的 `yield` 由 `async for` 推进。
- `StateGraph.add_node` 登记函数，`add_edge` 定义连接，`compile()` 编译调度规则；只有 `invoke()`／消费 `astream()` 时才执行节点。
- 节点返回局部字典，由图合并到本轮状态，不是所有节点共享并随意修改一个全局 dict。
- React 函数组件在首次渲染和状态变化时重新执行；事件处理器只在事件发生时运行。
- `useEffect` 在本轮渲染完成后运行；测试文件只在测试命令中运行。

遇到陌生函数，先查找调用位置，再回答：输入是什么、输出是什么、谁调用、何时调用。

## 二、推荐阅读顺序

如果卡在 LangGraph 的函数和 class，先看代码教程第 3.7 节“大白话讲节点调用”，
运行 lesson03_dispatch.py，再回来看源码。若不明白 await／yield，接着看第 5.2 节；
若不明白为什么查重两次，看第 11.8 节。不要只背名词，要能指出是谁把参数传进函数。

1. `backend/zhishiku/README.md`：掌握三条数据流和状态字段。
2. `config_data.py`：理解路径、切块、召回和大小限制。
3. `zhishiku.py`：学习一轮 RAG 问答的编排。
4. `vector_stories.py` 与 `reranker.py`：理解召回、精排、去重和降级。
5. `document_loader.py` 与 `agent.py`：理解文件如何变成知识块。
6. `auth.py` 与 `api.py`：理解认证、请求模型、接口和 SSE。
7. `src/compoment/zhishiku`：理解浏览器会话和流式回答。
8. `src/App.jsx` 与管理页：理解共享侧栏、登录和上传。
9. `tests`：用可执行示例验证前面的理解。

第一遍只追踪公共入口，以下划线开头的内部辅助函数可以第二遍再研究。

## 三、用户提问调用链

```text
Zhishiku.jsx: send/runQuestion
→ POST /api/knowledge/chat/stream
→ api.py: chat_stream
→ RagService.astream_events → initial_state → graph.astream
→ rewrite_question → retrieve_candidates → rerank_documents → prepare_context
→ 条件边：generate/agenerate 或 insufficient_evidence
→ custom 业务事件 + updates 最终结果
→ API 编码 SSE status/sources/token/done
→ 前端更新指定会话的助手消息
```

`ServiceState` 是一次请求的工作单，不是数据库：

```text
question 原问题
→ retrieval_query 可独立检索的问题
→ candidates 向量候选
→ documents 精排资料
→ context 带编号的模型上下文
→ sources 安全来源卡片
→ answer 最终答案
```

“日本站呢？”必须结合历史改写后再检索。Chroma 宽召回负责少漏资料，Rerank 精排负责把最相关资料放前面；精排失败时保留向量顺序。

## 四、文件上传调用链

```text
KnowledgeManager
→ multipart/form-data 上传
→ require_admin 验证 Cookie
→ run_in_threadpool(KnowledgeBaseService.upload_file)
→ graph.invoke → prepare_document → fingerprint → check_duplicate
→ 已存在：persist_document；未存在：split_chunks → persist_document
→ KnowledgeStore.index_document（锁内重新查重）
→ duplicate 或 Embedding + Chroma
```

目录导入先 `scan_directory`，再逐个调用 `ingest_document(parsed, category)` 执行同一张入库图；不重复解析、不直接绕过图写 Chroma。`--dry-run` 不执行入库图、不生成向量。

`IngestState` 只存在于本次调用。Chroma 持久化知识块、向量和 metadata，不保存整张状态工作单。

解析器统一返回 `ParsedDocument`。以后支持新格式时仍返回这个结构，后面的查重与切块代码就不需要修改。正文规范化后计算哈希，文件改名不会绕过去重；块 ID 由正文指纹和序号组成。

## 五、前端状态与 SSE

`KnowledgeConversationProvider` 是会话的唯一事实来源，左侧栏与聊天页通过同一个 Hook 读取它。

- `useState` 保存会影响画面的状态。
- `useRef` 保存 DOM、AbortController 等不要求触发渲染的句柄。
- `useMemo` 缓存派生值，`useCallback` 缓存函数引用。
- `useEffect` 同步网络、DOM 和 localStorage 等 React 外部系统。

一次 `reader.read()` 不等于一个 SSE 事件，所以前端先把字节解码到 `buffer`，再按空行拆出完整事件。token 先进入普通缓冲，每个动画帧最多更新一次 React，避免长回答导致高频重渲染。

生成期间使用纯文本，完成后再解析 Markdown。本地存储异常只返回 warning，不应让页面崩溃。

流式滚动单独读 `chatAutoScroll.js` → `useChatAutoScroll.js` → `Zhishiku.jsx`。前者是普通 JS 闭包控制器，中间的 Hook 在 DOM 更新后接入它，页面只提供消息容器与消息数组。每个 token 不再触发平滑滚动动画；向上阅读历史时暂停跟随，手动回到底部或发送新问题时恢复。具体仿写例子见代码教程 **7.3.1**。

## 六、认证与启动

登录成功后，后端签发带签名的 HttpOnly Cookie。`credentials: 'include'` 让浏览器自动携带它，前端 JavaScript 无法读取内容。`Depends(require_admin)` 会在上传或统计接口之前完成认证。

```text
python -m backend.run_api
→ 检查 8000 端口
→ Uvicorn 导入 backend.app:app
→ 创建 FastAPI 并 include_router
```

```text
npm run dev
→ Vite 加载 src/main.jsx
→ BrowserRouter
→ AppErrorBoundary
→ KnowledgeConversationProvider
→ App 根据路由渲染页面
```

本地启动时打开两个 PowerShell：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -m backend.run_api
```

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
npm run dev
```

## 七、自己写后端功能的模板

推荐把功能分为请求模型、业务服务、外部存储和 HTTP 接口四层：

```python
class CreateRequest(BaseModel):
    name: str

class ExampleService:
    def __init__(self, repository=default_repository):
        self.repository = repository

    def execute(self, name: str) -> dict:
        return self.repository.save(name.strip())

@router.post('/api/examples')
def create_example(payload: CreateRequest):
    return example_service.execute(payload.name)
```

把数据库、远程模型等依赖放进构造器，测试就能传 Fake。HTTP 层校验输入，服务层处理业务，存储层负责持久化。

写新函数时先明确单一职责、输入输出、异常策略和调用者。返回结构应该稳定，页面不应根据偶然的异常字符串猜测业务状态。

## 八、自己写 React 功能的原则

1. 组件只保留真正的状态，能计算出的值不要再复制一份。
2. 不在渲染期间直接请求网络或写存储；这类副作用放进事件处理器或 Effect。
3. 共享状态提升到共同 Provider，子组件通过 props 或 Hook 使用。
4. 请求同时维护 loading、成功和错误状态，并在 `finally` 中复位。
5. 组件卸载或切换任务时用 AbortController 取消旧请求。

一个最小请求组件通常这样组织：

```jsx
function ExamplePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const response = await fetch('/api/examples');
      if (!response.ok) throw new Error('加载失败');
      setItems(await response.json());
    } finally {
      setLoading(false);
    }
  }

  return <button onClick={load}>{loading ? '加载中' : '加载'}</button>;
}
```

## 九、怎样读和写测试

测试遵循 Arrange（准备）→ Act（执行）→ Assert（断言）。Fake 只实现生产代码真正调用的方法，不必复制完整第三方库。`monkeypatch` 临时替换环境变量或网络函数，`TestClient` 在内存中调用 FastAPI。

现有测试中的 Fake 隔离了真实模型和向量库，运行测试不会重新发送知识正文或修改正式数据。

先读 `test_documents_and_store.py` 的解析/查重，再读 `test_rag_and_api.py` 的引用/接口，最后读 `test_graphs.py` 的节点顺序、状态隔离、取消和并发竞争。后者用 `asyncio.run` 执行异步案例，用 `Barrier` 确保两个上传真的同时通过预检，而不是碰巧顺序执行。

```python
def test_example_saves_clean_name():
    # Arrange
    repository = FakeRepository()
    service = ExampleService(repository)

    # Act
    result = service.execute('  Amazon  ')

    # Assert
    assert result['name'] == 'Amazon'
```

运行测试与静态检查：

```powershell
D:\python\python.exe -B -m pytest backend\zhishiku\tests -q
npm run test:frontend
npm run lint
npm run build
```

## 十、推荐断点

- 提问入口：`api.py` 的 `chat_stream`。
- 改写结果：`RagService.rewrite_question` 结束处。
- 召回与精排：`retrieve_candidates`、`rerank_documents`。
- 分支选择：`route_answer`、`route_duplicate`。
- 模型流和最终合并：`agenerate`、`astream_events`。
- 响应关闭：`ClosingStreamingResponse.__call__`。
- 引用编号：`prepare_context` 循环内部。
- 文件入口：`KnowledgeBaseService.upload_file`。
- 向量写入：`KnowledgeStore.index_document` 的 `add_documents` 前。
- 前端流式入口：`Zhishiku.jsx` 的 `runQuestion`。
- SSE 分包：`consumeEvent`。
- 会话变化：Context 的 `updateConversation`。

调试时不要打印 API Key、管理员密码、完整 Cookie 或用户上传的全部正文。

## 十一、常见错误

- 把 `ServiceState` 或 `IngestState` 当成数据库记录。
- 入库和检索更换不同 Embedding 模型，导致向量距离失去意义。
- 按文件名去重，使改名后的相同正文再次入库。
- 把 Rerank 分数当成跨问题通用的固定阈值。
- 假设一次网络读取恰好等于一个 SSE 事件。
- 每个 token 都写 localStorage，造成高频序列化和容量问题。
- 只设防抖计时器却不在 `pagehide` / 页面转入后台时保存：立即刷新可能丢失最后一段。浏览器崩溃、系统强杀仍无法保证执行收尾。
- 在函数默认参数或调用方先读取 `localStorage`：属性读取本身也可能抛权限错误，应放进存储模块的 `try` 内。
- 在前端保存管理员密码或可读 token。
- 修改 `.env` 后忘记重启已经导入配置的后端。

## 十二、术语表

- **RAG**：先检索资料，再依据资料生成答案。
- **LangGraph**：按图中节点、边和条件分支调度业务的框架；不等于自主 Agent。
- **Reducer**：决定同名状态更新如何合并的规则；本项目字段默认覆盖，不给 history 累加。
- **checkpointer**：可选的图状态检查点存储；本项目没有开启，也不能把前端 UUID 当作服务器历史授权。
- **Embedding**：把文本转换为可以比较语义距离的向量。
- **Chroma**：保存知识块、向量和 metadata 的向量数据库。
- **Rerank**：根据问题重新排列初次召回的候选内容。
- **SSE**：服务器通过持续 HTTP 响应单向推送事件。
- **Context**：React 组件树中的共享状态通道。
- **Cookie**：浏览器随站点请求自动携带的数据；本项目用于管理员会话。
- **依赖注入**：从外部传入模型或数据库，使实现可替换、可测试。
- **单例**：模块内共享的一个实例；创建实例不等于执行其业务方法。
- **幂等**：同一操作重复执行不会不断产生额外副作用。

## 十三、补做浏览器验收记录（2026-09-14）

本节是验收记录，不是第四份教程。学习顺序不变；这里说明哪些行为实际检查过，以及测试时发现并补修了什么。

### 测试范围与数据保护

- 使用独立 Playwright 浏览器上下文，不读取日常浏览器的账号、Cookie 或聊天历史。
- 真实问答连接本机正式后端，使用现有 Chroma 和 DashScope；测试前后均为 **307 份文档、2998 个知识块**，健康状态 `ok`，`qwen3-rerank` 可用。
- 上传使用临时端口上的真实 FastAPI 路由、认证、LangGraph 入库图、文件解析和 `KnowledgeStore`，但将底层 Chroma 替换成内存测试对象。因此确实验证了页面到接口、解析、去重与写入逻辑，不会向正式库加入测试资料，也不会消耗上传 Embedding 额度。
- 管理员测试使用临时进程内的测试账号，不修改正式 `.env` 或真实管理员凭据。页面故障注入也只发生在独立测试上下文。

### 结果

| 场景 | 实际结果 |
| --- | --- |
| 真实长回答、引用、追问 | FBA 费用回答逐步显示；完成后表格正常，5 条来源可展开，引用编号能对应；“日本站呢？”携带最近历史并得到日本站相关回答 |
| 停止与立即刷新 | 修复后真实回答停止时的 36 字原文，在立即刷新后完整保留并显示“已停止生成” |
| 大量流式片段与不完整 Markdown | 离线服务通过真实图/SSE 发出 259 个 token 事件；生成中为纯文本，完成后表格和代码块正常；`done.answer` 等于全部增量拼接，来源先于答案显示 |
| 失败重试与会话隔离 | 模拟一次生成失败后“重新生成”成功，用户问题没有重复；切换/删除生成中的测试会话后，旧回答不写入新会话；后端并发计数最终归零 |
| 本地存储异常 | `QuotaExceededError` 和读取 `localStorage` 属性即抛出的 `SecurityError` 均不阻断聊天，显示非阻断保存提示 |
| 两层错误边界 | 故意让测试子组件渲染抛错：消息边界退回原始文字，页面边界显示“重新加载”；其他聊天界面仍可用。此项预期产生测试异常日志，不属于真实问答故障 |
| 侧栏与响应式 | 会话面板在知识库按钮下面展开/收起；整栏 280px/68px 切换并刷新恢复；最多 20 个会话，长列表独立滚动，账户区域仍在屏幕内；820px 平板和 390px 手机无整页水平溢出；手机默认关抽屉，Esc、遮罩、选择会话均可关闭 |
| 键盘 | Enter 发送，Shift+Enter 保留换行 |
| 管理登录 | 真实登录接口设置 8 小时 `HttpOnly + SameSite=Strict` Cookie，本地 `Secure=false`；页面 JavaScript 读不到它，刷新仍由后端验证登录态 |
| 多文件与拖拽上传 | 初始队列 5 个文件：TXT、DOCX、PDF 共 3 份入库，1 份重复跳过，1 份损坏 DOCX 明确报错；错误后继续处理剩余文件。额外拖拽 TXT 成功，临时库最终为 4 文档/4 知识块；页面显示真实上传进度和分类统计 |
| 401 与退出 | 测试 Cookie 失效后上传返回 401，页面回到登录并提示过期；该文件未入库。重新登录正常；退出删除 Cookie，受保护统计接口返回 401 |

截图：[真实回答与来源](verification/2026-09-14/02-real-completed.png)、[真实停止后刷新](verification/2026-09-14/09-real-stop-restored.png)、[手机抽屉](verification/2026-09-14/05-mobile-drawer.png)、[手机聊天](verification/2026-09-14/06-mobile-chat.png)、[隔离上传结果](verification/2026-09-14/08-admin-upload-results.png)。截图中的测试会话/测试文件不属于正式知识库。

### 这次补修的两个问题，建议结合源码学习

1. **防抖还没保存就刷新，最后的文字丢失**：在 `KnowledgeConversationContext.jsx` 增加离开/转入后台的即时保存；在 `knowledgeConversationStore.js` 将恢复的半截流式答案标记为已停止。注意，刷新不会接回旧 SSE。
2. **取存储对象时就被拒绝，来不及捕获异常**：把 `localStorage` 属性读取移到存储函数内部的 `try` 中；存储不存在时返回失败提示，不再跳过写入却返回成功。

两处修复均补了大白话注释，并同步到开发教程第 11 节、代码教程第 7 课。不要把“刷新时尽量保存”理解成“永远不会丢失”：系统强杀、浏览器崩溃、存储权限禁止时仍不能保证落盘；停止本地接收也不等于模型供应商瞬间停止计算或计费。

### 回归检查

- Python 编译：12 个业务/入口文件通过。
- `D:\python\python.exe -B -m pytest backend\zhishiku\tests -q`：28 项通过；仍有 2 条上游依赖弃用警告，本次未升级依赖。
- `npm run test:frontend`：6 项通过，包括新增的属性权限、缺失存储和半截答案恢复用例。
- `npm run lint`、`npm run build`：通过。
- 从代码教程原文提取第 7 课存储模块及第 10 课配套测试执行：2 项测试通过，另验证属性权限拒绝的读取/写入保护。
- `/tuijian/agentcall` 仍在统一应用的 OpenAPI 中；本次没有修改推荐业务逻辑。

以上是功能与交互验收，不等于所有问题的答案内容都已完成业务专家审核，也不代表移动真机、全部浏览器或公网代理配置均已验证。

## 十四、流式滚动抖动专项修复（2026-09-14）

用户继续反馈“生成时频繁抖动”后，专项检查发现：旧版每次消息更新都会重新启动平滑滚动。先前的功能验收证明按钮、接口和回答可用，但没有量化滚动动画是否重复，这是此次补充的检查重点。

- 修复前：模拟 100 个文本片段，观察到 103 次 `scrollIntoView` 调用；连续动画使滚动明显追不上新内容。
- 修复后：同场景不再调用 `scrollIntoView`，只即时调整消息容器。桌面采样中标题位置、输入框位置和消息宽度均保持固定，用户上滑后的 scrollTop 不随新 token 改变，回到底部后恢复跟随。
- 手机 390px 宽度：180 个片段完成，手动阅读与展开来源均保持位置，结束后的 Markdown 表格正常；底部误差小于 1px，无整页横向溢出。
- 真实知识库长回答：采集 3703 个绘制帧位置，标题始终为 0px、输入区始终为 661px，跟随底部误差小于 1px。帧数是本次浏览器采样数量，不是模型 token 数量。
- 新增 8 项滚动控制器测试，连同原存储测试共 14 项前端测试通过；后端 28 项测试、lint 和生产构建通过。新离线教学示例通过 JSX 编译检查，所用 Hook 与控制器已在真实页面运行。

源码顺序：`chatAutoScroll.js` → `useChatAutoScroll.js` → `Zhishiku.jsx` / `Zhishiku.css` → `chatAutoScroll.test.js`。代码教程 **7.3.1** 有完整离线练习，开发教程 **11.7** 解释设计原因。没有修改 HTTP/SSE 协议、模型配置或知识库数据，正式库仍是 307 份文档 / 2998 个知识块。

截图：[真实回答完成](verification/2026-09-14-scroll/real-completed.png)、[手机端表格完成](verification/2026-09-14-scroll/mobile-completed.png)。截图展示最终布局，动态稳定性由上述逐帧位置和交互检查确认；本次仍不代表所有浏览器或移动真机都已测试。
