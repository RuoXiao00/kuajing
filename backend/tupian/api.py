"""图片页面 API：Cookie 隔离浏览器历史，上传字段直接对应 Coze 开始节点。"""
from __future__ import annotations

import os
import re
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from .provider import MODES, SLOTS, MAX_UPLOAD, ImageTaskError, inspect_image

router = APIRouter(prefix="/api/images", tags=["图片生成"])
COOKIE = "kuajing_image_session"


def owner_of(request):
    owner = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{64}", owner):
        raise HTTPException(401, "请刷新页面初始化图片会话。")
    return owner


def service_of(request):
    return request.app.state.images


@router.get("/history")
def history(request: Request, response: Response, before: str | None = None):
    # 这个随机 Cookie 只代表本浏览器的图片空间，不复用管理员登录或知识库会话。
    owner = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{64}", owner):
        owner = uuid.uuid4().hex + uuid.uuid4().hex
        response.set_cookie(COOKIE, owner, max_age=365 * 86400, httponly=True,
                            secure=request.url.scheme == "https", samesite="strict", path="/api/images")
    response.headers["Cache-Control"] = "no-store"
    service = service_of(request)
    jobs, cursor = service.history(owner, before)
    return {"jobs": [service.public(job) for job in jobs], "before": cursor, "configured": service.provider.configured}


@router.post("/jobs", status_code=202)
async def create_job(request: Request):
    owner = owner_of(request)
    # 防止其他网站利用浏览器现有 Cookie 静默触发生图。正常同源/Vite 代理请求均允许。
    origin = request.headers.get("Origin", "")
    allowed = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin and origin not in [item.strip().rstrip("/") for item in allowed] and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "不允许的请求来源。")
    service = service_of(request)
    if not service.provider.configured:
        raise HTTPException(503, "后端尚未配置 Coze 令牌。")
    try:
        async with request.form(max_files=6, max_fields=3, max_part_size=MAX_UPLOAD) as form:
            prompt, mode, request_id = form.get("prompt", ""), form.get("mode", ""), form.get("request_id", "")
            if not all(isinstance(value, str) for value in (prompt, mode, request_id)):
                raise HTTPException(422, "提交字段格式不正确。")
            prompt = prompt.strip()
            # input 在 Coze 中是可选项：不传、空字符串、纯空白都允许，只限制最长长度。
            if len(prompt) > 3000 or mode not in MODES or not re.fullmatch(r"[a-f0-9-]{32,36}", request_id):
                raise HTTPException(422, "提示词最多 3000 字，请选择有效的生成类型。")
            uploads = {}
            for slot, upload in form.multi_items():
                if slot in {"prompt", "mode", "request_id"}:
                    continue
                if slot not in SLOTS or not isinstance(upload, UploadFile) or slot in uploads:
                    raise HTTPException(422, "上传图片的类型或数量不正确。")
                content = await upload.read(MAX_UPLOAD + 1)
                if not content or len(content) > MAX_UPLOAD:
                    raise HTTPException(413, "每张参考图片须小于 10 MB。")
                extension, mime = await run_in_threadpool(inspect_image, content)
                uploads[slot] = (content, extension, mime)
            if len(uploads) > 5:
                raise HTTPException(422, "每次最多上传 5 张参考图。")
            roles = MODES[mode][1]
            # 生成类型只决定展示/传递哪些参考图，不把可选的模特或背景图升级为必填。
            if "product_img1" not in uploads:
                raise HTTPException(422, "请上传至少 1 张产品图。")
            if any(slot.split("_img")[0] not in roles for slot in uploads):
                raise HTTPException(422, "参考图类型与当前生成类型不符，请重新选择。")
            job = await run_in_threadpool(service.submit, owner, request_id, prompt, mode, uploads)
            return service.public(job)
    except ImageTaskError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, response: Response):
    job = service_of(request).get(job_id, owner_of(request))
    if not job:
        raise HTTPException(404, "找不到这次生成记录。")
    response.headers["Cache-Control"] = "no-store"
    return service_of(request).public(job)


@router.post("/jobs/{job_id}/retry-save", status_code=202)
def retry_save(job_id: str, request: Request):
    try:
        return service_of(request).public(service_of(request).retry_save(job_id, owner_of(request)))
    except ImageTaskError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/jobs/{job_id}/files/{name}")
def image_file(job_id: str, name: str, request: Request, download: bool = False):
    service = service_of(request)
    job = service.get(job_id, owner_of(request))
    # 必须属于本会话且出现在数据库白名单中，不能通过文件名访问其他目录。
    item = next((item for item in job["images"] + job["references"] if item["name"] == name), None) if job else None
    if not item:
        raise HTTPException(404, "图片不存在。")
    path = service.root / job_id / name
    if not path.is_file():
        raise HTTPException(404, "本地图片文件已被移动或删除。")
    return FileResponse(path, media_type=item["mime"], filename=name if download else None,
                        headers={"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"})
