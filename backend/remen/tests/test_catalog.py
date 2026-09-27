"""共享快照的业务约束：离线测试，不消耗供应商额度、不写正式数据库。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.remen.catalog import BEIJING, CatalogStore, DailyCatalog, daily_slot
from backend.remen.pachon import AmazonCrawler, CrawlError, Product, create_app


NOW = datetime(2026, 9, 27, 6, tzinfo=BEIJING)


def product(n, **kwargs):
    return Product(asin=f'B{n:09}', title=f'Product {n}', url=f'https://www.amazon.com/dp/B{n:09}',
                   price=kwargs.pop('price', 12), currency='USD', **kwargs)


class Fake:
    provider = 'scrape_do'

    def __init__(self):
        self.calls = []
        self.generation = 0
        self.failure = False

    def fetch(self, keyword, page, **options):
        self.calls.append((keyword, page))
        if self.failure:
            raise CrawlError('scrape_do_upstream_error', 'safe error')
        return [product(self.generation + page), product(self.generation + 1)], NOW.isoformat(), False


def catalog(tmp_path, pages=3):
    clock = [NOW]
    fake = Fake()
    service = DailyCatalog(fake, tmp_path/'data.sqlite3', pages=pages, clock=lambda: clock[0],
                           categories={'all': ('all', 'products')})
    return service, fake, clock


def test_every_user_reads_same_persisted_collection_and_no_scroll_fetch(tmp_path):
    service, fake, _ = catalog(tmp_path)
    service.tick()
    calls = list(fake.calls)
    first = service.page('hot', 'all', 1, 2)
    second = service.page('hot', 'all', 2, 2)
    assert first['dataset_count'] == 3
    assert first['next_page'] == 2 and second['next_page'] is None
    assert service.page('hot', 'all', 99, 2)['products'] == []
    assert not set(p['asin'] for p in first['products']) & set(p['asin'] for p in second['products'])
    service.tick()
    reopened = DailyCatalog(fake, service.store.path, clock=lambda: NOW, categories={'all': ('all', 'products')})
    reopened.tick()
    assert reopened.envelope()['snapshot']['snapshot_id'] == first['snapshot_id']
    assert fake.calls == calls


def test_next_day_replaces_old_collection_and_failed_refresh_keeps_it(tmp_path):
    service, fake, clock = catalog(tmp_path)
    service.tick()
    old = service.envelope()['snapshot']
    clock[0] += timedelta(days=1)
    fake.failure = True
    service.tick()
    failure = service.envelope()
    assert failure['update_status'] == 'update_failed'
    assert failure['snapshot']['is_stale']
    assert failure['snapshot']['products'] == old['products']
    calls = len(fake.calls)
    service.tick()
    assert len(fake.calls) == calls
    clock[0] += timedelta(minutes=16)
    fake.failure = False
    fake.generation = 10
    service.tick()
    new = service.envelope()['snapshot']
    assert not new['is_stale'] and new['snapshot_id'] != old['snapshot_id']
    assert {p['asin'] for p in new['products']}.isdisjoint(p['asin'] for p in old['products'])
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM catalog').fetchone()[0] == 1


def test_failed_day_has_only_two_attempts(tmp_path):
    service, fake, clock = catalog(tmp_path)
    fake.failure = True
    for _ in range(5):
        service.tick()
        clock[0] += timedelta(hours=1)
    assert len(fake.calls) == 2
    assert service.envelope()['snapshot'] is None


def test_prices_ads_dedup_and_niche_share_same_source(tmp_path):
    service, fake, _ = catalog(tmp_path, pages=1)
    fake.fetch = Mock(return_value=([product(1, review_count=50), product(1), product(2, price=0),
        product(3, sponsored=True), product(4, review_count=150), product(5)], NOW.isoformat(), False))
    service.tick()
    assert len(service.envelope()['snapshot']['products']) == 3
    assert [p['asin'] for p in service.envelope('niche')['snapshot']['products']] == ['B000000001']
    assert fake.fetch.call_count == 1


def test_api_requests_including_refresh_are_read_only(tmp_path):
    fake = Fake()
    app = create_app(fake, catalog_path=tmp_path/'api.sqlite3', schedule=False)
    with TestClient(app) as client:
        assert client.get('/api/remen/products/snapshot').json()['snapshot'] is None
        assert client.get('/api/remen/products').status_code == 503
        assert fake.calls == []
        service = app.state.daily_products
        service.categories = {'all': ('all', 'products')}
        service.tick()
        calls = list(fake.calls)
        for address in ('/api/remen/products?refresh=true&page=2&limit=1',
                        '/api/remen/products/snapshot', '/api/remen/products?category=niche'):
            response = client.get(address)
            assert response.status_code == 200
        assert client.get('/api/remen/products?keyword=uncached').status_code == 422
        assert fake.calls == calls


def test_shared_source_page_cache_survives_instances_threads_and_rollover(tmp_path):
    stores = [CatalogStore(tmp_path/'pages.sqlite3') for _ in range(2)]
    fetch = Mock(return_value=[{'saved': True}])
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda store: store.cached_page('same', '2026-09-27', fetch), stores))
    assert fetch.call_count == 1
    assert sorted(item[2] for item in results) == [False, True]
    assert CatalogStore(stores[0].path).cached_page('same', '2026-09-27', fetch)[2]
    stores[0].cached_page('same', '2026-09-28', fetch)
    assert fetch.call_count == 2


def test_search_reused_by_new_crawler_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv('HOT_PRODUCTS_DB_PATH', str(tmp_path/'pages.sqlite3'))
    supplier = Mock()
    supplier.fetch.return_value = SimpleNamespace(products=[product(1).model_dump()])
    first = AmazonCrawler(mode='scrape_do')
    first._scrape_client = supplier
    assert first.fetch('desk organizer', 1)[2] is False
    second = AmazonCrawler(mode='scrape_do')
    second._scrape_client = Mock(side_effect=AssertionError('must not use network'))
    assert second.fetch('desk organizer', 1)[2] is True
    supplier.fetch.assert_called_once()


def test_lease_claim_and_old_writer_cannot_publish(tmp_path):
    store = CatalogStore(tmp_path/'lease.sqlite3')
    slot = daily_slot(NOW).isoformat()
    first = store.claim('all', slot, NOW)
    assert store.claim('all', slot, NOW) is None
    second = store.claim('all', slot, NOW + timedelta(minutes=31))
    assert second and second != first
    assert store.publish('all', slot, first, {'fetched_at': NOW.isoformat()}) is False
    assert store.publish('all', slot, second, {'fetched_at': NOW.isoformat()}) is True


def test_daily_boundary_is_beijing_0500():
    assert daily_slot(NOW.replace(hour=4)).date().isoformat() == '2026-09-26'
    assert daily_slot(NOW.replace(hour=5)).date().isoformat() == '2026-09-27'


def test_last_attempt_crash_expires_into_failure_instead_of_updating_forever(tmp_path):
    store = CatalogStore(tmp_path/'crash.sqlite3')
    slot = daily_slot(NOW).isoformat()
    store.claim('all', slot, NOW)
    store.claim('all', slot, NOW + timedelta(minutes=31))
    assert store.claim('all', slot, NOW + timedelta(minutes=62)) is None
    assert store.read('all', slot)[1]['status'] == 'failed'


def test_recommendation_amazon_sources_use_supplier_only(monkeypatch):
    from backend.tuijian import evidence
    source = Mock(return_value=b'<html>Amazon evidence</html>')
    monkeypatch.setenv('AMAZON_FETCH_MODE', 'scrape_do')
    monkeypatch.setattr(AmazonCrawler, 'source_html', source)
    monkeypatch.setattr(evidence, '_download_body', lambda *args, **kwargs: pytest.fail('direct Amazon request'))
    assert evidence._download(evidence.SOURCES[0][2]) == b'<html>Amazon evidence</html>'
    source.assert_called_once()
