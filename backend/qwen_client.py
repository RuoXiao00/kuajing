"""Qwen 客户端配置模块。

该模块负责加载环境变量并创建 OpenAI 兼容客户端，用于访问 DashScope / Qwen API。
"""

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI


_ENV_LOADED = False


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_qwen_env() -> None:
    """加载 Qwen 相关环境变量。

    作用：从项目根目录或模块目录的 .env 文件读取配置，避免手动设置环境变量。
    原理：通过 os.environ.setdefault 只在变量不存在时设置值。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    module_dir = Path(__file__).resolve().parent
    project_dir = module_dir.parent
    _load_env_file(project_dir / ".env")
    _load_env_file(module_dir / ".env")
    _ENV_LOADED = True


def get_dashscope_api_key() -> str:
    """返回 DashScope API Key。"""
    load_qwen_env()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY is missing. Put it in .env or set it as an environment variable."
        )
    return api_key


def configure_dashscope_env() -> str:
    """把 DashScope API Key 设置到环境变量中并返回该值。"""
    api_key = get_dashscope_api_key()
    os.environ["DASHSCOPE_API_KEY"] = api_key
    return api_key


def get_qwen_model() -> str:
    """返回 Qwen 模型名称，默认 qwen-max。"""
    load_qwen_env()
    return os.getenv("QWEN_MODEL", "qwen3.5-ocr")


def get_qwen_base_url() -> str:
    """返回 DashScope 兼容模式的基础 URL。"""
    load_qwen_env()
    return os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


def get_qwen_client() -> OpenAI:
    return OpenAI(
        api_key=get_dashscope_api_key(),
        base_url=get_qwen_base_url(),
    )
