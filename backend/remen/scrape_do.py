"""Scrape.do 的 Amazon 专用接口；只在服务器端持有令牌。

搜索接口返回 JSON，不应继续交给旧 HTML 搜索页解析器。这里仅负责传输和
字段归一化；每日共享缓存、采集预算和调度由调用方负责，不在失败后偷偷直连。
官方协议：https://scrape.do/documentation/amazon-scraper-api/search/
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit

import requests


SEARCH_ENDPOINT = "https://api.scrape.do/plugin/amazon/search"
HTML_ENDPOINT = "https://api.scrape.do/plugin/amazon/"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
MONTHLY_SALES = re.compile(r"([\d,.]+)\s*([kKmM]?)\+?\s+bought in (?:the )?past month", re.I)


class ScrapeDoError(Exception):
    """可公开的错误：永远不拼接供应商响应、请求 URL 或底层异常中的令牌。"""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.status_code = status


@dataclass(frozen=True)
class ScrapeDoPage:
    products: list[dict]
    source_url: str
    raw_count: int
    request_cost: float | None = None
    remaining_credits: float | None = None


def _number(value: object, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount < 0 or (positive and amount <= 0):
            return None
        number = float(amount)
        return number if math.isfinite(number) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _amazon_url(value: object) -> bool:
    """本项目采集美国站；拒绝其他站点、带凭据和非标准端口。"""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in {"www.amazon.com", "amazon.com"}
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def _image_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        allowed = any(hostname == base or hostname.endswith("." + base)
                      for base in ("media-amazon.com", "ssl-images-amazon.com", "images-amazon.com"))
        if (parsed.scheme == "https" and allowed and parsed.port in (None, 443)
                and not parsed.username and not parsed.password
                and not any(ord(char) < 32 for char in value)):
            return value
    except ValueError:
        pass
    return None


def _review_count(item: dict, rating: dict) -> int | None:
    count = _integer(rating.get("count"))
    if count is not None:
        return count
    # 美国站 EN 的显示缩写只能作为近似评论数，绝不能用来替代销量。
    text = item.get("reviewCount")
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"\(?\s*([\d,]+(?:\.\d+)?)\s*([kKmM]?)\s*\)?", text.strip())
    if not match:
        return None
    value = _number(match[1].replace(",", ""))
    return int(value * {"": 1, "k": 1000, "m": 1000000}[match[2].lower()]) if value is not None else None


def normalize_products(payload: object) -> tuple[list[dict], int]:
    """缺价格/币种的商品不展示；仅保留供应商真实字段，按 ASIN 去重。"""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ScrapeDoError("scrape_do_invalid_response", "商品数据服务未返回成功结果，请稍后重试。")
    raw = payload.get("products")
    if not isinstance(raw, list):
        raise ScrapeDoError("scrape_do_invalid_response", "商品数据服务返回的商品列表格式异常。")
    products: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        asin, title = item.get("asin"), item.get("title")
        if not isinstance(asin, str) or not ASIN_PATTERN.fullmatch(asin):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        source_url = item.get("url")
        if source_url is not None:
            if not _amazon_url(source_url):
                continue
            path = urlsplit(source_url).path
            if not re.search(r"/(?:dp|gp/product)/" + re.escape(asin) + r"(?:/|$)", path):
                continue
        price = item.get("price")
        if not isinstance(price, dict):
            continue
        amount = _number(price.get("amount"), positive=True)
        currency = price.get("currencyCode")
        # 不因请求参数 currency=USD 就假定返回币种也是 USD。
        if (amount is None or not isinstance(currency, str)
                or not re.fullmatch(r"[A-Z]{3}", currency) or currency in {"XXX", "XTS"}):
            continue
        sponsored = item.get("isSponsored", False)
        if not isinstance(sponsored, bool):
            continue
        rating = item.get("rating")
        rating = rating if isinstance(rating, dict) else {}
        rating_value = _number(rating.get("value"))
        if rating_value is not None and rating_value > 5:
            rating_value = None
        sales = item.get("sales_volume")
        sales = " ".join(sales.split()) if isinstance(sales, str) and sales.strip() else None
        sales_match = MONTHLY_SALES.search(sales or "")
        sales_count = None
        if sales_match:
            number = _number(sales_match[1].replace(",", ""))
            if number is not None:
                sales_count = int(number * {"": 1, "k": 1000, "m": 1000000}[sales_match[2].lower()])
        normalized = {
            "asin": asin, "title": " ".join(title.split()),
            "url": "https://www.amazon.com/dp/" + asin,
            "image_url": _image_url(item.get("imageUrl")),
            "price": amount, "currency": currency,
            "price_display": f"{currency} {amount:,.2f}",
            "rating": rating_value, "review_count": _review_count(item, rating),
            "sales": sales, "sales_count_min": sales_count,
            "sales_period": "past_month" if sales_count is not None else None,
            "sponsored": sponsored,
        }
        # 同页同 ASIN 出现广告和自然结果时保留自然结果，避免误伤有效候选。
        previous = products.get(asin)
        if previous is None or (previous["sponsored"] and not sponsored):
            products[asin] = normalized
    if raw and not products:
        raise ScrapeDoError("scrape_do_no_valid_products", "本次商品数据没有包含有效价格的可用商品。")
    return list(products.values()), len(raw)


class ScrapeDoClient:
    """一次方法调用对应一次付费请求；不在客户端自动重试或升档代理。"""

    def __init__(self, token: str, *, timeout: float = 90, zipcode: str = "10001",
                 super_proxy: bool = False, session: requests.Session | None = None):
        if not isinstance(token, str) or not token.strip():
            raise ScrapeDoError("scrape_do_not_configured", "尚未配置商品数据服务令牌。", 503)
        if not re.fullmatch(r"\d{5}(?:-\d{4})?", zipcode):
            raise ScrapeDoError("scrape_do_configuration", "商品数据服务的美国邮政编码配置无效。", 503)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 5 <= timeout <= 180:
            raise ScrapeDoError("scrape_do_configuration", "商品数据服务超时应为 5 至 180 秒。", 503)
        self._token = token.strip()
        self.timeout = timeout
        self.zipcode = zipcode
        self.super_proxy = bool(super_proxy)
        self._session = session

    def _request(self, endpoint: str, extra: dict[str, object]) -> tuple[bytes, dict[str, str]]:
        params = {"token": self._token, "geocode": "us", "zipcode": self.zipcode,
                  "language": "EN", **extra}
        if self.super_proxy:
            params["super"] = "true"
        session = self._session or requests.Session()
        owns_session = self._session is None
        try:
            # 禁止跟随 API 重定向，避免携带令牌访问其他主机；requests 负责参数编码。
            with session.get(endpoint, params=params, timeout=(10, self.timeout),
                             allow_redirects=False, stream=True) as response:
                status = response.status_code
                if status in (401, 402, 403):
                    raise ScrapeDoError("scrape_do_auth_or_credits", "商品数据服务鉴权失败或额度不足，请管理员检查配置与余额。", 503)
                if status == 429:
                    raise ScrapeDoError("scrape_do_rate_limited", "商品数据服务请求繁忙，请稍后重试。", 503)
                if status != 200:
                    raise ScrapeDoError("scrape_do_upstream_error", "商品数据服务暂时不可用，请稍后重试。", 502)
                headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
                resolved_url = headers.get("scrape.do-resolved-url")
                if resolved_url and not _amazon_url(resolved_url):
                    raise ScrapeDoError("scrape_do_unexpected_target", "商品数据服务跳转到其他站点，已停止解析。")
                declared_length = _integer(headers.get("content-length"))
                if declared_length is not None and declared_length > MAX_RESPONSE_BYTES:
                    raise ScrapeDoError("scrape_do_response_too_large", "商品数据响应过大，已停止接收。")
                body, total = [], 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ScrapeDoError("scrape_do_response_too_large", "商品数据响应过大，已停止接收。")
                    body.append(chunk)
                return b"".join(body), headers
        except requests.Timeout:
            raise ScrapeDoError("scrape_do_timeout", "商品数据服务请求超时，请稍后重试。", 504) from None
        except requests.RequestException:
            raise ScrapeDoError("scrape_do_network_error", "无法连接商品数据服务，请稍后重试。", 502) from None
        finally:
            if owns_session:
                session.close()

    def fetch(self, keyword: str, page: int = 1) -> ScrapeDoPage:
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 100:
            raise ScrapeDoError("invalid_keyword", "搜索关键词长度应为 1 至 100 个字符。", 422)
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 50:
            raise ScrapeDoError("invalid_page", "搜索页码应为 1 至 50。", 422)
        body, headers = self._request(SEARCH_ENDPOINT, {"keyword": keyword.strip(), "page": page, "currency": "USD"})
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ScrapeDoError("scrape_do_invalid_json", "商品数据服务返回格式异常，请稍后重试。") from None
        products, raw_count = normalize_products(payload)
        if "page" in payload and (isinstance(payload["page"], bool) or payload["page"] != page):
            raise ScrapeDoError("scrape_do_wrong_page", "商品数据服务返回的页码不匹配。")
        source_url = "https://www.amazon.com/s?" + urlencode({"k": keyword.strip(), "page": page, "language": "en_US", "currency": "USD"})
        return ScrapeDoPage(products=products, source_url=source_url, raw_count=raw_count,
                            request_cost=_number(headers.get("scrape.do-request-cost")),
                            remaining_credits=_number(headers.get("scrape.do-remaining-credits")))

    def fetch_html(self, url: str) -> bytes:
        """推荐资料中的 Amazon 公开榜单仍可使用 HTML，但也必须经过 Scrape.do。"""
        if not _amazon_url(url):
            raise ScrapeDoError("invalid_amazon_url", "仅允许获取 Amazon 美国站公开资料。", 422)
        body, headers = self._request(HTML_ENDPOINT, {"url": url})
        content_type = headers.get("content-type", "").lower()
        if "json" in content_type or not body.lstrip().startswith(b"<"):
            raise ScrapeDoError("scrape_do_invalid_html", "商品资料服务未返回可解析的网页。")
        return body
