"""对已启动的自动模式 preview 做隔离浏览器验收，不访问供应商。

构建环境：VITE_CONNECTION_MODE=auto、VITE_API_BASE_URL=https://api.qiyuange.online、
VITE_BASE_PATH=/kuajing/、VITE_ROUTER_MODE=hash；preview 监听 5175。
运行 python scripts/verify_demo.py。截图只含人工构造样例。
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'screenshots'
OUT.mkdir(parents=True, exist_ok=True)
URL = 'http://127.0.0.1:5175/kuajing/'

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 960})
    external = []
    def offline(route):
        external.append(route.request.url)
        route.abort()
    context.route('https://**/*', offline)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(URL)
    expect(page.locator('.demo-banner')).to_be_visible()
    expect(page.locator('.product-tile')).to_have_count(5)
    expect(page.get_by_label('当前类别序号')).to_have_text('1 / 8')
    page.get_by_role('button', name='下一类', exact=False).click()
    expect(page.get_by_label('当前类别序号')).to_have_text('2 / 8')
    page.screenshot(path=str(OUT / 'recommendations.png'))
    page.goto(URL + '#/remeng')
    expect(page.locator('[data-product-card]')).to_have_count(12)
    page.locator('.rm-load-more').scroll_into_view_if_needed()
    expect(page.locator('[data-product-card]')).to_have_count(24)
    page.locator('[data-product-card]').first.scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / 'products.png'))
    page.goto(URL + '#/zhishiku')
    page.get_by_role('button', name='亚马逊 FBA 物流有哪些主要费用？', exact=False).click()
    expect(page.get_by_text('具体收费标准会变化', exact=False)).to_be_visible()
    page.screenshot(path=str(OUT / 'knowledge.png'))
    page.goto(URL + '#/tupian')
    expect(page.locator('.ig-result')).to_have_count(4)
    page.get_by_label('放大生成图片 1').click()
    page.keyboard.press('Escape')
    with page.expect_download() as download:
        page.get_by_role('link', name='下载示例', exact=False).first.click()
    assert download.value.suggested_filename.endswith('.svg')
    page.locator('.ig-conversation').evaluate('(el) => { el.style.scrollBehavior = "auto"; el.scrollTop = 0; }')
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / 'images.png'))
    page.get_by_role('button', name='预览 4 张示例', exact=False).click()
    expect(page.locator('.ig-result')).to_have_count(8)
    page.reload()
    expect(page.locator('.ig-result')).to_have_count(4)
    assert all('/api/knowledge/health' in url for url in external), external
    assert not errors, errors
    page.set_viewport_size({'width': 390, 'height': 844})
    page.emulate_media(reduced_motion='reduce')
    for route in ['tupian', 'zhishiku', 'remeng', 'tuijian']:
        page.goto(URL + '#/' + route)
        expect(page.locator('.demo-banner')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), route
    page.wait_for_function('document.querySelector(".router-header").getBoundingClientRect().right <= 0')
    page.screenshot(path=str(OUT / 'mobile.png'))
    page.get_by_role('button', name='打开导航', exact=True).click()
    page.get_by_role('link', name='知识库', exact=True).click()
    expect(page.locator('.knowledge-page')).to_be_visible()
    # 模拟备案/CORS 恢复：刷新后必须连接真实接口，不继续展示内置数据。
    context.unroute('https://**/*', offline)
    calls = []
    def online(route):
        calls.append(route.request.url)
        data = '{"status":"ok","document_count":0,"chunk_count":0}' if '/health' in route.request.url else '{"categories":[],"update_status":"waiting"}'
        route.fulfill(status=200, content_type='application/json', body=data)
    context.route('https://api.qiyuange.online/**', online)
    page.goto(URL + '#/tuijian')
    page.reload()
    expect(page.locator('.demo-banner')).to_have_count(0)
    expect(page.locator('.recommendation-empty')).to_be_visible()
    assert any('/api/recommendations/latest' in url for url in calls), calls
    assert not errors, errors
    # 页面无人操作时每分钟自动探测并恢复；有输入时保留草稿，切页才切换。
    context.unroute('https://api.qiyuange.online/**', online)
    context.route('https://**/*', offline)
    idle = context.new_page()
    idle.clock.install()
    idle.goto(URL)
    expect(idle.locator('.demo-banner')).to_be_visible()
    context.unroute('https://**/*', offline)
    context.route('https://api.qiyuange.online/**', online)
    idle.clock.fast_forward(60001)
    expect(idle.locator('.demo-banner')).to_have_count(0)
    idle.close()
    browser.close()
    print('PASS: offline fallback, pagination, SSE, images, download, mobile, live recovery; screenshots saved.')
