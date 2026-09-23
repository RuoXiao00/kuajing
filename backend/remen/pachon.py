"""热门产品抓取接口（本文件可独立运行，不依赖推荐 Agent 或知识库）。

先看这段，再依次阅读：Product → 解析函数 → AmazonCrawler → HTTP 接口。
执行链路是：前端 fetch → FastAPI 校验参数 → 缓存/限流 → 抓取公开页面
→ 逐页提取真实字段 → 跨页去重/筛选/排序 → JSON。这里不调用大模型，也不编造商品。

【启动】在项目根目录的 PowerShell 中运行：
    
也可以直接运行本文件。默认监听 127.0.0.1:8001，不占用已有的 8000。
Swagger：http://127.0.0.1:8001/docs
离线自测：D:\\python\\python.exe -B -m backend.remen.pachon --self-test
依赖：fastapi、uvicorn、requests、beautifulsoup4、python-dotenv（本机已安装）。

【前端如何调用】以下只是示例，不会自动修改现有写死卡片的 Remeng.jsx：
    const query =D:\\python\\python.exe -B -m backend.remen.pachon new URLSearchParams({
      category: 'hot', period: 'day', subCategory: 'shuma', limit: '50', page: '1', max_pages: '5',
    });
    const response = await fetch(`http://127.0.0.1:8001/api/remen/products?${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message || '商品请求失败');
    // setProducts(data.products); setWarnings(data.warnings);
    // products.map(p => <article key={p.asin}>
    //   <img src={p.image_url || '/placeholder.png'} alt={p.title} />
    //   <p>{p.title}</p><p>{p.price_display ?? '价格未公开'}</p>
    //   <p>近月购买提示：{p.sales ?? '未公开'}</p>
    // </article>)
    // 注意：不能用 p.price || 0，否则未知价格会被误显示成免费。

【一次多抓一些怎么用】
默认尝试收集 50 个不同商品，最多扫描 5 页；达到目标就停止，不为凑页数继续抓。
例如 /api/remen/products?subCategory=shuma&limit=100&max_pages=10
limit 是最多返回多少条（1~200），max_pages 是最多查看多少页（1~20），不是每页条数。
page 是从第几张亚马逊搜索页开始（1~50），max_pages=1 可保持旧版单页行为。
去广告、跨页去重和小众筛选后，商品可能少于 limit；禁止复制商品或假造销量来凑数。
响应新增 pages_scanned/page_results/stop_reason/partial/next_page，方便看实际扫描情况。
中途失败且已有商品：HTTP 200 + partial=true + warnings；一条都没有就遇到错误：
保留原有 429/502/503/504 错误，不把服务故障冒充“成功但没有商品”。
next_page 是下一张尚未扫描的搜索页，不是数据库游标，也不保证存在下一页；若最后一页
商品超过 limit，会按当前候选排序截断，因此它不保证无遗漏导出，跨请求还需按 ASIN 去重。
fetched_at 是参与本次结果的最早页面时间，各页的精确时间在 page_results 内。
同一批次复用一个独立浏览器；全部命中缓存就不启动浏览器。大批量是串行翻页，真实访问
仍至少间隔三秒；120 秒是页间检查的软预算，已开始的单页
仍受自己的超时控制。请求可能耗时较长，前端/反向代理不要设置几秒钟就断开的超时。

【数据边界，务必理解】
1. 默认请求美国站 Amazon.com；热门页遇到合法区域跳转时支持日本、英国、新加坡站，
   保留实际商品站点链接与币种。推荐采样仍默认限制美国站，不悄悄改变其来源范围。
   图片描述使用商品标题，不伪造详情页长描述。
   美国站也可能按访问地区显示 JPY 等币种，currency 必须读网页，不能写死 USD。
2. “100+ bought in past month”是近月购买趋势估计，不是日销量或精确订单数。
   没有公开提示时 sales=null，不能拿评论数、搜索排名、价格当销量。
3. day / 15-days 参数兼容页面按钮，但不冒充历史筛选：period_applied=false，
   返回当前快照并附 warnings。只累计网页快照也不能还原真实日订单数。
4. hot 在本次搜索结果内按公开购买提示/评论热度排序，不是全站官方热销榜。
   niche 仅指评论数 <=100 的候选，不能据此断言竞争低或销量好。
5. 只改本文件，因而接口不会自动出现在原 backend.app:app 的 8000 服务中。
   以后允许修改入口时可 app.include_router(router)，并用 get_crawler 的说明接入。

【抓取方式与安全】
默认 AMAZON_FETCH_MODE=browser：用独立的无头 Chrome 正常加载公开网页、执行 JS，
并仅在内存复用本爬虫自己获得的匿名 Cookie；不读取日常浏览器账号、历史或用户配置目录。
browser 和 direct 都是本机直连亚马逊，不用第三方抓取服务，不需要抓取令牌。
浏览器依赖（若没有安装）：
    D:\\python\\python.exe -m pip install playwright
本机已有 Chrome，默认 AMAZON_BROWSER_CHANNEL=chrome。若只安装 Edge，可在启动前运行：
    $env:AMAZON_BROWSER_CHANNEL = "msedge"
没有 Chrome/Edge 的服务器可使用 Playwright 自带 Chromium：
    D:\\python\\python.exe -m playwright install chromium
    $env:AMAZON_BROWSER_CHANNEL = "chromium"
如只想研究普通 requests 请求，可设 $env:AMAZON_FETCH_MODE = "direct"。
浏览器模式比普通 HTTP 更接近网页正常运行环境，但不能保证通过风控。遇到验证码/
403/429/503 明确报错并冷却一分钟；不破解验证码、不轮换代理、不关闭 TLS 校验。
成功结果缓存五分钟，真实抓取之间至少间隔三秒；默认首屏在服务运行时每30分钟后台更新，失败保留旧数据。
单进程限流适合本地学习；公网部署还应在网关限流，不能只靠 CORS 防止滥用。

资料依据：
https://playwright.dev/python/docs/browsers
https://sellercentral.amazon.com/seller-forums/discussions/t/144c8912-02b6-442a-bb7c-663f5e27125d

| 参数 | 作用 | 可以填写什么 | 不填写时 |
|---|---|---|---|
| `subCategory` | 选择品类对应的默认搜索词 | 见下方品类表 | `all` |
| `keyword` | 自定义搜索关键词 | 1～100 个字符，不能全是空格 | 使用品类默认搜索词 |
| `category` | 选择商品筛选方式 | `hot` 或 `niche` | `hot` |
| `limit` | 最多返回多少个不同商品 | `1`～`200` | `50` |
| `max_pages` | 最多扫描多少页 | `1`～`20` | `5` |
| `page` | 从第几页开始扫描 | `1`～`50` | `1` |
| `period` | 兼容页面时间按钮 | `current`、`day`、`15-days` | `current` |

| `subCategory` 的值 | 对应品类 |
|---|---|
| `all` | 全部品类 |
| `shuma` | 消费电子与数码 |
| `fuzhuan` | 服装时尚 |
| `jiaju` | 家具园艺 |
| `meir` | 美容健康 |
| `muying` | 母婴玩具 |
| `qimo` | 汽摩配件 |
| `shipin` | 食品保健品 |
| `qita` | 其他特色品类 |
"""



from __future__ import annotations

import copy
import importlib.util
import logging
import math
import os
import re
import sys
import threading
import time
from collections import OrderedDict, deque
from contextlib import ExitStack, contextmanager, asynccontextmanager
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AMAZON_URL = "https://www.amazon.com"
# 这是网页自身的语言/币种偏好，不是“绕过验证”的参数。实测不带偏好时可能被
# 地区设置带到日本站；显式请求英文/美元，实际站点和币种仍以页面为准。
SEARCH_PREFERENCES = {"language": "en_US", "currency": "USD"}
# 热门页允许真实区域站，价格和链接必须来自实际站点；不是放开任意重定向。
# 推荐采样默认仍保持原来的美国站约束，避免悄悄改变每日推荐的资料范围。
MARKETPLACES = {"www.amazon.com": "美国站", "www.amazon.co.jp": "日本站",
                "www.amazon.co.uk": "英国站", "www.amazon.sg": "新加坡站"}


def _marketplace_base(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname in MARKETPLACES
                and parsed.port in (None, 443) and not parsed.username and not parsed.password):
            return "https://" + parsed.hostname
    except ValueError:
        pass
    return None


MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 限制 HTML 体积，避免异常网页无限占用内存。
MAX_PRODUCTS = 200
MAX_BATCH_PAGES = 20
MAX_SEARCH_PAGE = 50
BATCH_SOFT_TIMEOUT = 120  # 页与页之间检查；不谎称能强行中断已经开始的浏览器操作。
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
SALES_PATTERN = re.compile(r"([\d,.]+\s*[kKmM]?\+?)\s+bought in (?:the )?past month", re.I)

# 键名直接对应 Remeng.jsx 的 subCategory，不需要前端翻译中文再发给后端。
# 这些是搜索种子词，不是声称覆盖整个亚马逊大类；keyword 参数可覆盖种子词。
CATEGORIES = {
    "all": ("全部品类", "best sellers"),
    "shuma": ("消费电子与数码", "electronics accessories"),
    "fuzhuan": ("服装时尚", "clothing fashion accessories"),
    "jiaju": ("家具园艺", "home garden accessories"),
    "meir": ("美容健康", "beauty personal care"),
    "muying": ("母婴玩具", "baby toys"),
    "qimo": ("汽摩配件", "automotive accessories"),
    "shipin": ("食品保健品", "grocery dietary supplements"),
    "qita": ("其他特色品类", "handmade craft supplies"),
}
CategoryKey = Literal["all", "shuma", "fuzhuan", "jiaju", "meir", "muying", "qimo", "shipin", "qita"]


