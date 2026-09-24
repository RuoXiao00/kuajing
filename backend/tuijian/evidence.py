"""公开资料采集：固定来源、有限请求、来源可追溯，不把搜索热度当成销量。

商品明细仍由 pachon.AmazonCrawler 获取；这里仅补充选题资料，不使用商品代理服务。
网页文本是不可信数据，只提取标题/链接，不能把网页里的指令交给模型执行。
"""
from datetime import datetime
import hashlib
import re
import time
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from backend.remen.pachon import SHARED_AMAZON_ACCESS, AmazonCrawler, CrawlError

SOURCES = (
    ("bestsellers", "Amazon 畅销榜", "https://www.amazon.com/Best-Sellers/zgbs"),
    ("movers", "Amazon 排名上升榜", "https://www.amazon.com/gp/movers-and-shakers"),
    ("newreleases", "Amazon 新品榜", "https://www.amazon.com/gp/new-releases"),
    ("trends", "Google 美国搜索热搜", "https://trends.google.com/trending/rss?geo=US"),
)

# 这是采样范围，不是预先决定的推荐结果。每天从 20 个领域选 16 个先抓实物数据，
# 优先探索近期较少推荐的领域，并在同领域的三个检索词之间轮换，再交给模型比较。
CATALOG = (
    ("home", "家居收纳", ("drawer organizer", "under sink organizer", "storage bins")),
    ("kitchen", "厨房用品", ("food storage containers", "vegetable chopper", "kitchen scale")),
    ("cleaning", "清洁用品", ("spin scrubber", "microfiber cleaning cloth", "lint roller")),
    ("lighting", "照明", ("desk lamp", "under cabinet lights", "night light")),
    ("pet", "宠物用品", ("pet grooming brush", "cat water fountain", "dog puzzle toy")),
    ("office", "办公用品", ("desk organizer", "laptop stand", "monitor stand")),
    ("travel", "旅行用品", ("packing cubes", "travel pillow", "luggage organizer")),
    ("outdoor", "户外用品", ("camping lantern", "camping chair", "hiking backpack")),
    ("fitness", "健身用品", ("resistance bands", "yoga mat", "foam roller")),
    ("beauty", "美容工具", ("makeup brushes", "makeup organizer", "hair brush")),
    ("audio", "音频配件", ("wireless earbuds", "bluetooth speaker", "headphone stand")),
    ("phone", "手机配件", ("phone stand", "phone tripod", "phone grip")),
    ("charging", "充电配件", ("usb c charger", "charging station", "power bank")),
    ("garden", "园艺用品", ("garden gloves", "plant pots", "watering can")),
    ("car", "汽车用品", ("car phone holder", "car trunk organizer", "car seat cushion")),
    ("bath", "浴室用品", ("shower caddy", "bath mat", "soap dispenser")),
    ("sleep", "睡眠用品", ("sleep mask", "bed pillow", "white noise machine")),
    ("craft", "手工用品", ("crochet kit", "paint brushes", "sewing kit")),
    ("tools", "家用工具", ("screwdriver set", "measuring tape", "tool organizer")),
    ("drink", "饮水用品", ("insulated water bottle", "travel mug", "water bottle carrier")),
)


def exploration_plan(run_at, history):
    counts = {}
    for entry in history:
        for category in entry.get("categories", []):
            key = category.get("candidate_id")
            counts[key] = counts.get(key, 0) + 1
    day = datetime.fromisoformat(run_at).date().toordinal()
    ordered = sorted(enumerate(CATALOG), key=lambda pair: (
        counts.get(pair[1][0], 0), (pair[0] - day) % len(CATALOG)))[:16]
    return [{"candidate_id": key, "title": title, "keyword": words[(day + index) % len(words)]}
            for index, (key, title, words) in ordered]


