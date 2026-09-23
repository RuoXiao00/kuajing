"""跨境阁统一 FastAPI 应用入口。

推荐、知识库问答和管理接口挂在同一个应用中。开发时 Vite 把 /api 代理到
这里；生产时前端静态站点与 API 应由同一域名提供，以便 Strict Cookie 生效。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.tuijian.agent import router as recommendation_router
from backend.zhishiku.api import router as knowledge_router
from backend.tuijian.daily import DailyRecommendations
from backend.remen.pachon import create_app as create_product_app, router as product_router, CrawlError
from backend.tupian.api import router as image_router
from backend.tupian.service import ImageService, DEFAULT_ROOT as IMAGE_ROOT

# 复用爬虫应用的生命周期，把热门接口接入8000，不再要求用户另开8001。
product_app = create_product_app()


# 导入本模块时会创建唯一 FastAPI 应用并登记路由；接口函数本身仍要等请求
# 到达才执行。run_api.py 的字符串 backend.app:app 就指向这里的 app 变量。
def _frontend_origins() -> list[str]:
    """读取允许跨域的前端来源。

    来源必须写完整协议和域名，以逗号分隔。这里拒绝通配符，因为管理接口
    使用 Cookie；“任意来源 + 凭证”既不安全，也会被浏览器 CORS 规则阻止。
    """

    raw = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    if "*" in origins:
        raise RuntimeError("FRONTEND_ORIGINS 不允许使用通配符 *，请配置明确前端域名")
    return origins


@asynccontextmanager
async def lifespan(application):
    """服务启动即准备每日推荐；页面只读快照，不承担调度或生成职责。

    单个后端实例只创建一个调度器。生成在后台线程执行，不阻塞知识库接口。
    RECOMMENDATIONS_DB_PATH 可用于独立验收，默认路径与正式知识库完全分离。
    """
    from backend.tuijian.daily import DEFAULT_DB
    service = DailyRecommendations(os.getenv("RECOMMENDATIONS_DB_PATH", str(DEFAULT_DB)))
    application.state.recommendations = service
    # 生图使用独立目录和后台线程；切换页面只会读取任务，不会再次调用收费工作流。
    application.state.images = ImageService(os.getenv("IMAGE_STORAGE_DIR", str(IMAGE_ROOT)))
    async with product_app.router.lifespan_context(product_app):
        application.state.amazon_crawler = product_app.state.amazon_crawler
        application.state.first_pages = product_app.state.first_pages
        await service.start()
        try:
            yield
        finally:
            application.state.images.close()
            await service.stop()


app = FastAPI(
    title="跨境阁 API",
    version="2.0.0",
    description="产品推荐、亚马逊知识库 RAG 与管理员知识文件入库接口。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization"],
)

app.include_router(recommendation_router)
# include_router 相当于把两个子模块维护的“接口清单”装入统一应用。
# 因此前端只连接一个 8000 端口，推荐与知识库接口不会各启一台服务器。
app.include_router(knowledge_router)
app.include_router(product_router)
app.include_router(image_router)
app.add_exception_handler(CrawlError, product_app.exception_handlers[CrawlError])


@app.get("/", tags=["系统"], summary="API 入口")
def api_root() -> dict[str, str]:
    """提供最小导航信息，避免根路径看起来像 404。"""

    return {
        "service": "跨境阁 API",
        "docs": "/docs",
        "knowledge_health": "/api/knowledge/health",
    }
