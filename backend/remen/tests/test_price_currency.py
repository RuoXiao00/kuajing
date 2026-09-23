"""价格币种离线回归：真实站点 + 符号，不能只凭金额或默认请求币种推断。"""
import pytest
from backend.remen.pachon import parse_amazon_html


def card(price, symbol=''):
    return f'''<div data-component-type="s-search-result" data-asin="B012345678">
    <h2>Example</h2><span class="a-price"><span class="a-offscreen">{price}</span>
    <span class="a-price-symbol">{symbol}</span></span></div>'''


@pytest.mark.parametrize('price,source,currency', [
    ('¥968', 'https://www.amazon.co.jp/s', 'JPY'),
    ('￥968', 'https://www.amazon.co.jp/s', 'JPY'),
    ('CNY 968', 'https://www.amazon.co.jp/s', 'CNY'),
    ('GBP 968', 'https://www.amazon.co.jp/s', 'GBP'),
    ('$968', 'https://www.amazon.sg/s', 'SGD'),
    ('USD 968', 'https://www.amazon.sg/s', 'USD'),
    ('¥968', 'https://www.amazon.com/s', None),
    ('¥968', 'https://www.amazon.co.jp.evil.test/s', None),
    ('968', 'https://www.amazon.co.jp/s', None),
])
def test_source_aware_currency(price, source, currency):
    result = parse_amazon_html(card(price), source)[0]
    assert result.price == 968
    assert result.currency == currency


def test_price_symbol_is_read_even_when_offscreen_amount_is_valid():
    assert parse_amazon_html(card('968', 'JPY'))[0].currency == 'JPY'
    # 同一价格块里的明确币种优先于按日本站 ¥ 的兜底。
    assert parse_amazon_html(card('¥968', 'CNY'), 'https://www.amazon.co.jp/s')[0].currency == 'CNY'