class Product(BaseModel):
    """一张商品卡片的数据契约；Pydantic 负责检查输出，不负责抓网页。

    页面刚抓到的是字符串、字典和缺失值，本类把它们统一成稳定的 JSON 字段。
    `| None` 表示公开来源没有这个值；None 序列化成 JSON 的 null，而不是零。
    完整第一页可以保存到独立首屏快照数据库，不写知识库。
    """

    asin: str = Field(description="Amazon 商品 ID；前端列表 key，也用于同页去重")
    title: str = Field(description="公开商品标题，可作为图片下方的描述和 img.alt")
    image_url: str | None = Field(default=None, description="商品主图地址；不是本机文件路径")
    url: str = Field(description="由 ASIN 组成的商品页链接，不保留广告追踪参数")
    price: float | None = Field(default=None, description="当前有效正数价格；零值/缺失/无法确认时为 null，不包括运费/优惠推算")
    currency: str | None = Field(default=None, description="网页实际显示币种，例如 USD/JPY；无法识别为 null，不做汇率换算")
    price_display: str | None = Field(default=None, description="可直接显示的价格，例如 USD 19.99")
    sales: str | None = Field(default=None, description="原始近月购买提示，例如 100+ bought in past month")
    sales_count_min: int | None = Field(default=None, description="从近月提示提取的显示数值；仅供排序，不是精确销量")
    sales_period: Literal["past_month"] | None = Field(default=None, description="仅公开提示明确写近月时赋值")
    rating: float | None = Field(default=None, description="0~5 星评分，不是销量")
    review_count: int | None = Field(default=None, description="评论/评分条数；K 等缩写是近似显示值")
    sponsored: bool = Field(default=False, description="是否为赞助广告；接口默认过滤广告商品")


class PageResult(BaseModel):
    """每一张成功解析的搜索页的小账本；调用方能分清“翻了几页”和“返回几条”。"""

    page: int = Field(description="本次实际读取的亚马逊页号")
    count: int = Field(description="本页解析到的商品数，尚未排除广告或跨页重复")
    added_count: int = Field(description="本页新增的合格唯一商品数，尚未按 limit 截断")
    from_cache: bool = Field(description="该页是否直接复用五分钟内缓存")
    fetched_at: str = Field(description="该页原始抓取时间，而不是本次读取缓存的时间")


class ProductResponse(BaseModel):
    """HTTP 200 的完整结构：products 是数据，warnings 解释不能承诺的数据含义。"""

    products: list[Product]
    category: Literal["hot", "niche"]
    sub_category: str
    sub_category_name: str
    keyword: str
    period: Literal["current", "day", "15-days"]
    period_applied: bool = False
    data_period: str = "current_snapshot"
    page: int
    limit: int
    count: int
    fetched_at: str
    from_cache: bool
    provider: str
    source: str = "Amazon.com"
    source_url: str
    selection_rule: str
    warnings: list[str]
    # 以下是本次请求的进度，不会写入数据库，也不是亚马逊全站商品总数。
    max_pages: int = Field(description="本次允许扫描的最大页数")
    pages_scanned: int = Field(description="成功解析的页数，不包括失败页")
    page_results: list[PageResult] = Field(description="按扫描顺序记录各页来源和新增数量")
    candidate_count: int = Field(description="筛选、去重后且按 limit 截断前的候选数量")
    target_reached: bool = Field(description="是否已获得至少 limit 个合格唯一商品")
    partial: bool = Field(description="是否因中途错误或时间预算提前中断；不足数量不一定是错误")
    stop_reason: Literal["target_reached", "page_limit", "empty_page", "no_progress", "upstream_error", "time_budget"]
    error_code: str | None = Field(default=None, description="中途失败的安全错误码；完整异常不会返回")
    next_page: int | None = Field(default=None, description="后续可尝试的搜索页号，不保证存在，亦非无遗漏导出游标")


@dataclass
class BatchResult:
    """内部传递对象：collect 收集，接口包装；不是前端请求模型，也没有额外 I/O。

    dataclass 自动生成 __init__，大白话就是把本次抓取的小账本装进一个有名字的盒子，
    避免函数返回八个值之后，调用者把第三个和第五个位置拿反。
    """

    products: list[Product]
    pages: list[PageResult]
    stop_reason: str
    next_page: int | None
    error: CrawlError | None = None


class CrawlError(Exception):
    """给底层故障起稳定的错误码；不向浏览器泄露代理凭据、堆栈或原始响应。"""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _config(name: str, default: str = "") -> str:
    """系统环境优先，其次只读项目 .env；不修改 os.environ 或任何文件。

    配置在构造爬虫时读取，启动后改了环境变量应重启本服务。密钥永不返回前端。
    """
    value = os.getenv(name)
    if value is None:
        value = dotenv_values(PROJECT_ROOT / ".env").get(name)
    return str(value).strip() if value is not None else default


