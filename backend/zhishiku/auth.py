"""单管理员 Cookie 会话认证。

管理员账号、bcrypt 哈希和签名密钥全部来自环境变量。源码里没有默认密码，
配置缺失时管理接口返回 503，而不是悄悄启用弱口令。
"""

from __future__ import annotations

import os
import hmac
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import bcrypt
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


COOKIE_NAME = "kuajing_admin_session"
SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class AdminSettings:
    """从部署环境读取的安全配置快照。"""

    username: str
    password_hash: str
    session_secret: str
    cookie_secure: bool


def get_admin_settings() -> AdminSettings:
    """读取并校验管理员配置；不返回任何配置值到 HTTP 响应。"""

    # 每次认证重新读取环境变量，测试可用 monkeypatch 临时注入配置；
    # frozen=True 则保证返回的配置快照不会被请求代码意外修改。
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
    secret = os.getenv("SESSION_SECRET", "").strip()
    missing = [
        name
        for name, value in (
            ("ADMIN_USERNAME", username),
            ("ADMIN_PASSWORD_HASH", password_hash),
            ("SESSION_SECRET", secret),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"管理员功能尚未配置：缺少 {', '.join(missing)}",
        )
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员功能配置无效：SESSION_SECRET 至少需要 32 个字符",
        )
    return AdminSettings(
        username=username,
        password_hash=password_hash,
        session_secret=secret,
        cookie_secure=os.getenv("COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes", "on"},
    )


def client_ip(request: Request) -> str:
    """取得限流键。

    默认只信任 TCP 对端地址，避免攻击者伪造 X-Forwarded-For 绕过限流。
    仅当受控反向代理会清洗该请求头时，才设置 TRUST_PROXY_HEADERS=true。
    """

    if os.getenv("TRUST_PROXY_HEADERS", "false").lower() in {"1", "true", "yes", "on"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        # 从客户端连接信息中，取出**主机地址（一般就是访问者的 IP 地址）**。
    return request.client.host if request.client else "unknown"


class LoginRateLimiter:
    """进程内登录失败计数：每 IP 15 分钟最多尝试 5 次。"""

    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, ip: str) -> None:
        # monotonic 只测时间间隔，不受系统时钟被人工调整影响，适合限流。
        now = time.monotonic()
        with self._lock:
            values = self._attempts[ip]
            # 清理掉15分钟之前的失败记录
            while values and now - values[0] > LOGIN_WINDOW_SECONDS:
                values.popleft()
            # 剩下的失败次数≥5次，直接不让登
            if len(values) >= LOGIN_MAX_ATTEMPTS:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="登录尝试过多，请 15 分钟后再试",
                    headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
                )

    def record_failure(self, ip: str) -> None:
        with self._lock:
            self._attempts[ip].append(time.monotonic())

    def clear(self, ip: str) -> None:
        with self._lock:
            self._attempts.pop(ip, None)


login_limiter = LoginRateLimiter()


def verify_credentials(username: str, password: str, settings: AdminSettings) -> bool:
    """用 bcrypt 比较密码；明文密码只存在于当前请求内，不写日志。"""

    username_matches = hmac.compare_digest(username, settings.username)
    # bcrypt 最多接收 72 字节。超长输入按登录失败处理，不能让第三方库异常
    # 变成 500，也不能悄悄截断后验证成另一个密码。
    if len(password.encode("utf-8")) > 72:
        return False
    try:
        password_matches = bcrypt.checkpw(
            password.encode("utf-8"), settings.password_hash.encode("utf-8")
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员密码哈希格式无效，请重新生成 bcrypt 哈希",
        )
    return username_matches and password_matches


def _serializer(settings: AdminSettings) -> URLSafeTimedSerializer:
    # 前导下划线表示模块内部辅助函数。salt 把管理员 Cookie 与其他签名用途
    # 隔离；签名能发现篡改，但 payload 本身不是加密后的秘密内容。
    return URLSafeTimedSerializer(settings.session_secret, salt="kuajing-admin-v1")


def set_session_cookie(response: Response, settings: AdminSettings) -> None:
    """签发 8 小时 Cookie；JavaScript 无法读取 HttpOnly 内容。"""

    token = _serializer(settings).dumps({"username": settings.username})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response, settings: AdminSettings | None = None) -> None:
    """让浏览器删除会话 Cookie。"""

    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=settings.cookie_secure if settings else False,
        httponly=True,
        samesite="strict",
    )


def require_admin(request: Request) -> str:
    """FastAPI 依赖：验证签名、8 小时有效期和用户名。"""

    # 此函数由 api.py 写进 Depends。FastAPI 会在受保护接口之前执行它；
    # 抛出 HTTPException 后，上传或统计函数不会继续运行。
    settings = get_admin_settings()
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录管理员账号")
    try:
        payload = _serializer(settings).loads(token, max_age=SESSION_SECONDS)
    except SignatureExpired as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录") from error
    except BadSignature as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效") from error
    if not isinstance(payload, dict) or payload.get("username") != settings.username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效")
    return settings.username
