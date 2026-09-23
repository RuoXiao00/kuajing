"""后端共用的模型与环境配置。

这个模块只做两件事：加载项目根目录 ``.env``，以及创建 Qwen/Embedding
客户端。业务代码统一从这里获取客户端，可避免不同功能悄悄使用不同模型。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# override=False 表示系统/部署环境已有值时优先使用它，.env 只补缺失配置。
# 这是常见的“部署环境覆盖本地默认”约定。
load_dotenv(PROJECT_ROOT / ".env", override=False)


def req_setting(name: str) -> str:
    """读取必填环境变量，缺少时只报告变量名，不泄露其他配置。"""

    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"缺少环境变量 {name}；请在项目根目录 .env 或部署环境中配置它。"
        )
    return value


def embeddings() -> DashScopeEmbeddings:
    """创建知识库入库和检索共同使用的向量模型。

    入库和检索必须使用同一个 Embedding 模型，否则两次产生的向量不在同一
    坐标空间，距离就没有可比较意义。默认值可用环境变量覆盖，但已有向量库
    更换模型后必须重新入库。
    """

    # 此函数是工厂：每次调用返回一个客户端对象，而不是直接执行向量化。
    # 真正网络请求发生在 Chroma 调用 embedding_function 时。
    req_setting("DASHSCOPE_API_KEY")
    return DashScopeEmbeddings(
        model=os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4")
    )


def chat_model(
    *,
    model_name: str | None = None,
    temperature: float = 0,
    streaming: bool = False,
) -> ChatTongyi:
    """创建 Qwen 聊天模型。

    参数说明：
    - ``model_name``：本次任务使用的模型；不传时读取 ``QWEN_MODEL``。
      问题改写会显式传 ``qwen-flash``，正式回答通常使用 ``qwen-max``。
    - ``temperature``：随机度；知识库回答强调事实稳定性，因此默认为 0。
    - ``streaming``：是否要求供应商逐块返回文本。当前 LangChain 会把
      ``ChatTongyi(streaming=False)`` 视为硬禁用公共 ``stream()``，因此 SSE
      回答必须显式传 True；普通 ``invoke()`` 保持 False，避免改变其他功能。
    """

    # model_name 参数使问题改写和正式回答可以共享工厂但选择不同模型。
    # 自己扩展模型功能时，优先在工厂集中处理公共配置。
    req_setting("DASHSCOPE_API_KEY")
    return ChatTongyi(
        model=model_name or os.getenv("QWEN_MODEL", "qwen-max"),
        temperature=temperature,
        streaming=streaming,
    )
