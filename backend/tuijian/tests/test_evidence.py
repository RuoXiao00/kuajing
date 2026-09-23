"""证据先行的行为测试：默认网络禁用，模型和本机爬虫都用替身。"""
import copy
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from backend.tuijian import evidence
from backend.tuijian.daily import snapshot_payload


@pytest.fixture
def rec(monkeypatch):
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-not-a-real-key')
    module = importlib.import_module('backend.tuijian.agent')
    monkeypatch.setattr(module, 'collect_public_sources', lambda *args: [])
    return module


def test_source_parser_rejects_error_page_and_deduplicates_asin():
    assert evidence.parse_source('bestsellers', b'<title>Sorry!</title>') == []
    assert evidence.parse_source('movers', b'<a href="/dp/B012345678">Amazon Business Card</a>') == []
    body = b'<div id="gridItemRoot"><span class="zg-bdg-text">#1</span><a href="/dp/B012345678"><img alt="A real useful product title"></a></div>' * 2
    items = evidence.parse_source('bestsellers', body)
    assert len(items) == 1 and items[0]['url'] == 'https://www.amazon.com/dp/B012345678'
    with pytest.raises(ValueError):
        evidence.parse_source('trends', b'<!DOCTYPE x><rss/>')


def test_public_source_failure_and_retry_only_missing(monkeypatch):
    calls = []
    def download(url):
        calls.append(url)
        return b'<rss><channel><item><title>water bottle</title><pubDate>today</pubDate></item></channel></rss>'
    monkeypatch.setattr(evidence, '_download', download)
    monkeypatch.setattr(evidence.time, 'sleep', lambda _: None)
    first = evidence.collect_public_sources('2026-09-21T05:00:00+08:00')
    assert [s['status'] for s in first] == ['unavailable'] * 3 + ['ok']
    evidence.collect_public_sources('2026-09-21T05:15:00+08:00', first)
    assert len(calls) == 7  # 热搜已成功，补试不再抓一次。


def test_plan_explores_less_recommended_families_and_rotates_keywords():
    a = evidence.exploration_plan('2026-09-21T05:00:00+08:00', [])
    history = [{'categories':[{'candidate_id': c['candidate_id']} for c in a]}]
    b = evidence.exploration_plan('2026-09-22T05:00:00+08:00', history)
    assert len(a) == len(b) == 16
    assert set(c['candidate_id'] for c in b[:4]).isdisjoint(c['candidate_id'] for c in a)
    assert any(c['keyword'] != next(x['keyword'] for x in a if x['candidate_id'] == c['candidate_id'])
               for c in b if c['candidate_id'] in {x['candidate_id'] for x in a})


def test_no_evidence_means_no_model_call(rec, monkeypatch):
    monkeypatch.setattr(rec, '_invoke_model', lambda *args: pytest.fail('无证据不得调用模型'))
    with pytest.raises(rec.ProductEvidenceError):
        rec.start_analyze({'step_num':0})


def test_graph_collects_before_model_and_rejects_invented_ids(rec, monkeypatch):
    events, checkpoints = [], []
    monkeypatch.setattr(rec, 'exploration_plan', lambda *args: [
        {'candidate_id':'home','title':'家居','keyword':'organizer'},
        {'candidate_id':'office','title':'办公','keyword':'desk stand'}])
    class Crawler:
        def collect(self, keyword, **kwargs):
            events.append('fetch:' + keyword)
            return SimpleNamespace(products=[rec.Product(asin='B012345678', title='Real useful stand',
                url='https://www.amazon.com/dp/B012345678', price=15, currency='USD')],
                pages=[], error=None, stop_reason='page_limit')
    def invoke(messages, node):
        events.append(node)
        if node == 'start_analyze':
            assert len(json.loads(messages[-1].content)['candidates']) == 2
            return AIMessage(content=json.dumps({'categories':[
                {'candidate_id':'invented','reason':'假证据'},
                {'candidate_id':'home','reason':'实际采样15美元', 'supporting_evidence_ids':['fake']},
                {'candidate_id':'home','reason':'重复'},
                {'candidate_id':'office','reason':'真实支架'}]}))
        return AIMessage(content=json.dumps({'categories':[{'title':'家居','answer':'实际商品价格15美元，缺少历史。'}]}))
    monkeypatch.setattr(rec, 'AmazonCrawler', Crawler)
    monkeypatch.setattr(rec, '_invoke_model', invoke)
    result = rec.generate_recommendations([], {}, datetime.now(timezone.utc), lambda c: checkpoints.append(copy.deepcopy(c)))
    assert events == ['fetch:organizer','fetch:desk stand','start_analyze','sum_up']
    assert [c['candidate_id'] for c in result['categories']] == ['home','office']
    assert len(result['products']) == 1  # 两个类别相同 ASIN，不能伪装成两件商品。
    assert result['categories'][0]['evidence_links'] == []
    assert checkpoints[1]['candidate_pool'][0]['products']
    public = snapshot_payload(result)
    assert public['evidence']['candidate_products'] == 1
    assert 'candidate_pool' not in public  # 候选全集仅供恢复，不膨胀页面响应。


