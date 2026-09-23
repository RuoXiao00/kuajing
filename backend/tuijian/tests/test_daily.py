"""每日推荐回归：固定时钟、临时 SQLite、Fake 模型/爬虫，不访问真实收费服务。"""
import asyncio
import copy
import importlib
import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from backend.tuijian.daily import BEIJING, DailyRecommendations, RecommendationStore, schedule_slot


@pytest.fixture
def rec(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-not-a-real-key")
    module = importlib.import_module("backend.tuijian.agent")
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


class Clock:
    def __init__(self, value="2026-09-21T04:59:00+08:00"):
        self.now = datetime.fromisoformat(value)
    def __call__(self):
        return self.now


def complete_payload(label="first"):
    return {"categories": [{"title": f"Category {i}", "keyword": f"keyword {i}",
        "products": [{"asin": f"B{i:09d}", "title": label}], "fetch_complete": True,
        "analysis_status": "success", "answer": label, "status": "partial"} for i in range(10)]}


def service(tmp_path, clock, generator):
    return DailyRecommendations(tmp_path / "daily.sqlite3", clock=clock, generator=generator)


def test_boundary_timezone_startup_and_restart_idempotence(tmp_path, rec):
    clock, calls = Clock(), []
    def generate(*args):
        calls.append(args[2])
        return complete_payload()
    daily = service(tmp_path, clock, generate)
    assert schedule_slot(clock()).isoformat() == "2026-09-20T05:00:00+08:00"
    assert schedule_slot(clock().astimezone(__import__('datetime').timezone.utc)) == schedule_slot(clock())
    assert daily.tick() is True  # 首次没有历史，05:00之前也生成一份当前周期的结果。
    assert daily.tick() is False
    clock.now += timedelta(minutes=1)
    assert daily.tick() is True
    replacement = service(tmp_path, clock, generate)
    replacement.store.recover(clock())
    assert replacement.tick() is False
    assert len(calls) == 2
    clock.now += timedelta(days=4)
    assert replacement.tick() is True
    assert len(calls) == 3  # 只补最新一期，不连续生成漏掉的四天。


def test_partial_preserves_complete_and_retry_once_reuses_checkpoint(tmp_path, rec):
    clock, calls = Clock("2026-09-21T06:00:00+08:00"), []
    def generate(history, prior, now, checkpoint, stop):
        calls.append(copy.deepcopy(prior))
        if len(calls) == 1:
            return complete_payload()
        value = complete_payload("partial")
        value["categories"][0]["analysis_status"] = "failed"
        checkpoint(value)
        return value
    daily = service(tmp_path, clock, generate)
    daily.tick()
    first = daily.latest()
    clock.now += timedelta(days=1)
    daily.tick()
    failed = daily.latest()
    assert failed["snapshot_id"] == first["snapshot_id"]
    assert failed["is_stale"] and failed["update_status"] == "update_failed"
    assert daily.tick() is False
    clock.now += timedelta(minutes=14, seconds=59)
    assert daily.tick() is False
    clock.now += timedelta(seconds=1)
    assert daily.tick() is True
    assert calls[-1]["categories"][0]["analysis_status"] == "failed"
    clock.now += timedelta(hours=1)
    assert daily.tick() is False
    assert daily.latest()["retry_at"] is None
    assert len(calls) == 3


def test_initial_partial_then_success_atomically_replaces(tmp_path, rec):
    clock, count = Clock(), 0
    def generate(*args):
        nonlocal count
        count += 1
        payload = complete_payload()
        if count == 1:
            payload["categories"][0]["analysis_status"] = "failed"
        return payload
    daily = service(tmp_path, clock, generate)
    daily.tick()
    assert daily.latest()["partial"]
    clock.now += timedelta(minutes=15)
    daily.tick()
    assert not daily.latest()["partial"]
    assert daily.latest()["update_status"] == "ready"


def test_empty_and_failure_do_not_publish_fake_data(tmp_path, rec):
    clock = Clock()
    def generate(*args):
        raise RuntimeError("secret exception must not be exposed")
    daily = service(tmp_path, clock, generate)
    daily.tick()
    state = daily.latest()
    assert state["categories"] == [] and state["snapshot_id"] is None
    assert "secret" not in json.dumps(state)
    assert state["update_status"] == "update_failed"


def test_interrupted_task_uses_remaining_budget_and_persisted_data(tmp_path, rec):
    clock = Clock()
    daily = service(tmp_path, clock, lambda *args: complete_payload())
    slot = schedule_slot(clock()).isoformat()
    daily.store.claim(slot, clock())
    daily.store.checkpoint(slot, {"categories": [{"title": "saved", "keyword": "saved"}]})
    daily.store.recover(clock())
    attempt, prior = daily.store.claim(slot, clock())
    assert attempt == 2 and prior["categories"][0]["title"] == "saved"
    daily.store.recover(clock())
    assert daily.store.claim(slot, clock()) is None


def test_http_is_read_only_including_empty_and_legacy_keyword(tmp_path, rec, monkeypatch):
    clock = Clock()
    def forbidden(*args, **kwargs):
        pytest.fail("GET must not generate or crawl")
    daily = service(tmp_path, clock, forbidden)
    monkeypatch.setattr(rec.graph, "invoke", forbidden)
    monkeypatch.setattr(rec.AmazonCrawler, "collect", forbidden)
    app = FastAPI()
    app.state.recommendations = daily
    app.include_router(rec.router)
    client = TestClient(app)
    for _ in range(3):
        for path in ["/api/recommendations/latest", "/tuijian/agentcall"]:
            response = client.get(path)
            assert response.status_code == 200
            assert response.json()["categories"] == []
    assert client.get('/tuijian/agentcall?keyword=shoes').status_code == 422
    with daily.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_single_flight_and_reader_sees_only_published_snapshot(tmp_path, rec):
    clock, entered, release = Clock(), threading.Event(), threading.Event()
    def generate(*args):
        entered.set()
        assert release.wait(5)
        return complete_payload()
    daily = service(tmp_path, clock, generate)
    thread = threading.Thread(target=daily.tick)
    thread.start()
    assert entered.wait(5)
    try:
        assert daily.tick() is False
        assert daily.latest()["snapshot_id"] is None
        assert daily.latest()["update_status"] == "updating"
    finally:
        release.set()
        thread.join(5)
    assert daily.latest()["update_status"] == "ready"


def test_history_seven_days_and_retention_keeps_last_good(tmp_path, rec):
    clock = Clock()
    daily = service(tmp_path, clock, lambda *args: complete_payload())
    daily.tick()
    clock.now += timedelta(days=8)
    assert daily.store.history(clock(), schedule_slot(clock()).isoformat()) == []
    clock.now += timedelta(days=40)
    slot = schedule_slot(clock()).isoformat()
    daily.store.claim(slot, clock())
    daily.store.finish(slot, {}, clock(), error="failed")
    assert daily.latest()["products"]  # 保留最后可用结果，而不是故障30天后清空。


def test_category_normalization_and_rotation(rec):
    data = {"categories": [{"title":"Backpacks", "keyword":"Travel Bag"},
        {"title":"backpacks!", "keyword":"other"}, {"title":"Other", "keyword":"travel  bag!"},
        {"title":"Desk Lamp", "keyword":"desk lamp"}]}
    assert len(rec._extract_categories(json.dumps(data))) == 2
    candidates = [{"asin":str(i), "sales_count_min":100-i, "review_count":20} for i in range(9)]
    used = set()
    chosen = rec._select_products(candidates, {'3','4'}, used)
    assert [p['asin'] for p in chosen] == ['0','1','2','5','6']
    second = rec._select_products(candidates, set(), used)
    assert not ({p['asin'] for p in chosen} & {p['asin'] for p in second})


def test_crawler_adapter_preserves_currency_and_unknown_fields(rec):
    for amount, currency in [(1234, 'JPY'), (19.99, 'SGD'), (12, 'USD'), (15, 'GBP'), (0, 'USD'), (None, None)]:
        item = rec.Product(asin='B012345678', title='item', url='https://www.amazon.com/dp/B012345678',
                           price=amount, currency=currency, price_display=str(amount), review_count=0)
        result = rec._normalize_product(item)
        assert result['amount'] == (amount if amount and amount > 0 else None)
        assert result['currency'] == currency
        assert result['review_count'] == 0 and result['sales'] is None


def test_graph_retry_only_failed_fetch_and_analysis(rec, monkeypatch):
    payload = complete_payload()
    payload['categories'][2].update(fetch_complete=False, products=[], analysis_status='pending')
    payload['categories'][4].update(analysis_status='failed', answer='')
    calls, model_calls = [], []
    class Crawler:
        def collect(self, keyword, **kwargs):
            calls.append((keyword, kwargs))
            return SimpleNamespace(products=[rec.Product(asin='B999999999',title='real',url='https://www.amazon.com/dp/B999999999')],
                                   pages=[], error=None, stop_reason='page_limit')
    class Model:
        def invoke(self, messages):
            model_calls.append(messages)
            return AIMessage(content=json.dumps({'categories':[{'title':f'Category {i}','answer':'依据真实字段'} for i in [2,4]]}))
    monkeypatch.setattr(rec, 'AmazonCrawler', Crawler)
    monkeypatch.setattr(rec, 'model', Model())
    result = rec.generate_recommendations([], payload, Clock()(), lambda _: None)
    assert len(calls) == 1 and calls[0][0] == 'keyword 2'
    assert calls[0][1] == {'page':1,'limit':30,'max_pages':2,'category':'hot'}
    assert len(model_calls) == 1
    assert len(json.loads(model_calls[0][-1].content)) == 2
    assert all(c['analysis_status'] == 'success' for c in result['categories'])


def test_scheduler_start_is_nonblocking_and_stop_is_cooperative(tmp_path, rec):
    async def run():
        started = threading.Event()
        def generate(history, prior, now, checkpoint, stop):
            started.set()
            assert stop.wait(5)
            raise rec.GenerationInterrupted()
        daily = service(tmp_path, Clock(), generate)
        await daily.start()
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(.01)
        assert started.is_set()
        assert daily.latest()['update_status'] == 'updating'
        await daily.stop()
        assert daily.task.done()
        assert daily.latest()['snapshot_id'] is None
    asyncio.run(run())
