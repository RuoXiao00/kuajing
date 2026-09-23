"""知识库与管理后台的 FastAPI 路由。

接口层只负责 HTTP 协议：校验 JSON/文件、认证、限流、SSE 编码和状态码。
RAG、文件解析与 Chroma 写入分别由业务模块完成，便于独立测试。
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from anyio import CancelScope
from starlette.concurrency import run_in_threadpool

from .agent import knowledge_base_service
from .auth import (
    clear_session_cookie,
    client_ip,
    get_admin_settings,
    login_limiter,
    require_admin,
    set_session_cookie,
    verify_credentials,
)
from .config_data import MAX_HISTORY_MESSAGES, MAX_QUESTION_LENGTH, MAX_UPLOAD_BYTES
from .document_loader import DocumentParseError
from .reranker import reranker
from .vector_stories import knowledge_store
from .zhishiku import ChatHistoryItem, rag_service


router = APIRouter()


# Pydantic 请求模型在应用启动导入时完成类定义；每个请求到达后，FastAPI
# 才创建实例、运行 validator，不合法的数据会在业务函数前自动得到 422。
class HistoryMessage(BaseModel):
    """聊天历史的一项；只接受用户和助手消息，系统提示不能由前端注入。"""

    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"] = Field(description="消息作者")
    content: str = Field(min_length=1, max_length=6_000, description="消息正文")
    # 限制处理对象 
    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        # @classmethod 接收模型类 cls，而不是尚未创建完成的 self。返回值成为
        # 最终字段值；抛 ValueError 会被 Pydantic 收集为校验错误。
        value = value.strip()
        if not value:
            raise ValueError("历史消息不能为空")
        return value


class ChatRequest(BaseModel):
    """两个聊天接口共用的 JSON 请求体。

    conversation_id 只用于前后端关联一次会话，后端不据此永久存储匿名历史。
    history 最多 10 条，应按从旧到新的顺序发送。
    """

    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID = Field(description="浏览器用 crypto.randomUUID() 创建的会话 ID")
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="本轮原始问题，最多 2,000 个字符",
    )
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_MESSAGES,
        description="最近最多 10 条历史消息，不含本轮问题",
    )

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value

    def history_dicts(self) -> list[ChatHistoryItem]:
        """转成 RAG 服务使用的普通字典，隔离 Pydantic 与业务层。"""

        return [
            ChatHistoryItem(role=item.role, content=item.content)
            for item in self.history
        ]


class LoginRequest(BaseModel):
    """管理员登录 JSON；密码只用于本次 bcrypt 验证。"""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class PublicChatLimiter:
    """公开聊天的进程内限流：每 IP 每分钟 20 次，全局同时生成最多 2 个。

    公网多 worker 部署时，各 worker 的内存不共享，还应在 Nginx/API Gateway
    配置同样或更严格的限流；本实现仍可保护单进程开发和小型部署。
    """

    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._active = 0
        self._lock = threading.Lock()

    def start(self, ip: str) -> None:
        # start 成功后必须和 finish 配对。接口放在 finally 里释放名额，确保
        # 模型异常或浏览器断开时不会永久误判“生成任务已满”。
        now = time.monotonic()
        with self._lock:
            calls = self._calls[ip]
            while calls and now - calls[0] > 60:
                calls.popleft()
            if len(calls) >= 20:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="请求过于频繁，请稍后再试",
                    headers={"Retry-After": "60"},
                )
            if self._active >= 2:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="当前生成任务已满，请稍后再试",
                    headers={"Retry-After": "5"},
                )
            calls.append(now)
            self._active += 1

    def finish(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)


chat_limiter = PublicChatLimiter()


class ClosingStreamingResponse(StreamingResponse):
    """让 ASGI 响应的完整生命周期负责关闭流并释放一次并发名额。

    仅把清理放在生成器 finally 不够：响应头发送失败时，生成器可能尚未启动；
    send 在两个 yield 之间失败时，生成器也未必自动 close。这里兜住响应层异常。
    """

    def __init__(self, *args: Any, release: Callable[[], None], **kwargs: Any) -> None:
        # 这是“继承后补收尾”的写法：super().__init__ 先让父类设置响应体、头等。
        # *args/**kwargs 接住并转交父类参数；release 则是我们新增的清理回调。
        # Callable[[], None] 表示“调用时无参数，也不需要返回业务结果的函数”。
        super().__init__(*args, **kwargs)
        self._release = release
        self._released = False

    async def __call__(self, scope, receive, send) -> None:
        # __call__ 让实例能像函数一样被调用。ASGI 服务器执行 response(scope,
        # receive, send) 时会进入这里，不是构造 ClosingStreamingResponse(...) 时。
        # scope 是连接信息；receive 用来接收连接事件；send 用来发送响应头和正文。
        # 由 Uvicorn/Starlette 调用，不是路由手动调用。shield 只保护清理，不保护生成：
        # 用户停止时应取消图，不能屏蔽取消后继续回答。没有捕获 CancelledError。
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                # “暂停营业”也要把账结清：shield 只让本地清理不再被取消打断。
                # 它不负责拦住用户停止，更没有把整个模型生成过程罩起来继续跑。
                try:
                    await self.body_iterator.aclose()
                finally:
                    # 先关流，再释放名额；关闭本身异常也不能永久占着名额。
                    # _released 像一次性凭条，防止重复 finish 把另一个人的名额也减掉。
                    if not self._released:
                        self._released = True
                        self._release()


def _safe_service_error(error: Exception) -> tuple[int, str]:
    """把内部异常映射成不包含密钥、URL、绝对路径的公开提示。"""

    if isinstance(error, RuntimeError) and "缺少环境变量" in str(error):
        return status.HTTP_503_SERVICE_UNAVAILABLE, str(error)
    return status.HTTP_503_SERVICE_UNAVAILABLE, "知识库服务暂时不可用，请稍后重试"


def _sse(event: str, data: dict[str, Any]) -> str:
    """编码一个标准 SSE 事件；JSON 可安全承载换行和中文 token。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/api/knowledge/chat",
    summary="知识库非流式问答",
    response_description="完整答案、来源卡片和本次是否使用 Rerank",
)
# 装饰器在模块导入时登记路径和函数，不会立刻调用 chat。请求命中后，
# FastAPI 先构造 payload/request，校验完成才执行下面的函数。
def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
    """一次性完成 RAG 问答。

    适合 Swagger、自动测试和不支持 SSE 的客户端。浏览器聊天页使用下面的
    stream 接口，二者接收完全相同的请求结构。
    """

    chat_limiter.start(client_ip(request))
    try:
        result = rag_service.ask(payload.question, payload.history_dicts())
        return {
            "conversation_id": str(payload.conversation_id),
            "answer": result["answer"],
            "sources": result["sources"],
            "rerank_used": result["rerank_used"],
        }
    except Exception as error:
        code, detail = _safe_service_error(error)
        raise HTTPException(status_code=code, detail=detail) from error
    finally:
        chat_limiter.finish()


