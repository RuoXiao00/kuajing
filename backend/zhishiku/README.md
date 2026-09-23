# 知识库后端设计说明

本模块使用 LangGraph 1.2.5，包含三条边界清晰的数据流：

- 问答：HTTP 请求 → 问题改写 → Chroma 召回 → Qwen3 Rerank → 引用回答。
- 单文件入库：管理员上传 → 文件解析 → 规范化去重 → 切块 → Embedding → Chroma。
- 目录导入：递归预扫描 → 内容去重 → 逐文档入库 → JSON 审计报告。

问答图：START → rewrite_question → retrieve_candidates → rerank_documents →
prepare_context → 条件边（generate 或 insufficient_evidence）→ END。

入库图：START → prepare_document → fingerprint → check_duplicate → 条件边
（重复时直接 persist_document，新正文经 split_chunks）→ persist_document → END。
上传提供 bytes，批量导入的 ingest_document 提供 ParsedDocument；两者共用此图。

服务 __init__ 编译图但不执行节点。ask 调 graph.invoke，astream_events 消费
graph.astream(custom + updates, version="v2")。每次有独立状态，节点返回局部更新，
字段默认覆盖，未返回字段保留；不原地修改输入，不给历史使用累加 reducer。

匿名会话不使用 SQLite，不在服务器永久保存。前端只提交当前会话最近 10 条消息。

## 问答状态字段

ServiceState 是一次请求内共享的普通字典，不是数据库表。字段含义如下：

| 字段 | 写入者 | 读取者 | 内容与生命周期 |
| --- | --- | --- | --- |
| question | API | 改写、生成 | 用户本轮原始问题，始终保留 |
| history | API | 改写、生成 | 最近最多 10 条 user/assistant 消息 |
| retrieval_query | 改写步骤 | Chroma、Rerank | 可独立理解的检索问题；改写失败时等于 question |
| candidates | Chroma | Rerank | 向量距离排序的最多 12 个 Document |
| documents | Rerank | 上下文整理 | 精排后的最多 5 个 Document；失败时使用向量前 5 |
| context | 上下文整理 | 回答模型 | 带 [资料 n] 编号的临时参考文本 |
| sources | 上下文整理 | API、页面 | 安全文件名、标题、分类、日期和短摘要 |
| answer | generate/insufficient_evidence | JSON API/SSE done | 完整 Markdown 回答 |
| rerank_used | Rerank | API、页面 | 本次是否真实完成远程精排 |
| status | 各步骤 | SSE | 当前进度提示，请求结束后不持久化 |

为什么分开 question 和 retrieval_query：用户看到并需要回答的是原问题，但“日本站呢？”
无法直接向量检索。改写只服务检索，不能偷偷改变用户最终要问的内容。

为什么分开 candidates 和 documents：前者用于观察宽召回是否覆盖正确资料，后者用于
观察 Rerank 是否选对资料。只保留一个 documents 字段会让调试时无法判断问题发生在
向量召回还是精排。

## 入库状态字段

IngestState 同样只存在于当前上传或单文档导入的图执行中：

| 字段 | 写入者 | 读取者 | 数据格式 |
| --- | --- | --- | --- |
| file_data | 上传入口 | prepare_document | 可选原始 bytes，最大 25 MiB；预解析入口不需要 |
| filename | API | 解析器、metadata | basename，不保存服务器绝对路径 |
| category | API | Chroma | 最长 80 字符的业务分类 |
| parsed_document | prepare_document 或导入入口 | 指纹、切块、写入 | 标题、章节、正文、资料日期 |
| content_hash | 指纹步骤 | Chroma 查重 | 规范化正文 SHA-256 |
| is_duplicate | check_duplicate | route_duplicate | 预检 bool，不是最终存储结果 |
| chunks | 切块步骤 | 测试、向量化 | 含文档/章节前缀的约 800 字符文本 |
| result | Chroma | API | indexed 或 duplicate、块数和说明 |
| status | 各步骤 | 日志/UI | 当前阶段，不参与流程判断 |