def _number(value: object) -> float | None:
    """把美国站 1,299.99 / $19.99 转成数字；解析不到返回 None，不能猜成 0。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    if re.search(r"-\s*\d", str(value)):
        return None
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
    if not match:
        return None
    number = float(match.group().replace(",", ""))
    return number if math.isfinite(number) else None


def _count(value: object) -> int | None:
    """识别 (2.3K)、100+、1,234；K/M 是数量缩写，不是额外销量信息。"""
    number = _number(value)
    if number is None:
        return None
    match = re.search(r"\d(?:\.\d+)?\s*([km])", str(value), re.I)
    multiplier = {"k": 1000, "m": 1_000_000}.get(match[1].lower(), 1) if match else 1
    return int(number * multiplier)


def _currency(price_text: str | None, source_url: str | None = None, *, allow_ambiguous: bool = True) -> str | None:
    """站点域名不等于币种：本机实测 Amazon.com 显示过 JPY，写死 USD 会误导用户。

    优先取明确的三字母币种，再识别符号。¥ 仅在确认日本站来源时兜底为日元。
    以后支持其他国家，需要连数字分隔符规则一起扩展，不能只改域名。
    """
    if not price_text:
        return None
    match = re.search(r"\b(USD|JPY|EUR|GBP|CAD|AUD|CNY|INR|SGD|AED|SAR|MXN|BRL|HKD|NZD|TWD)\b", price_text, re.I)
    if match:
        return match[1].upper()
    for symbol, currency in (("HK$", "HKD"), ("NZ$", "NZD"), ("NT$", "TWD"), ("CA$", "CAD"), ("C$", "CAD"), ("A$", "AUD"), ("S$", "SGD"), ("R$", "BRL"), ("€", "EUR"), ("£", "GBP"), ("₹", "INR")):
        if symbol in price_text:
            return currency
    if re.search(r"日元|日本円|円", price_text):
        return "JPY"
    if re.search(r"人民币|人民幣|RMB|CN[¥￥]", price_text, re.I):
        return "CNY"
    if not allow_ambiguous:
        return None
    base = _marketplace_base(source_url or "")
    if "¥" in price_text or "￥" in price_text:
        return "JPY" if base == "https://www.amazon.co.jp" else None
    if "$" in price_text:
        return "SGD" if base == "https://www.amazon.sg" else "USD"
    return None


def _positive_price(text: str | None) -> float | None:
    """价格专用校验，不能修改通用 _number：评论数/评分的 0 仍然有效。

    搜索请求固定 en_US，允许 1,299.99 / 0.99 / .99；不把 19,99 猜成 19。
    0 元可能是占位或促销条件，并不足以证明商品免费。没有可靠正数就返回 None。
    一个字符串出现两个金额（如价格区间）时不擅自取第一个金额当成交价。
    """
    if not text:
        return None
    numbers = re.findall(r"[+-]?(?:\d[\d,.]*|\.\d+)", text)
    if len(numbers) != 1 or not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?|\.\d{1,2}", numbers[0]):
        return None
    amount = float(numbers[0].replace(",", ""))
    return amount if math.isfinite(amount) and amount > 0 else None


def _price_fields(card, source_url: str | None = None) -> dict:
    """只读本卡片的首个非划线价格块，不把划线原价、运费或每件单价拿来补价格。

    优先读无障碍完整价格；部分布局缺失/显示 0 时，再读取同一块的整数与小数。
    两部分必须用小数点连接，例如 19 和 99 是 19.99，而不是 1999。
    没有正数时三个字段一起置空，避免前端 price=null 却仍显示 $0.00。
    """
    price_block = card.select_one(".a-price:not(.a-text-price)")
    empty = {"price": None, "currency": None, "price_display": None}
    if price_block is None:
        return empty
    full = price_block.select_one(".a-offscreen")
    text = full.get_text(strip=True) if full else None
    amount = _positive_price(text)
    if amount is None:
        whole = price_block.select_one(".a-price-whole")
        fraction = price_block.select_one(".a-price-fraction")
        symbol = price_block.select_one(".a-price-symbol")
        if whole is not None:
            integer = whole.get_text(strip=True).rstrip(".")
            decimal = fraction.get_text(strip=True) if fraction else ""
            # en_US 下小数最多两位；格式不明则放弃，不拼出一个看起来合理的数。
            if not decimal or re.fullmatch(r"\d{1,2}", decimal):
                currency_text = symbol.get_text(strip=True) if symbol else (_currency(text) or "")
                text = f"{currency_text} {integer}{'.' + decimal if decimal else ''}".strip()
                amount = _positive_price(text)
    # 有些布局完整文本只有数字，币种单独放在同一价格块的 symbol 节点。
    # 不读取整张卡片的其他币种，避免把运费或划线原价的单位配给当前金额。
    symbol = price_block.select_one(".a-price-symbol")
    symbol_text = symbol.get_text(strip=True) if symbol else None
    currency = (_currency(text, allow_ambiguous=False) or _currency(symbol_text, allow_ambiguous=False)
                or _currency(text, source_url) or _currency(symbol_text, source_url))
    return {"price": amount, "currency": currency, "price_display": text} if amount is not None else empty


def _safe_url(value: object) -> str | None:
    """图片只允许 HTTP(S)，拒绝 javascript:、data: 和带账号密码的 URL。"""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def _sales(value: object) -> dict:
    """只有明确的近月购买文案才能进入销量字段；reviewCount 永远不能传来凑数。"""
    match = SALES_PATTERN.search(str(value)) if value is not None else None
    return {
        "sales": match.group(0) if match else None,
        "sales_count_min": _count(match[1]) if match else None,
        "sales_period": "past_month" if match else None,
    }


def parse_amazon_html(html: str, source_url: str = AMAZON_URL) -> list[Product]:
    """解析搜索页的公开商品卡片；这是纯函数，给相同 HTML 就得到相同结果。

    BeautifulSoup 把 HTML 变成可以查找的树，select 是 CSS 选择器，不运行 JS。
    先定位每个商品容器，再在容器内部找价格/图片，避免把 A 的价格配到 B 的图。
    注意：亚马逊会改 DOM，选择器失效要修解析器，不能把“解析失败”谎报成无商品。
    """
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('#captchacharacters, form[action*="validateCaptcha"]') or "enter the characters you see below" in soup.get_text(" ", strip=True).lower():
        raise CrawlError("amazon_blocked", "亚马逊要求验证码，已停止抓取；请使用获准的数据接口。", 503)
    # 同时兼容两种布局，不能让一个未填充的主容器遮掉已经有内容的备用容器。
    cards = soup.select('[data-component-type="s-search-result"][data-asin], .s-result-item[data-asin]')
    if not cards:
        if "did not match any products" in soup.get_text(" ", strip=True).lower():
            return []
        raise CrawlError("page_structure_changed", "没有识别到亚马逊商品卡片，可能被拦截或页面结构改变。", 503)
    result = []
    seen = set()
    for card in cards:
        asin = str(card.get("data-asin", "")).upper()
        if not ASIN_PATTERN.fullmatch(asin) or asin in seen:
            continue
        image = card.select_one("img.s-image")
        heading = card.select_one("h2")
        title = (heading.get_text(" ", strip=True) if heading else "") or (image.get("alt", "").strip() if image else "")
        if not title:
            continue
        price_fields = _price_fields(card, source_url)
        # mini 是当前实测布局，small/star 兼容旧版；查询范围仍限于本张商品卡片。
        rating_tag = card.select_one(".a-icon-star-mini .a-icon-alt, .a-icon-star-small .a-icon-alt, .a-icon-star .a-icon-alt")
        review_tag = card.select_one('a[href*="customerReviews"] .s-underline-text, .a-size-base.s-underline-text')
        text = card.get_text(" ", strip=True)
        review_match = re.search(r"([\d,.]+[kKmM]?)\s+(?:ratings|reviews)\b", text, re.I)
        rating = _number(rating_tag.get_text() if rating_tag else None)
        result.append(Product(
            asin=asin, title=title[:1000], image_url=_safe_url(image.get("src")) if image else None,
            url=f"{_marketplace_base(source_url) or AMAZON_URL}/dp/{asin}", **price_fields,
            rating=rating if rating is not None and 0 <= rating <= 5 else None,
            review_count=_count(review_tag.get_text()) if review_tag else (_count(review_match[1]) if review_match else None),
            sponsored=bool(card.select_one('.puis-sponsored-label-text, [aria-label="Sponsored"]')),
            **_sales(text),
        ))
        seen.add(asin)
    if cards and not result:
        raise CrawlError("page_structure_changed", "商品容器存在但缺少有效 ASIN/标题，请检查页面结构。", 502)
    return result


def _next_search_url(html: str, keyword: str, page: int, source_url: str = AMAZON_URL) -> str | None:
    """读取网页真正的“下一页”链接，而不是每次把第一页网址的 page 数字加一。

    实测链接还带当前搜索的翻页参数；连续访问该链接，比丢掉这些参数重新搜索更稳定。
    但网页内容不可信：必须验证 HTTPS、同一已确认站点、/s 路径、同一关键词、页号恰好 +1，
    不能让一个被篡改的链接把爬虫带到登录页、其他站点或服务器内网。
    没有合格链接就返回 None，调用方仍可使用受控的搜索 URL，不盲目访问它。
    """
    anchor = BeautifulSoup(html, "html.parser").select_one("a.s-pagination-next[href]")
    if anchor is None:
        return None
    href = str(anchor.get("href", ""))
    if len(href) > 4096:
        return None
    try:
        base = _marketplace_base(source_url) or AMAZON_URL
        target = urljoin(base + "/s", href)
        parsed = urlsplit(target)
        query = parse_qs(parsed.query)
        if (parsed.scheme == "https" and parsed.hostname == urlsplit(base).hostname
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path == "/s" and query.get("k") == [keyword]
                and query.get("page") == [str(page + 1)]):
            return target
    except ValueError:
        pass
    return None


class AmazonCrawler:
    """一个进程复用一个实例，把配置、缓存、访问节奏放在一起。

    __init__ 在创建实例时运行，只准备本地状态；直到 fetch 才访问亚马逊。
    浏览器不是你的日常 Chrome 窗口：它使用独立临时上下文，关闭后不会留下登录档案。
    类实例中的缓存/Cookie 仅活到进程退出，不写文件，不碰正式业务数据库。
    """

    def __init__(self, mode: str | None = None, *, allow_regional_redirects: bool = False):
        self.provider = mode or _config("AMAZON_FETCH_MODE", "browser")
        if self.provider not in {"direct", "browser"}:
            raise ValueError("AMAZON_FETCH_MODE 只支持 browser 或 direct，两者都是本机直连")
        self.channel = _config("AMAZON_BROWSER_CHANNEL", "chrome")
        if self.channel not in {"chrome", "msedge", "chromium"}:
            raise ValueError("AMAZON_BROWSER_CHANNEL 只支持 chrome、msedge、chromium")
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        # 一次只运行一个抓取任务，避免多个浏览器争抢资源和同时访问同一站点。
        self._slots = threading.BoundedSemaphore(1)
        # HTTP 批次也只放行一个，避免多个批次各留一个浏览器、轮流抢单页名额。
        self._batch_slots = threading.BoundedSemaphore(1)
        self._visits = OrderedDict()
        self._next_fetch_at = 0.0
        self._blocked_until = 0.0
        self._browser_state = None
        self.allow_regional_redirects = allow_regional_redirects
        self._marketplace_url = AMAZON_URL
        # 跨 HTTP 请求保留已校验的下一页链接。滚动一次就是一次请求，不能只放闭包里。
        self._next_urls = OrderedDict()

    def _accept_browser_url(self, url: str) -> None:
        base = _marketplace_base(url)
        if base is None or (base != AMAZON_URL and not self.allow_regional_redirects):
            raise CrawlError("unexpected_redirect", "商品页跳转到非支持站点，已停止解析。")
        if base != self._marketplace_url:
            with self._lock:
                # 站点切换后不能用另一市场相同关键词/页码的缓存冒充新站点结果。
                self._marketplace_url = base
                self._cache.clear()
                self._next_urls.clear()

    def invalidate_page(self, keyword: str, page: int):
        """用户主动刷新只失效这一页缓存，仍必须通过后续请求间隔/冷却/并发检查。"""
        with self._lock:
            self._cache.pop((keyword, page), None)

    def check_rate(self, address: str) -> None:
        """每个 IP 每分钟最多 20 次。只信 TCP 地址，不盲信可伪造的 X-Forwarded-For。"""
        now = time.monotonic()
        with self._lock:
            bucket = self._visits.setdefault(address, deque())
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= 20:
                raise CrawlError("rate_limited", "请求过于频繁，请一分钟后再试。", 429)
            bucket.append(now)
            self._visits.move_to_end(address)
            while len(self._visits) > 1024:
                self._visits.popitem(last=False)

    @staticmethod
    def _check_status(status: int) -> None:
        """HTTP 200 不一定代表商品页，还需由解析器检查验证码；其他状态先在这里拦下。"""
        if status in {403, 429, 503}:
            raise CrawlError("amazon_blocked", "亚马逊限制了当前访问或暂不可用，已暂停抓取一分钟；没有返回假数据。", 503)
        if status != 200:
            raise CrawlError("upstream_http_error", f"亚马逊返回 HTTP {status}，未取得有效商品数据。")

    def _download(self, keyword: str, page: int) -> bytes:
        """requests 直连模式：不运行网页 JS，因此可能拿到验证页而不是商品。

        固定域名，用户只能传关键词不能传网址，避免服务器被当成任意网址代理。
        params 自动处理中文、空格和 &；stream 限制下载体积；不关闭 HTTPS 证书校验。
        """
        try:
            with requests.get(AMAZON_URL + "/s", params={"k": keyword, **SEARCH_PREFERENCES, "page": page}, headers={
                "User-Agent": "KuajingProductResearch/1.0 (public product information)",
                "Accept-Language": "en-US,en;q=0.9",
            }, timeout=(10, 30), allow_redirects=False, stream=True) as response:
                self._check_status(response.status_code)
                body = bytearray()
                deadline = time.monotonic() + 45
                for block in response.iter_content(64 * 1024):
                    body.extend(block)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise CrawlError("response_too_large", "网页超过 5 MiB 安全大小限制。")
                    if time.monotonic() > deadline:
                        raise CrawlError("upstream_timeout", "网页下载时间过长，已停止。", 504)
                return bytes(body)
        except requests.exceptions.SSLError as error:
            raise CrawlError("tls_error", "HTTPS 证书校验失败，请检查系统时间、证书或代理；不要关闭证书校验。") from error
        except requests.Timeout as error:
            raise CrawlError("upstream_timeout", "抓取等待超时，请稍后重试。", 504) from error
        except requests.RequestException as error:
            # 原始异常可能包含代理凭据，故意不用 str(error)，日志也不输出 exc_info。
            raise CrawlError("upstream_connection_error", "无法连接亚马逊，请检查网络或代理。") from error

    @contextmanager
    def _browser_session(self) -> Iterator[Callable[[str, int], bytes]]:
        """把“打开一次、连续翻页、最后关闭”打包成 with 可管理的资源。

        @contextmanager + yield 大白话：先开浏览器，把一个下载函数借给调用者，调用者
        用完或中途报错，最终都回到 finally 关掉浏览器。yield 这里不是 SSE，不发送网络事件。
        下载函数是闭包：记住本批次的 tab/context，不用把浏览器对象放进全局变量。
        它只能在创建自己的工作线程内调用，整个 collect 使用普通同步 def，满足这个要求。

        storage_state 只保存本爬虫匿名上下文的 Cookie/localStorage 快照，减少每次都像
        新访客的情况；不是你的日常浏览器账号，不保存到磁盘。批内直接复用同一个页面，
        不必每翻一页启动一次 Chrome，网页会话和页面自身状态也能保持连续。
        """
        try:
            # 延迟导入：缺少浏览器依赖时，普通 direct 模式和离线测试仍然可以运行。
            from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout, sync_playwright
        except ImportError as error:
            raise CrawlError("browser_dependency_missing",
                             "浏览器直连需要 Playwright：请运行 D:\\python\\python.exe -m pip install playwright 后重启。", 503) from error

        try:
            with sync_playwright() as driver:
                options = {"headless": True, "timeout": 15_000}
                if self.channel != "chromium":
                    options["channel"] = self.channel
                # headless=True 不弹窗；使用浏览器自己的 UA/指纹，不加“隐身补丁”。
                browser = driver.chromium.launch(**options)
                try:
                    context = browser.new_context(locale="en-US", viewport={"width": 1365, "height": 900},
                                                  storage_state=self._browser_state)
                    try:
                        tab = context.new_page()
                        tab.set_default_timeout(8_000)
                        def download(keyword: str, page: int) -> bytes:
                            """等有效商品再解析；暂时未就绪最多恢复一次，不把错误交给用户反复点击。"""
                            key = (keyword, page)
                            with self._lock:
                                entry = self._next_urls.get(key)
                            url = entry[1] if entry and entry[0] > time.monotonic() else (
                                self._marketplace_url + "/s?" + urlencode(
                                    {"k": keyword, **SEARCH_PREFERENCES, "page": page}))
                            for attempt in range(2):
                                try:
                                    response = tab.goto(url, wait_until="domcontentloaded", timeout=35_000)
                                    if response is None:
                                        raise CrawlError("upstream_timeout", "商品页正在跳转，暂未取得完整响应。", 504)
                                    self._check_status(response.status)
                                    self._accept_browser_url(tab.url)
                                    # 容器先出现，ASIN/标题可能后填。旧条件只等到空容器就开始解析。
                                    # 等真实字段而非 networkidle，避免广告/统计长连接一直占住页面。
                                    try:
                                        tab.wait_for_function("""() => {
                                            if (document.querySelector('#captchacharacters, form[action*="validateCaptcha"]')
                                                || /did not match any products/i.test(document.body?.innerText || '')) return true;
                                            return [...document.querySelectorAll('[data-component-type="s-search-result"][data-asin], .s-result-item[data-asin]')]
                                                .some(card => /^[A-Z0-9]{10}$/i.test(card.dataset.asin || '')
                                                    && (card.querySelector('h2')?.textContent?.trim()
                                                        || card.querySelector('img.s-image')?.alt?.trim()));
                                        }""", timeout=12_000)
                                    except BrowserTimeout:
                                        pass  # 解析器区分验证码、暂未完成和真正的空搜索，不伪造空列表。
                                    self._accept_browser_url(tab.url)
                                    raw = tab.content().encode("utf-8")
                                    if len(raw) > MAX_RESPONSE_BYTES:
                                        raise CrawlError("response_too_large", "渲染后的网页超过 5 MiB 安全大小限制。")
                                    parse_amazon_html(raw.decode("utf-8"), self._marketplace_url)
                                    next_url = _next_search_url(raw.decode("utf-8"), keyword, page, self._marketplace_url)
                                    if next_url is not None:
                                        with self._lock:
                                            self._next_urls[(keyword, page + 1)] = (time.monotonic() + 300, next_url)
                                            self._next_urls.move_to_end((keyword, page + 1))
                                            while len(self._next_urls) > 64:
                                                self._next_urls.popitem(last=False)
                                    self._browser_state = context.storage_state()
                                    return raw
                                except BrowserTimeout:
                                    problem = CrawlError("upstream_timeout", "浏览器加载商品页超时，请稍后重试。", 504)
                                except BrowserError as error:
                                    raise CrawlError("browser_unavailable", "浏览器未能继续加载商品，请检查网络后重试。", 503) from error
                                except CrawlError as error:
                                    problem = error
                                # 验证码、限制访问和外部站点不重试，继续遵守原有冷却机制。
                                if attempt or problem.code not in {"page_structure_changed", "upstream_timeout"}:
                                    raise problem
                                LOGGER.info("amazon_page_recovery page=%s code=%s", page, problem.code)
                                time.sleep(max(3.0, self._next_fetch_at - time.monotonic()))
                                self._next_fetch_at = time.monotonic() + 3
                                # 使用已确认市场的同一页，不前进游标、不回第一页、不改关键词。
                                url = self._marketplace_url + "/s?" + urlencode(
                                    {"k": keyword, **SEARCH_PREFERENCES, "page": page})

                        yield download
                    finally:
                        context.close()
                finally:
                    browser.close()
        except BrowserTimeout as error:
            raise CrawlError("upstream_timeout", "浏览器操作超时，请稍后重试。", 504) from error
        except BrowserError as error:
            raise CrawlError("browser_unavailable",
                             "浏览器未能启动或连接网页。请确认已安装 Chrome，或设置 AMAZON_BROWSER_CHANNEL=msedge；同时检查网络。", 503) from error

    def _download_browser(self, keyword: str, page: int) -> bytes:
        """兼容单页抓取：开一个独立会话取一页；批量抓取会复用 _browser_session。"""
        with self._browser_session() as download:
            return download(keyword, page)

    def fetch(self, keyword: str, page: int, *, wait_for_interval: bool = False,
              browser_downloader: Callable[[str, int], bytes] | None = None) -> tuple[list[Product], str, bool]:
        """返回 (商品列表, UTC 抓取时间, 是否命中缓存)，是两种下载方式共同的入口。

        大白话：先看抽屉里有没有五分钟内的结果，有就直接拿；没有才访问远端。
        锁只保护很短的内存操作，不在持锁时等网络。信号量相当于只有一张“抓取通行证”，
        finally 确保失败也归还通行证。冷却期间仍允许读取有效缓存，不发新的网络请求。
        wait_for_interval 仅供批量循环使用：翻页太快就等剩余的三秒间隔；不是绕开限流。
        单页调用仍默认立即报 429。等待时已取得通行证，别的请求不能插队同时访问。
        browser_downloader 是可选的“怎么取网页”函数：批量时传入复用浏览器的版本，
        不传则按原来的单页方式。先查缓存再调用它，所以全缓存命中时不会启动浏览器。
        """
        key = (keyword, page)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1]), cached[2], True
        if not self._slots.acquire(blocking=False):
            raise CrawlError("crawler_busy", "已有抓取任务正在处理，请稍后再试。", 429)
        try:
            now = time.monotonic()
            if now < self._blocked_until:
                raise CrawlError("amazon_cooldown", "亚马逊刚刚限制访问，正在冷却，请一分钟后再试。", 503)
            if now < self._next_fetch_at:
                if not wait_for_interval:
                    raise CrawlError("crawl_interval", "两次真实抓取至少间隔三秒，请稍后再试。", 429)
                time.sleep(self._next_fetch_at - now)
            self._next_fetch_at = time.monotonic() + 3
            if self.provider == "browser":
                download = browser_downloader or self._download_browser
                raw = download(keyword, page)
            else:
                raw = self._download(keyword, page)
            products = parse_amazon_html(raw.decode("utf-8", errors="replace"), self._marketplace_url)
            fetched_at = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._cache[key] = (time.monotonic() + 300, copy.deepcopy(products), fetched_at)
                self._cache.move_to_end(key)
                while len(self._cache) > 64:
                    self._cache.popitem(last=False)
            return products, fetched_at, False
        except CrawlError as error:
            if error.code == "amazon_blocked":
                self._blocked_until = time.monotonic() + 60
            raise
        finally:
            self._slots.release()

    def collect(self, keyword: str, page: int, limit: int, max_pages: int,
                category: Literal["hot", "niche"]) -> BatchResult:
        """批量入口负责资源生命周期；翻页和计数交给 _collect_pages。

        ExitStack 可以理解为“资源归还清单”：首次缺页时才登记一个浏览器，
        之后所有缺页复用它，成功、失败或提前返回，离开 with 都自动归还。
        浏览器下载函数只存在于本次调用中，不跨请求、跨线程共享。
        """
        if not self._batch_slots.acquire(blocking=False):
            raise CrawlError("crawler_busy", "已有批量抓取正在进行，请等待完成后再发起新请求。", 429)
        try:
            with ExitStack() as resources:
                shared_download = None

                def download(keyword: str, page: int) -> bytes:
                    nonlocal shared_download  # 更新外层本批次变量，不是修改全局浏览器。
                    if shared_download is None:
                        shared_download = resources.enter_context(self._browser_session())
                    return shared_download(keyword, page)

                return self._collect_pages(keyword, page, limit, max_pages, category, download)
        finally:
            self._batch_slots.release()

    def _collect_pages(self, keyword: str, page: int, limit: int, max_pages: int,
                       category: Literal["hot", "niche"],
                       browser_downloader: Callable[[str, int], bytes]) -> BatchResult:
        """一次 HTTP 请求内逐页收集，保留原 fetch 的缓存、浏览器隔离和拦截冷却。

        谁调用：collect；输入是已校验的关键词、起始页、数量、页数和筛选类型。
        为什么不能只把 limit 改成 200：一页若只有 16 件，切片 [:200] 仍只有 16 件。
        要真的多拿，必须逐页读取；但只在过滤后的不同商品够数时才能停止，否则重复商品
        或广告会把数量虚撑大。每页缓存保存原始商品，不保存当前用户的 hot/niche 筛选。

        dict 以 ASIN 为键：同一商品跨页出现时只保留首次合格记录，避免价格/字段乱混。
        连续两页没有新增原始 ASIN 才停止；“小众筛选全不合格”不能误判成没有下一页。
        后续页面失败时不重跑前面成功页面，也不无限重试；已有数据交回接口并明确标记。
        """
        if not (1 <= page <= MAX_SEARCH_PAGE and 1 <= limit <= MAX_PRODUCTS
                and 1 <= max_pages <= MAX_BATCH_PAGES and category in {"hot", "niche"}):
            raise ValueError("收集参数越界；HTTP 调用由 Query 校验，直接调用 collect 也不能跳过限制")
        started = time.monotonic()
        products_by_asin = {}
        seen_raw_asins = set()
        records = []
        duplicate_pages = 0
        next_page = page
        stop_reason = "page_limit"
        error = None
        for current_page in range(page, min(page + max_pages, MAX_SEARCH_PAGE + 1)):
            if time.monotonic() - started >= BATCH_SOFT_TIMEOUT:
                if not products_by_asin:
                    raise CrawlError("batch_timeout", "本批次达到时间预算，尚未找到符合条件的商品。", 504)
                stop_reason = "time_budget"
                break
            try:
                items, fetched_at, cached = self.fetch(keyword, current_page, wait_for_interval=True,
                                                       browser_downloader=browser_downloader)
            except CrawlError as caught:
                if not products_by_asin:
                    raise
                error = caught
                stop_reason = "upstream_error"
                next_page = current_page  # 失败页尚未收集，后续从这里继续而不是跳过。
                break
            before = len(products_by_asin)
            raw_asins = {item.asin for item in items}
            new_raw_asins = raw_asins - seen_raw_asins
            seen_raw_asins.update(raw_asins)
            for item in items:
                if item.sponsored:
                    continue
                if category == "niche" and (item.review_count is None or item.review_count > 100):
                    continue
                products_by_asin.setdefault(item.asin, item)
            records.append(PageResult(page=current_page, count=len(items),
                                      added_count=len(products_by_asin) - before,
                                      from_cache=cached, fetched_at=fetched_at))
            next_page = current_page + 1 if current_page < MAX_SEARCH_PAGE else None
            if len(products_by_asin) >= limit:
                stop_reason = "target_reached"
                break
            if not items:
                stop_reason, next_page = "empty_page", None
                break
            duplicate_pages = duplicate_pages + 1 if not new_raw_asins else 0
            if duplicate_pages >= 2:
                # 有些搜索只重复返回上一页。不能继续请求到页数上限再把重复当作新数据。
                stop_reason, next_page = "no_progress", None
                break
        return BatchResult(list(products_by_asin.values()), records, stop_reason, next_page, error)


router = APIRouter(prefix="/api/remen", tags=["热门产品"])


def get_crawler(request: Request) -> AmazonCrawler:
    """Depends 会在请求时调用本函数：取当前应用实例，而不是每个请求新建缓存。

    以后接到统一 app 时，先 app.state.amazon_crawler = AmazonCrawler()，再
    include_router(router)，并注册 create_app 中同样的 CrawlError 异常处理器。
    更省事的方式是把本 app 挂载到统一服务，但须核对路径。不要只为常量导入推荐 agent。
    """
    return request.app.state.amazon_crawler


@router.get("/products", response_model=ProductResponse, summary="抓取亚马逊公开商品卡片")
def get_products(
    request: Request,
    category: Literal["hot", "niche"] = Query("hot", description="hot=当前候选热度排序；niche=评论数不超过100的候选"),
    period: Literal["current", "day", "15-days"] = Query("current", description="day/15-days只兼容页面参数，不伪造历史销量"),
    sub_category: CategoryKey = Query("all", alias="subCategory", description="与前端 subCategory 的键名对应"),
    keyword: str | None = Query(None, min_length=1, max_length=100, description="可选自定义关键词，覆盖品类种子词"),
    page: int = Query(1, ge=1, le=MAX_SEARCH_PAGE, description="从第几张亚马逊搜索页开始，不是全站商品数据库分页"),
    limit: int = Query(50, ge=1, le=MAX_PRODUCTS, description="本次最多返回的合格唯一商品数，默认50；数量不够会继续翻页"),
    max_pages: int = Query(5, ge=1, le=MAX_BATCH_PAGES, description="本次最多扫描的页数，默认5、最多20；设1恢复单页行为"),
    crawler: AmazonCrawler = Depends(get_crawler),
    refresh: bool = Query(False, description="主动更新时忽略这一页缓存，仍遵守冷却与限流"),
) -> ProductResponse:
    """前端 GET 的入口，普通 def 会由 FastAPI 线程池执行，不阻塞异步事件循环。

    Query 在函数运行前校验参数，不合法返回 422；Depends 注入可替换的爬虫，
    测试可换 Fake 而不联网。200 可能少于 limit 条，因为缺失、广告、小众筛选
    会减少结果；不能用假商品补满。429=本机限流/忙碌，502=网络/解析异常，
    503=上游限制或缺配置，504=超时；错误 detail 中有 error_code 和 message。
    多页请求中途出错而前面已有商品，则 HTTP 200 + partial=true；前端先显示已有商品，
    再显示 warnings，不要只凭 200 就告诉用户“已抓满”。max_pages 不是并发线程数量。
    """
    crawler.check_rate(request.client.host if request.client else "unknown")
    name, seed = CATEGORIES[sub_category]
    query = keyword.strip() if keyword is not None else seed
    if not query:
        raise HTTPException(422, detail={"error_code": "empty_keyword", "message": "关键词不能只包含空白。"})
    if refresh:
        crawler.invalidate_page(query, page)
    batch = crawler.collect(query, page, limit, max_pages, category)
    result = _product_response(batch, category, sub_category, period, query, page, limit, max_pages, crawler)
    store = getattr(request.app.state, 'first_pages', None)
    if store is not None and keyword is None and limit == 200 and max_pages == 1:
        try:
            store.save(result.model_dump(mode='json'))
        except Exception as error:
            LOGGER.warning('first_page_save error=%s', type(error).__name__)
    return result


def _product_response(batch, category, sub_category, period, query, page, limit, max_pages, crawler):
    """接口和后台定时任务共用字段转换，避免保存数据的币种、价格或游标与接口错位。"""
    name, _ = CATEGORIES[sub_category]
    products = batch.products
    candidate_count = len(products)
    warnings = ["这是本次扫描搜索页的公开快照，不代表亚马逊全站榜单；价格和可售状态以商品页为准。"]
    if category == "niche":
        products.sort(key=lambda p: p.review_count)
        rule = "本次扫描页非广告且跨页去重的商品中，已公开评论数不超过100；按评论数升序。"
        warnings.append("小众只是低评论数候选，不等于低竞争或高利润；缺少评论数的商品不参与判断。")
    else:
        products.sort(key=lambda p: (p.sales_count_min is not None, p.sales_count_min or 0, p.review_count or 0), reverse=True)
        rule = "本次扫描页非广告且跨页去重的商品中，优先按公开近月购买提示降序，再按评论热度；不是官方销量排名。"
    if period != "current":
        warnings.append("公开搜索页不提供近一天/近15天真实销量，本请求未按该时间段筛选，返回当前快照。")
    products = products[:limit]
    if batch.error is not None:
        warnings.append(f"第 {batch.next_page} 页中断（{batch.error.code}）：{batch.error.message} 已保留前面成功取得的商品。")
    if batch.stop_reason == "time_budget":
        warnings.append("达到批量抓取的页间时间预算，已停止继续翻页；可以稍后从 next_page 继续。")
    if batch.stop_reason == "no_progress":
        warnings.append("连续两页没有新的商品 ID，已停止重复抓取；这不表示已遍历亚马逊全部商品。")
    if len(products) < limit:
        warnings.append(f"目标最多 {limit} 条，实际获得 {len(products)} 条；已成功扫描 {len(batch.pages)} 页，停止原因：{batch.stop_reason}。")
    if any(p.sales is None for p in products):
        warnings.append("部分商品未公开近月购买提示，sales 为 null；评论数不会被当作销量。")
    if not products:
        warnings.append("本次扫描没有符合条件的商品，可换关键词、品类或页码；没有填充模拟数据。")
    return ProductResponse(
        products=products, category=category, sub_category=sub_category, sub_category_name=name,
        keyword=query, period=period, page=page, limit=limit, count=len(products),
        fetched_at=min(record.fetched_at for record in batch.pages),
        from_cache=all(record.from_cache for record in batch.pages), provider=crawler.provider,
        source_url=("https://" + urlsplit(products[0].url).hostname if products else crawler._marketplace_url) + "/s?" + urlencode({"k": query, **SEARCH_PREFERENCES, "page": page}),
        selection_rule=rule, warnings=warnings,
        max_pages=max_pages, pages_scanned=len(batch.pages), page_results=batch.pages,
        candidate_count=candidate_count, target_reached=candidate_count >= limit,
        partial=batch.stop_reason in {"upstream_error", "time_budget"},
        stop_reason=batch.stop_reason, error_code=batch.error.code if batch.error else None,
        next_page=batch.next_page,
    )


@router.get("/products/snapshot", summary="快速读取最近保存的首屏，不进行抓取")
def first_page_snapshot(request: Request, category: Literal['hot', 'niche'] = Query('hot'),
                        sub_category: CategoryKey = Query('all', alias='subCategory')):
    store = getattr(request.app.state, 'first_pages', None)
    payload = store.read(category, sub_category) if store else None
    # no-store 防止浏览器/代理缓存把新发布的快照又变成固定首屏。
    return JSONResponse(content={'snapshot': payload}, headers={'Cache-Control':'no-store'})


@router.get("/health", summary="检查爬虫依赖，不访问亚马逊")
def health(crawler: AmazonCrawler = Depends(get_crawler)) -> dict:
    """configured 仅表示 Python 依赖齐全，不承诺浏览器已安装或远端没有风控。"""
    dependency_ready = importlib.util.find_spec("playwright") is not None
    return {"configured": crawler.provider == "direct" or dependency_ready,
            "provider": crawler.provider, "browser_channel": crawler.channel,
            "browser_dependency_installed": dependency_ready,
            "marketplace": urlsplit(crawler._marketplace_url).hostname, "live_checked": False}


def create_app(crawler: AmazonCrawler | None = None, *, snapshot_path=None, schedule=None) -> FastAPI:
    """应用工厂：正式启动传真实爬虫，测试传 Fake；接口代码不必写两套。"""
    # Fake 爬虫默认关闭正式存储/定时联网；测试可显式传临时数据库，避免写正式数据。
    if __package__:
        from .first_page import FirstPageStore, FirstPageUpdater, DEFAULT_PATH
    else:
        from first_page import FirstPageStore, FirstPageUpdater, DEFAULT_PATH
    enabled = crawler is None if schedule is None else schedule

    @asynccontextmanager
    async def lifespan(application):
        updater = task = None
        if application.state.first_pages is None and enabled:
            application.state.first_pages = FirstPageStore(DEFAULT_PATH)
        if enabled:
            shared = application.state.amazon_crawler
            def refresh_default():
                query = CATEGORIES['all'][1]
                batch = shared.collect(query, 1, 200, 1, 'hot')
                return _product_response(batch, 'hot', 'all', 'current', query, 1, 200, 1, shared).model_dump(mode='json')
            updater = FirstPageUpdater(application.state.first_pages, refresh_default)
            task = asyncio.create_task(updater.run())
        try:
            yield
        finally:
            if updater:
                await updater.stop()
                await task

    application = FastAPI(title="跨境阁：亚马逊商品抓取", version="1.0.0", lifespan=lifespan)
    application.state.first_pages = FirstPageStore(snapshot_path) if snapshot_path is not None else None
    application.state.amazon_crawler = crawler if crawler is not None else AmazonCrawler(allow_regional_redirects=True)
    origins = [origin.strip().rstrip("/") for origin in _config(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("FRONTEND_ORIGINS 请填写具体前端来源，不允许 *")
    application.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                               allow_methods=["GET"], allow_headers=["Accept", "Content-Type"])

    @application.exception_handler(CrawlError)
    async def handle_crawl_error(_request: Request, error: CrawlError) -> JSONResponse:
        # handler 只编码 JSON，不做阻塞网络 IO；它把底层故障翻译为稳定公开协议。
        LOGGER.warning("amazon_crawler error_code=%s", error.code)
        return JSONResponse(status_code=error.status, content={"detail": {
            "error_code": error.code, "message": error.message,
        }}, headers={"Retry-After": "60"} if error.status == 429 or error.code in {"amazon_blocked", "amazon_cooldown"} else None)

    application.include_router(router)
    return application


app = create_app()


def _self_test() -> None:
    """测试也放在这个文件，遵守只改本文件的范围；所有输入都是离线夹具。

    unittest 按 test_ 方法找用例；assert 是把期望写成代码，出错时能定位哪一条。
    Fake 在边界替换网络，不碰真实服务、知识库或浏览器历史。
    Arrange 准备 HTML，Act 调解析/接口，Assert 检查输出，这就是测试常说的 AAA 三步。
    """
    import unittest
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient

    sample = '''<div data-component-type="s-search-result" data-asin="B012345678">
    <h2><span>Example headphones</span></h2><img class="s-image" src="https://m.media-amazon.com/item.jpg">
    <span class="a-price"><span class="a-offscreen">$19.99</span></span>
    <i class="a-icon-star-small"><span class="a-icon-alt">4.5 out of 5 stars</span></i>
    <span class="a-size-base s-underline-text">(50)</span><span>1K+ bought in past month</span></div>'''

    def fake_products(start: int, count: int, **changes) -> list[Product]:
        """可控地制造不同 ASIN；仅用于断言翻页数量，绝不混入正式接口响应。"""
        return [Product(asin=f"B{index:09d}", title=f"Fixture {index}",
                        url=f"{AMAZON_URL}/dp/B{index:09d}", review_count=50,
                        sales_count_min=index, **changes) for index in range(start, start + count)]

    fixture_time = "2026-09-18T00:00:00+00:00"

    class Tests(unittest.TestCase):
        def test_html(self):
            product = parse_amazon_html(sample)[0]
            self.assertEqual((product.price, product.review_count, product.sales_count_min), (19.99, 50, 1000))
            self.assertEqual(product.sales_period, "past_month")

        def test_missing_not_zero(self):
            html = '<div data-component-type="s-search-result" data-asin="B012345678"><h2>Example</h2><span>232 reviews</span></div>'
            result = parse_amazon_html(html)[0]
            self.assertIsNone(result.price)
            self.assertIsNone(result.sales)
            self.assertIsNone(result.sales_count_min)

        def test_html_zero_price_and_dedupe(self):
            result = parse_amazon_html((sample + sample).replace("$19.99", "$0.00"))
            self.assertEqual(len(result), 1)
            self.assertIsNone(result[0].price)
            self.assertIsNone(result[0].price_display)
            self.assertIsNone(result[0].currency)
            self.assertEqual(result[0].sales_count_min, 1000)

        def test_split_price_and_zero_placeholder(self):
            for full in ("", '<span class="a-offscreen">$0.00</span>'):
                parts = full + '<span class="a-price-symbol">S$</span><span class="a-price-whole">19<span>.</span></span><span class="a-price-fraction">99</span>'
                product = parse_amazon_html(sample.replace('<span class="a-offscreen">$19.99</span>', parts))[0]
                self.assertEqual((product.price, product.currency), (19.99, "SGD"))

        def test_price_validation_and_currencies(self):
            for text, amount, currency in (("JPY 2,333", 2333, "JPY"), ("SGD 19.99", 19.99, "SGD"), ("S$19.99", 19.99, "SGD"), ("$0.99", .99, "USD"), ("$.99", .99, "USD"), ("£12.50", 12.5, "GBP"), ("CNY 88", 88, "CNY")):
                product = parse_amazon_html(sample.replace("$19.99", text))[0]
                self.assertEqual((product.price, product.currency), (amount, currency))
            for text in ("$0", "$0.00", "$-1", "EUR 19,99", "$10 - $20", "unknown"):
                product = parse_amazon_html(sample.replace("$19.99", text))[0]
                self.assertIsNone(product.price)
                self.assertIsNone(product.price_display)

        def test_no_fallback_to_list_price_or_shipping(self):
            html = sample.replace('$19.99', '$0.00').replace('</h2>', '</h2><span class="a-price a-text-price"><span class="a-offscreen">$99.99</span></span>')
            html += '<span>$5 shipping</span>'
            self.assertIsNone(parse_amazon_html(html)[0].price)

        def test_live_layout_currency_and_mini_rating(self):
            # 用实测结构做离线回归：修一次选择器，就留一个夹具防止以后又改坏。
            html = sample.replace("$19.99", "JPY\u00a02,333").replace("a-icon-star-small", "a-icon-star-mini")
            product = parse_amazon_html(html)[0]
            self.assertEqual((product.price, product.currency, product.rating), (2333, "JPY", 4.5))
            self.assertEqual(_currency("$19.99"), "USD")
            self.assertEqual(_currency("C$19.99"), "CAD")
            self.assertIsNone(_currency("¥100"))

        def test_blocked_and_changed_pages(self):
            for html in ['<input id="captchacharacters">', '<html>Unexpected page</html>']:
                with self.assertRaises(CrawlError):
                    parse_amazon_html(html)

        def test_http_parameters_and_period(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "_download", return_value=sample.encode()) as download:
                with TestClient(create_app(crawler)) as client:
                    response = client.get("/api/remen/products?subCategory=shuma&period=day&max_pages=1")
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.json()["period_applied"])
                    self.assertEqual(response.json()["count"], 1)
                    self.assertTrue(client.get("/api/remen/products?subCategory=shuma&max_pages=1").json()["from_cache"])
                    for query in ["page=0", "page=51", "limit=201", "max_pages=0", "max_pages=21", "subCategory=bad", "period=year", "keyword=%20%20"]:
                        self.assertEqual(client.get("/api/remen/products?" + query).status_code, 422)
                self.assertEqual(download.call_count, 1)

        def test_niche_and_advertisements(self):
            crawler = AmazonCrawler(mode="direct")
            raw = sample + sample.replace('B012345678', 'B012345679').replace('(50)', '(500)')
            raw += sample.replace('B012345678', 'B012345670').replace('<h2>', '<span aria-label="Sponsored">Ad</span><h2>')
            with patch.object(crawler, "_download", return_value=raw.encode()):
                result = TestClient(create_app(crawler)).get("/api/remen/products?category=niche&max_pages=1").json()
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["products"][0]["review_count"], 50)

        def test_network_error_does_not_leak_secret(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(requests, "get", side_effect=requests.ConnectionError('https://example.invalid?token=fake-secret')):
                response = TestClient(create_app(crawler)).get("/api/remen/products")
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("fake-secret", response.text)

        def test_rate_limit_and_busy_release(self):
            crawler = AmazonCrawler(mode="direct")
            for _ in range(20):
                crawler.check_rate("fixture")
            with self.assertRaises(CrawlError):
                crawler.check_rate("fixture")
            with patch.object(crawler, "_download", side_effect=CrawlError("fixture", "fixture")):
                for _ in range(3):
                    crawler._next_fetch_at = 0  # 测名额归还，不让访问间隔掩盖本测试的故障。
                    with self.assertRaises(CrawlError) as caught:
                        crawler.fetch("fixture", 1)
                    self.assertEqual(caught.exception.code, "fixture")

        def test_cache_returns_independent_data(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "_download", return_value=sample.encode()):
                first, _, _ = crawler.fetch("fixture", 1)
                first[0].title = "不能污染缓存"
                second, _, cached = crawler.fetch("fixture", 1)
                self.assertTrue(cached)
                self.assertEqual(second[0].title, "Example headphones")

        def test_numbers_and_image_safety(self):
            self.assertEqual(_count("2.3K"), 2300)
            self.assertEqual(_number("$1,299.99"), 1299.99)
            for value in (None, True, -1, float("nan"), float("inf"), "-12.50"):
                self.assertIsNone(_number(value))
            for url in ("javascript:alert(1)", "data:image/png;bad", "https://user:pass@example.com/p.jpg"):
                self.assertIsNone(_safe_url(url))

        def test_next_page_link_validation(self):
            def html(href):
                return f'<a class="s-pagination-next" href="{href}">Next</a>'

            valid = "/s?k=electronics+accessories&amp;page=2&amp;ref=sr_pg_1"
            self.assertEqual(_next_search_url(html(valid), "electronics accessories", 1),
                             AMAZON_URL + "/s?k=electronics+accessories&page=2&ref=sr_pg_1")
            for href in ("https://example.invalid/s?k=x&page=2", "http://www.amazon.com/s?k=x&page=2",
                         "https://user:pass@www.amazon.com/s?k=x&page=2", "/gp/sign-in?k=x&page=2",
                         "/s?k=x&page=1", "/s?k=other&page=2", "/s?k=x&page=2&page=3",
                         "https://www.amazon.com:9000/s?k=x&page=2"):
                self.assertIsNone(_next_search_url(html(href), "x", 1))
            self.assertIsNone(_next_search_url("<html>no pagination</html>", "x", 1))

        def test_browser_selection_and_cache(self):
            crawler = AmazonCrawler(mode="browser")
            with patch.object(crawler, "_download_browser", return_value=sample.encode()) as browser:
                with patch.object(crawler, "_download") as plain:
                    crawler.fetch("fixture", 1)
                    _, _, cached = crawler.fetch("fixture", 1)
            self.assertTrue(cached)
            browser.assert_called_once_with("fixture", 1)
            plain.assert_not_called()  # 不先用已被拦截的 HTTP 再重试浏览器，避免增加请求。

        def test_block_cooldown(self):
            crawler = AmazonCrawler(mode="browser")
            with patch.object(crawler, "_download_browser", side_effect=CrawlError("amazon_blocked", "fixture", 503)) as browser:
                for expected in ("amazon_blocked", "amazon_cooldown"):
                    with self.assertRaises(CrawlError) as caught:
                        crawler.fetch("fixture", 1)
                    self.assertEqual(caught.exception.code, expected)
                browser.assert_called_once()  # 连续点刷新不会持续打到亚马逊。

        def test_fetch_spacing_and_busy(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "_download", return_value=sample.encode()):
                crawler.fetch("first", 1)
                with self.assertRaises(CrawlError) as caught:
                    crawler.fetch("second", 1)
                self.assertEqual(caught.exception.code, "crawl_interval")
            crawler._slots.acquire()
            try:
                with self.assertRaises(CrawlError) as caught:
                    crawler.fetch("other", 1)
                self.assertEqual(caught.exception.code, "crawler_busy")
            finally:
                crawler._slots.release()

        def test_http_failures_and_download_bound(self):
            crawler = AmazonCrawler(mode="direct")
            # MagicMock 假装 requests 的 with 响应对象；绝不发送这些请求。
            with patch.object(requests, "get") as get:
                response = get.return_value.__enter__.return_value
                for status, expected in ((403, "amazon_blocked"), (429, "amazon_blocked"), (503, "amazon_blocked"), (404, "upstream_http_error")):
                    response.status_code = status
                    with self.assertRaises(CrawlError) as caught:
                        crawler._download("fixture", 1)
                    self.assertEqual(caught.exception.code, expected)
                response.status_code = 200
                response.iter_content.return_value = [b"x" * (MAX_RESPONSE_BYTES + 1)]
                with self.assertRaises(CrawlError) as caught:
                    crawler._download("fixture", 1)
                self.assertEqual(caught.exception.code, "response_too_large")
            for cause, expected in ((requests.Timeout(), "upstream_timeout"), (requests.exceptions.SSLError(), "tls_error")):
                with patch.object(requests, "get", side_effect=cause):
                    with self.assertRaises(CrawlError) as caught:
                        crawler._download("fixture", 1)
                    self.assertEqual(caught.exception.code, expected)

        def test_browser_cookie_reuse_and_finally_cleanup(self):
            class FakeBrowserError(Exception):
                pass

            class FakeTimeout(FakeBrowserError):
                pass

            # 替换模块边界，不启动任何真实浏览器；即使没安装 Playwright 也能测。
            driver = MagicMock()
            start = MagicMock()
            start.return_value.__enter__.return_value = driver
            fake_module = SimpleNamespace(Error=FakeBrowserError, TimeoutError=FakeTimeout, sync_playwright=start)
            browser = driver.chromium.launch.return_value
            context = browser.new_context.return_value
            tab = context.new_page.return_value
            tab.url = AMAZON_URL + "/s?k=fixture"
            tab.goto.return_value.status = 200
            tab.content.return_value = sample
            context.storage_state.return_value = {"cookies": [], "origins": []}
            crawler = AmazonCrawler(mode="browser")
            with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
                crawler._download_browser("fixture & test", 1)
                self.assertIn("k=fixture+%26+test", tab.goto.call_args.args[0])
                self.assertEqual(crawler._browser_state, {"cookies": [], "origins": []})
                crawler._download_browser("fixture", 1)
                self.assertEqual(context.storage_state.return_value, browser.new_context.call_args.kwargs["storage_state"])
                tab.content.return_value = sample + '<a class="s-pagination-next" href="/s?k=fixture&amp;page=2&amp;ref=sr_pg_1">Next</a>'
                with crawler._browser_session() as download:
                    download("fixture", 1)
                    download("fixture", 2)
                    self.assertIn("ref=sr_pg_1", tab.goto.call_args.args[0])
                tab.goto.return_value.status = 503
                with self.assertRaises(CrawlError):
                    crawler._download_browser("fixture", 1)
            self.assertEqual(context.close.call_count, 4)
            self.assertEqual(browser.close.call_count, 4)  # 成功/失败都关闭，不能留下后台浏览器。

        def test_missing_browser_dependency(self):
            crawler = AmazonCrawler(mode="browser")
            with patch.dict(sys.modules, {"playwright.sync_api": None}):
                with self.assertRaises(CrawlError) as caught:
                    crawler._download_browser("fixture", 1)
            self.assertEqual(caught.exception.code, "browser_dependency_missing")

        def test_empty_results_health_and_cors(self):
            self.assertEqual(parse_amazon_html("<html>did not match any products</html>"), [])
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "_download") as download:
                with TestClient(create_app(crawler)) as client:
                    response = client.get("/api/remen/health", headers={"Origin": "http://localhost:5173"})
                    self.assertFalse(response.json()["live_checked"])
                    self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5173")
                download.assert_not_called()

        def test_batch_default_fifty_and_early_stop(self):
            crawler = AmazonCrawler(mode="direct")
            # 每页20件：默认50需要3页；第4页不应再请求。用 Fake 跳过网络和等待。
            def fetch_page(_keyword, page, **_options):
                return fake_products((page - 1) * 20, 20), fixture_time, False

            with patch.object(crawler, "fetch", side_effect=fetch_page) as fetch:
                response = TestClient(create_app(crawler)).get("/api/remen/products")
            result = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual((result["count"], result["limit"], result["pages_scanned"], result["candidate_count"]), (50, 50, 3, 60))
            self.assertEqual(len({p["asin"] for p in result["products"]}), 50)
            self.assertEqual(result["stop_reason"], "target_reached")
            self.assertFalse(result["partial"])
            self.assertTrue(result["target_reached"])
            self.assertEqual(fetch.call_count, 3)
            self.assertEqual(result["next_page"], 4)
            # 排序发生在所有已扫描候选上，不是先截断50条再排序。
            self.assertEqual(result["products"][0]["sales_count_min"], 59)

        def test_batch_dedupe_filter_then_count(self):
            crawler = AmazonCrawler(mode="direct")
            first = fake_products(0, 2) + fake_products(9, 1, sponsored=True)
            second = fake_products(0, 1) + fake_products(2, 2)
            with patch.object(crawler, "fetch", side_effect=[(first, fixture_time, False), (second, fixture_time, False)]) as fetch:
                batch = crawler.collect("fixture", 1, 4, 5, "hot")
            self.assertEqual(len(batch.products), 4)
            self.assertEqual([p.added_count for p in batch.pages], [2, 2])
            self.assertEqual(fetch.call_count, 2)

        def test_batch_niche_does_not_stop_after_filtered_page(self):
            crawler = AmazonCrawler(mode="direct")
            first = fake_products(0, 3)
            for product in first:
                product.review_count = 900
            with patch.object(crawler, "fetch", side_effect=[(first, fixture_time, False), (fake_products(10, 2), fixture_time, False)]):
                batch = crawler.collect("fixture", 1, 2, 5, "niche")
            self.assertEqual([p.added_count for p in batch.pages], [0, 2])
            self.assertEqual(batch.stop_reason, "target_reached")

        def test_batch_repeated_and_empty_pages_stop(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "fetch", return_value=(fake_products(0, 2), fixture_time, False)) as fetch:
                batch = crawler.collect("fixture", 1, 50, 20, "hot")
                self.assertEqual((batch.stop_reason, len(batch.products), fetch.call_count), ("no_progress", 2, 3))
                self.assertIsNone(batch.next_page)
            with patch.object(crawler, "fetch", return_value=([], fixture_time, False)) as fetch:
                batch = crawler.collect("fixture", 1, 50, 20, "hot")
                self.assertEqual(batch.stop_reason, "empty_page")
                fetch.assert_called_once()

        def test_batch_partial_failure_preserves_products(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "fetch", side_effect=[(fake_products(0, 16), fixture_time, False), CrawlError("amazon_blocked", "fixture blocked", 503)]) as fetch:
                response = TestClient(create_app(crawler)).get("/api/remen/products")
            data = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual((data["count"], data["pages_scanned"], data["next_page"]), (16, 1, 2))
            self.assertTrue(data["partial"])
            self.assertFalse(data["target_reached"])
            self.assertEqual(data["error_code"], "amazon_blocked")
            self.assertEqual(fetch.call_count, 2)

        def test_batch_failure_without_products_stays_error(self):
            crawler = AmazonCrawler(mode="direct")
            for values in ([CrawlError("amazon_blocked", "fixture", 503)],
                           [(fake_products(0, 1, sponsored=True), fixture_time, False), CrawlError("upstream_timeout", "fixture", 504)]):
                with patch.object(crawler, "fetch", side_effect=values):
                    response = TestClient(create_app(crawler)).get("/api/remen/products")
                self.assertIn(response.status_code, (503, 504))
                self.assertIn("detail", response.json())

        def test_batch_cache_metadata_and_page_limits(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(crawler, "fetch", side_effect=[(fake_products(0, 16), fixture_time, True), (fake_products(16, 16), "2026-09-18T00:01:00+00:00", False)]):
                data = TestClient(create_app(crawler)).get("/api/remen/products?max_pages=2").json()
            self.assertFalse(data["from_cache"])
            self.assertEqual(data["fetched_at"], fixture_time)
            self.assertEqual(data["stop_reason"], "page_limit")
            self.assertFalse(data["partial"])
            with patch.object(crawler, "fetch", return_value=(fake_products(0, 2), fixture_time, True)) as fetch:
                data = TestClient(create_app(crawler)).get("/api/remen/products?page=50&max_pages=20").json()
                self.assertEqual(data["pages_scanned"], 1)
                self.assertIsNone(data["next_page"])
                self.assertTrue(data["from_cache"])
                fetch.assert_called_once()

        def test_batch_maximum_two_hundred(self):
            crawler = AmazonCrawler(mode="direct")
            def fetch_page(_keyword, page, **_options):
                return fake_products((page - 1) * 16, 16), fixture_time, True

            with patch.object(crawler, "fetch", side_effect=fetch_page):
                data = TestClient(create_app(crawler)).get("/api/remen/products?limit=200&max_pages=20").json()
            self.assertEqual((data["count"], data["pages_scanned"]), (200, 13))
            self.assertTrue(data["target_reached"])
            for args in ((0, 50, 5, "hot"), (1, 201, 5, "hot"), (1, 50, 21, "hot")):
                with self.assertRaises(ValueError):
                    crawler.collect("fixture", *args)

        def test_batch_soft_budget(self):
            crawler = AmazonCrawler(mode="direct")
            # monotonic 是单调时钟，不受系统改时间影响。这里推进虚拟时间，不真的等两分钟。
            with patch.object(time, "monotonic", side_effect=[0, 0, BATCH_SOFT_TIMEOUT + 1]):
                with patch.object(crawler, "fetch", return_value=(fake_products(0, 2), fixture_time, False)) as fetch:
                    batch = crawler.collect("fixture", 1, 50, 5, "hot")
            self.assertEqual((batch.stop_reason, batch.next_page, len(batch.products)), ("time_budget", 2, 2))
            fetch.assert_called_once()

        def test_batch_wait_keeps_rate_control(self):
            crawler = AmazonCrawler(mode="direct")
            with patch.object(time, "monotonic", return_value=100), patch.object(time, "sleep") as sleep:
                crawler._next_fetch_at = 103
                with patch.object(crawler, "_download", return_value=sample.encode()):
                    crawler.fetch("fixture", 1, wait_for_interval=True)
                    crawler.fetch("fixture", 1, wait_for_interval=True)  # 缓存命中不等待。
            sleep.assert_called_once_with(3)

        def test_batch_reuses_browser_and_all_cached_opens_none(self):
            crawler = AmazonCrawler(mode="browser")
            with patch.object(crawler, "_browser_session") as session, patch.object(crawler, "_download_browser") as single:
                download = session.return_value.__enter__.return_value
                download.side_effect = [sample.encode(), sample.replace("B012345678", "B012345679").encode()]
                with patch.object(time, "monotonic", return_value=100), patch.object(time, "sleep"):
                    first = crawler.collect("fixture", 1, 2, 5, "hot")
                    second = crawler.collect("fixture", 1, 2, 5, "hot")
                self.assertEqual(len(first.products), 2)
                self.assertTrue(all(page.from_cache for page in second.pages))
                session.assert_called_once()  # 不是每一页启动一个浏览器。
                self.assertEqual(download.call_count, 2)
                session.return_value.__exit__.assert_called_once()
                single.assert_not_called()

        def test_batch_closes_browser_on_partial_and_releases_batch_slot(self):
            crawler = AmazonCrawler(mode="browser")
            with patch.object(crawler, "_browser_session") as session:
                download = session.return_value.__enter__.return_value
                download.side_effect = [sample.encode(), CrawlError("amazon_blocked", "fixture", 503)]
                with patch.object(time, "monotonic", return_value=100), patch.object(time, "sleep"):
                    result = crawler.collect("fixture", 1, 50, 5, "hot")
                self.assertEqual(result.stop_reason, "upstream_error")
                self.assertEqual(len(result.products), 1)
                session.return_value.__exit__.assert_called_once()
            self.assertTrue(crawler._batch_slots.acquire(blocking=False))
            try:
                with self.assertRaises(CrawlError) as caught:
                    crawler.collect("fixture", 1, 50, 5, "hot")
                self.assertEqual(caught.exception.code, "crawler_busy")
            finally:
                crawler._batch_slots.release()

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    # __main__ 表示“直接启动”，被其他模块 import 时不会擅自占用端口。
    if "--self-test" in sys.argv:
        _self_test()
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("REMEN_PORT", "8001")))
