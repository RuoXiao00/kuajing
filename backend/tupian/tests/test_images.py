"""离线验收：临时数据库、图片和供应商替身；不会访问 Coze 或正式知识库。"""
import io
import json
import threading
import time
import uuid

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.tupian.api import router
from backend.tupian.provider import (CozeProvider, ImageTaskError, MODES, extract_output,
                                     inspect_image, public_image_url, sse_events)
from backend.tupian.service import ACTIVE, ImageService


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), "#e1e6dc").save(buffer, format="PNG")
    return buffer.getvalue()


class FakeProvider:
    configured = True

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def generate(self, prompt, mode, references, progress):
        self.calls += 1
        self.last_input = (prompt, mode, set(references))
        self.entered.set()
        self.release.wait(3)
        progress("generating")
        return [f"https://cdn.example.com/{index}.png" for index in range(4)], "四张产品图已生成。"


@pytest.fixture(autouse=True)
def no_vendor_calls(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("图片测试禁止真实供应商请求")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)


@pytest.fixture
def setup(tmp_path):
    provider = FakeProvider()
    service = ImageService(tmp_path, provider=provider, downloader=lambda url: (png(), "png", "image/png"))
    app = FastAPI()
    app.state.images = service
    app.include_router(router)
    with TestClient(app) as client:
        client.get("/api/images/history")
        yield service, provider, client, app
    provider.release.set()
    service.close()
    service.pool.shutdown(wait=True)


def post(client, request_id=None, mode="product", roles=("product",), prompt="柔和光线的产品图"):
    data = {"mode": mode, "request_id": request_id or uuid.uuid4().hex}
    if prompt is not None:
        data["prompt"] = prompt
    return client.post("/api/images/jobs", data=data,
                       files={f"{role}_img1": ("reference.png", png(), "image/png") for role in roles})


def wait_job(service, job_id, owner):
    for _ in range(100):
        job = service.get(job_id, owner)
        if job["status"] not in ACTIVE:
            return job
        time.sleep(.02)
    pytest.fail("替身任务未按时完成")


def test_submit_refresh_download_and_restart(setup, tmp_path):
    service, provider, client, _ = setup
    response = post(client)
    assert response.status_code == 202
    job_id = response.json()["id"]
    owner = client.cookies.get("kuajing_image_session")
    job = wait_job(service, job_id, owner)
    assert job["status"] == "completed" and len(job["images"]) == 4
    for _ in range(3):
        history = client.get("/api/images/history").json()
        assert len(history["jobs"]) == 1
        assert "sources" not in history["jobs"][0] and "owner" not in history["jobs"][0]
    assert provider.calls == 1
    saved = client.get(job["images"][0]["url"] + "?download=true")
    assert saved.content == png() and "attachment" in saved.headers["content-disposition"]
    assert client.get(job["references"][0]["url"]).status_code == 200
    restored = ImageService(tmp_path, provider=provider)
    assert restored.get(job_id, owner)["status"] == "completed"
    assert provider.calls == 1
    restored.close()


def test_browser_isolation(setup):
    service, _, client, app = setup
    job = post(client).json()
    job = wait_job(service, job["id"], client.cookies.get("kuajing_image_session"))
    with TestClient(app) as stranger:
        assert stranger.get("/api/images/history").json()["jobs"] == []
        assert stranger.get(f"/api/images/jobs/{job['id']}").status_code == 404
        assert stranger.get(job["images"][0]["url"]).status_code == 404


def test_idempotency_and_single_active_job(setup):
    service, provider, client, _ = setup
    provider.release.clear()
    request_id = uuid.uuid4().hex
    first = post(client, request_id).json()
    assert provider.entered.wait(1)
    second = post(client, request_id).json()
    assert first["id"] == second["id"]
    assert post(client).status_code == 400
    provider.release.set()
    wait_job(service, first["id"], client.cookies.get("kuajing_image_session"))
    assert provider.calls == 1


def test_save_retry_never_regenerates(setup):
    service, provider, client, _ = setup
    def failing(url):
        if url.endswith("/2.png"):
            raise ImageTaskError("下载失败")
        return png(), "png", "image/png"
    service.downloader = failing
    job = post(client).json()
    owner = client.cookies.get("kuajing_image_session")
    partial = wait_job(service, job["id"], owner)
    assert partial["status"] == "partial" and len(partial["images"]) == 3
    assert partial["can_retry_save"]
    service.downloader = lambda url: (png(), "png", "image/png")
    assert client.post(f"/api/images/jobs/{job['id']}/retry-save").status_code == 202
    completed = wait_job(service, job["id"], owner)
    assert completed["status"] == "completed" and len(completed["images"]) == 4
    assert provider.calls == 1


def test_interrupted_restart_does_not_charge(setup, tmp_path):
    service, provider, client, _ = setup
    job = post(client).json()
    owner = client.cookies.get("kuajing_image_session")
    job = wait_job(service, job["id"], owner)
    job["status"] = "generating"
    service.save(job)
    restored = ImageService(tmp_path, provider=provider)
    assert restored.get(job["id"], owner)["status"] == "interrupted"
    assert provider.calls == 1
    restored.close()


