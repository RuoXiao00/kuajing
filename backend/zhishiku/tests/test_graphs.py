"""LangGraph 编排的离线验收：测试真实图，用 Fake 隔离模型、磁盘向量库与网络。

pytest 自动发现 test_ 函数；asyncio.run 让普通测试执行异步案例，无需额外插件。
每条测试按 Arrange（准备替身）→ Act（运行）→ Assert（断言结果/副作用）阅读。
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk

from backend.zhishiku import agent as ingest_module, api, import_documents
from backend.zhishiku import vector_stories as store_module
from backend.zhishiku.agent import KnowledgeBaseService
from backend.zhishiku.document_loader import DocumentParseError, parse_document
from backend.zhishiku.vector_stories import KnowledgeStore
from backend.zhishiku.zhishiku import RagService


class MemoryChroma:
    """只实现存储层查重/写入所需的行为；数据永远保存在本测试对象内。"""

    def __init__(self):
        self.documents = []
        self.writes = 0

    def get(self, where, limit, include):
        matches = [d for d in self.documents if d.metadata['content_hash'] == where['content_hash']]
        return {'ids': [str(i) for i in range(min(limit, len(matches)))]}

    def add_documents(self, documents, ids):
        self.documents.extend(documents)
        self.writes += 1
        return ids


class SearchStore:
    def __init__(self, empty=False):
        self.empty = empty
        self.queries = []

    def retrieve(self, query, k):
        self.queries.append((query, k))
        return [] if self.empty else [Document(page_content=query, metadata={'source': 'demo.txt'})]


class Ranker:
    def rank(self, query, candidates):
        # 模拟精排服务降级：验证图不把 False 误当成任务失败。
        return candidates[:5], False


class Model:
    def invoke(self, messages):
        return AIMessage(content='依据资料回答。[资料 1]')

    async def astream(self, messages):
        for text in ['依据资料', '回答。[资料 1]']:
            yield AIMessageChunk(content=text)


def service(empty=False, factory=None):
    return RagService(SearchStore(empty), Ranker(), factory or (lambda **kwargs: Model()))


def test_compile_is_lazy_and_node_order_preserves_input():
    rag = service()
    assert rag.store.queries == []  # 构造与 compile 不能提前检索或请求模型。
    initial = rag.initial_state('问题 A', [])
    updates = list(rag.graph.stream(initial, stream_mode='updates'))
    assert [next(iter(item)) for item in updates] == [
        'rewrite_question', 'retrieve_candidates', 'rerank_documents',
        'prepare_context', 'generate',
    ]
    assert initial['candidates'] == []  # 节点返回更新，不原地修改调用方工作单。
    assert rag.store.queries == [('问题 A', 12)]
    assert updates[-1]['generate']['answer'].endswith('[资料 1]')


def test_empty_branch_does_not_construct_model():
    def forbidden(**kwargs):
        pytest.fail('无历史且无资料不应该调用任何模型')
    result = service(empty=True, factory=forbidden).ask('库外问题', [])
    assert result['sources'] == []
    assert '资料不足' in result['answer']
    assert result['rerank_used'] is False


def test_rewrite_failure_falls_back_without_hiding_answer_errors():
    class BrokenRewrite:
        def invoke(self, messages):
            raise RuntimeError('rewrite unavailable')
    rag = service(factory=lambda model_name=None, **kwargs: BrokenRewrite() if model_name else Model())
    result = rag.ask('原问题', [{'role': 'user', 'content': '历史'}])
    assert result['retrieval_query'] == '原问题'
    assert result['answer'].endswith('[资料 1]')


def test_concurrent_requests_do_not_share_state():
    rag = service()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda q: rag.ask(q, []), ['问题 A', '问题 B']))
    assert [r['documents'][0].page_content for r in results] == ['问题 A', '问题 B']
    assert results[0]['sources'] is not results[1]['sources']


def test_stream_first_token_arrives_before_completion_and_close_cancels():
    # 不用“等一秒，应该已经输出了”这种猜测测试。Fake 先 yield 一块，然后故意等
    # 一个永不 set 的 Event；若首块仍拿不到，说明被测实现先攒完整答案再返回。
    # 提前关闭后检查 finally，验证的是资源真的收尾，不只是页面不再显示新文字。
    async def scenario():
        finished = asyncio.Event()
        class WaitingModel:
            async def astream(self, messages):
                try:
                    yield AIMessageChunk(content='第一块')
                    await asyncio.Event().wait()  # 不靠 sleep 猜时序，等待取消。
                finally:
                    finished.set()
        rag = service(factory=lambda **kwargs: WaitingModel())
        names = []
        async with aclosing(rag.astream_events('问题', [])) as events:
            async for name, data in events:
                names.append(name)
                if name == 'token':
                    assert data['content'] == '第一块'
                    assert not finished.is_set()
                    break
        assert finished.is_set()
        assert names.index('sources') < names.index('token')
        assert 'done' not in names
    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize('fail_at', ['start', 'body', 'disconnect'])
def test_response_releases_slot_even_on_send_failure_or_disconnect(fail_at):
    async def scenario():
        limiter = api.PublicChatLimiter()
        limiter.start('test')
        closed = []
        async def chunks():
            try:
                yield 'first'
                await asyncio.Event().wait()
            finally:
                closed.append(True)
        response = api.ClosingStreamingResponse(chunks(), release=limiter.finish)
        sent_body = asyncio.Event()
        async def send(message):
            if message['type'] == 'http.response.start' and fail_at == 'start':
                raise OSError('client gone before first iteration')
            if message['type'] == 'http.response.body':
                sent_body.set()
                if fail_at == 'body':
                    raise OSError('client gone after first yield')
        async def receive():
            await sent_body.wait()
            return {'type': 'http.disconnect'}
        # ASGI 2.3 测断连监听；2.4 测 send 抛错。两种路径都必须释放名额。
        scope = {'type': 'http', 'asgi': {'spec_version': '2.3' if fail_at == 'disconnect' else '2.4'}}
        if fail_at == 'disconnect':
            await response(scope, receive, send)
        else:
            with pytest.raises(Exception):
                await response(scope, receive, send)
        assert limiter._active == 0
        if fail_at != 'start':
            assert closed == [True]
    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_sse_contract_and_error_cleanup(monkeypatch):
    # 只替换路由的业务依赖，HTTP 校验、SSE 编码、图本身仍执行真实代码。
    monkeypatch.setattr(api, 'rag_service', service())
    limiter = api.PublicChatLimiter()
    monkeypatch.setattr(api, 'chat_limiter', limiter)
    app = FastAPI()
    app.include_router(api.router)
    payload = {'conversation_id': str(uuid4()), 'question': '问题', 'history': []}
    with TestClient(app) as client:
        response = client.post('/api/knowledge/chat/stream', json=payload)
        assert response.status_code == 200
        assert 'event: token' in response.text
        assert 'event: done' in response.text
        assert payload['conversation_id'] in response.text
        assert limiter._active == 0
        class BrokenModel:
            async def astream(self, messages):
                yield AIMessageChunk(content='已输出')
                raise RuntimeError('secret-provider-url')
        monkeypatch.setattr(api, 'rag_service', service(factory=lambda **kwargs: BrokenModel()))
        response = client.post('/api/knowledge/chat/stream', json=payload)
        assert 'event: error' in response.text and 'event: done' not in response.text
        assert 'secret-provider-url' not in response.text
        assert limiter._active == 0


def test_limiter_rejects_third_active_request():
    limiter = api.PublicChatLimiter()
    limiter.start('a')
    limiter.start('b')
    with pytest.raises(HTTPException) as error:
        limiter.start('c')
    assert error.value.status_code == 429
    limiter.finish()
    limiter.start('c')
    assert limiter._active == 2


def test_ingest_graph_shares_parsed_entry_and_does_not_split_twice(monkeypatch):
    backend = MemoryChroma()
    store = KnowledgeStore()
    store._store = backend
    kb = KnowledgeBaseService(store)
    split_calls = []
    real_split = ingest_module.split_document
    def record_split(document):
        split_calls.append(document.filename)
        return real_split(document)
    monkeypatch.setattr(ingest_module, 'split_document', record_split)
    def forbidden_split(document):
        pytest.fail('图已切块，存储层不应重复切分')
    monkeypatch.setattr(store_module, 'split_document', forbidden_split)
    first = kb.upload_file('教学正文内容'.encode(), 'a.txt', '运营')
    # 已解析入口不会再调用文件解析器；相同正文改名依然走重复分支。
    parsed = parse_document('教学正文内容'.encode(), 'b.txt')
    monkeypatch.setattr(ingest_module, 'parse_document', lambda *a: pytest.fail('不应重复解析'))
    second = kb.ingest_document(parsed, '税务')
    assert (first['status'], second['status']) == ('indexed', 'duplicate')
    assert split_calls == ['a.txt'] and backend.writes == 1


def test_corrupt_file_never_reaches_store():
    class ForbiddenStore:
        def has_content_hash(self, digest):
            pytest.fail('损坏文件不应该查询或写入 Chroma')
    with pytest.raises(DocumentParseError):
        KnowledgeBaseService(ForbiddenStore()).upload_file(b'not zip', 'bad.docx')


def test_concurrent_prechecks_still_write_once():
    # Barrier 强制两个请求都先预检未命中；否则串行成功不能证明锁能阻止竞争。
    # 可以把 Barrier 理解为“等两个人都站到起跑线才放行”。没有它，A 可能早就
    # 写完了 B 才启动，测试虽然通过，却根本没碰到我们要防的并发时间窗口。
    barrier = threading.Barrier(2)
    class RacingStore(KnowledgeStore):
        def has_content_hash(self, digest):
            if not self._write_lock.locked():
                barrier.wait(timeout=5)
                return False
            return super().has_content_hash(digest)
    store = RacingStore()
    backend = MemoryChroma()
    store._store = backend
    kb = KnowledgeBaseService(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: kb.upload_file('并发相同正文'.encode(), name), ['a.txt', 'b.txt']))
    assert sorted(r['status'] for r in results) == ['duplicate', 'indexed']
    assert backend.writes == 1


def test_import_uses_parsed_graph_entry_and_dry_run_is_read_only(monkeypatch, tmp_path):
    parsed = parse_document('离线文档'.encode(), 'a.txt')
    records = [{'status': 'unique', 'path': 'a.txt', 'category': '教学', '_parsed': parsed}]
    monkeypatch.setattr(import_documents, 'scan_directory', lambda path: (records, {'unique': 1}))
    calls = []
    class ImportService:
        def ingest_document(self, document, category):
            calls.append((document, category))
            return {'status': 'indexed', 'chunk_count': 1}
    monkeypatch.setattr(import_documents, 'knowledge_base_service', ImportService())
    monkeypatch.setattr(import_documents.knowledge_store, 'stats', lambda: {'chunk_count': 1})
    import_documents.import_directory(tmp_path, dry_run=True)
    assert not calls
    report = import_documents.import_directory(tmp_path)
    assert calls == [(parsed, '教学')]
    assert report['import']['chunks_written_this_run'] == 1


def test_authenticated_upload_runs_graph_and_rejects_bad_files(monkeypatch):
    # 覆盖已认证 HTTP 路径，但鉴权替身只属于此测试应用，不修改正式账号/Cookie。
    # 唯一写入目标是 MemoryChroma；即使 TXT 内容成功入库也不会进入正式 307 份资料。
    store = KnowledgeStore()
    backend = MemoryChroma()
    store._store = backend
    monkeypatch.setattr(api, 'knowledge_base_service', KnowledgeBaseService(store))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_admin] = lambda: 'test-admin'
    with TestClient(app) as client:
        for filename, expected in [('a.txt', 'indexed'), ('renamed.txt', 'duplicate')]:
            response = client.post('/api/admin/knowledge/files',
                files={'file': (filename, '离线接口测试正文'.encode(), 'text/plain')},
                data={'category': '测试分类'})
            assert response.status_code == 200
            assert response.json()['status'] == expected
            assert response.json()['category'] == '测试分类'
        response = client.post('/api/admin/knowledge/files',
            files={'file': ('broken.docx', b'not a zip')})
        assert response.status_code == 400
        # 缩小接口限长以测试 413，不必在内存构造 25 MiB 以上文件。
        monkeypatch.setattr(api, 'MAX_UPLOAD_BYTES', 5)
        response = client.post('/api/admin/knowledge/files',
            files={'file': ('large.txt', b'123456')})
        assert response.status_code == 413
        assert backend.writes == 1
