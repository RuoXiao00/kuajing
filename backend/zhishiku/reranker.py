"""Qwen3 Rerank 精排封装，任何远程失败都会安全退回向量顺序。"""

from __future__ import annotations

import os
import threading
from typing import Any

import requests
from langchain_core.documents import Document

from .config_data import RERANK_BASE_URL, RERANK_ENABLED, RERANK_MODEL, RERANK_TOP_N


class QwenReranker:
    """对 Chroma 召回候选做第二阶段相关性排序。

    向量检索擅长快速找出候选，Rerank 会同时阅读“问题 + 每个候选块”后重新
    比较语义相关性，通常能把真正回答问题的段落排到前面。分数仅在本次请求
    的候选之间有意义，不设置跨请求的固定阈值。
    """

    def __init__(self) -> None:
        # 这些字段只记录本进程最近一次精排健康状态，不会写进 Chroma。
        # 锁避免并发请求同时更新状态时互相覆盖。
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_success = False

    @property
    def configured(self) -> bool:
        """只报告能否尝试精排，不返回密钥或具体 URL。"""

        # 配置齐全只表示可以尝试，不代表远程服务必然健康；真实结果要等
        # rank 发出请求，因此 health 还要结合最近一次错误。
        return bool(
            RERANK_ENABLED
            and RERANK_BASE_URL
            and os.getenv("DASHSCOPE_API_KEY", "").strip()
        )

    def health(self) -> dict[str, Any]:
        """返回可公开展示的运行状态。

        available 表示配置齐全；degraded 表示已禁用、缺配置或上次请求失败。
        last_error 只保留我们定义的安全摘要，不转发供应商响应正文。
        """

        if not RERANK_ENABLED:
            reason = "Rerank 已通过配置关闭"
        elif not RERANK_BASE_URL:
            reason = "未配置 DASHSCOPE_RERANK_BASE_URL"
        elif not os.getenv("DASHSCOPE_API_KEY", "").strip():
            reason = "未配置 DASHSCOPE_API_KEY"
        else:
            reason = self._last_error
        return {
            "enabled": RERANK_ENABLED,
            "available": self.configured,
            "degraded": not self.configured or self._last_error is not None,
            "model": RERANK_MODEL,
            "reason": reason,
        }

    def rank(
        self,
        query: str,
        candidates: list[Document],
        top_n: int = RERANK_TOP_N,
    ) -> tuple[list[Document], bool]:
        """返回精排后的文档与 rerank_used 标志。

        False 明确告诉 API/前端本次使用了向量降级顺序。即使精排超时、
        限流或响应格式变化，知识库仍可回答，而不是整条链路 500。
        """

        fallback = candidates[:top_n]
        if not candidates or not self.configured:
            return fallback, False

        try:
            # qwen3-rerank 使用百炼的 OpenAI 兼容 Rerank 协议：请求字段位于
            # JSON 顶层。它不同于 qwen3.7-text-rerank 的 input/parameters
            # 原生协议，混用虽然都是 HTTP 200/400 接口，却会导致稳定失败。
            # 同步 HTTP 请求运行在本轮 RAG 中。连接和读取分别设置超时，
            # 避免远程服务长时间占用有限的生成并发名额。
            response = requests.post(
                f"{RERANK_BASE_URL}/reranks",
                headers={
                    "Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": RERANK_MODEL,
                    "query": query,
                    "documents": [document.page_content for document in candidates],
                    "top_n": min(top_n, len(candidates)),
                    # 官方建议用英文 instruct。此句让模型偏向寻找“能直接回答
                    # 问题的段落”，而不只是主题词相似的段落。
                    "instruct": (
                        "Given a web search query, retrieve relevant passages "
                        "that answer the query."
                    ),
                },
                timeout=(5, 25),
            )
            response.raise_for_status()
            payload = response.json()
            output = payload.get("output", payload) if isinstance(payload, dict) else {}
            results = output.get("results", []) if isinstance(output, dict) else []
            ranked: list[Document] = []
            # 响应给出候选数组的原下标；先检查类型和范围，再映射回 Document，
            # 这是处理任何外部接口数据时都应该遵守的边界校验。
            for item in results:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                if not isinstance(index, int) or not 0 <= index < len(candidates):
                    continue
                score = item.get("relevance_score", item.get("score"))
                source = candidates[index]
                source.metadata = {
                    **source.metadata,
                    "_rerank_score": float(score) if score is not None else None,
                }
                ranked.append(source)
            if not ranked:
                raise ValueError("精排响应没有有效 results")
            with self._lock:
                self._last_success = True
                self._last_error = None
            return ranked[:top_n], True
        except (requests.RequestException, ValueError, TypeError, KeyError):
            with self._lock:
                self._last_success = False
                self._last_error = "上次精排请求失败，当前已回退到向量排序"
            return fallback, False


# 这是共享实例，不会自己启动后台任务；只有 rank 被调用时才访问 DashScope。
reranker = QwenReranker()
