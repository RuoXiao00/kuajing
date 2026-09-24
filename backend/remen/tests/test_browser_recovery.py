"""滚动加载故障的离线回归：不访问真实亚马逊，不写正式快照。"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from backend.remen.pachon import AmazonCrawler, CrawlError, parse_amazon_html, _next_search_url

HTML = '''<div class="s-result-item" data-component-type="s-search-result" data-asin="B012345678">
<h2>Product</h2><img class="s-image" alt="Product fallback" src="https://example.test/image.jpg">
<span class="a-price"><span class="a-offscreen">JPY 1,500</span></span></div>'''


@pytest.fixture
def browser(monkeypatch):
    class BrowserError(Exception): pass
    class Timeout(BrowserError): pass
    driver = MagicMock()
    start = MagicMock()
    start.return_value.__enter__.return_value = driver
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', SimpleNamespace(Error=BrowserError, TimeoutError=Timeout, sync_playwright=start))
    context = driver.chromium.launch.return_value.new_context.return_value
    tab = context.new_page.return_value
    tab.url = 'https://www.amazon.co.jp/s?k=fixture&page=2'
    tab.goto.return_value.status = 200
    tab.content.return_value = HTML
    context.storage_state.return_value = {'cookies': [], 'origins': []}
    sleep = MagicMock()
    monkeypatch.setattr('backend.remen.pachon.time.sleep', sleep)
    return tab, sleep


def test_regional_redirect_is_real_product_data_and_next_request_stays_there(browser):
    tab, _ = browser
    crawler = AmazonCrawler(allow_regional_redirects=True)
    tab.content.return_value = HTML + '<a class="s-pagination-next" href="/s?k=fixture&amp;page=3&amp;ref=sr_pg_2">Next</a>'
    first = crawler.collect('fixture', 2, 200, 1, 'hot')
    assert first.products[0].url == 'https://www.amazon.co.jp/dp/B012345678'
    assert first.products[0].currency == 'JPY'
    crawler.collect('fixture', 3, 200, 1, 'hot')
    assert tab.goto.call_args.args[0] == 'https://www.amazon.co.jp/s?k=fixture&page=3&ref=sr_pg_2'
    assert tab.goto.call_count == 2


def test_page_not_ready_recovers_same_page_once(browser):
    tab, sleep = browser
    tab.content.side_effect = ['<div class="s-result-item" data-asin=""></div>', HTML]
    crawler = AmazonCrawler(allow_regional_redirects=True)
    batch = crawler.collect('fixture', 2, 200, 1, 'hot')
    assert len(batch.products) == 1 and batch.next_page == 3
    assert tab.goto.call_count == 2 and sleep.call_count == 1
    assert all('page=2' in call.args[0] for call in tab.goto.call_args_list)


def test_empty_heading_uses_image_title_even_with_unfilled_primary_container():
    html = '<div data-component-type="s-search-result" data-asin=""></div>' + HTML.replace('<h2>Product</h2>', '<h2></h2>').replace('data-component-type="s-search-result"', '')
    assert parse_amazon_html(html)[0].title == 'Product fallback'


def test_recovery_is_bounded_and_does_not_fake_empty_result(browser):
    tab, _ = browser
    tab.content.return_value = '<div class="s-result-item" data-asin=""></div>'
    crawler = AmazonCrawler(allow_regional_redirects=True)
    with pytest.raises(CrawlError, match='缺少有效'):
        crawler.collect('fixture', 2, 200, 1, 'hot')
    assert tab.goto.call_count == 2
    assert not crawler._cache


@pytest.mark.parametrize('host', ['evil.example', 'www.amazon.com.evil.example'])
def test_unknown_redirect_never_parsed_or_retried(browser, host):
    tab, sleep = browser
    tab.url = f'https://{host}/s'
    with pytest.raises(CrawlError) as caught:
        AmazonCrawler(allow_regional_redirects=True).collect('fixture', 2, 200, 1, 'hot')
    assert caught.value.code == 'unexpected_redirect'
    assert tab.goto.call_count == 1
    tab.content.assert_not_called()
    sleep.assert_not_called()


def test_recommendation_default_does_not_silently_change_market(browser):
    tab, _ = browser
    with pytest.raises(CrawlError) as caught:
        AmazonCrawler().collect('fixture', 2, 200, 1, 'hot')
    assert caught.value.code == 'unexpected_redirect'


def test_captcha_still_stops_and_cools_down(browser):
    tab, sleep = browser
    tab.content.return_value = '<input id="captchacharacters">'
    crawler = AmazonCrawler(allow_regional_redirects=True)
    with pytest.raises(CrawlError) as caught:
        crawler.collect('fixture', 2, 200, 1, 'hot')
    assert caught.value.code == 'amazon_blocked' and crawler._blocked_until > 0
    assert tab.goto.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize('html', [
    '<title>Robot Check</title><p>Verification</p>',
    '<p>To discuss automated access to Amazon data please contact us.</p>',
])
def test_http_200_block_page_without_captcha_input_is_not_retried(browser, html):
    tab, sleep = browser
    tab.content.return_value = html
    crawler = AmazonCrawler(allow_regional_redirects=True)
    with pytest.raises(CrawlError) as caught:
        crawler.collect('fixture', 2, 200, 1, 'hot')
    assert caught.value.code == 'amazon_blocked'
    assert crawler._blocked_until > 0
    assert tab.goto.call_count == 1
    sleep.assert_not_called()


def test_regional_next_link_must_stay_on_same_site():
    assert _next_search_url('<a class="s-pagination-next" href="https://evil.example/s?k=fixture&page=3">Next</a>', 'fixture', 2, 'https://www.amazon.co.jp') is None
    assert _next_search_url('<a class="s-pagination-next" href="https://www.amazon.com/s?k=fixture&page=3">Next</a>', 'fixture', 2, 'https://www.amazon.co.jp') is None
