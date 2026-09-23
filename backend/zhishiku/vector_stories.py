"""Chroma 的唯一访问层：入库、召回、去重和统计都经过这里。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from backend._common import embeddings

from .config_data import CHROMA_DIR, COLLECTION_NAME, RECALL_K, ensure_runtime
from .document_loader import KnowledgeChunk, ParsedDocument, content_hash, split_document


class KnowledgeStore:
    """封装知识库持久化细节。

    Chroma 同时保存正文、向量和 metadata，因此它是知识数据的唯一事实来源。
    去重直接查询 metadata.content_hash，不再维护 content_hashes.txt，避免两份
    状态在写入失败、恢复备份或删除数据后彼此不一致。
    """

    def __init__(self) -> None:
        # 构造器只准备 Python 状态，不立即创建 Embedding 客户端或打开 Chroma。
        # 仅导入 FastAPI 路由时因此不会提前检查密钥或访问向量库。
        self._store: Chroma | None = None
        # 一个进程中只允许一个线程同时进行“查重 + 写入”，缩小并发重复窗口。
        self._write_lock = threading.Lock()
        self._recent_results: list[dict[str, Any]] = []

    @property
    def store(self) -> Chroma:
        """延迟创建客户端，使 FastAPI 导入时不会立刻请求模型配置。"""

        # @property 让调用方像读字段一样写 self.store，内部仍能延迟初始化。
        # 第一次访问创建客户端，以后复用；这种模式叫 lazy initialization。
        if self._store is None:
            ensure_runtime()
            self._store = Chroma(
                collection_name=COLLECTION_NAME,
                embedding_function=embeddings(),
                persist_directory=str(CHROMA_DIR),
            )
        return self._store

    def reset_client(self) -> None:
        """备份/替换 runtime 后丢弃旧客户端，下次访问再连接新目录。"""

        self._store = None

    def has_content_hash(self, digest: str) -> bool:
        """查询 Chroma 中是否已有相同规范化正文。"""

        result = self.store.get(where={"content_hash": digest}, limit=1, include=["metadatas"])
        return bool(result.get("ids"))

    def index_document(
        self, document: ParsedDocument, category: str = "未分类", *,
        prepared_chunks: list[KnowledgeChunk] | None = None,
    ) -> dict[str, Any]:
        """把一个解析好的文档切块、向量化并写入 Chroma。

        返回值给上传接口和批量导入器共用：
        - status=indexed：新正文已写入，chunk_count 是实际知识块数；
        - status=duplicate：正文指纹已存在，没有再次调用 Embedding；
        - status=error：由上层捕获异常后构造，本方法本身会抛出异常。

        prepared_chunks 仅供内部入库图传入“同一 document”的预切块；不暴露给 HTTP。
        不传时仍在本层切块，兼容原来的 index_document(document, category) 调用。
        不信任图上的预检结果：无论是否提供块，都先在锁内查询正文指纹。
        """

        # 查重和写入必须在同一把锁内，否则两个线程可能同时查到不存在，
        # 随后都写入。此锁只覆盖当前 Python 进程，多实例部署需额外协调。
        digest = content_hash(document.text)
        safe_category = category.strip()[:80] or "未分类"
        with self._write_lock:
            if self.has_content_hash(digest):
                result = {
                    "status": "duplicate",
                    "filename": document.filename,
                    "category": safe_category,
                    "chunk_count": 0,
                    "message": "正文内容已存在，未重复入库",
                }
                self._remember(result)
                return result

            # 复用图的切分结果，避免同一文档切两次。None 与空列表含义不同：
            # None 表示尚未切分；空列表是无效输入，不能报“成功写入 0 块”。
            # “节点拆开”不等于“规则各写一套”：切块算法还是 split_document，
            # 只是图先调用后把结果传进来。旧调用没传 prepared_chunks 时，本层才补切。
            # 将来改切块规则只改算法入口，不要分别改上传、批量导入和存储三个版本。
            chunks = split_document(document) if prepared_chunks is None else prepared_chunks
            if not chunks:
                raise ValueError("文档没有可写入的知识块")
            uploaded_at = datetime.now(timezone.utc).isoformat()
            langchain_documents: list[Document] = []
            ids: list[str] = []
            for chunk in chunks:
                ids.append(chunk.chunk_id)
                langchain_documents.append(
                    Document(
                        page_content=chunk.text,
                        metadata={
                            # source 只存安全文件名，不存服务器绝对路径。
                            "source": document.filename,
                            "title": document.title,
                            "section": chunk.section,
                            "category": safe_category,
                            "published_at": document.published_at,
                            "content_hash": digest,
                            "chunk_index": chunk.chunk_index,
                            "uploaded_at": uploaded_at,
                        },
                    )
                )

            # 一次传入该文档所有 chunks，Embedding 实现会进行数组批处理。
            self.store.add_documents(langchain_documents, ids=ids)
            result = {
                "status": "indexed",
                "filename": document.filename,
                "category": safe_category,
                "chunk_count": len(chunks),
                "message": f"成功写入 {len(chunks)} 个知识块",
            }
            self._remember(result)
            return result

    def retrieve(self, query: str, k: int = RECALL_K) -> list[Document]:
        """向量召回前 k 条候选，并把向量距离保存在临时 metadata 中。

        Chroma 返回的 score 是距离（越小通常越相似），它只用于本次请求排序，
        不作为跨问题的固定质量阈值。
        """

        results = self.store.similarity_search_with_score(query, k=k)
        documents: list[Document] = []
        for document, distance in results:
            document.metadata = {**document.metadata, "_vector_distance": float(distance)}
            documents.append(document)
        return documents

    def stats(self) -> dict[str, Any]:
        """返回管理页/健康检查需要的安全统计，不暴露路径和密钥。"""

        # 文档数按不同 content_hash 统计，知识块数按 collection.count 统计。
        # 一份文档通常切成多个块，所以两个数字不能互相替代。
        count = self.store._collection.count()
        raw = self.store.get(include=["metadatas"]) if count else {"metadatas": []}
        metadatas = [item or {} for item in raw.get("metadatas") or []]
        hashes = {str(item.get("content_hash")) for item in metadatas if item.get("content_hash")}
        categories = {str(item.get("category")) for item in metadatas if item.get("category")}
        timestamps = [str(item.get("uploaded_at")) for item in metadatas if item.get("uploaded_at")]
        return {
            "document_count": len(hashes),
            "chunk_count": count,
            "category_count": len(categories),
            "last_updated_at": max(timestamps, default=None),
            "recent_uploads": list(self._recent_results),
        }

    def _remember(self, result: dict[str, Any]) -> None:
        """只在内存保留最近 20 条上传结果；重启后清空，不属于知识数据。"""

        self._recent_results.insert(0, result)
        del self._recent_results[20:]


# 单例让问答、上传和统计共享同一个 Chroma 客户端。
# 若以后需要第二套知识库，应创建新的配置实例，不要在请求中改这个全局对象。
knowledge_store = KnowledgeStore()


# 兼容旧教学代码中的类名；新代码应直接使用 knowledge_store。
class Embedding_retrive:
    """旧接口兼容层，get_retrive 等价于向量召回。"""

    def get_retrive(self, question: str) -> list[Document]:
        return knowledge_store.retrieve(question)
