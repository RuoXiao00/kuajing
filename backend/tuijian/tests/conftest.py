"""推荐回归测试默认禁止真实资料下载；真实验收必须使用独立脚本显式执行。"""
import pytest
import requests


@pytest.fixture(autouse=True)
def no_real_public_requests(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("推荐测试必须注入资料替身，禁止访问真实外部来源")
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
