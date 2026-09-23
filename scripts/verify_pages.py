"""离线验证 Pages 子路径、Hash 刷新及同站跨域 Cookie/生图/原图下载。

运行：python -B scripts/verify_pages.py
临时 HTTPS 服务使用 app.kuajing.test / api.kuajing.test；隔离浏览器自行解析到本机。
临时目录保存构建、证书和图片，模型与 Coze 均为替身，不接触正式后端或数据库。
"""
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from playwright.sync_api import expect, sync_playwright
import uvicorn

from backend.tupian.api import router
from backend.tupian.service import ImageService


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="kuajing-pages-check-"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    frontend, backend = f"https://app.kuajing.test:{port}", f"https://api.kuajing.test:{port}"
    dist = artifacts / "dist"
    env = {**os.environ, "VITE_API_BASE_URL": backend, "VITE_ROUTER_MODE": "hash", "VITE_BASE_PATH": "/kuajing/"}
    subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "run", "build", "--", "--outDir", str(dist)],
                   cwd=ROOT, env=env, check=True)

    # 自签证书只供此隔离浏览器测试；实际部署由 Caddy 申请公开可信证书。
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "*.kuajing.test")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("*.kuajing.test")]), critical=False)
            .sign(key, hashes.SHA256()))
    (artifacts / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (artifacts / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    content = io.BytesIO()
    Image.new("RGB", (64, 64), "#78968a").save(content, format="PNG")
    png = content.getvalue()

    class Provider:
        configured = True
        calls = 0

        def generate(self, prompt, mode, references, progress):
            assert prompt == "" and mode == "product" and set(references) == {"product_img1"}
            self.calls += 1
            progress("generating")
            return [f"https://images.invalid/{i}.png" for i in range(4)], "四张测试产品图已生成。"

    provider = Provider()
    service = ImageService(artifacts / "images", provider, lambda url: (png, "png", "image/png"))
    app = FastAPI()
    app.state.images = service
    app.add_middleware(CORSMiddleware, allow_origins=[frontend], allow_credentials=True,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Accept"])
    app.include_router(router)

    @app.get("/kuajing/{path:path}")
    def static_file(path: str):
        target = (dist / (path or "index.html")).resolve()
        if not target.is_relative_to(dist.resolve()) or not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    previous_origin = os.environ.get("FRONTEND_ORIGINS")
    os.environ["FRONTEND_ORIGINS"] = frontend
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", ssl_certfile=str(artifacts / "cert.pem"),
                                         ssl_keyfile=str(artifacts / "key.pem")))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True, args=[
                "--host-resolver-rules=MAP *.kuajing.test 127.0.0.1", "--no-proxy-server"])
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            errors, failed = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("response", lambda response: failed.append(response.url) if response.status >= 400 else None)
            page.goto(frontend + "/kuajing/#/settings")
            expect(page.get_by_label("显示昵称")).to_be_visible()
            assert page.locator(".logo").evaluate("el => el.complete && el.naturalWidth > 0")
            page.reload()
            expect(page.get_by_label("显示昵称")).to_be_visible()
            page.get_by_role("link", name="图片生成", exact=True).click()
            expect(page).to_have_url(frontend + "/kuajing/#/tupian")
            expect(page.locator(".ig-welcome")).to_be_visible()
            cookies = context.cookies(backend + "/api/images/history")
            assert any(c["name"] == "kuajing_image_session" and c["secure"] and c["httpOnly"]
                       and c["sameSite"] == "Strict" for c in cookies)
            page.get_by_label("上传产品图", exact=True).set_input_files({"name": "product.png", "mimeType": "image/png", "buffer": png})
            page.get_by_role("button", name="生成 4 张").click()
            expect(page.locator(".ig-result")).to_have_count(4, timeout=15000)
            expect(page.locator(".ig-result img").first).to_be_visible()
            assert page.locator(".ig-result img").first.evaluate("el => el.complete && el.naturalWidth > 0")
            with page.expect_download() as downloaded:
                page.get_by_role("link", name="保存原图").first.click()
            assert Path(downloaded.value.path()).read_bytes() == png
            page.reload()
            expect(page.locator(".ig-result")).to_have_count(4)
            assert provider.calls == 1, "刷新不得重复执行工作流"
            page.screenshot(path=str(artifacts / "pages.png"), full_page=True)
            other = browser.new_context(ignore_https_errors=True)
            other_page = other.new_page()
            other_page.goto(frontend + "/kuajing/#/tupian")
            expect(other_page.locator(".ig-welcome")).to_be_visible()
            expect(other_page.locator(".ig-result")).to_have_count(0)
            assert not errors and not failed, (errors, failed)
            browser.close()
        print("PASS: Pages 子路径、静态资源、Hash 刷新、跨域 Strict Cookie、四图生成、下载、历史隔离。")
        print(f"Artifacts: {artifacts}")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        service.close()
        if previous_origin is None:
            os.environ.pop("FRONTEND_ORIGINS", None)
        else:
            os.environ["FRONTEND_ORIGINS"] = previous_origin


if __name__ == "__main__":
    main()
