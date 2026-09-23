# 跨境电商知识库 RAG 开发者教程

> 面向本项目的系统学习文档。目标不是只让你“能运行”，而是让你能够解释、调试、修改、测试和部署这套知识库。

## 你最终要具备的能力

学完后，你应该能够：

1. 说清楚一条用户问题如何经过前端、FastAPI、检索、Rerank 和大模型。
2. 说清楚一份 DOCX/PDF/TXT 如何解析、去重、切块、向量化并进入 Chroma。
3. 看懂 `ServiceState`、`IngestState`、Pydantic Model、React Context 和 SSE。
4. 自己增加接口、文件格式、状态字段、页面功能和自动测试。
5. 根据错误发生的位置判断是前端、接口、模型、Rerank 还是向量库问题。
6. 把项目部署到云服务器，并保证知识库数据可以持久保存和恢复。

## 文档导航

- [1. 五分钟启动](#1-五分钟启动)
- [2. 先建立完整架构认识](#2-先建立完整架构认识)
- [3. 项目目录与职责](#3-项目目录与职责)
- [4. Python 基础知识](#4-python-基础知识)
- [5. 状态对象怎么理解](#5-状态对象怎么理解)
- [6. RAG 问答流程](#6-rag-问答流程)
- [7. 知识文件入库流程](#7-知识文件入库流程)
- [8. Embedding、Chroma 与 Rerank](#8-embeddingchroma-与-rerank)
- [9. FastAPI 与接口](#9-fastapi-与接口)
- [10. SSE 流式回答](#10-sse-流式回答)
- [11. React 前端](#11-react-前端)
- [12. 管理员认证与安全](#12-管理员认证与安全)
- [13. 自动测试](#13-自动测试)
- [14. 常见扩展方法](#14-常见扩展方法)
- [15. 云服务器与数据持久化](#15-云服务器与数据持久化)
- [16. 故障排查](#16-故障排查)
- [17. 学习练习](#17-学习练习)
- [18. 术语表](#18-术语表)

---

## 1. 五分钟启动

### 1.1 安装后端依赖

打开 PowerShell：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -m pip install -r backend\zhishiku\requirements.txt
D:\python\python.exe -m pip check
```

### 1.2 安装前端依赖

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
npm install
```

### 1.3 配置环境变量

项目根目录使用 `.env`，字段参考 `.env.example`。不要把真实 `.env` 提交到 Git 或发送给别人。

关键配置：

| 配置 | 用途 | 注意事项 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 聊天、Embedding、Rerank 的访问密钥 | 不能写进前端 |
| `QWEN_MODEL` | 最终回答模型 | 当前默认 `qwen-max` |
| `QWEN_REWRITE_MODEL` | 历史追问改写模型 | 当前默认 `qwen-flash` |
| `DASHSCOPE_EMBEDDING_MODEL` | 入库与查询的向量模型 | 更换后必须重新入库 |
| `RERANK_ENABLED` | 是否启用精排 | 失败时自动降级 |
| `RERANK_MODEL` | 精排模型 | 当前使用 `qwen3-rerank` |
| `DASHSCOPE_RERANK_BASE_URL` | 带 Workspace ID 的基础地址 | 程序会追加 `/reranks` |
| `ADMIN_USERNAME` | 管理员账号 | 不在前端硬编码 |
| `ADMIN_PASSWORD_HASH` | bcrypt 密码哈希 | 不能填写明文 |
| `SESSION_SECRET` | Cookie 签名密钥 | 至少 32 字符 |
| `COOKIE_SECURE` | 是否只通过 HTTPS 发送 Cookie | 本地 false，生产 true |
| `FRONTEND_ORIGINS` | 允许访问后端的前端来源 | 禁止使用 `*` |

修改 `.env` 后要重启后端，因为部分配置会在 Python 模块第一次导入时读取。

### 1.4 启动后端

PowerShell 窗口一：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -m backend.run_api
```

### 1.5 启动前端

PowerShell 窗口二：

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
npm run dev
```

### 1.6 常用地址

| 页面或接口 | 地址 |
| --- | --- |
| 知识库聊天 | `http://localhost:5173/zhishiku` |
| 管理后台 | `http://localhost:5173/admin` |
| Swagger | `http://127.0.0.1:8000/docs` |
| 健康检查 | `http://127.0.0.1:8000/api/knowledge/health` |

### 1.7 判断是否启动成功

浏览器打开健康检查，应该得到类似：

```json
{
  "status": "ok",
  "document_count": 307,
  "chunk_count": 1234,
  "rerank": {
    "enabled": true,
    "available": true,
    "degraded": false,
    "model": "qwen3-rerank",
    "reason": null
  }
}
```

`chunk_count` 以你当前 Chroma 的真实统计为准。`degraded` 不表示完全不可用，它表示本次只能依赖向量排序。

---

## 2. 先建立完整架构认识

本项目是 **LangGraph 编排的 RAG 工作流**，不是自主规划的通用 Agent。问题改写、检索、精排、生成由图中的边调度；无资料走独立分支。上传与批量导入也执行同一张入库图。LangGraph 不会自动让模型选择工具，也不会自动开启服务器历史存储。

### 2.1 问答数据流

```text
浏览器输入问题
  → 前端提交最近 10 条历史
  → FastAPI 校验请求
  → 改写含代词或省略信息的追问
  → Chroma 召回 12 个候选块
  → qwen3-rerank 精排 5 个块
  → 为资料分配 [资料 n] 编号
  → Qwen 仅依据资料生成答案
  → SSE 把状态、来源和 token 发回页面
```

### 2.2 入库数据流

```text
管理员上传文件
  → Cookie 认证
  → 校验类型与大小
  → DOCX/PDF/TXT 解析
  → 正文规范化
  → SHA-256 内容去重
  → 按章节重叠切块
  → DashScope Embedding
  → Chroma 保存向量、正文和 metadata
```

### 2.3 前后端职责边界

| 前端负责 | 后端负责 |
| --- | --- |
| 输入框、消息展示、停止按钮 | 请求校验、限流与认证 |
| 浏览器本地会话 | 历史问题改写 |
| SSE 解析和 token 追加 | Chroma 检索与 Rerank |
| 来源卡片和 Markdown | 系统提示词与答案生成 |
| 上传队列和进度 | 文件解析、去重和入库 |

匿名会话只存在浏览器 localStorage。服务器不会根据 `conversation_id` 查询永久历史；每次请求所需的最近历史由前端主动提交。

---

## 3. 项目目录与职责

### 3.1 后端

| 文件 | 作用 | 建议阅读重点 |
| --- | --- | --- |
| `backend/run_api.py` | 后端启动器 | 端口检查、`uvicorn.run` |
| `backend/app.py` | 统一 FastAPI 应用 | CORS、`include_router` |
| `backend/_common.py` | 模型工厂和环境配置 | `.env`、Embedding/Chat 模型 |
| `backend/zhishiku/config_data.py` | 知识库常量 | 切块、召回、路径 |
| `backend/zhishiku/zhishiku.py` | RAG 问答服务 | 状态、改写、检索、生成 |
| `backend/zhishiku/vector_stories.py` | Chroma 访问层 | 入库、召回、统计 |
| `backend/zhishiku/reranker.py` | 精排封装 | 请求协议、降级 |
| `backend/zhishiku/document_loader.py` | 文件解析和切块 | dataclass、生成器、哈希 |
| `backend/zhishiku/agent.py` | 单文件入库编排 | `IngestState` |
| `backend/zhishiku/auth.py` | 管理认证 | Cookie、bcrypt、限流 |
| `backend/zhishiku/api.py` | HTTP 接口 | Pydantic、Depends、SSE |
| `backend/zhishiku/import_documents.py` | 批量导入命令 | 预扫描、报告、退出码 |

### 3.2 前端

| 文件 | 作用 |
| --- | --- |
| `src/main.jsx` | React 浏览器入口和 Provider 包裹顺序 |
| `src/routers/index.jsx` | URL 与页面组件的映射 |
| `src/App.jsx` | 全局导航、折叠和知识库历史列表 |
| `src/AppErrorBoundary.jsx` | 页面级与消息级错误兜底 |
| `KnowledgeConversationContext.jsx` | 会话共享状态和取消生成 |
| `knowledgeConversationStore.js` | localStorage 清洗、裁剪与安全持久化 |
| `Zhishiku.jsx` | 提问、SSE 解析、消息和来源展示 |
| `AdminDashboard.jsx` | 管理登录、统计与文件上传 |

`runtime`、`dist`、`node_modules` 和 `__pycache__` 不是学习业务逻辑的入口。`runtime/chroma` 是数据库文件，不能当普通文本手工编辑。

---

## 4. Python 基础知识

### 4.1 模块导入

第一次执行 `import backend.zhishiku.api` 时，Python 会从上到下执行顶层语句：导入依赖、建立类和函数、创建 `router`、`rag_service` 等单例。函数体不会因为被定义就执行。

模块被第二次导入时通常从 `sys.modules` 复用，因此模块级环境变量不会自动刷新。这就是修改 `.env` 后要重启的原因。

### 4.2 class、实例和 self

```python
class KnowledgeStore:
    def __init__(self):
        self._store = None

store = KnowledgeStore()
```

- `KnowledgeStore` 是类，描述一类对象具有哪些数据和方法。
- `KnowledgeStore()` 创建实例并调用 `__init__`。
- `self` 指当前实例。
- `self._store` 属于这个实例；前导下划线表示内部使用约定。

类适合保存一组相关行为和需要共享的状态。单纯输入得到输出、不需要保存状态的逻辑通常写成普通函数更清晰。

### 4.3 类型标注

```python
def retrieve(query: str, k: int) -> list[Document]:
    ...
```

类型标注帮助编辑器和读者理解契约，但 Python 默认不会自动阻止错误类型。FastAPI/Pydantic 会在 HTTP 边界进行运行时校验。

### 4.4 TypedDict

`TypedDict` 描述普通字典允许有哪些键：

```python
class ChatHistoryItem(TypedDict):
    role: str
    content: str
```

它不会创建数据库表，不会自动实例化，也不会自动验证网络请求。适合描述在多个业务步骤间传递的状态字典。

`NotRequired[T]` 表示键可能尚未产生。例如上传刚开始时还没有 `chunks`，解析完成后才补上。

### 4.5 dataclass

`ParsedDocument` 和 `KnowledgeChunk` 使用 `@dataclass(slots=True)`。dataclass 自动生成初始化方法，适合字段明确的数据载体；`slots=True` 可以防止临时添加拼错的属性，并降低内存开销。

### 4.6 生成器与 yield

```python
from collections.abc import Iterator


def text_parts(text: str) -> Iterator[str]:
    # 调用时返回生成器；for 每次取值才执行到下一个 yield。
    for offset in range(0, len(text), 2):
        yield text[offset:offset + 2]


print(list(text_parts("逐块输出")))  # ['逐块', '输出']；不联网。
```

这是生成器语法演示，不是假装调用项目中已删除的旧方法。实际模型的异步增量由 `agenerate` 消费，图事件由 `astream_events` 产出。

普通函数用 `return` 一次返回；生成器用 `yield` 分批产出。调用生成器只得到迭代器，`for` 每取一次才继续执行。这是后端流式回答的基础。

### 4.7 装饰器

`@router.post(...)` 把函数登记为 HTTP 接口；`@property` 让方法以字段形式访问；`@field_validator` 把方法登记为 Pydantic 字段校验器。装饰器本质上是在定义完成后包装或登记函数。

### 4.8 异常与 finally

`try/except` 负责把预期异常转换为稳定结果；`finally` 无论成功还是失败都会运行。本项目用 `finally` 释放聊天并发名额、关闭上传文件和复位前端 loading。

不要使用空的 `except Exception: pass`。如果确实要降级，应记录安全状态并返回明确的降级结果。

---

## 5. 状态对象怎么理解

### 5.1 ServiceState

`ServiceState` 是一轮问答的临时工作单：

| 字段 | 谁写入 | 谁读取 | 内容 | 是否持久化 |
| --- | --- | --- | --- | --- |
| `question` | API/初始状态 | 改写、生成 | 用户原问题 | 否 |
| `history` | 前端请求 | 改写、生成 | 最近最多 10 条消息 | 否 |
| `retrieval_query` | 改写步骤 | 检索、精排 | 可独立理解的问题 | 否 |
| `candidates` | Chroma 检索 | Rerank | 最多 12 个候选 | 否 |
| `documents` | Rerank | 上下文整理 | 最多 5 个最终资料块 | 否 |
| `context` | 上下文整理 | 回答模型 | 带 `[资料 n]` 的文本 | 否 |
| `sources` | 上下文整理 | API/页面 | 安全来源卡片 | 浏览器随消息保存 |
| `answer` | generate／insufficient_evidence | JSON API／SSE done | 最终 Markdown | 浏览器随消息保存 |
| `rerank_used` | 精排步骤 | API/页面 | 本轮是否成功精排 | 浏览器消息字段 |
| `status` | 各步骤 | SSE/页面 | 当前阶段提示 | 否 |

`question` 和 `retrieval_query` 必须分开：前者决定要回答什么，后者只为检索服务。`candidates` 与 `documents` 分开，才能判断质量问题发生在初次召回还是精排。

### 5.2 IngestState

| 字段 | 含义 | 生命周期 |
| --- | --- | --- |
| `file_data` | 可选；上传入口提供原始 bytes | 本次图执行；预解析入口不需要 |
| `filename` | 安全文件名 | 解析和 metadata |
| `category` | 业务分类 | 写入 metadata |
| `parsed_document` | 统一后的文档对象 | 解析节点产生，或由目录预扫描提供 |
| `content_hash` | 规范化正文 SHA-256 | fingerprint 写，check_duplicate 读 |
| `is_duplicate` | 预检查是否命中 | 条件边读取；不是最终数据库结论 |
| `chunks` | 待向量化知识块 | split_chunks 写，persist_document 读 |
| `result` | indexed/duplicate 等结果 | 返回 API |
| `status` | 当前阶段说明 | 本次调用 |

当前入库是 `StateGraph(IngestState)`：`prepare_document → fingerprint → check_duplicate`，未重复时经 `split_chunks`，最终统一进入 `persist_document`。节点返回局部更新，而不是原地修改输入。图的预检只省去不必要的切块；数据库入口仍在同一把锁内重新查重并写入。

### 5.3 LangGraph 如何执行和合并状态

节点是普通函数，但它的调用方变成了图调度器。下面是完整、离线的最小示例，保存为 `mini_graph.py`，执行 `D:\python\python.exe mini_graph.py`：

```python
from typing import TypedDict
from langgraph.graph import START, END, StateGraph


class State(TypedDict):
    # 调用者写原问题，rewrite 读取；全程仅属于本次 invoke。
    question: str
    # rewrite 写检索问题，下一节点/调用者读取。
    retrieval_query: str


def rewrite(state: State):
    # 返回局部更新；question 未返回不会丢失，不需要 state.update。
    return {"retrieval_query": state["question"].strip()}


builder = StateGraph(State)  # State 是契约，不是某次请求的值。
builder.add_node("rewrite", rewrite)  # 传函数，不写 rewrite()。
builder.add_edge(START, "rewrite")
builder.add_edge("rewrite", END)
graph = builder.compile()  # 到这里尚未运行 rewrite。

original = {"question": " VAT ", "retrieval_query": ""}
result = graph.invoke(original)  # 现在调度器才调用 rewrite。
assert original["retrieval_query"] == ""  # 原始输入未被原地修改。
assert result == {"question": " VAT ", "retrieval_query": "VAT"}
print(result["retrieval_query"])  # 预期输出 VAT。
```

本项目全部状态字段采用默认的“同名覆盖，未返回保留”。`TypedDict` 不生成默认值，也不做 HTTP 运行时校验；Pydantic 与 `initial_state` 分别承担这两项职责。

`Annotated[list, reducer]` 可指定累加规则，但没有需要时不应添加。尤其 history 已由浏览器提供完整快照，再累加容易重复消息。条件边只返回分支名称，节点才返回状态更新；不要混淆这两个返回值。

图在服务构造时编译并复用，但每次执行有独立工作单。不启用 checkpointer，所以 `conversation_id` 不会自动恢复上次图状态，也不需要恢复旧 SQLite 代码。

### 5.4 状态设计方法

用大白话记：State 是“本次工作单”，Config 是“本次运行开关”，事件是“发给外面
的通知”，Chroma 才是“长期保存知识的地方”。它们解决不同问题，不能看到都有
state/context 等名字就认为属于同一份数据。

`NotRequired[T]` 表示某个键可能尚不存在；`T | None` 则表示键对应的值可为 None。
入库时预解析入口没有 file_data，重复分支没有 chunks，这正是使用 NotRequired 的
原因。自己增加节点时必须先确认前面的分支会不会产生你准备读取的键。

自己设计状态时：

1. 区分原始输入、中间结果和最终输出。
2. 每个字段只表达一种含义。
3. 写明谁产生、谁消费、何时失效。
4. 临时状态不要误写入数据库。
5. 调试需要区分的阶段不要复用同一个字段覆盖。

---

## 6. RAG 问答流程

RAG 是 Retrieval-Augmented Generation，即“检索增强生成”。模型回答前先从自己的资料库检索证据，再把问题和证据一起交给生成模型。

### 6.1 为什么需要 RAG

大模型本身可能不知道你的内部资料，也可能把旧知识或猜测说得很肯定。RAG 的价值是：

- 把企业自己的文档提供给模型。
- 让回答可以显示具体来源。
- 更新知识时主要更新文档，不一定要重新训练模型。
- 资料不足时可以明确拒绝编造。

RAG 不能自动保证所有答案正确。切块、召回、精排、资料时效和提示词都会影响结果。

### 6.2 initial_state

`initial_state` 创建字段齐全的工作单。即使某一步还没有结果，也先使用空列表、空字符串或 `False`，后续代码就不容易因缺键出现 `KeyError`。

### 6.3 rewrite_question

有历史消息时，使用较轻量的模型把追问改成独立问题。例如：

```text
历史：美国站品牌备案需要什么？
追问：日本站呢？
改写：亚马逊日本站品牌备案需要什么材料？
```

改写只改变检索词，不覆盖用户原问题。没有历史就不额外调用模型；调用失败、返回空文本或过长文本时回退原问题。

### 6.4 retrieve_candidates 与 rerank_documents

第一阶段使用 Embedding 相似度快速检索 12 条。第二阶段让 Rerank 同时阅读问题和候选内容，再选出 5 条。

两阶段组合的原因：全库逐条 Rerank 成本高；只用向量距离又可能把主题相似但不能直接回答的段落排得过高。

### 6.5 prepare_context

最终资料被格式化为：

```text
[资料 1]
标题：日本站品牌备案
分类：品牌营销
发布日期：2025-01-02
正文：
...
```

同一个编号也出现在前端来源卡片中。这样回答里的 `[资料 1]` 才能定位到真实文件。

浏览器只收到安全文件名、标题、分类、日期和短摘要，不会拿到服务器绝对路径、密钥或完整正文指纹。

### 6.6 SYSTEM_PROMPT

系统提示词要求模型：只依据资料、事实结论引用来源、资料不足时说明不足、区分国家和站点、提醒时效，并把文档内容视为不可信资料而非系统指令。

文档可能含有“忽略规则”等文字。如果不声明文档只是资料，恶意文档可能形成提示注入。系统提示的优先级必须高于检索资料。

### 6.7 ask 与 astream_events

难点先记两句：LangGraph 可以直接用普通函数当节点；这里用
`RunnableLambda(generate, afunc=agenerate)` 是为同一节点配置同步与异步实现，
不是因为普通函数不能用，也不会让这两个函数都执行一次。

`agenerate` 是协程，框架等待它返回最终字典；`astream_events` 是异步生成器，
API 用 async for 逐次取事件。`get_stream_writer()({...})` 先取得当前图的发送函数，
再把数据传给该函数；只有图运行期间才能用，staticmethod 并不取消这个运行条件。

- `ask` 使用 `self.graph.invoke(initial_state)`，生成节点调用同步模型，返回完整状态；API 挑选公开字段。
- `astream_events` 使用同一张图的 `astream(stream_mode=["custom", "updates"], version="v2")`。`generate` 节点的异步实现 `agenerate` 显式构造 `streaming=True` 模型，消费 `model.astream`。
- `custom` 发送 status/sources/token；`updates` 提供末节点的完整答案，再构造 done。不订阅 messages，避免输出改写模型的中间文本。
- `RunnableLambda(generate, afunc=agenerate)` 让同一节点在同步/异步运行时使用对应实现；节点顺序只有 `_build_graph` 这一份。
- 没有资料时经条件边进入 `insufficient_evidence`，不调用回答模型。`prepare`／`stream_answer` 的旧手动流程已删除。

---

## 7. 知识文件入库流程

### 7.1 文件校验

`parse_document` 是统一入口：

1. 使用 `Path(filename).name` 去掉客户端路径。
2. 只允许 `.docx`、`.pdf`、`.txt`。
3. 拒绝空文件和超过 25 MiB 的文件。
4. 根据后缀分派到具体解析器。

浏览器的 `accept` 只能帮助用户选择文件，不能当安全校验。真正校验必须放在后端。

### 7.2 DOCX

DOCX 本质是 ZIP + XML。程序先统计解压后大小，降低压缩炸弹风险；然后按 XML body 原始顺序遍历段落与表格。

不能简单地把 `document.paragraphs` 和 `document.tables` 拼接，因为它们是两份列表，会破坏“段落—表格—段落”的原顺序。

标题样式和常见中文编号用于识别章节。每遇到新标题就把之前正文保存为一个 section。

### 7.3 PDF

PDF 按页提取文本，并把页码作为章节名。扫描版 PDF 只有图片、没有文字层，当前项目明确报错而不做 OCR。

如果以后增加 OCR，应作为独立、可选且受限的步骤，并对图片大小、页数、成本和超时设置限制。

### 7.4 TXT

依次尝试 UTF-8 BOM、UTF-8 和 GB18030。全部失败才返回编码错误。读取后仍要经过统一正文清洗。

### 7.5 normalize_text

规范化会统一换行、移除 BOM/零宽字符、压缩行内空格并限制连续空行。它同时服务去重和切块，所以不能随意改变；修改规范化规则可能让旧文档产生新哈希。

### 7.6 content_hash

SHA-256 用于判断规范化正文是否相同。它是内容指纹，不是加密文件，也不是用户密码哈希。

文档标题会参与当前正文语义，避免两个正文相同但站点标题不同的文件被错误合并。

### 7.7 split_document

默认目标约 800 字符、相邻重叠 120 字符。分隔器优先使用段落和句子边界，最后才按字符兜底。

每块增加文档标题和章节标题前缀，因为向量检索时知识块会脱离原文单独出现。前缀帮助模型判断站点与主题。

重叠能保护切块边界的上下文，但过大会增加重复存储和 Embedding token。调整后应该用真实问题重新评估召回效果。

### 7.8 入库结果

- `indexed`：新正文已向量化并写入。
- `duplicate`：Chroma 已有相同 `content_hash`，不重复调用 Embedding。
- `error`：上层把解析或外部服务异常转换为可展示结果。

---

## 8. Embedding、Chroma 与 Rerank

### 8.1 Embedding 是什么

Embedding 模型把文本变成一组数字。语义接近的文本在向量空间中距离通常更近，因此查询也转换为向量后，就能寻找相似知识块。

入库和查询必须使用同一个 Embedding 模型。已经用模型 A 建好的向量库，不能直接用模型 B 查询；更换模型后应备份并重新入库。

### 8.2 Chroma 保存什么

每个知识块包含：

- `id`：`content_hash:chunk_index`。
- `page_content`：带标题和章节前缀的文本。
- 向量：Embedding 结果。
- metadata：`source`、`title`、`section`、`category`、`published_at`、`content_hash`、`chunk_index`、`uploaded_at`。

Chroma 是知识数据的唯一事实来源。单独维护一个哈希文本文件容易在写入失败、恢复备份或删除数据后与数据库不一致。

### 8.3 延迟初始化

`KnowledgeStore.store` 使用 `@property` 在第一次真正访问时创建 Chroma 客户端。这样仅仅导入 FastAPI 或查看帮助时不会立即要求模型配置。

### 8.4 锁与并发

`index_document` 把“查重 + 写入”放在同一把线程锁内，避免一个进程中的两个上传请求同时看到不存在并重复写入。

这把锁只保护单 Python 进程。将来使用多个 Uvicorn worker 时，需要数据库唯一约束、集中任务队列或跨进程锁。

### 8.5 向量距离

Chroma 当前返回的是距离，通常越小越相似。这个值保存在临时 `_vector_distance` metadata 中，仅用于本次请求调试，不应设置跨问题固定阈值。

### 8.6 Rerank 协议与降级

Rerank 请求地址是基础 URL 后追加 `/reranks`，JSON 顶层包含 `model`、`query`、`documents`、`top_n` 和 `instruct`。

远程结果通过候选数组下标映射回 `Document`。代码必须验证下标类型与范围，不能直接信任外部响应。

缺配置、超时、限流、非法响应都会返回向量排序前 5 条和 `False`。降级的原则是：降低质量但保持服务可用，同时通过 health 和响应标志公开状态。

---

## 9. FastAPI 与接口

### 9.1 APIRouter 和统一应用

`backend/zhishiku/api.py` 创建 `APIRouter`，只维护知识库相关路径。`backend/app.py` 创建唯一 `FastAPI`，再用 `include_router` 合并知识库和产品推荐接口。

好处是业务模块可以分开维护，但部署时只有一个后端地址和一个 Swagger。

### 9.2 Pydantic 请求模型

`ChatRequest` 在业务逻辑之前校验：

- `conversation_id` 必须是 UUID。
- `question` 去掉首尾空白后必须非空，最长 2,000 字符。
- `history` 最多 10 条。
- 历史 `role` 只能是 `user` 或 `assistant`，不能提交 `system`。
- `extra='forbid'` 拒绝未声明字段。

验证失败时 FastAPI 自动返回 422，RAG 服务不会运行。

### 9.3 普通问答

`POST /api/knowledge/chat`

请求：

```json
{
  "conversation_id": "018fd17f-6448-7c65-a90e-3f35e756bd61",
  "question": "日本站品牌备案需要什么材料？",
  "history": [
    {"role": "user", "content": "美国站品牌备案怎么办？"},
    {"role": "assistant", "content": "需要准备商标和品牌信息。"}
  ]
}
```

成功响应：

```json
{
  "conversation_id": "018fd17f-6448-7c65-a90e-3f35e756bd61",
  "answer": "日本站应先……[资料 1]",
  "sources": [
    {
      "id": 1,
      "source": "日本站品牌备案.docx",
      "title": "日本站品牌备案",
      "category": "品牌营销",
      "published_at": "2025-01-02",
      "excerpt": "文档摘要……",
      "rerank_score": 0.93
    }
  ],
  "rerank_used": true
}
```

PowerShell 调用：

```powershell
$body = @{
  conversation_id = [guid]::NewGuid().ToString()
  question = '日本站品牌备案需要什么材料？'
  history = @()
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8000/api/knowledge/chat' `
  -Method Post `
  -ContentType 'application/json' `
  -Body $body
```

### 9.4 流式问答

`POST /api/knowledge/chat/stream` 使用相同 JSON，但返回 `text/event-stream`。浏览器聊天页使用这个接口。

### 9.5 健康检查

`GET /api/knowledge/health` 不需要管理员登录，返回文档数、知识块数和 Rerank 状态，但不暴露绝对路径或密钥。

状态含义：

- `ok`：向量库和 Rerank 可用。
- `degraded`：向量库可用，但 Rerank 关闭、缺配置或最近失败。
- `unavailable`：统计向量库时发生异常。

### 9.6 管理员接口

| 方法与路径 | 请求 | 成功结果 | 常见错误 |
| --- | --- | --- | --- |
| `POST /api/admin/login` | JSON 账号密码 | 设置 8 小时 Cookie | 401、429、503 |
| `GET /api/admin/session` | 自动携带 Cookie | 当前用户名 | 401 |
| `POST /api/admin/logout` | 自动携带 Cookie | 删除 Cookie | 401 |
| `POST /api/admin/knowledge/files` | `file` + `category` | indexed/duplicate | 400、401、413、503 |
| `GET /api/admin/knowledge/stats` | Cookie | 文档/块/分类统计 | 401、503 |

上传接口一次只接收一个文件。前端多选后会循环调用，使每个文件都有独立进度和结果。

### 9.7 状态码

- 200：请求成功，包括正常入库和重复跳过。
- 400：文件损坏、空正文、不支持格式或扫描版 PDF。
- 401：没有有效管理员会话。
- 413：上传超过 25 MiB。
- 422：JSON 或表单不符合 Pydantic/FastAPI 契约。
- 429：聊天或登录过于频繁，或并发生成已满。
- 503：模型、配置或向量服务暂时不可用。

### 9.8 如何新增接口

推荐步骤：

1. 先定义 Pydantic 输入/输出结构。
2. 把业务逻辑写在 Service，不把全部代码塞进路由函数。
3. 在路由层完成认证、限流、错误到 HTTP 状态码的映射。
4. 为成功、非法输入、未认证和外部失败补测试。
5. 在 Swagger 中验证示例。

---

## 10. SSE 流式回答

### 10.1 SSE 格式

一条事件由事件名、JSON 数据和一个空行组成：

```text
event: token
data: {"content":"日本站"}

```

空行表示该事件结束。后端 `_sse` 使用 `json.dumps`，所以中文、引号和换行都能安全编码。

### 10.2 本项目事件顺序

```text
status: 正在理解问题
status: 正在召回相关资料
status: 精排完成或已降级
sources: 全部来源卡片
token: 增量文字，可重复多次
done: 完整答案、会话 ID、rerank_used
```

发生异常时发送 `error`。连接已经建立后，不能再依赖普通 HTTP 错误正文通知页面，因此错误也需要成为 SSE 事件。

### 10.3 为什么前端必须缓冲

TCP/HTTP 只保证字节顺序，不保证一次读取刚好对应一个事件：

```text
读取 1：event: tok
读取 2：en\ndata: {...}\n\nevent: status...
```

因此前端算法是：

1. `reader.read()` 得到 `Uint8Array`。
2. `TextDecoder` 以流式方式解码 UTF-8。
3. 追加到 `buffer`。
4. 按两个换行分割完整事件。
5. 最后不完整的一段继续留在 `buffer`。
6. 分别处理 event 和 data。

### 10.4 帧级 token 合并

如果每个 token 都执行一次 React `setState`，长答案会触发大量数组复制、渲染和 localStorage 序列化。

`queuedText` 先收集 token，`requestAnimationFrame` 在每个屏幕帧最多提交一次。收到 `done`、`error` 或进入 `finally` 前必须 flush，避免末尾文字留在缓冲中。

### 10.5 停止生成

前端为请求创建 `AbortController`，点击停止或切换会话时执行 `abort()`。`ClosingStreamingResponse.__call__` 在响应生命周期的 finally 中关闭业务迭代器，后者通过 `aclosing` 关闭图和模型流，并释放一次并发名额。响应头尚未发出就失败、发送正文失败、断连监听触发也必须清理。

取消异常继续向上传播，不作为普通 error 吞掉；仅清理阶段用 `CancelScope(shield=True)` 防止清理被中断。底层 DashScope SDK 的同步网络等待可能仍需等返回，不能承诺点击停止就瞬间停止远端计算或计费。

更新消息同时使用 `conversationId + messageId` 定位，即使旧异步回调晚到，也不会把文字写进新会话。

### 10.6 代理缓冲

后端设置 `Cache-Control: no-cache, no-transform` 和 `X-Accel-Buffering: no`。生产环境的 Nginx/CDN 仍需确认没有缓存或聚合 SSE，否则页面看起来会在最后一次性显示答案。

---

## 11. React 前端

### 11.1 Provider 和 Context

`KnowledgeConversationProvider` 包围整个 `App`，拥有：

- `conversations`：最多 20 个会话。
- `activeId`：当前会话 ID。
- `activeConversation`：由前两者计算出的当前对象。
- `isGenerating`：是否正在生成。
- `controllerRef`：当前请求的 AbortController。
- 新建、删除、切换、更新和停止方法。

侧栏与聊天页都使用 `useKnowledgeConversations()`。这叫“状态提升”：共享数据只保留一份，避免两个组件状态不同步。

### 11.2 Hook 使用原则

| Hook | 本项目用途 | 不适合保存 |
| --- | --- | --- |
| `useState` | 输入、服务状态、会话数组 | 不影响界面的临时句柄 |
| `useRef` | DOM、文件 input、AbortController | 需要立即重渲染的状态 |
| `useMemo` | 当前会话、Context value | 有副作用的操作 |
| `useCallback` | 稳定的会话操作和统计加载函数 | 普通无需传递的局部逻辑 |
| `useEffect` | 健康检查、持久化、清理 | 可直接在点击中完成的动作 |
| `useLayoutEffect` | DOM 更新后、绘制前校正消息滚动位置 | 网络请求、大段耗时计算 |

不要为了“优化”到处使用 `useMemo/useCallback`。只有引用稳定会影响 Effect 或子组件时才有意义。

### 11.3 localStorage 安全边界

localStorage 可能出现：旧版本结构、用户手工修改、JSON 损坏、隐私模式禁用、容量不足。

`loadConversations` 会逐层清洗对象、角色、字符串、来源和消息数量。`persistConversations` 捕获所有写入异常，并优先保留当前会话和较新记录。

属性读取也在保护范围内：`loadConversations()` 不在默认参数取 `localStorage`；Provider 用 `persistConversations(undefined, conversations, activeId)`，由函数在 `try` 内取得浏览器存储。否则浏览器可能在“拿到存储对象”这一步就抛错，内部的 `setItem` 保护根本来不及执行。没有存储对象也必须返回失败警告，不能跳过写入却声称成功。

内存中的当前会话不会立即因为持久化裁剪而消失；裁剪只作用于准备写入的快照。

### 11.4 防抖持久化

Provider 在会话改变后等待 750ms 再写 localStorage。密集 token 会不断取消旧计时器，最终合并为较少写入。

用户不一定等满 750ms 才刷新：Effect 同时监听 `pagehide` 和 `visibilitychange`（页面进入后台），立刻保存最新快照。一次状态用 `pending` 标记只保存一次，避免两个离开事件重复写入。清理函数只取消计时器和解绑监听，不在每次 Effect 清理时保存，否则每个 token 都会写库，防抖就失效了。

刷新会中断旧 SSE，所以恢复时半截答案保留原文并标记“已停止”，不假装它仍在生成。此机制改善正常刷新/离开时的数据保留，但无法保证浏览器崩溃、系统强杀或存储被禁止时也能保存。

防抖适合“只关心停止变化后的结果”；节流适合“持续期间固定频率执行”。

### 11.5 Markdown 与错误边界

流式内容可能暂时包含未闭合代码块或表格，生成中使用纯文本。完成后才交给 `ReactMarkdown + remark-gfm`。

`MessageRenderBoundary` 只包单条消息，Markdown 渲染失败时回退纯文本。`AppErrorBoundary` 处理更高层渲染异常并提供重新加载入口。

React Error Boundary 不能捕获事件处理器、`fetch` Promise 或服务端错误，这些必须在对应异步代码中 `try/catch`。

### 11.6 上传进度

上传使用 `XMLHttpRequest`，因为浏览器 Fetch 对上传进度支持不稳定。XHR 的 `upload.onprogress` 计算百分比，再更新对应队列项。

队列采用顺序上传：减少带宽争抢和 Embedding 限流；单文件失败只更新自身，不阻止后续文件。遇到 401 则整个管理会话已失效，应返回登录页。

### 11.7 流式回答为什么会抖，怎样稳定跟随

原实现每次 `messages` 更新都调用 `scrollIntoView({behavior: 'smooth'})`，CSS 又设置了 `scroll-behavior: smooth`。文字不断增长时，旧滚动动画还没到目的地，下一段动画就又开始了。仅合并 token 不能解决滚动动画自身的冲突。

现在分成两个可独立学习的文件：

- `chatAutoScroll.js`：普通 JS 控制器。闭包中的 `following` 记住“是否继续跟随”，不触发 React 重渲染，也不保存到聊天历史。`update()` 只在允许跟随时即时滚动消息容器；`followLatest()` 用于发送新问题或切换会话；`dispose()` 负责解绑监听。
- `useChatAutoScroll.js`：把控制器接入 React 生命周期。`useLayoutEffect` 在 DOM 已更新、浏览器绘制前校正位置；`ResizeObserver` 处理消息窗口尺寸改变；卸载时关闭观察器并清理控制器。

消息区域向上滚动、触摸向下拖、按 PageUp/Home 或展开资料都会暂停跟随；手动回到底部、切换会话或发送新问题才恢复。跟随不能在每个 token 到达时重新打开，否则用户看历史时仍会被拉回去。

CSS 也要配合：`scroll-behavior: auto` 不叠加动画，`overflow-anchor: none` 避免浏览器锚定再次补偿位置，`scrollbar-gutter: stable` 预留滚动条宽度，防止内容超过一屏时突然重新换行。不是关闭所有滚动，而是让一个明确的控制器负责消息区的位置。

大白话理解：你让电梯跟着最新一层走，但不能每来一个字就重新播放一遍电梯启动动画。你主动停下来读旧资料时，系统也不应该替你继续往下走。答案完成后切换为 Markdown 可能改变一次内容布局，这与生成期间反复往返抖动不是一回事。

参考：[React 的 useLayoutEffect](https://react.dev/reference/react/useLayoutEffect)、[MDN 的 scrollIntoView](https://developer.mozilla.org/en-US/docs/Web/API/Element/scrollIntoView)。

---

## 12. 管理员认证与安全

### 12.1 bcrypt

管理员配置保存 bcrypt 哈希，不保存明文密码。登录时 `bcrypt.checkpw` 对比用户输入和哈希。bcrypt 输入上限是 72 字节，代码对超长密码按登录失败处理，避免第三方库异常变成 500。

`hmac.compare_digest` 用于比较用户名，减少普通字符串比较可能产生的时序差异。

### 12.2 签名 Cookie

登录成功后，`itsdangerous.URLSafeTimedSerializer` 签发包含用户名的签名值。签名可以发现篡改，但不是加密，所以 payload 仍不能保存密码或密钥。

Cookie 属性：

- `HttpOnly`：浏览器脚本无法读取。
- `SameSite=Strict`：降低跨站请求携带 Cookie 的风险。
- `Secure`：只通过 HTTPS 发送；生产必须开启。
- `Max-Age=28800`：有效期 8 小时。

### 12.3 Depends

`Depends(require_admin)` 是接口前置依赖。FastAPI 先读取 Cookie、验证签名、有效期和用户名；验证失败会直接返回 401，接口主体不会运行。

### 12.4 登录限流

每个 IP 在 15 分钟窗口内最多失败 5 次。代码使用 `time.monotonic()`，它只关心经过时间，不受系统时间被调整影响。

当前限流存放在单进程内存中。多 worker 或多服务器部署时，每个进程各有一份计数，生产环境还应在 Nginx、网关或 Redis 层增加集中限流。

### 12.5 聊天限流

公开聊天限制每 IP 每分钟 20 次，并且全局最多同时生成 2 个回答。`start` 成功后必须在 `finally` 调用 `finish`，否则异常请求会泄漏并发名额。

### 12.6 CORS 和可信代理

`FRONTEND_ORIGINS` 必须填写完整前端来源，不能使用 `*`，因为管理接口需要 Cookie。

默认不信任 `X-Forwarded-For`，避免客户端伪造 IP 绕过限流。只有受控反向代理会覆盖并清洗该头时，才设置 `TRUST_PROXY_HEADERS=true`。

---

## 13. 自动测试

### 13.1 测试为什么重要

测试不是另一套业务代码，而是可执行的需求说明。修改切块、接口或认证后，它能快速告诉你已有行为是否被破坏。

### 13.2 AAA 结构

```python
def test_example():
    # Arrange：准备输入和依赖
    service = Service(fake_dependency)

    # Act：执行被测试行为
    result = service.run('input')

    # Assert：检查外部可观察结果
    assert result['status'] == 'ok'
```

### 13.3 Fake 与依赖注入

Fake 只实现生产代码真正调用的方法。例如 `FakeStore.retrieve` 返回预设 Document，`FakeModel.stream` 产出预设文本块。

因为 `RagService` 从构造器接收 store、ranker 和 model factory，测试可以替换外部依赖，不需要真实联网。

### 13.4 monkeypatch

`monkeypatch` 临时替换环境变量、模块常量或网络函数，测试结束自动恢复。它适合制造超时、错误响应和特定配置。

### 13.5 TestClient

FastAPI `TestClient` 在当前 Python 进程调用 ASGI 应用，可以检查状态码、JSON、Cookie 和认证流程，不必启动 8000 端口。

### 13.6 现有测试覆盖

- DOCX 标题、表格与段落顺序。
- TXT 三种中文编码。
- 有文字 PDF 与扫描版 PDF。
- 空文件、损坏文件和不支持格式。
- 稳定正文哈希与确定性块 ID。
- Chroma 内容去重。
- Rerank 排序和失败降级。
- 历史改写、提示词引用与流式回答。
- SSE 编码。
- 管理 Cookie 和未认证上传。
- 非法聊天请求 422。
- localStorage 损坏、裁剪和容量异常。

这些测试使用内存 Fake，不会把 307 份正文重新发送给外部服务，也不会修改正式 Chroma。

新增 `test_graphs.py` 专测图的节点顺序、无资料分支、输入不被原地修改、请求隔离、模型流取消、响应发送失败清理及锁内并发去重。测试使用真实 LangGraph 调度器和 Fake 外部依赖，不执行正式入库。

### 13.7 运行命令

```powershell
cd C:\Users\ruoxiao\Desktop\kuajing
D:\python\python.exe -B -m pytest backend\zhishiku\tests -p no:cacheprovider -q
npm run test:frontend
npm run lint
npm run build
```

修改哪一层，就先运行该层测试；提交或部署前再运行全部命令。

---

## 14. 常见扩展方法

### 14.1 新增文件类型

假设要支持 Markdown：

1. 在 `SUPPORTED_SUFFIXES` 增加 `.md`。
2. 新增 `_parse_markdown(data, filename)`。
3. 解码并规范化文字，返回 `ParsedDocument`。
4. 在 `parse_document` 增加分派。
5. 增加正常、空文件、编码异常和章节测试。

不要让新解析器直接写 Chroma，否则网页上传和批量导入会产生不同逻辑。

### 14.2 新增 metadata

例如增加 `marketplace`：

1. 决定它来自文件、管理员输入还是正文识别。
2. 在入库阶段写入每个块 metadata。
3. 在来源卡片白名单中选择是否公开。
4. 扩展前端 `sanitizeSource`，防止旧 localStorage 结构崩溃。
5. 增加接口和存储测试。

旧知识块不会自动拥有新字段。要决定兼容默认值还是重新入库，不能假设数据库自动迁移。

### 14.3 调整切块

先修改 `.env` 的 `KNOWLEDGE_CHUNK_SIZE` 和 `KNOWLEDGE_CHUNK_OVERLAP`，再用真实问题评估召回。已有 Chroma 不会自动重新切块，正式应用新规则需要备份并重建向量库。

### 14.4 修改召回数量

`KNOWLEDGE_RECALL_K` 控制向量候选数，`KNOWLEDGE_RERANK_TOP_N` 控制最终资料数。候选越多可能提高覆盖，但增加 Rerank 成本；最终资料越多可能增加上下文噪声和 token。

### 14.5 新增 RAG 步骤

新增查询分类、站点过滤或权限过滤时：

1. 为产物增加独立状态字段。
2. 写独立方法或节点。
3. 在 `_build_graph` 注册节点，修改普通边或条件边，重新编译；JSON 与 SSE 自动复用同一拓扑，不再各改一份手写顺序。
4. 定义失败是终止还是降级。
5. 测试正常、失败和无结果。

### 14.6 增加服务器会话

当前匿名聊天只保存在浏览器。若未来需要账号同步历史，应新增明确的用户认证、会话表、消息表、数据删除和隐私策略；不能仅凭前端传入的 `conversation_id` 查询或写入他人数据。

### 14.7 写新前端页面

先明确数据归谁拥有。如果多个页面都使用，就放 Provider；只在单个页面使用，就保留在局部组件。网络协议解析抽成独立函数，展示组件只接收已经清洗的数据。

---

## 15. 云服务器与数据持久化

### 15.1 上传代码后知识库还在不在

知识数据位于：

```text
backend/zhishiku/runtime/chroma
```

只上传源码而不上传这个目录，云服务器不会自动拥有本机已经入库的 307 份资料。可以选择：

1. 停止本机后端后，把完整 `runtime/chroma` 复制到服务器相同位置。
2. 把原始资料上传到服务器，再运行批量导入命令重新生成。

复制正在写入的 Chroma 目录可能得到不一致备份，所以备份和迁移前应停止后端。

### 15.2 云端持久化

服务器重启不会自动删除普通磁盘上的 runtime；但容器重新创建、临时云盘或无状态平台可能删除它。

使用容器时，应把 `backend/zhishiku/runtime` 挂载到持久卷。部署平台升级版本前确认持久卷不会随应用实例销毁。

### 15.3 不应该上传什么

- 不上传本机 `.env` 到公共仓库。
- 不上传 `node_modules`、`dist`、缓存和 `__pycache__` 作为源码。
- 不在前端构建变量中放 DashScope Key、管理员哈希或 Session Secret。
- 不通过聊天或日志公开完整 Cookie、密钥和服务器路径。

### 15.4 生产配置

- 使用 HTTPS，并设置 `COOKIE_SECURE=true`。
- `FRONTEND_ORIGINS` 填生产前端域名，不使用通配符。
- 推荐前端和 API 同源，由 Nginx 转发 `/api`。
- 为 SSE 关闭代理缓冲并配置足够长的读取超时。
- 限制上传体积和反向代理请求体大小。
- 使用强管理员密码和随机 `SESSION_SECRET`。
- 定期备份 runtime，并实际演练恢复。

### 15.5 备份与恢复

推荐流程：

```text
停止后端
→ 确认目标确实是 backend/zhishiku/runtime
→ 整体复制或移动为带时间戳备份
→ 部署或重建
→ 启动并检查 health 的文档数和块数
```

恢复时同样先停止后端，再替换整个 runtime，最后重启让延迟客户端连接新目录。

---

## 16. 故障排查

### 页面回答途中变空白

检查浏览器 Console。当前代码已对 localStorage 写入、Markdown 渲染和页面渲染设置保护。重点确认是否存在第三方组件异常、内存耗尽或非知识库页面的新错误。

### health 显示 degraded

检查 `RERANK_ENABLED`、Workspace Base URL、API Key 和最近的网络错误。降级时问答仍能依赖 Chroma。

### health 显示 unavailable

检查 API Key、runtime 目录权限、Chroma 文件完整性和 Embedding 模型配置。不要先删除 runtime。

### 问题返回 422

检查 UUID、空问题、历史数量、历史角色和多余字段。查看响应中的 Pydantic 错误位置。

### 管理接口返回 401

确认已经登录、Cookie 未过期、前端请求带 `credentials: 'include'`，以及生产域名、HTTPS 和 SameSite 配置一致。

### 上传返回 413

文件超过后端 25 MiB 限制，或反向代理设置了更小的 body 限制。不要只在前端放宽。

### 扫描版 PDF 报错

当前没有 OCR，这是预期行为。先使用可靠 OCR 工具生成带文字层 PDF 或转成 TXT/DOCX，再上传。

### 流式回答最后一次性出现

检查 Nginx/CDN 是否缓冲 SSE，确认 `X-Accel-Buffering: no` 没被覆盖，并检查代理读取超时。

### 端口 8000 被占用

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

先确认 PID 对应程序，不要直接结束未知进程。`backend.run_api` 会识别已经运行的本项目服务。

### 修改配置不生效

重启后端，并确认修改的是项目根目录 `.env`。Embedding 模型改变还需要重建向量库。

---

## 17. 学习练习

### 第一阶段：只读追踪

1. 从 `chat_stream` 开始，写出调用的每个方法。
2. 给 `ServiceState` 每个字段记录一次实际示例。
3. 找到 `rag_service`、`knowledge_store`、`reranker` 在何时创建、何时真正工作。

### 第二阶段：断点调试

1. 在 `rewrite_question` 结束处观察原问题与检索问题。
2. 在 Rerank 前后比较 candidates/documents。
3. 在 `prepare_context` 检查 `[资料 n]` 与 sources 是否一致。
4. 在前端 `consumeEvent` 观察 status、sources、token、done。

调试时避免打印 API Key、密码、Cookie 和完整上传正文。

### 第三阶段：安全小改动

1. 新增一个常用问题按钮。
2. 为来源卡片增加已有 metadata 的展示。
3. 新增一条非法历史角色测试。
4. 新增一个空 TXT 测试。

每次改动先写预期，再修改代码，最后运行相关测试和完整构建。

### 第四阶段：独立扩展

实现 Markdown 文件上传支持：先写解析测试，再写解析器和分派，最后通过管理页上传验证。不要绕过统一 `ParsedDocument` 和 `KnowledgeStore`。

---

## 18. 术语表

| 术语 | 含义 |
| --- | --- |
| RAG | 检索增强生成：检索资料后再生成答案 |
| Embedding | 把文本转换成语义向量 |
| Vector Store | 保存向量并执行相似度查询的存储 |
| Chroma | 本项目使用的向量数据库 |
| Chunk | 原文切分得到的知识块 |
| Metadata | 附着在知识块上的文件名、分类、日期等结构化信息 |
| Recall | 初次从向量库找回候选内容 |
| Rerank | 对少量候选进行第二次精细排序 |
| Prompt | 发送给模型的指令和上下文 |
| SSE | 服务端通过持续 HTTP 响应单向推送事件 |
| ASGI | Python 异步 Web 应用与服务器之间的标准接口 |
| Pydantic | 运行时数据校验和模型库 |
| Dependency Injection | 从外部传入依赖，使代码可替换、可测试 |
| Context | React 跨组件共享状态的机制 |
| Hook | React 函数组件使用状态和副作用的接口 |
| Debounce | 变化停止一段时间后执行一次 |
| AbortController | 浏览器取消 fetch 请求的标准 API |
| Cookie | 浏览器随站点请求自动携带的数据 |
| Hash | 数据的稳定指纹；正文去重使用 SHA-256 |
| Idempotent | 重复执行不会不断产生额外副作用 |

---

## 最后的学习方法

不要以“是否背下所有代码”判断自己是否学会。真正的标准是：

1. 能顺着调用链找到代码。
2. 能说清每层的输入、输出和失败方式。
3. 能先写测试，再做一个小改动。
4. 出错时知道应该观察哪个状态、接口或日志。
5. 部署前知道哪些配置和数据必须安全保存。

建议同时配合 `docs/zhishiku-learning-guide.md` 阅读：学习指南适合快速建立顺序，本教程适合系统查阅与动手实践。