@pytest.mark.parametrize("mode,roles", [(key, value[1]) for key, value in MODES.items()])
def test_all_mode_roles(setup, mode, roles):
    service, _, client, _ = setup
    job = post(client, mode=mode, roles=roles)
    assert job.status_code == 202
    wait_job(service, job.json()["id"], client.cookies.get("kuajing_image_session"))


def test_bad_files_missing_roles_and_origin(setup):
    _, provider, client, _ = setup
    assert post(client, mode="model", roles=("model",), prompt="").status_code == 422
    assert post(client, roles=(), prompt=None).status_code == 422
    assert post(client, prompt="a" * 3001).status_code == 422
    assert post(client, roles=("product", "background")).status_code == 422
    invalid = client.post("/api/images/jobs", data={"prompt": "test", "mode": "product", "request_id": uuid.uuid4().hex},
                          files={"product_img1": ("image.png", b"<html>fake image</html>", "image/png")})
    assert invalid.status_code == 400
    assert client.post("/api/images/jobs", headers={"Origin": "https://evil.example"}).status_code == 403
    assert provider.calls == 0


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("prompt", [None, "", "  \n  "])
def test_only_product_required_for_every_mode(setup, mode, prompt):
    service, provider, client, _ = setup
    response = post(client, mode=mode, prompt=prompt)
    assert response.status_code == 202
    job = wait_job(service, response.json()["id"], client.cookies.get("kuajing_image_session"))
    assert job["status"] == "completed" and job["prompt"] == ""
    assert provider.last_input == ("", mode, {"product_img1"})


def test_extract_nested_output_and_deduplicate():
    content = json.dumps({"output": json.dumps({"data": [{"url": "https://cdn.example/a.png"}, "https://cdn.example/a.png", "https://cdn.example/b.png"], "msg": "已经生成。"})})
    urls, message = extract_output(content)
    assert urls == ["https://cdn.example/a.png", "https://cdn.example/b.png"]
    assert message == "已经生成。"
    assert extract_output("![结果](https://cdn.example/a.png)")[0] == urls[:1]


def test_sse_multiline_and_image_validation():
    assert list(sse_events(["id: 0", "event: Message", "data: {", 'data: "x": 1}', ""])) == [("Message", '{\n"x": 1}', "0")]
    assert inspect_image(png()) == ("png", "image/png")
    with pytest.raises(ImageTaskError):
        inspect_image(b"<svg></svg>")


@pytest.mark.parametrize("url", ["http://cdn.example/a.png", "https://127.0.0.1/x", "https://[::1]/x", "https://localhost/x", "https://user:secret@cdn.example/x"])
def test_unsafe_output_urls(url):
    with pytest.raises(ImageTaskError):
        public_image_url(url)


class FakeResponse:
    ok = True
    headers = {"Content-Type": "text/event-stream"}
    def __init__(self, lines=None):
        self.lines = lines
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def json(self): return {"code": 0, "data": {"id": "123456"}}
    def iter_lines(self): return iter(self.lines)


def stream_lines(events):
    lines = []
    for index, (event, data) in enumerate(events):
        lines += [f"id: {index}", f"event: {event}", "data: " + json.dumps(data), ""]
    return lines


@pytest.mark.parametrize("prompt", ["prompt", ""])
def test_real_adapter_parameter_contract(monkeypatch, tmp_path, prompt):
    monkeypatch.setenv("COZE_API_TOKEN", "test-only-token")
    monkeypatch.setenv("COZE_APP_ID", "")
    reference = tmp_path / "ref.png"
    reference.write_bytes(png())
    calls = []
    content = json.dumps({"data": ["https://cdn.example/a.png"], "msg": "完成"})
    lines = stream_lines([("Message", {"content": content[:12], "node_seq_id": "0", "node_is_finish": False}),
                          ("Message", {"content": content[12:], "node_seq_id": "1", "node_is_finish": True}), ("Done", {})])
    def fake_post(self, url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(lines if url.endswith("stream_run") else None)
    monkeypatch.setattr(requests.Session, "post", fake_post)
    urls, reply = CozeProvider().generate(prompt, "model", {"product_img1": reference, "model_img1": reference}, lambda status: None)
    assert urls == ["https://cdn.example/a.png"] and reply == "完成"
    payload = calls[-1][1]["json"]
    assert payload["parameters"]["need_what"] == "生成产品和模特的结合图"
    assert payload["parameters"]["input"] == f"{prompt}\n请一次生成 4 张图片。".strip()
    assert json.loads(payload["parameters"]["product_img1"]) == {"file_id": "123456"}
    assert "workflow_id" in payload and "wordflow_id" not in payload


@pytest.mark.parametrize("events,match", [
    ([("Error", {"error_code": 403, "error_message": "secret token"})], "授权失败"),
    ([("Interrupt", {})], "问答"),
    ([("Message", {"content": "x", "node_seq_id": 1})], "不完整"),
    ([("Message", {"content": "x", "node_seq_id": 0}), ("Done", {})], "尚未完成"),
    ([("Done", {})], "没有返回图片"),
    ([], "提前中断"),
])
def test_stream_failures(monkeypatch, events, match):
    monkeypatch.setenv("COZE_API_TOKEN", "test-only-token")
    monkeypatch.setattr(requests.Session, "post", lambda *args, **kwargs: FakeResponse(stream_lines(events)))
    with pytest.raises(ImageTaskError, match=match):
        CozeProvider().generate("prompt", "product", {}, lambda status: None)
