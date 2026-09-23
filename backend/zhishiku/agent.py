"""知识文件入库服务，以及入库过程使用的状态说明。"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from .document_loader import (
    KnowledgeChunk,
    ParsedDocument,
    content_hash,
    parse_document,
    split_document,
)
from .vector_stories import KnowledgeStore, knowledge_store


class IngestState(TypedDict):
    """一次文件入库从开始到结束共享的“工作单”。

    TypedDict 只说明字典允许有哪些键，不创建数据库，也不会自动保存数据。
    upload_file 先放入字节、文件名与分类；ingest_document 则直接提供解析对象。
    两个入口执行同一张图，节点返回局部字典，由 LangGraph 覆盖合并同名字段。

    生命周期：
    1. API 写入 file_data、filename、category；
    2. 解析步骤写入 parsed_document；
    3. 指纹/切块步骤写入 content_hash、chunks；
    4. Chroma 入库步骤写入 result 与 status。
    """

    # 【API 输入；parse_document 读取】浏览器上传的原始文件字节。
    # 批量导入已有 parsed_document 时不需要字节，所以它是 NotRequired。
    # NotRequired 表示字典可以“没有这个键”，不等于 bytes | None（键存在但值可空）。
    # 因此读可选键前要确认走的是哪条输入路径，或像 prepare_document 一样先 get。
    # 文件字节只在本轮执行中暂存，不保存为聊天历史或 Chroma metadata。
    file_data: NotRequired[bytes]
    # 【API 输入；解析和 metadata 读取】安全文件名，不应包含服务器绝对路径。
    filename: str
    # 【API 输入；Chroma metadata 读取】管理者填写的业务分类，如“税务要求”。
    category: str

    # 【解析步骤写入；后续步骤读取】不同文件格式统一后的正文、标题和章节。
    parsed_document: NotRequired[ParsedDocument]
    # 【指纹步骤写入；Chroma 查重读取】规范化全文的 SHA-256 十六进制字符串。
    content_hash: NotRequired[str]
    # 【预检查节点写入；条件边读取】bool 仅用于跳过切块，不是最终数据库结论。
    # 两个请求可能同时预检未命中，写入层必须在锁内重新确认。
    is_duplicate: NotRequired[bool]
    # 【切块步骤写入；向量化读取】约 800 字且包含标题前缀的知识块列表。
    chunks: NotRequired[list[KnowledgeChunk]]
    # 【入库步骤写入；API 读取】indexed/duplicate、块数、文件名等结构化结果。
    result: NotRequired[dict[str, Any]]
    # 【各步骤写入；日志/UI 读取】当前阶段的简短说明，不参与流程判断。
    status: NotRequired[str]


# 【类与实例】class 只定义服务模板；执行到这里不会上传文件。
# 模块末尾创建共享实例，upload_file 被调用时才执行解析、切块和写入。
class KnowledgeBaseService:
    """把文件解析、正文去重、切块与向量写入组织成一个可复用入口。"""

    def __init__(self, store: KnowledgeStore = knowledge_store) -> None:
        # 通过参数注入 store：生产环境使用默认 Chroma，测试可传 FakeStore。
        # 自己写服务类时，把外部依赖放进构造器，通常比在方法里写死更容易测试。
        self.store = store
        # 只编译规则；这里没有文件输入，因此不会解析文档或调用 Embedding。
        self.graph = self._build_graph()

    def _build_graph(self):
        """构造可复用的入库图，不启用 checkpointer 或自动重试写入。"""

        graph = StateGraph(IngestState)
        graph.add_node("prepare_document", self.prepare_document)
        graph.add_node("fingerprint", self.fingerprint)
        graph.add_node("check_duplicate", self.check_duplicate)
        graph.add_node("split_chunks", self.split_chunks)
        graph.add_node("persist_document", self.persist_document)
        graph.add_edge(START, "prepare_document")
        graph.add_edge("prepare_document", "fingerprint")
        graph.add_edge("fingerprint", "check_duplicate")
        # 预检命中时跳过切块，但仍进入持久化节点取得锁内确认的权威结果。
        graph.add_conditional_edges("check_duplicate", self.route_duplicate, {
            "persist_document": "persist_document", "split_chunks": "split_chunks",
        })
        graph.add_edge("split_chunks", "persist_document")
        graph.add_edge("persist_document", END)
        return graph.compile()

    def prepare_document(self, state: IngestState) -> dict[str, Any]:
        """图入口节点：上传解析 bytes；目录导入复用预扫描结果，不再解析一次。"""

        # 同一个业务可以有不同入口，但尽早转换成相同内部格式，后面的节点就不用
        # 到处判断“这是上传还是批量导入”。这里统一后，后续只读 parsed_document。
        # parsed_document 是“已提取文字的对象”，file_data 是“未解析的文件字节”；
        # 别把 DOCX 的二进制直接当普通正文去切块或计算业务去重指纹。
        parsed = state.get("parsed_document")
        if parsed is None:
            parsed = parse_document(state["file_data"], state["filename"])
        return {"parsed_document": parsed, "status": "正在计算正文指纹"}

    def fingerprint(self, state: IngestState) -> dict[str, Any]:
        """读取统一正文，返回 SHA-256；文件名、分类不同不影响正文去重。"""

        return {"content_hash": content_hash(state["parsed_document"].text), "status": "正在检查重复"}

    def check_duplicate(self, state: IngestState) -> dict[str, Any]:
        """只查询 Chroma，不新增向量；返回值供条件边决定是否值得切块。"""

        return {"is_duplicate": self.store.has_content_hash(state["content_hash"])}

    @staticmethod
    def route_duplicate(state: IngestState) -> str:
        # 路由函数只返回节点名；真正的结果以 persist_document 返回值为准。
        return "persist_document" if state["is_duplicate"] else "split_chunks"

    def split_chunks(self, state: IngestState) -> dict[str, Any]:
        """仅新正文执行：按章节切块，沿用标题前缀、重叠和确定性 ID。"""

        return {"chunks": split_document(state["parsed_document"]), "status": "正在生成向量"}

    def persist_document(self, state: IngestState) -> dict[str, Any]:
        """把预切块交给唯一存储入口；最终查重与写入仍在同一把进程锁中。"""

        # 不能拿图的 is_duplicate 直接宣称入库成功。检查与写入之间有时间窗口，
        # 存储层再次查重才可挡住并发上传；重复结果也统一登记到最近上传记录。
        # 两次查重解决不同问题：第一次省切块；第二次防竞争。
        # 例如 A、B 都预检“没有”，A 先拿锁写入后，B 再拿锁就发现“已有”，
        # B 返回 duplicate 而不是再做 Embedding。图里的条件边不能替代这把锁。
        # 若看到 is_duplicate=False 但最终 result.status="duplicate"，这不矛盾，
        # 说明预检和真正写入之间，另一请求先写进去了。向前端返回最终 result。
        result = self.store.index_document(
            state["parsed_document"], state["category"],
            prepared_chunks=state.get("chunks"),
        )
        return {"result": result, "status": result["status"]}

    def upload_file(self, data: bytes, filename: str, category: str = "未分类") -> dict[str, Any]:
        """解析并入库单个文件，返回管理接口可以直接序列化的结果。

        使用方式：
            result = KnowledgeBaseService().upload_file(file_bytes, "VAT.docx", "税务")
        正文重复时返回 duplicate，不会再次收费调用 Embedding。
        """

        # 每次调用创建新工作单；invoke 按图中的边执行，不手动串联各方法。
        state: IngestState = {
            "file_data": data,
            "filename": filename,
            "category": category,
            "status": "正在解析文件",
        }
        return self.graph.invoke(state)["result"]

    def ingest_document(self, document: ParsedDocument, category: str = "未分类") -> dict[str, Any]:
        """供批量导入调用：传入预扫描成功的对象，复用完整入库图及同一结果契约。"""

        # 这里的 state 是另一个新的工作单，不是上一次 upload_file 的残留。
        # 仿写新入口时，应继续进入 graph.invoke，而不是绕过图直接调用存储；
        # 否则以后给图加校验节点，新入口可能悄悄跳过校验。
        state: IngestState = {
            "filename": document.filename, "category": category,
            "parsed_document": document, "status": "正在准备文档",
        }
        return self.graph.invoke(state)["result"]


# 模块第一次被 import 时创建单例，但此时不会开始任何文件入库任务。
knowledge_base_service = KnowledgeBaseService()
