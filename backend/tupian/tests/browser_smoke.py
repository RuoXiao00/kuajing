"""手动浏览器验收：先运行 Vite，再执行本文件。仅连接本机替身，不调用 Coze。

python -B -m backend.tupian.tests.browser_smoke
测试存档放在系统临时目录，正式知识库及图片存档均不受影响。
"""
import io
import socket
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect
import uvicorn
import requests

from backend.tupian.api import router
from backend.tupian.service import ImageService


def main():
    root = Path(tempfile.mkdtemp(prefix="kuajing-image-browser-"))
    image = Image.new("RGB", (768, 768), "#f0f1e9")
    draw = ImageDraw.Draw(image)
    draw.ellipse((170,610,590,680), fill="#d9dfd1")
    draw.rounded_rectangle((255,220,505,640), radius=35, fill="#77968d")
    draw.rounded_rectangle((300,130,460,255), radius=18, fill="#e2dccc")
    draw.rounded_rectangle((285,360,475,480), radius=12, fill="#d9dfd1")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    content = buffer.getvalue()

    class FakeProvider:
        configured = True
        calls = 0
        def generate(self, prompt, mode, references, progress):
            self.calls += 1
            assert prompt == "" and mode == "all_views" and set(references) == {"product_img1"}
            progress("generating")
            time.sleep(3)
            return [f"https://example.com/{i}.png" for i in range(4)], "为你完成了四张产品图，点击图片即可查看细节。"

    provider = FakeProvider()
    service = ImageService(root / "store", provider, lambda url: (content, "png", "image/png"))
    app = FastAPI()
    app.state.images = service
    app.include_router(router)
    # 给测试页面提供同源入口，真实验证 Cookie 和浏览器附件下载，而不是拦截伪造下载。
    @app.get("/{path:path}")
    def frontend(path: str, request: Request):
        response = requests.get(f"http://localhost:5173/{path}", params=request.query_params, timeout=10)
        return Response(response.content, status_code=response.status_code,
                        media_type=response.headers.get("Content-Type"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            # 使用已安装 Chrome 的隔离临时上下文，不读取用户日常浏览器资料。
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1050}, accept_downloads=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://localhost:{port}/tupian")
            expect(page.get_by_text("从一张产品图开始", exact=True)).to_be_visible()
            page.screenshot(path=str(root / "desktop-empty.png"))
            page.get_by_role("combobox").select_option("all_views")
            expect(page.get_by_role("button", name="生成 4 张")).to_be_disabled()
            expect(page.locator("#ig-submit-hint")).to_contain_text("请先上传产品图")
            page.get_by_label("上传产品图", exact=True).set_input_files({"name": "test.png", "mimeType": "image/png", "buffer": content})
            # 空提示词、仅产品图：七种生成类型都应能点击，选配参考图不能阻塞提交。
            for mode in ("product", "model", "background", "views", "model_views", "background_views", "all_views"):
                page.get_by_role("combobox").select_option(mode)
                expect(page.get_by_role("button", name="生成 4 张")).to_be_enabled()
            expect(page.get_by_label("图片提示词")).to_have_value("")
            page.get_by_role("button", name="生成 4 张").click()
            expect(page.locator(".ig-placeholder")).to_have_count(4)
            page.reload()
            expect(page.locator(".ig-result")).to_have_count(4, timeout=20000)
            assert provider.calls == 1
            expect(page.get_by_text("✓ 4 张原图已保存到本机", exact=False)).to_be_visible()
            widths = page.locator(".ig-result-image img").evaluate_all("els => els.map(el => ({width: el.clientWidth, valid: el.complete && el.naturalWidth > 0}))")
            assert all(item["width"] > 350 and item["valid"] for item in widths)
            page.get_by_role("button", name="放大生成图片 1").click()
            expect(page.locator("dialog")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("dialog")).to_have_count(0)
            with page.expect_download() as download_info:
                page.locator(".ig-result a").first.click()
            download = download_info.value
            download.save_as(str(root / download.suggested_filename))
            assert (root / download.suggested_filename).read_bytes() == content
            page.locator(".ig-conversation").evaluate("el => { el.style.scrollBehavior = 'auto'; el.scrollTop = 150; }")
            page.screenshot(path=str(root / "desktop-results.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_function("document.querySelector('.router-header').getBoundingClientRect().right <= 0")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            columns = page.locator(".ig-results").evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length")
            assert columns == 1
            page.reload()
            expect(page.locator(".ig-result")).to_have_count(4)
            page.locator(".ig-conversation").evaluate("el => { el.style.scrollBehavior = 'auto'; el.scrollTop = 150; }")
            assert page.locator(".ig-thread").evaluate("el => el.scrollWidth <= el.clientWidth")
            assert page.locator(".ig-composer").evaluate("el => el.scrollWidth <= el.clientWidth")
            page.screenshot(path=str(root / "mobile-results.png"), animations="disabled")
            assert provider.calls == 1 and not errors, errors
            browser.close()
        print("PASS: mode uploads, 4 large images, refresh recovery, no duplicate generation, preview, download, mobile layout.")
        print("Screenshots:", root)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        service.close()
        service.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
