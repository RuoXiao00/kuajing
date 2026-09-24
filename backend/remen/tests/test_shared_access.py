"""使用独立预算和事件验证并发，不访问供应商或正式数据库。"""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock

import pytest

from backend.remen.pachon import AmazonCrawler, CrawlCoordinator, CrawlError

HTML = b'<div class="s-result-item" data-asin="B012345678"><h2>Product</h2></div>'


def test_different_crawlers_share_cooldown_but_keep_cached_data(monkeypatch):
    access = CrawlCoordinator()
    a, b = (AmazonCrawler(mode='direct', coordinator=access) for _ in range(2))
    monkeypatch.setattr(a, '_download', Mock(return_value=HTML))
    a.fetch('cached', 1)
    access.next_fetch_at = 0
    blocked = Mock(side_effect=CrawlError('amazon_blocked', 'blocked', 503))
    monkeypatch.setattr(b, '_download', blocked)
    with pytest.raises(CrawlError, match='blocked'):
        b.fetch('new', 1)
    assert a.fetch('cached', 1)[2] is True
    with pytest.raises(CrawlError) as caught:
        a.fetch('different', 1)
    assert caught.value.code == 'amazon_cooldown'
    assert a._download.call_count == blocked.call_count == 1
    # 新建每日任务不能通过重新构造爬虫重置云服务器的冷却时间。
    assert AmazonCrawler(coordinator=access)._blocked_until == a._blocked_until > 0


def test_crawlers_share_interval(monkeypatch):
    access = CrawlCoordinator()
    a, b = (AmazonCrawler(mode='direct', coordinator=access) for _ in range(2))
    for crawler in (a, b):
        monkeypatch.setattr(crawler, '_download', Mock(return_value=HTML))
    a.fetch('a', 1)
    with pytest.raises(CrawlError) as caught:
        b.fetch('b', 1)
    assert caught.value.code == 'crawl_interval'
    b._download.assert_not_called()


def test_two_batches_cannot_open_browsers_at_the_same_time(monkeypatch):
    access = CrawlCoordinator()
    a, b = (AmazonCrawler(mode='direct', coordinator=access) for _ in range(2))
    started, second_waiting, release, second_entered = (threading.Event() for _ in range(4))

    def first(*args):
        started.set()
        assert release.wait(3)
        return 'first'

    def second(*args):
        second_entered.set()
        return 'second'

    def run_second():
        second_waiting.set()
        return b.collect('b', 1, 10, 1, 'hot')

    monkeypatch.setattr(a, '_collect_pages', first)
    monkeypatch.setattr(b, '_collect_pages', second)
    with ThreadPoolExecutor(2) as pool:
        fa = pool.submit(a.collect, 'a', 1, 10, 1, 'hot')
        assert started.wait(2)
        fb = pool.submit(run_second)
        try:
            assert second_waiting.wait(2)
            assert not second_entered.wait(.1)
        finally:
            release.set()
        assert fa.result(2) == 'first'
        assert fb.result(2) == 'second'


def test_exception_releases_shared_lock(monkeypatch):
    access = CrawlCoordinator()
    a, b = (AmazonCrawler(mode='direct', coordinator=access) for _ in range(2))
    monkeypatch.setattr(a, '_collect_pages', Mock(side_effect=ValueError('fixture')))
    monkeypatch.setattr(b, '_collect_pages', Mock(return_value='ok'))
    with pytest.raises(ValueError):
        a.collect('a', 1, 10, 1, 'hot')
    with ThreadPoolExecutor(1) as pool:
        assert pool.submit(b.collect, 'b', 1, 10, 1, 'hot').result(2) == 'ok'
