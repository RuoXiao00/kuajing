"""供应商适配离线测试：不使用真实令牌，不消耗 Scrape.do 额度。"""

import json
from unittest.mock import Mock

import pytest
import requests

from backend.remen.scrape_do import (
    HTML_ENDPOINT, SEARCH_ENDPOINT, MAX_RESPONSE_BYTES, ScrapeDoClient,
    ScrapeDoError, normalize_products,
)


def product(**overrides):
    return {"asin": "B012345678", "title": "Product", "url": "https://www.amazon.com/dp/B012345678?ref=abc",
            "imageUrl": "https://m.media-amazon.com/images/I/product.jpg",
            "price": {"amount": 12.5, "currencyCode": "USD"},
            "rating": {"value": 4.7, "count": 1400}, "isSponsored": False, **overrides}


def payload(*products, **extra):
    return {"status": "success", "page": 1, "products": list(products), **extra}


def client_with_response(data=None, *, body=None, status=200, headers=None, error=None):
    response = Mock()
    response.status_code = status
    response.headers = headers or {}
    response.iter_content.return_value = [body if body is not None else json.dumps(data).encode()]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    session = Mock()
    session.get.return_value = response
    if error:
        session.get.side_effect = error
    return ScrapeDoClient("fake-test-token", session=session), session, response


def test_search_uses_official_endpoint_and_separate_encoded_params():
    client, session, _ = client_with_response(payload(product()), headers={
        "Scrape.do-Request-Cost": "1", "Scrape.do-Remaining-Credits": "998"})
    result = client.fetch("coffee & tea")
    assert result.request_cost == 1 and result.remaining_credits == 998
    assert result.raw_count == 1
    args, kwargs = session.get.call_args
    assert args == (SEARCH_ENDPOINT,)
    assert kwargs["params"]["keyword"] == "coffee & tea"
    assert kwargs["params"]["geocode"] == "us"
    assert kwargs["params"]["zipcode"] == "10001"
    assert "super" not in kwargs["params"]
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert "token" not in result.source_url and "coffee+%26+tea" in result.source_url
    saved = result.products[0]
    assert saved["price"] == 12.5 and saved["currency"] == "USD"
    assert saved["sales"] is None and saved["sales_count_min"] is None
    assert saved["review_count"] == 1400 and saved["rating"] == 4.7
    assert saved["url"] == "https://www.amazon.com/dp/B012345678"


@pytest.mark.parametrize("amount", [None, 0, -1, True, False, "NaN", "Infinity", float("inf"), "1e9999", {}, ""])
def test_invalid_price_is_not_saved(amount):
    invalid = product(asin="B000000001", url=None, price={"amount": amount, "currencyCode": "USD"})
    items, _ = normalize_products(payload(invalid, product()))
    assert [item["asin"] for item in items] == ["B012345678"]


@pytest.mark.parametrize("currency", [None, "", "$", "usd", "UNKNOWN", "XXX", "XTS"])
def test_currency_must_be_reported_by_provider(currency):
    invalid = product(asin="B000000001", url=None, price={"amount": 9.9, "currencyCode": currency})
    items, _ = normalize_products(payload(invalid, product()))
    assert len(items) == 1 and items[0]["asin"] == "B012345678"


def test_duplicate_prefers_organic_and_real_currency_over_request_preference():
    ads = product(isSponsored=True)
    organic = product(price={"amount": 100, "currencyCode": "JPY"}, sales_volume="1.2K+ bought in past month")
    items, count = normalize_products(payload(ads, organic, product()))
    assert count == 3 and len(items) == 1
    assert items[0]["currency"] == "JPY" and items[0]["sponsored"] is False
    assert items[0]["sales_count_min"] == 1200 and items[0]["sales_period"] == "past_month"


def test_reviews_and_unknown_sales_never_become_monthly_sales():
    items, _ = normalize_products(payload(product(rating={"value": 8}, reviewCount="(2.3K)", sales_volume="Popular")))
    assert items[0]["review_count"] == 2300
    assert items[0]["rating"] is None
    assert items[0]["sales"] == "Popular" and items[0]["sales_period"] is None


@pytest.mark.parametrize("url", ["https://example.org/dp/B012345678", "https://www.amazon.com.evil.test/dp/B012345678",
    "https://www.amazon.com:444/dp/B012345678", "https://user@www.amazon.com/dp/B012345678",
    "http://www.amazon.com/dp/B012345678", "https://www.amazon.com/dp/B099999999"])
