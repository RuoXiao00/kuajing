"""只启动统一后端，热门与推荐都可读取；不启动真实定时抓取、不写正式数据库。"""
import importlib
from fastapi.testclient import TestClient
from backend.remen.pachon import create_app


def test_unified_lifecycle_provides_hot_routes_without_8001(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-not-a-real-key')
    module = importlib.import_module('backend.app')
    events = []
    class Daily:
        def __init__(self, *args):
            pass
        async def start(self):
            events.append('start')
        async def stop(self):
            events.append('stop')
        def latest(self):
            return {'categories': []}
    fake_crawler = object()
    monkeypatch.setattr(module, 'DailyRecommendations', Daily)
    monkeypatch.setattr(module, 'product_app', create_app(fake_crawler, snapshot_path=tmp_path/'hot.sqlite3'))
    with TestClient(module.app) as client:
        assert client.get('/api/remen/products/snapshot').json() == {'snapshot': None}
        assert client.get('/api/recommendations/latest').json() == {'categories': [], 'presentation_version': 1}
        assert module.app.state.amazon_crawler is fake_crawler
    assert events == ['start', 'stop']
