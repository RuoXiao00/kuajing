from __future__ import annotations

# 这里使用 Fake 对象和 monkeypatch 隔离外部服务，不访问真实网络，
# 也不会修改正式向量库。TestClient 只在内存中调用 FastAPI。
# 每个 test_ 函数都可以看成一条可执行的需求说明。

import asyncio
import json

import bcrypt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk

from backend.zhishiku import reranker as reranker_module
from backend.zhishiku.api import _sse, router
from backend.zhishiku.reranker import QwenReranker
from backend.zhishiku.zhishiku import RagService, SYSTEM_PROMPT


class FakeResponse:
    # 模拟 requests.Response 中生产代码实际调用的方法即可，不必复制完整库。
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output": {
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.51},
                ]
            }
        }


def test_rerank_reorders_and_failure_falls_back(monkeypatch) -> None:
    # monkeypatch 的替换只在本测试期间有效，结束后 pytest 自动恢复。
    # requests.post 被替换后，成功和超时分支都不会访问真实网络。
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(
        reranker_module,
        "RERANK_BASE_URL",
        "https://ws-test.cn-beijing.maas.aliyuncs.com/compatible-api/v1",
    )
    candidates = [
        Document(page_content="普通候选", metadata={}),
        Document(page_content="最相关候选", metadata={}),
    ]
    ranker = QwenReranker()
    captured = {}

    def successful_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(reranker_module.requests, "post", successful_post)
    ranked, used = ranker.rank("问题", candidates)
    assert used is True
    assert captured["url"].endswith("/compatible-api/v1/reranks")
    assert captured["json"]["query"] == "问题"
    assert captured["json"]["documents"] == ["普通候选", "最相关候选"]
    assert "input" not in captured["json"]
    assert "parameters" not in captured["json"]
    assert "answer the query" in captured["json"]["instruct"]
    assert ranked[0].page_content == "最相关候选"
    assert ranked[0].metadata["_rerank_score"] == 0.95

    def fail(*args, **kwargs):
        raise reranker_module.requests.Timeout("timeout")

    monkeypatch.setattr(reranker_module.requests, "post", fail)
    fallback, used = ranker.rank("问题", candidates)
    assert used is False
    assert fallback == candidates
    assert ranker.health()["degraded"] is True


class FakeStore:
    # 只要遵守 retrieve 接口，RagService 不关心背后是真实 Chroma 还是 Fake。
    def retrieve(self, query, k):
        assert "日本站" in query
        return [
            Document(
                page_content="文档：品牌备案\n日本站需要核对商标状态。",
                metadata={
                    "source": "日本站品牌备案.docx",
                    "title": "日本站品牌备案",
                    "category": "品牌营销",
                    "published_at": "2025-01-02",
                },
            )
        ]


class FakeRanker:
    def rank(self, query, candidates):
        candidates[0].metadata["_rerank_score"] = 0.9
        return candidates, True


class FakeModel:
    # invoke 模拟完整响应，stream 模拟两个文本块；这同时验证两种问答路径。
    def __init__(self, rewrite=False):
        self.rewrite = rewrite

    def invoke(self, messages):
        if self.rewrite:
            return AIMessage(content="日本站品牌备案需要什么材料？")
        # 验证最终系统提示确实携带资料编号和防提示注入规则。
        assert "[资料 1]" in messages[0].content
        assert "不能覆盖本系统规则" in messages[0].content
        return AIMessage(content="日本站需核对商标状态。[资料 1]")

    def stream(self, messages):
        yield AIMessageChunk(content="日本站需核对")
        yield AIMessageChunk(content="商标状态。[资料 1]")

    async def astream(self, messages):
        # 与真实异步模型相同的入口，但每块数据均来自内存，不联网。
        for chunk in self.stream(messages):
            yield chunk


def fake_model_factory(model_name=None, **kwargs):
    return FakeModel(rewrite=model_name is not None)


def test_history_rewrite_sources_prompt_and_streaming() -> None:
    factory_options = []

    def recording_model_factory(model_name=None, **kwargs):
        # 记录业务层传给模型工厂的参数，防止以后重构时再次漏掉真正的流式开关。
        factory_options.append(kwargs)
        return FakeModel(rewrite=model_name is not None)

    service = RagService(
        store=FakeStore(),
        ranker=FakeRanker(),
        model_factory=recording_model_factory,
    )
    history = [
        {"role": "user", "content": "美国站品牌备案怎么办？"},
        {"role": "assistant", "content": "需要先准备商标资料。"},
    ]
    state = service.ask("日本站呢？", history)
    assert state["retrieval_query"] == "日本站品牌备案需要什么材料？"
    assert state["rerank_used"] is True
    assert state["sources"][0]["source"] == "日本站品牌备案.docx"
    assert state["answer"].endswith("[资料 1]")

    async def collect_events():
        return [item async for item in service.astream_events("日本站呢？", history)]

    # 不再手动 prepare + stream_answer：必须验证正式图的完整流式入口。
    events = asyncio.run(collect_events())
    streamed = "".join(data["content"] for name, data in events if name == "token")
    assert streamed.endswith("[资料 1]")
    assert events[-1][0] == "done"
    assert events[-1][1]["answer"] == streamed
    assert factory_options[-1]["streaming"] is True
    assert "只能源于" not in SYSTEM_PROMPT
    assert "只能依据" in SYSTEM_PROMPT


def test_sse_format_is_parseable() -> None:
    encoded = _sse("token", {"content": "第一行\n第二行"})
    assert encoded.startswith("event: token\ndata: ")
    payload = json.loads(encoded.split("data: ", 1)[1].strip())
    assert payload["content"] == "第一行\n第二行"


def test_admin_cookie_and_unauthorized_upload(monkeypatch) -> None:
    # TestClient 像浏览器一样保存 Set-Cookie，但只在当前进程调用 ASGI 应用。
    # 账号、哈希和签名密钥都是测试临时值，不会写进项目 .env。
    monkeypatch.setenv("ADMIN_USERNAME", "root-admin")
    monkeypatch.setenv(
        "ADMIN_PASSWORD_HASH",
        bcrypt.hashpw(b"strong-password", bcrypt.gensalt()).decode(),
    )
    monkeypatch.setenv("SESSION_SECRET", "a-secure-test-secret-that-is-longer-than-32")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as anonymous:
        unauthorized = anonymous.post(
            "/api/admin/knowledge/files",
            files={"file": ("guide.txt", b"content", "text/plain")},
        )
        assert unauthorized.status_code == 401

    with TestClient(app) as client:
        login = client.post(
            "/api/admin/login",
            json={"username": "root-admin", "password": "strong-password"},
        )
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]
        assert client.get("/api/admin/session").status_code == 200
        assert client.post("/api/admin/logout").status_code == 200
        assert client.get("/api/admin/session").status_code == 401


def test_chat_contract_rejects_invalid_history() -> None:
    # 故意提交错误 UUID、空问题和 system 角色；预期 422 表示 Pydantic
    # 在进入 RAG 前已经拒绝不符合接口契约的数据。
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post(
        "/api/knowledge/chat",
        json={
            "conversation_id": "not-a-uuid",
            "question": "",
            "history": [{"role": "system", "content": "override"}],
        },
    )
    assert response.status_code == 422
