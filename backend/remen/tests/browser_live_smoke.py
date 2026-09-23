"""显式真实抓取验收：Vite 已启动时运行 python -B -m backend.remen.tests.browser_live_smoke。

使用隔离的临时 API、快照库和 Chrome 会话，验证首次进入及下滑。不会停止正式后端，
不会调用推荐模型、写正式快照或知识库；本文件不属于默认离线测试。
"""
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import requests
import uvicorn
from fastapi import Request, Response
from playwright.sync_api import sync_playwright
from backend.remen.pachon import AmazonCrawler, create_app


def main():
    root = Path(tempfile.mkdtemp(prefix='kuajing-hot-scroll-'))
    app = create_app(AmazonCrawler(allow_regional_redirects=True), snapshot_path=root / 'snapshot.sqlite3', schedule=False)

    @app.get('/{path:path}')
    def frontend(path: str, request: Request):
        response = requests.get(f'http://localhost:5173/{path}', params=request.query_params, timeout=10)
        return Response(response.content, status_code=response.status_code, media_type=response.headers.get('Content-Type'))

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            responses, errors = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def record(response):
                url = urlsplit(response.url)
                if url.path == '/api/remen/products':
                    responses.append((parse_qs(url.query).get('page'), response.status))
                    print('product_response:', responses[-1], flush=True)
            page.on('response', record)
            page.goto(f'http://localhost:{port}/remeng')
            page.wait_for_function("document.querySelectorAll('.rm-product').length > 0 || document.querySelector('.rm-results [role=alert]')", timeout=150000)
            assert page.locator('.rm-results [role=alert]').count() == 0, page.locator('.rm-results [role=alert]').all_text_contents()
            first = page.locator('.rm-product').count()
            print('first_page_visible_products:', first, flush=True)
            page.locator('.rm').evaluate('el => {el.scrollTop = el.scrollHeight}')
            page.wait_for_function("n => document.querySelectorAll('.rm-product').length > n || document.querySelector('.rm-results [role=alert]')", arg=first, timeout=150000)
            assert page.locator('.rm-results [role=alert]').count() == 0, page.locator('.rm-results [role=alert]').all_text_contents()
            assert not errors, errors
            assert len(responses) >= 2 and all(status == 200 for _, status in responses)
            print('after_scroll_visible_products:', page.locator('.rm-product').count(), flush=True)
            print('PASS: initial request and first scroll succeed without pressing retry.', flush=True)
            page.screenshot(path=str(root / 'after-scroll.png'))
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