@router.post(
    "/api/knowledge/chat/stream",
    summary="知识库 SSE 流式问答",
    response_class=StreamingResponse,
)
# 此接口返回 StreamingResponse 而不是普通 dict。生成器每 yield 一段，
# ASGI 服务器就能把该段继续发送给浏览器，连接无需等完整答案。
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    """以 SSE 顺序发送 status、sources、token、done 或 error 事件。

    前端应逐行解析 event/data；用户点击“停止生成”时调用 AbortController.abort，
    连接关闭后响应层 finally 关闭图并释放并发名额。输入不合法返回 422，
    触发限流在响应开始前返回 429；开始发送后业务异常通过 error 事件报告。
    这里的异步只负责等待图事件；同步检索节点由 LangGraph 在线程中执行。
    """

    chat_limiter.start(client_ip(request))

    async def generate() -> AsyncIterator[str]:
        # AsyncIterator[str] 是“等待后逐次产出字符串”，不是一次返回所有字符串。
        # 图执行时才产生事件；路由只加会话追踪 ID、编码 SSE，不知道节点顺序。
        # 这是嵌套函数：它记住本请求的 payload，叫“闭包”。每次 HTTP 请求创建
        # 自己的 generate 和事件流，不会因为复用 rag_service 就共用某个用户的输入。
        try:
            async with aclosing(rag_service.astream_events(
                payload.question, payload.history_dicts(),
            )) as events:
                async for event, data in events:
                    if event == "done":
                        data = {**data, "conversation_id": str(payload.conversation_id)}
                    yield _sse(event, data)
        except Exception as error:
            # 已发出响应头之后，不能突然把 200 改成 503。只能在同一连接里发送
            # error 事件，前端据此显示失败。连接正常关闭也不代表业务成功，要看 done。
            _, message = _safe_service_error(error)
            yield _sse("error", {"message": message})

    return ClosingStreamingResponse(
        generate(),
        release=chat_limiter.finish,
        # 传 finish 而非 finish()：前者是把“稍后执行的函数”交给响应对象，
        # 后者会现在就释放名额，导致模型还在生成时限流却以为已经空闲。
        media_type="text/event-stream",
        headers={
            # 禁止缓存和代理缓冲，否则浏览器可能等结束后才一次收到全部 token。
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/api/knowledge/health", summary="知识库健康状态")
def knowledge_health() -> dict[str, Any]:
    """返回知识块、文档数量和 Rerank 状态；绝不返回密钥或绝对路径。"""

    rerank_health = reranker.health()
    try:
        stats = knowledge_store.stats()
        service_status = "degraded" if rerank_health["degraded"] else "ok"
        return {
            "status": service_status,
            "document_count": stats["document_count"],
            "chunk_count": stats["chunk_count"],
            "rerank": rerank_health,
        }
    except Exception:
        return {
            "status": "unavailable",
            "document_count": 0,
            "chunk_count": 0,
            "rerank": rerank_health,
        }


@router.post("/api/admin/login", summary="管理员登录")
def admin_login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    """验证账号密码并设置 8 小时 HttpOnly + SameSite=Strict Cookie。

    成功响应正文不含 token；浏览器通过 Cookie 自动携带会话。生产 HTTPS
    必须配置 COOKIE_SECURE=true。
    """

    settings = get_admin_settings()
    ip = client_ip(request)
    login_limiter.check(ip)
    if not verify_credentials(payload.username, payload.password, settings):
        login_limiter.record_failure(ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码不正确")
    login_limiter.clear(ip)
    set_session_cookie(response, settings)
    return {"authenticated": True, "username": settings.username, "expires_in": 28_800}


@router.get("/api/admin/session", summary="检查管理员会话")
# `Depends` 就是 “依赖”，意思是：执行这个接口函数之前，先自动运行 `require_admin` 这个函数；它的返回值，会赋值给 `admin` 这个参数。
def admin_session(admin: Annotated[str, Depends(require_admin)]) -> dict[str, Any]:
    """页面刷新时检查 Cookie 是否仍有效。"""

    return {"authenticated": True, "username": admin}


@router.post("/api/admin/logout", summary="管理员退出")
def admin_logout(
    response: Response,
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, bool]:
    """删除管理员会话 Cookie。"""

    clear_session_cookie(response, get_admin_settings())
    return {"authenticated": False}


@router.post("/api/admin/knowledge/files", summary="上传并入库一个知识文件")
# async def 用于等待 UploadFile 的读取和关闭；文件解析与向量入库仍委托给
# 业务服务。Annotated 同时携带 Python 类型和 FastAPI 的参数来源信息。
async def upload_knowledge_file(
    _: Annotated[str, Depends(require_admin)],
    file: Annotated[UploadFile, File(description="DOCX、PDF 或 TXT，最大 25 MiB")],
    category: Annotated[str, Form(max_length=80)] = "未分类",
) -> JSONResponse:
    """接收 multipart/form-data。

    字段 file 是一个文件，category 是可选分类。管理页选择多个文件时，会
    对每个文件各调用一次本接口，因此能单独展示进度、重复和失败状态。
    """

    try:
        # 多读 1 字节” 的技巧，不用读完整个文件就能判断是否超限，省内存还防大文件攻击
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "status": "error", "filename": file.filename or "未命名文件",
                    "category": category or "未分类", "chunk_count": 0,
                    "message": "单文件不能超过 25 MiB",
                },
            )
        # 上传接口异步读取文件，但解析/Embedding 是同步操作；整个入库图交给
        # 线程池执行，不能在事件循环里直接阻塞，否则聊天 SSE 也会被上传卡住。
        result = await run_in_threadpool(
            knowledge_base_service.upload_file,
            data, file.filename or "未命名文件", category or "未分类"
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content=result)
    except DocumentParseError as error:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "filename": file.filename or "未命名文件",
                "category": category or "未分类",
                "chunk_count": 0,
                "message": str(error),
            },
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "filename": file.filename or "未命名文件",
                "category": category or "未分类",
                "chunk_count": 0,
                "message": "向量服务暂时不可用，文件没有完成入库",
            },
        )
    finally:
        await file.close()


@router.get("/api/admin/knowledge/stats", summary="知识库管理统计")
def admin_knowledge_stats(
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, Any]:
    """返回唯一正文数、知识块数、分类数、更新时间和本进程最近上传结果。"""

    try:
        return knowledge_store.stats()
    except Exception as error:
        code, detail = _safe_service_error(error)
        raise HTTPException(status_code=code, detail=detail) from error
