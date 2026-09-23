"""项目后端启动器。

使用方式：在项目根目录运行 `python -m backend.run_api`，或运行 `npm run backend`。
这个文件不负责实现 API；它只负责启动前的端口检查，把常见的 Windows 10048
转换为可理解的提示。真正的统一 FastAPI 应用是 `backend.app:app`。
"""

from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request


HOST = "127.0.0.1"
# 绑定 127.0.0.1 只允许本机访问。部署到服务器时通常由反向代理转发，
# 是否改为 0.0.0.0 应结合防火墙和部署方式决定。
PORT = int(os.getenv("BACKEND_PORT", "8000"))


def _port_is_open() -> bool:
  """判断端口是否已有 TCP 服务监听。

  TCP 连接成功只说明“有人占用端口”，不能证明对方是我们的 FastAPI；
  所以调用方还要继续请求知识库健康端点，区分本项目服务和其他程序。
  """
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.settimeout(1)
    return connection.connect_ex((HOST, PORT)) == 0


def _is_our_fastapi_running() -> bool:
  """通过本项目专属健康端点确认端口上的服务可以复用。"""
  try:
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/knowledge/health", timeout=2) as response:
      content_type = response.headers.get("Content-Type", "")
      return response.status == 200 and "application/json" in content_type
  except (urllib.error.URLError, TimeoutError, OSError):
    return False


def main() -> None:
  """启动一个且仅启动一个后端实例。

  当已有本项目 FastAPI 时直接结束，避免第二个 Uvicorn 抢占同一个端口。
  当端口被其他程序占用时不擅自结束它，而是让用户根据 PID 做安全判断。
  """
  # 端口检查只用于给出清晰提示，不会杀掉任何已运行的进程。
  if _port_is_open():
    if _is_our_fastapi_running():
      print(f"FastAPI 已在 http://{HOST}:{PORT} 运行，无需重复启动。")
      return
    raise RuntimeError(
      f"端口 {PORT} 已被其他服务占用。请先用 PowerShell 检查 PID，"
      "确认用途后再停止该进程，或设置 BACKEND_PORT 使用其他端口。"
    )

  import uvicorn

  # 延迟导入应用：端口已被占用时不加载模型和外部配置，启动反馈更快。
  uvicorn.run("backend.app:app", host=HOST, port=PORT)


if __name__ == "__main__":
  # python -m backend.run_api 会进入这里；被测试 import 时不会自动启动服务。
  main()
