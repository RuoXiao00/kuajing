"""推荐故障回归：所有模型/商品查询均用 Fake，不消耗 DashScope 或抓取额度。"""
import copy
import importlib
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError, APITimeoutError, APIStatusError


@pytest.fixture
def rec(monkeypatch):
    # 先提供测试配置再导入；创建客户端不等于发请求，invoke 会在各用例被替换。
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-not-a-real-key')
    module = importlib.import_module('backend.tuijian.agent')
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(module, 'collect_public_sources', lambda *args: [])
    return module


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return AIMessage(content=response)


def connection_error():
    return APIConnectionError(request=httpx.Request('POST', 'https://example.invalid'))


def status_error(status, message):
    response = httpx.Response(status, request=httpx.Request('POST', 'https://example.invalid'))
    return APIStatusError(message, response=response, body={'message': message})


def categories():
    return [{'title': 'Backpacks', 'keyword': 'backpack', 'status': 'success', 'error': '',
             'products': [{'title': '真实背包', 'price': {'value': 25, 'currency': 'USD'},
                           'image_url': 'https://example.invalid/image', 'url': 'https://example.invalid/product',
                           'rating_value': 4.5, 'review_count': 20, 'sales': '100+'}]}]


def test_compact_payload_does_not_change_products(rec):
    original = categories()
    before = copy.deepcopy(original)
    payload = rec._analysis_payload(original)
    assert len(payload) <= 24000
    assert 'https://' not in payload
    assert '真实背包' in payload
    assert original == before


def test_escaping_and_huge_fields_still_fit_complete_json(rec):
    data = categories() * 10
    for category in data:
        category['title'] = '\x00' * 300
        category['products'] = [{key: '\x00' * 2000 for key in
                                 ('title', 'price', 'rating_value', 'review_count', 'sales')} for _ in range(5)]
    payload = rec._analysis_payload(data)
    assert len(payload) <= 24000
    assert len(json.loads(payload)) == 10


@pytest.mark.parametrize('error,code,status,retry', [
    (connection_error(), 'model_connection_failed', 502, True),
    (APITimeoutError(request=httpx.Request('POST', 'https://example.invalid')), 'model_timeout', 504, True),
    (status_error(429, 'rate limit'), 'rate_limited_429', 429, True),
    (status_error(429, 'insufficient_quota'), 'quota_exhausted', 503, False),
    (status_error(401, 'invalid api key'), 'authentication_failed', 502, False),
    (status_error(503, 'server failure'), 'upstream_unavailable', 503, True),
    (status_error(400, 'bad request'), 'model_request_rejected', 502, False),
])
def test_classification_and_retry_budget(rec, monkeypatch, error, code, status, retry):
    # Arrange：准备连续失败的替身；Act：调用真正的重试函数；Assert：精确检查次数。
    fake = FakeModel([error, error])
    monkeypatch.setattr(rec, 'model', fake)
    assert rec._classify_model_error(error)[::2] == (code, status)
    assert rec._retryable(code) is retry
    with pytest.raises(type(error)):
        rec._invoke_model([HumanMessage(content='test')], 'test_node')
    assert len(fake.calls) == (2 if retry else 1)


def test_retry_can_recover_and_logs_do_not_contain_exception_body(rec, monkeypatch, caplog):
    error = connection_error()
    error.args = ('secret-token must not enter log https://example.invalid/?token=secret-token',)
    fake = FakeModel([error, 'OK'])
    monkeypatch.setattr(rec, 'model', fake)
    assert rec._invoke_model([], 'sum_up').content == 'OK'
    assert 'node=sum_up' in caplog.text
    assert 'secret-token' not in caplog.text


def test_invalid_category_json_is_explicit_failure(rec, monkeypatch):
    fake = FakeModel(['not JSON'])
    monkeypatch.setattr(rec, 'model', fake)
    with pytest.raises(rec.ResponseFormatError):
        rec.start_analyze({'message': [], 'step_num': 0, 'candidate_pool': [{
            'candidate_id':'travel', 'title':'Backpacks', 'keyword':'backpack',
            'fetch_complete':True, 'products':categories()[0]['products']}]})
    assert len(fake.calls) == 1


@pytest.mark.parametrize('responses,expected', [
    ([connection_error(), connection_error()], 'model_connection_failed'),
    (['not JSON'], 'response_json_invalid'),
    (['{"categories":[{"title":"Backpacks","answer":null}]}'], 'response_json_invalid'),
])
def test_failed_analysis_preserves_real_products(rec, monkeypatch, responses, expected):
    monkeypatch.setattr(rec, 'model', FakeModel(responses))
    before = categories()
    result = rec.sum_up({'categories': before, 'step_num': 2})
    assert result['categories'][0]['products'] == before[0]['products']
    assert result['categories'][0]['analysis_status'] == expected
    assert result['categories'][0]['answer'] == ''
    assert '分析暂时失败' in result['categories'][0]['error']
    assert result['message'] == []


def test_graph_keeps_products_when_analysis_fails_without_refetch(rec, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    fake = FakeModel(['{"categories":[{"candidate_id":"travel","reason":"真实背包样本"}]}',
                      connection_error(), connection_error()])
    monkeypatch.setattr(rec, 'model', fake)
    fetch_calls = []
    monkeypatch.setattr(rec, 'exploration_plan', lambda *args: [
        {'candidate_id':'travel','title':'Backpacks','keyword':'backpack'}])
    class Crawler:
        def __init__(self, **kwargs):
            pass
        def collect(self, keyword, **kwargs):
            fetch_calls.append(keyword)
            product = rec.Product(asin='B012345678', title='真实背包', url='https://www.amazon.com/dp/B012345678')
            return SimpleNamespace(products=[product], pages=[], error=None, stop_reason='page_limit')
    monkeypatch.setattr(rec, 'AmazonCrawler', Crawler)
    result = rec.generate_recommendations([], {}, datetime.now(timezone.utc), lambda _: None)
    assert result['answer'] == ''
    assert result['products'][0]['title'] == '真实背包'
    assert len(fetch_calls) == 1
    assert len(fake.calls) == 3


def test_http_without_service_never_invokes_model(rec, monkeypatch):
    fake = FakeModel([])
    monkeypatch.setattr(rec, 'model', fake)
    app = FastAPI()
    app.include_router(rec.router)
    assert TestClient(app).get('/tuijian/agentcall').status_code == 503
    assert fake.calls == []


def test_successful_analysis_protocol_and_timeout_settings(rec, monkeypatch):
    assert rec.model.request_timeout.connect == 10
    assert rec.model.request_timeout.read == 60
    assert rec.model.max_retries == 0
    monkeypatch.setattr(rec, 'model', FakeModel(['{"categories":[{"title":"Backpacks","answer":"依据真实评分分析"}]}']))
    result = rec.sum_up({'categories': categories(), 'step_num': 2})
    assert result['categories'][0]['analysis_status'] == 'success'
    assert result['step_num'] == 3


def test_product_fetch_error_does_not_leak_token(rec, monkeypatch, caplog):
    class Crawler:
        def collect(self, *args, **kwargs):
            raise rec.CrawlError('upstream_connection_error', 'secret-token must not be exposed')
    result = rec.collect_product_data({'categories': [{'title':'Backpacks','keyword':'backpack'}],
                                      'crawler': Crawler(), 'step_num':1})
    assert result['categories'][0]['status'] == 'error'
    assert 'secret-token' not in json.dumps(result) + caplog.text