def _download(url):
    # 榜单也访问 Amazon，必须与热门页/推荐搜索共用间隔和验证码冷却。
    # Google 资料不占 Amazon 的名额；地址仍全部来自上面的固定白名单。
    if url.startswith("https://www.amazon.com/"):
        with SHARED_AMAZON_ACCESS.request():
            body = _download_body(url, amazon=True)
            soup = BeautifulSoup(body, "html.parser")
            text = soup.get_text(" ", strip=True).lower()
            if (soup.select_one('#captchacharacters, form[action*="validateCaptcha"]')
                    or "automated access to amazon data" in text
                    or "enter the characters you see below" in text):
                raise CrawlError("amazon_blocked", "商品来源要求验证，已暂停采集。", 503)
            return body
    return _download_body(url)


def _download_body(url, amazon=False):
    # 流式读取限制内存；不跟随重定向、不下载外部文章或模型生成的任意 URL。
    with requests.get(url, timeout=(10, 20), stream=True, allow_redirects=False,
                      headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}) as response:
        if amazon:
            AmazonCrawler._check_status(response.status_code)
        if response.status_code != 200:
            raise ValueError("http_status")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 5_000_000:
                raise ValueError("response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)


def parse_source(source_id, body):
    items = []
    if source_id == "trends":
        # 不展开外部 XML 实体；避免恶意 XML 的实体膨胀。
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            raise ValueError("unsafe_xml")
        root = ElementTree.fromstring(body)
        for node in root.findall("./channel/item")[:30]:
            title = (node.findtext("title") or "").strip()[:200]
            published = node.findtext("pubDate")
            if title:
                items.append({"title": title, "published_at": published,
                    "url": "https://trends.google.com/trends/explore?geo=US&q=" + quote_plus(title)})
    else:
        soup = BeautifulSoup(body, "html.parser")
        if soup.select_one('form[action*="validateCaptcha"], input#captchacharacters'):
            raise ValueError("captcha")
        seen = set()
        # 仅接受带排名标记的榜单卡片。全页面 /dp/ 链接会混入信用卡广告、导航推荐，
        # 这些不是榜单证据；布局变化时宁可标记不可用，也不能误报成功。
        cards = soup.select('[id="gridItemRoot"], .zg-grid-general-faceout, .zg-carousel-general-faceout, .zg-item-immersion')
        links = [link for card in cards if card.select_one('.zg-bdg-text, .zg-badge-text')
                 for link in card.select('a[href*="/dp/"]')]
        for link in links:
            match = re.search(r"/dp/([A-Z0-9]{10})(?:[/?]|$)", link.get("href", ""))
            img = link.find("img")
            title = link.get_text(" ", strip=True) or (img.get("alt", "") if img else "")
            if match and len(title) > 12 and match[1] not in seen:
                seen.add(match[1])
                items.append({"title": title[:240], "asin": match[1],
                              "url": "https://www.amazon.com/dp/" + match[1]})
            if len(items) >= 40:
                break
    for item in items:
        item["evidence_id"] = source_id + "-" + hashlib.sha256(item["title"].encode()).hexdigest()[:12]
    return items


def collect_public_sources(run_at, previous=None, check_stop=lambda: None):
    previous = {s["id"]: s for s in previous or []}
    results, blocked = [], False
    for source_id, name, url in SOURCES:
        check_stop()
        if previous.get(source_id, {}).get("status") == "ok":
            results.append(previous[source_id])  # 同一期补试复用已成功的资料。
            continue
        record = {"id": source_id, "name": name, "url": url, "fetched_at": datetime.now(datetime.fromisoformat(run_at).tzinfo).isoformat(),
                  "status": "unavailable", "items": [], "error": ""}
        if blocked and source_id != "trends":
            record["error"] = "captcha_cooldown"
        else:
            try:
                items = parse_source(source_id, _download(url))
                record.update(items=items, status="ok" if items else "unavailable",
                              error="" if items else "no_usable_items")
            except Exception as error:
                # 不记录异常正文（可能含代理凭据）；验证码后不继续访问其它 Amazon 榜单。
                if isinstance(error, CrawlError):
                    record["error"] = error.code
                else:
                    record["error"] = "captcha" if isinstance(error, ValueError) and str(error) == "captcha" else "source_unavailable"
                blocked = blocked or record["error"] in {"captcha", "amazon_blocked", "amazon_cooldown"}
            if source_id != "trends":
                time.sleep(3)
        results.append(record)
    return results