def test_candidate_checkpoint_resume_reuses_success(rec, monkeypatch):
    calls = []
    class Crawler:
        def collect(self, keyword, **kwargs):
            calls.append(keyword)
            raise rec.CrawlError('amazon_blocked', 'secret not for output')
    state = {'step_num':0,'run_at':'2026-09-21T05:00:00+08:00','crawler':Crawler(),
        'candidate_pool':[
            {'candidate_id':'a','keyword':'a','fetch_complete':True,'products':[{'asin':'x'}]},
            {'candidate_id':'b','keyword':'b'}, {'candidate_id':'c','keyword':'c'}]}
    result = rec.collect_market_evidence(state)
    assert calls == ['b']
    assert result['candidate_pool'][0]['products'] == [{'asin':'x'}]
    assert result['candidate_pool'][2]['fetch_error'] == 'upstream_stopped'


def test_recent_products_only_kept_when_needed(rec):
    items = [{'asin':str(i),'sales_count_min':100-i} for i in range(10)]
    chosen = rec._select_products(items, {'0','1','2','3','4'}, set())
    assert [p['asin'] for p in chosen] == ['0','1','5','6','7']
    assert len(rec._select_products(items[:3], {'0','1','2'}, set())) == 3


def test_unsubstantiated_growth_and_sales_are_replaced_by_real_facts(rec):
    category = {'products':[{'title':'Real stand','sales':'100+ bought in past month',
                 'amount':15,'currency':'USD','rating_value':4.5,'review_count':26}]}
    answer, warning = rec._safe_analysis('月销量1000，市场需求持续增长。', category)
    assert '1000' not in answer and '15 USD' in answer and '100+' in answer
    assert warning and '不能据此判断市场增长' in answer
    assert rec._safe_analysis('公开近月购买提示100+，缺少可比历史。', category)[1] == ''


def test_browser_failure_is_data_error_and_stops_repeated_launches(rec):
    calls = []
    class Crawler:
        def collect(self, *args, **kwargs):
            calls.append(args)
            raise rec.CrawlError('browser_unavailable', 'private body')
    state = {'step_num':0, 'run_at':'2026-09-22T05:00:00+08:00', 'crawler':Crawler(),
        'candidate_pool':[{'candidate_id':str(i),'keyword':'test'} for i in range(16)]}
    result = rec.collect_market_evidence(state)
    assert len(calls) == 1
    with pytest.raises(rec.ProductEvidenceError) as caught:
        rec.start_analyze({**state, **result})
    assert rec._classify_model_error(caught.value)[0] == 'product_browser_unavailable'
    assert 'private' not in rec._classify_model_error(caught.value)[1]


def test_saved_legacy_model_error_is_explained_by_actual_checkpoint():
    from backend.tuijian.daily import data_failure_message
    message = data_failure_message({'candidate_pool':[{'fetch_error':'browser_unavailable','products':[]}]})
    assert '浏览器' in message and '格式' not in message
    assert data_failure_message({'candidate_pool':[{'products':[{'asin':'actual'}]}]}) == ''


def test_legacy_snapshot_display_does_not_rewrite_original_or_generate(rec, monkeypatch):
    original = {'categories':[{'answer':'月销量1000，持续增长。',
        'products':[{'title':'真实商品','amount':15,'currency':'USD','sales':'100+ bought in past month'}]}]}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        recommendations=SimpleNamespace(latest=lambda:original))))
    monkeypatch.setattr(rec, '_invoke_model', lambda *args: pytest.fail('只读展示不能调用模型'))
    result = rec.get_latest_recommendations(request)
    assert result['presentation_version'] == 1
    assert '1000' not in result['categories'][0]['answer']
    assert '1000' in original['categories'][0]['answer']
    assert result['categories'][0]['analysis_warning']
