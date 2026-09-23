"""共享首屏回归：临时数据库和爬虫替身，无真实网络请求。"""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.remen.first_page import FirstPageStore, FirstPageUpdater
from backend.remen.pachon import create_app, Product, PageResult, AmazonCrawler, CrawlError
import pytest


def payload(at=10000):
    return dict(category='hot', sub_category='all', page=1, pages_scanned=1, period='current',
                partial=False, fetched_at=datetime.fromtimestamp(at, timezone.utc).isoformat(),
                products=[{'asin':'B012345678', 'title':'real product'}])


def test_latest_survives_restart_and_old_or_failed_responses(tmp_path):
    path = tmp_path / 'snapshots.sqlite3'
    store = FirstPageStore(path)
    assert store.save(payload())
    assert not store.save({**payload(12000), 'partial':True})
    assert not store.save({**payload(12000), 'products':[]})
    assert not store.save({**payload(12000), 'page':2})
    store.save(payload(9000))
    assert FirstPageStore(path).read() == payload()
    assert store.read('niche','all') is None


def test_update_is_time_based_without_visits_and_retries_failures(tmp_path):
    store = FirstPageStore(tmp_path / 'snapshot.sqlite3')
    now, calls = [10000], []
    def refresh():
        calls.append(now[0])
        if now[0] < 10001:
            raise ValueError('private exception must not be shown')
        return payload(now[0])
    updater = FirstPageUpdater(store, refresh, lambda:now[0])
    updater.tick()
    now[0] = 10299
    updater.tick()
    assert len(calls) == 1
    now[0] = 10300
    updater.tick()
    assert store.read() == payload(10300)
    restarted = FirstPageUpdater(store, refresh, lambda:now[0])
    restarted.tick()
    assert len(calls) == 2
    now[0] = 12100
    restarted.tick()
    assert store.read() == payload(12100)


class FakeCrawler:
    provider = 'direct'
    def __init__(self):
        self.calls = []
        self.invalidated = []
    def check_rate(self, address):
        pass
    def invalidate_page(self, keyword, page):
        self.invalidated.append((keyword, page))
    def collect(self, keyword, page, limit, max_pages, category):
        self.calls.append((keyword, page))
        product = Product(asin='B012345678',title='real item',price=20,currency='SGD',url='https://www.amazon.com/dp/B012345678')
        return SimpleNamespace(products=[product],pages=[PageResult(page=page,count=1,added_count=1,
            from_cache=False,fetched_at=payload()['fetched_at'])],stop_reason='page_limit',next_page=page+1,error=None)


def test_read_api_does_not_crawl_and_successful_live_page_is_shared(tmp_path):
    crawler = FakeCrawler()
    app = create_app(crawler, snapshot_path=tmp_path/'api.sqlite3')
    with TestClient(app) as client:
        assert client.get('/api/remen/products/snapshot').json() == {'snapshot':None}
        assert crawler.calls == []
        response = client.get('/api/remen/products?limit=200&max_pages=1&refresh=true')
        assert response.status_code == 200
        saved = response.json()
        for _ in range(3):
            read = client.get('/api/remen/products/snapshot')
            assert read.json()['snapshot'] == saved
            assert read.headers['cache-control'] == 'no-store'
        assert len(crawler.calls) == 1 and crawler.invalidated == [('best sellers',1)]
        assert client.get('/api/remen/products/snapshot?category=niche').json()['snapshot'] is None
        assert saved['products'][0]['price'] == 20 and saved['products'][0]['currency'] == 'SGD'


def test_custom_keyword_and_pagination_never_replace_default(tmp_path):
    crawler = FakeCrawler()
    app = create_app(crawler, snapshot_path=tmp_path/'api.sqlite3')
    with TestClient(app) as client:
        for suffix in ('&keyword=other', '&page=2'):
            assert client.get('/api/remen/products?limit=200&max_pages=1'+suffix).status_code == 200
        assert client.get('/api/remen/products/snapshot').json()['snapshot'] is None


def test_manual_refresh_does_not_bypass_cooldown():
    crawler = AmazonCrawler(mode='direct')
    crawler._cache[('best sellers',1)] = (float('inf'), [], 'cached')
    crawler._blocked_until = float('inf')
    crawler.invalidate_page('best sellers', 1)
    with pytest.raises(CrawlError) as caught:
        crawler.fetch('best sellers',1)
    assert caught.value.code == 'amazon_cooldown'
