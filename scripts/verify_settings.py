"""设置页浏览器验收。先启动 Vite，再执行 python -B scripts/verify_settings.py。

浏览器使用隔离上下文，接口全部替身，不触发抓取/模型，不改用户设置或正式库。
"""
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect


def main():
    root = Path(tempfile.mkdtemp(prefix='kuajing-settings-'))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1100})
        requests = []

        def api(route):
            url = urlsplit(route.request.url)
            if url.path == '/api/remen/products/snapshot':
                route.fulfill(json={'snapshot': None})
            elif url.path == '/api/remen/products':
                page = int(parse_qs(url.query).get('page', ['1'])[0])
                requests.append(page)
                route.fulfill(json={'category': 'hot', 'sub_category': 'all', 'period': 'current', 'page': page,
                    'pages_scanned': 1, 'next_page': page + 1 if page < 4 else None, 'partial': False,
                    'fetched_at': '2026-09-22T10:00:00Z', 'warnings': [],
                    'products': [{'asin': f'B{page:02}{i:07}', 'title': f'Fixture product {page}-{i}',
                                  'price': 12, 'currency': 'USD'} for i in range(6)]})
            elif url.path == '/api/images/history':
                route.fulfill(json={'jobs': [], 'before': None, 'configured': True})
            else:
                route.fulfill(json={})
        context.route('**/api/**', api)
        context.route('https://api.frankfurter.dev/**', lambda route: route.fulfill(json=[{'base': 'CNY', 'quote': 'USD', 'rate': .14, 'date': '2026-09-22'}]))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://localhost:5173/settings')
        expect(page.get_by_label('显示昵称')).to_have_value('跨境用户')
        page.get_by_label('显示昵称').fill('选品同学')
        page.get_by_role('button', name='保存昵称').click()
        expect(page.locator('.account-nickname')).to_have_text('选品同学')
        page.get_by_label('默认首页').select_option('/tupian')
        page.get_by_role('switch', name='热门产品自动加载').click()
        page.get_by_role('switch', name='展开左侧导航').click()
        expect(page.locator('.App')).to_have_class('App nav-collapsed ')
        page.reload()
        expect(page.get_by_label('显示昵称')).to_have_value('选品同学')
        expect(page.get_by_label('默认首页')).to_have_value('/tupian')
        expect(page.get_by_role('switch', name='热门产品自动加载')).to_have_attribute('aria-checked', 'false')
        expect(page.get_by_role('switch', name='展开左侧导航')).to_have_attribute('aria-checked', 'false')
        page.goto('http://localhost:5173/')
        expect(page).to_have_url('http://localhost:5173/tupian')
        page.goto('http://localhost:5173/remeng')
        expect(page.locator('.rm-product')).to_have_count(6)
        page.locator('.rm').evaluate('el => { el.scrollTop = el.scrollHeight }')
        page.wait_for_timeout(400)  # 给 IntersectionObserver 一个触发窗口，断言关闭开关后不会请求。
        assert requests == [1], requests
        page.get_by_role('button', name='继续加载', exact=True).click()
        expect(page.locator('.rm-product')).to_have_count(12)
        assert requests == [1, 2], requests
        page.goto('http://localhost:5173/settings')
        page.get_by_role('switch', name='热门产品自动加载').click()
        page.goto('http://localhost:5173/remeng')
        expect(page.locator('.rm-product')).to_have_count(6)
        page.locator('.rm').evaluate('el => { el.scrollTop = el.scrollHeight }')
        expect(page.locator('.rm-product')).to_have_count(12)
        assert requests[-2:] == [3, 4], requests
        page.goto('http://localhost:5173/settings')
        page.get_by_role('switch', name='展开左侧导航').click()

        other = context.new_page()
        other.goto('http://localhost:5173/settings')
        other.get_by_label('显示昵称').fill('同步昵称')
        other.get_by_role('button', name='保存昵称').click()
        expect(page.locator('.account-nickname')).to_have_text('同步昵称')
        page.evaluate("localStorage.setItem('settings-test-chat', 'preserved')")
        page.get_by_role('button', name='恢复默认', exact=True).click()
        page.get_by_role('button', name='取消', exact=True).click()
        expect(page.get_by_label('显示昵称')).to_have_value('同步昵称')
        page.get_by_role('button', name='恢复默认', exact=True).click()
        page.get_by_role('button', name='确认恢复').click()
        expect(page.get_by_label('显示昵称')).to_have_value('跨境用户')
        expect(page.get_by_label('默认首页')).to_have_value('/tuijian')
        assert page.evaluate("localStorage.getItem('settings-test-chat')") == 'preserved'
        page.screenshot(path=str(root / 'desktop.png'), full_page=True, animations='disabled')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.reload()
        expect(page.get_by_label('显示昵称')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(root / 'mobile.png'), full_page=True, animations='disabled')
        assert not errors, errors
        blocked = context.new_page()
        blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('storage blocked')}})")
        blocked.goto('http://localhost:5173/settings')
        expect(blocked.locator('.st-warning')).to_be_visible()
        blocked.get_by_label('显示昵称').fill('临时用户')
        blocked.get_by_role('button', name='保存昵称').click()
        expect(blocked.locator('.account-nickname')).to_have_text('临时用户')
        expect(blocked.locator('.st-warning')).to_contain_text('本次打开')
        browser.close()
    print('PASS nickname, persistence, home route, sidebar, automatic/manual pagination, cross-tab sync, reset, blocked storage, mobile.')
    print('Screenshots:', root)


if __name__ == '__main__':
    main()