存储入口新增可选关键字参数 prepared_chunks，图预切分后传入以免重复切块。
即使图预检未发现重复，存储层也必须在锁内重新查重再写入；两次调用可能并发。
此锁只保护单进程，不能替代多进程/多实例的写入协调；本次没有新增自动重试写入。

DOCX 通过 XML body 顺序读取段落与表格，避免 document.paragraphs 和
document.tables 分开读取造成原文顺序错乱。PDF 按页提取文字；没有文字层时不做
OCR。TXT 依次尝试 UTF-8 BOM、UTF-8 和 GB18030。

每个块的 ID 由 content_hash 与 chunk_index 组成，因此同一正文重复处理会得到相同
ID。Metadata 保存 source、title、section、category、published_at、content_hash、
chunk_index 和 uploaded_at。

## 接口约定

POST /api/knowledge/chat 与 POST /api/knowledge/chat/stream 使用相同请求：

~~~json
{
  "conversation_id": "UUID",
  "question": "问题",
  "history": [{"role": "user", "content": "历史消息"}]
}
~~~

流式接口使用标准 SSE：

- status：阶段说明，可含 rerank_used。
- sources：生成前一次发送全部来源卡片。
- token：一个增量文本块，前端按顺序追加。
- done：最终答案、conversation_id 和 rerank_used。
- error：可以安全展示的错误说明。

连接建立后发生的异常使用 error 事件，而不是把供应商原始错误返回浏览器。浏览器
AbortController 关闭连接后，ClosingStreamingResponse 的响应级 finally 关闭业务流、
图流和模型流，并只释放一次并发名额。同步 SDK 中已开始的网络请求可能仍待返回，
不能保证点击停止就瞬间停止远端计算或计费。

token 的 JSON 为 {"content": "增量文本"}；sources 在答案前发出，done 的 answer
由相同增量合并，不再次请求模型。仅回答节点投递答案 token，不输出改写模型文本。

管理员文件接口使用 multipart/form-data：

- file：一个 DOCX/PDF/TXT 文件。
- category：可选分类。
- 200：indexed 或 duplicate。
- 400：损坏、空正文、不支持格式或扫描版 PDF。
- 401：没有有效管理员 Cookie。
- 413：超过 25 MiB。
- 503：Embedding/Chroma 暂时不可用。

## 安全设计

- 管理员明文密码不进入源码和 .env，只保存 bcrypt 哈希。
- Cookie 使用 HttpOnly、SameSite=Strict，生产环境必须打开 Secure。
- FRONTEND_ORIGINS 禁止星号通配符。
- 登录每 IP 15 分钟最多失败 5 次。
- 聊天每 IP 每分钟最多 20 次，全局最多同时生成 2 个回答。
- 默认不信任 X-Forwarded-For；只有受控代理会清洗该头时才打开相关配置。
- 文档内容在系统提示中被声明为不可信资料，不能覆盖系统指令。
- 来源 API 不返回服务器路径、API Key 或完整 content_hash。

## Rerank 降级

标准流程召回 12 条后精排 5 条。qwen3-rerank 请求失败、超时、限流或缺少配置时，
rank 方法返回向量排序前 5 条并令 rerank_used=false。分数只在当前候选列表中进行
相对比较，不设置跨请求固定阈值。

健康接口中的 available 表示配置是否齐全；degraded 表示本次只能或最近曾经只能使用
向量排序。修改环境变量后必须重启后端，因为配置在模块导入时读取。

## 开发调用

Python 非流式调用：

~~~python
from backend.zhishiku.zhishiku import RagService

service = RagService()
result = service.ask(
    "日本站品牌备案需要什么材料？",
    [{"role": "user", "content": "美国站需要什么？"}],
)
print(result["answer"])
print(result["sources"])
~~~

单文件入库调用：

~~~python
from pathlib import Path
from backend.zhishiku.agent import KnowledgeBaseService

path = Path("资料/VAT.txt")
result = KnowledgeBaseService().upload_file(path.read_bytes(), path.name, "税务要求")
print(result)
~~~

HTTP 启动、目录导入和测试命令见项目根目录 README。