def test_unexpected_product_urls_are_rejected(url):
    with pytest.raises(ScrapeDoError) as caught:
        normalize_products(payload(product(url=url)))
    assert caught.value.code == "scrape_do_no_valid_products"


def test_bad_image_is_omitted_without_losing_valid_product():
    items, _ = normalize_products(payload(product(imageUrl="https://m.media-amazon.com.evil.test/a.jpg")))
    assert items[0]["image_url"] is None


@pytest.mark.parametrize("data", [{}, [], {"status": "error", "errorMessage": "fake-test-token"},
                                  {"status": "success", "products": {}}, None])
def test_malformed_or_failed_payload_is_not_successful_empty_page(data):
    with pytest.raises(ScrapeDoError) as caught:
        normalize_products(data)
    assert caught.value.code == "scrape_do_invalid_response"
    assert "fake-test-token" not in str(caught.value)


def test_actual_empty_page_is_distinguished_from_invalid_products():
    assert normalize_products(payload()) == ([], 0)
    with pytest.raises(ScrapeDoError) as caught:
        normalize_products(payload(product(price=None)))
    assert caught.value.code == "scrape_do_no_valid_products"


@pytest.mark.parametrize("status,code", [(401, "scrape_do_auth_or_credits"), (402, "scrape_do_auth_or_credits"),
    (403, "scrape_do_auth_or_credits"), (429, "scrape_do_rate_limited"),
    (503, "scrape_do_upstream_error"), (302, "scrape_do_upstream_error")])
def test_http_errors_do_not_log_provider_body_or_retry(status, code):
    client, session, response = client_with_response(body=b"secret-token", status=status)
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch("coffee")
    assert caught.value.code == code and "secret-token" not in str(caught.value)
    session.get.assert_called_once()
    response.iter_content.assert_not_called()


@pytest.mark.parametrize("error,code", [(requests.Timeout("url?token=secret"), "scrape_do_timeout"),
    (requests.ConnectionError("url?token=secret"), "scrape_do_network_error")])
def test_network_exceptions_are_sanitized(error, code):
    client, _, _ = client_with_response(error=error)
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch("coffee")
    assert caught.value.code == code and "secret" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize("body", [b"not json token=secret", b"\xff", b"<html>503</html>"])
def test_invalid_json_is_safe(body):
    client, _, _ = client_with_response(body=body)
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch("coffee")
    assert caught.value.code == "scrape_do_invalid_json" and "secret" not in str(caught.value)


def test_size_limit_applies_to_declared_and_streamed_body():
    for headers, body in [({"Content-Length": str(MAX_RESPONSE_BYTES + 1)}, b""),
                          ({}, b"x" * (MAX_RESPONSE_BYTES + 1))]:
        client, _, _ = client_with_response(headers=headers, body=body)
        with pytest.raises(ScrapeDoError) as caught:
            client.fetch("coffee")
        assert caught.value.code == "scrape_do_response_too_large"


def test_resolved_site_and_page_mismatch_are_rejected():
    client, _, _ = client_with_response(payload(product()), headers={"Scrape.do-Resolved-Url": "https://example.org"})
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch("coffee")
    assert caught.value.code == "scrape_do_unexpected_target"
    client, _, _ = client_with_response(payload(product(), page=2))
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch("coffee", 1)
    assert caught.value.code == "scrape_do_wrong_page"


def test_html_rank_source_uses_plugin_and_target_allowlist():
    client, session, _ = client_with_response(body=b"<!doctype html><h1>Best sellers</h1>")
    assert client.fetch_html("https://www.amazon.com/Best-Sellers/zgbs/").startswith(b"<!doctype")
    assert session.get.call_args.args == (HTML_ENDPOINT,)
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch_html("http://127.0.0.1:8000")
    assert caught.value.code == "invalid_amazon_url"
    session.get.assert_called_once()


def test_html_endpoint_json_error_not_passed_to_rank_parser():
    client, _, _ = client_with_response(body=b'{"error":"secret"}', headers={"Content-Type": "application/json"})
    with pytest.raises(ScrapeDoError) as caught:
        client.fetch_html("https://www.amazon.com/Best-Sellers/zgbs/")
    assert caught.value.code == "scrape_do_invalid_html"


def test_missing_token_never_starts_http_request():
    session = Mock()
    with pytest.raises(ScrapeDoError) as caught:
        ScrapeDoClient("  ", session=session)
    assert caught.value.code == "scrape_do_not_configured"
    session.get.assert_not_called()
