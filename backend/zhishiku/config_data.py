"""知识库的集中配置。

把路径和调优参数集中在这里的作用是：上传、批量导入、检索和健康检查会
始终访问同一套 Chroma 数据，调节切块或召回数量时也不会遗漏某个模块。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# 【学习提示：这个模块什么时候运行】
# Python 第一次 import 本模块时，会从上到下执行一次模块顶层代码：计算路径、
# 读取 .env，并把常量保存到模块对象中。以后再次 import 通常直接复用缓存，
# 因此修改 .env 后要重启后端，不能期待每次请求都重新读取配置。
# 配置模块会被 Rerank 健康检查、独立导入命令等入口直接导入，不能依赖
# backend._common “碰巧先被加载”。在这里显式读取项目根目录 .env，能保证
# FastAPI、命令行脚本和单独模块调试三种启动方式获得相同配置。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
CHROMA_DIR = RUNTIME_DIR / "chroma"
COLLECTION_NAME = os.getenv("KNOWLEDGE_COLLECTION", "amazon_cross_border_knowledge")

# 约 800 个中文字符能保留一段完整说明，又不会让单块混入过多主题。
CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", "800"))
# 重叠用于保护切块边界处的句子，代价是少量重复存储和 Embedding token。
CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", "120"))

# 先宽召回 12 条提高覆盖率，再用 Rerank 从中选出最相关的 5 条。
RECALL_K = int(os.getenv("KNOWLEDGE_RECALL_K", "12"))
RERANK_TOP_N = int(os.getenv("KNOWLEDGE_RERANK_TOP_N", "5"))

MAX_QUESTION_LENGTH = 2_000
MAX_HISTORY_MESSAGES = 10
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")
# 这里保存的是 OpenAI 兼容 Rerank 的“基础地址”，例如
# https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-api/v1。
# 业务层统一追加 /reranks，避免有人把 chat/completions 或原生 API 地址误用。
RERANK_BASE_URL = os.getenv("DASHSCOPE_RERANK_BASE_URL", "").strip().rstrip("/")
REWRITE_MODEL = os.getenv("QWEN_REWRITE_MODEL", "qwen-flash")


def ensure_runtime() -> None:
    """在首次启动或备份旧 runtime 后，重新创建需要的运行目录。"""

    # exist_ok=True 让这个操作具备“幂等性”：目录已经存在时不会报错。
    # 自己写初始化函数时，也应尽量做到多次调用与调用一次的最终结果相同。
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
