"""在实际部署容器内运行一次采集诊断；不修改快照、不调用模型、不输出密钥/Cookie。

默认只访问一次固定 Amazon 搜索页。不能用开发电脑的成功代替服务器网络验收。
可直接通过 docker compose exec -T api python - < deploy/diagnose-crawler.py 执行，
因此旧镜像也能检查，无需重新安装依赖或构建镜像。
"""
import json
import re
import urllib.request
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


def page_summary(html):
    """仅输出结构计数和固定标志，避免把网页正文、查询参数或会话信息贴进日志。"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    title = soup.title.get_text(strip=True).lower() if soup.title else ""
    cards = soup.select('[data-component-type="s-search-result"][data-asin], .s-result-item[data-asin]')
    return {
        "bytes": len(html.encode("utf-8")),
        "cards": len(cards),
        "valid_asin_cards": sum(bool(re.fullmatch(r"[A-Z0-9]{10}", str(c.get("data-asin", "")), re.I)) for c in cards),
        "captcha": bool(soup.select_one('#captchacharacters, form[action*="validateCaptcha"]'))
            or "enter the characters you see below" in text or "robot check" in title,
        "automated_access": "automated access to amazon data" in text,
        "continue_shopping": "continue shopping" in text and not cards,
        "service_error": "sorry! something went wrong" in text or "sorry, something went wrong" in text,
        "icp_block": "non-compliance icp filing" in text or "beian.aliyun.com" in html,
        "empty_search": "did not match any products" in text,
    }


def error_kind(error):
    # Playwright 的异常正文可能包含 URL；只提取已知网络错误名称，绝不原样打印。
    match = re.search(r"\bnet::(ERR_[A-Z_]+)\b", str(error))
    return match[1] if match else type(error).__name__


def main():
    from backend.remen.pachon import AmazonCrawler, CrawlError, parse_amazon_html
    from playwright.sync_api import sync_playwright
    result = {"diagnostic_version": 1}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as response:
            result["internal_api_http"] = response.status
    except Exception as error:
        result["internal_api_error"] = type(error).__name__
    crawler = AmazonCrawler()
    result["browser_channel"] = crawler.channel
    try:
        with sync_playwright() as p:
            options = {"headless": True, "timeout": 15000}
            if crawler.channel != "chromium":
                options["channel"] = crawler.channel
            browser = p.chromium.launch(**options)
            try:
                context = browser.new_context(locale="en-US", viewport={"width": 1365, "height": 900})
                page = context.new_page()
                response = page.goto("https://www.amazon.com/s?k=best+sellers&language=en_US&currency=USD&page=1",
                                     wait_until="domcontentloaded", timeout=35000)
                result["amazon_http"] = response.status if response else None
                result["final_host"] = urlsplit(page.url).hostname
                # 只等待页面加载，不点击验证码或继续购物，不重复访问。
                try:
                    page.wait_for_selector('[data-component-type="s-search-result"][data-asin], .s-result-item[data-asin], #captchacharacters', timeout=12000)
                except Exception:
                    pass
                html = page.content()
                result["page"] = page_summary(html)
                try:
                    products = parse_amazon_html(html, page.url)
                    result["parsed_products"] = len(products)
                    result["valid_prices"] = sum(bool(p.price and p.price > 0 and p.currency) for p in products)
                except CrawlError as error:
                    result["parse_error"] = error.code
            finally:
                browser.close()
    except Exception as error:
        result["browser_error"] = error_kind(error)
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
