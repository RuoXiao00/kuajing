"""仅在后端调用 Coze；浏览器不接触令牌，也不直接访问上传接口。

调用链：页面 → api.py → service.py 后台任务 → 本模块 → Coze。
使用官方 HTTP 接口，与 cozepy 的 files.upload / workflows.runs.stream 等价。
"""
from __future__ import annotations

import io
import ipaddress
import json
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

MODES = {
    "product": ("生成产品图", ("product",)),
    "model": ("生成产品和模特的结合图", ("product", "model")),
    "background": ("生成产品和背景的结合图", ("product", "background")),
    "views": ("生成产品多视图", ("product",)),
    "model_views": ("生成产品和模特和多视图", ("product", "model")),
    "background_views": ("生成产品和背景和多视图", ("product", "background")),
    "all_views": ("生成产品和背景和模特和多视图", ("product", "model", "background")),
}
SLOTS = tuple(f"{role}_img{i}" for role in ("product", "model", "background") for i in (1, 2))
MAX_UPLOAD = 10 * 1024 * 1024
MAX_IMAGE = 25 * 1024 * 1024


class ImageTaskError(Exception):
    """只携带可公开的说明；不要把供应商原始响应或带签名的 URL 输出到日志。"""


def inspect_image(content: bytes) -> tuple[str, str]:
    """检查真实文件内容而非扩展名，拒绝 HTML/SVG 伪装和过大的解压尺寸。"""
    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP"} or img.width * img.height > 40_000_000:
                raise ImageTaskError("请使用不超过 4000 万像素的 JPG、PNG 或 WebP 图片。")
            kind = img.format
            img.verify()
        return {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png"), "WEBP": ("webp", "image/webp")}[kind]
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageTaskError("图片文件无法读取，请重新选择 JPG、PNG 或 WebP 图片。") from exc


def provider_error(code=None, message="") -> ImageTaskError:
    # 原始 msg 可能包含请求参数、凭据或内部地址；只据此分类，不原样回传。
    text = str(message).lower()
    if str(code) == "700012006" or ("token" in text and any(word in text for word in ("invalid", "expired", "revoked"))):
        return ImageTaskError("Coze 令牌无效或已过期，请在后端 .env 更新 COZE_API_TOKEN 后重启后端。")
    if str(code) in {"401", "403", "4100", "4101"} or any(word in text for word in ("token", "unauthorized", "permission", "权限", "鉴权")):
        return ImageTaskError("Coze 授权失败，请检查后端令牌及工作流运行、文件上传权限。")
    if any(word in text for word in ("credit", "balance", "余额", "quota", "insufficient")):
        return ImageTaskError("Coze 额度不足或达到调用限制，请检查账户额度后再试。")
    if any(word in text for word in ("publish", "发布")):
        return ImageTaskError("工作流尚未发布为 API，请在 Coze 发布当前版本后重试。")
    number = str(code) if re.fullmatch(r"\d{1,12}", str(code)) else "未知"
    return ImageTaskError(f"Coze 请求失败（错误码 {number}），请检查工作流发布状态、输入绑定和运行记录。")


def check_http_response(response):
    if not response.ok:
        try:
            body = response.json()
        except ValueError:
            body = {}
        raise provider_error(body.get("code", response.status_code), body.get("msg", ""))


def sse_events(lines):
    """SSE 按空行分包，data 可以有多行；不能把一条网络数据块当成完整 JSON。"""
    event, data, event_id, total = "", [], None, 0
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        total += len(line)
        if total > 4_000_000:
            raise ImageTaskError("工作流输出过大，请检查结束节点是否只返回图片和回复。")
        if not line:
            if event or data:
                yield event, "\n".join(data), event_id
            event, data, event_id = "", [], None
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line.startswith("id:"):
            event_id = line[3:].strip()
    if event or data:
        yield event, "\n".join(data), event_id


def extract_output(content):
    """兼容结束节点的 JSON 字符串、data 数组、url 对象及 Markdown 图片。

    只解析工作流输出，不把提示词/上传参考图当作生成结果；最多返回四张不同图片。
    嵌套 JSON 常见于 End.output 包着图像节点的 data/msg，递归深度设上限。
    """
    urls, messages = [], []

    def walk(value, depth=0, key=""):
        if depth > 10:
            return
        if isinstance(value, dict):
            for name, item in value.items():
                walk(item, depth + 1, name)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1, key)
        elif isinstance(value, str):
            value = value.strip()
            if not value:
                return
            try:
                decoded = json.loads(value.removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, (dict, list)):
                walk(decoded, depth + 1, key)
                return
            if re.fullmatch(r"https://[^\s<>\"]+", value):
                if value not in urls:
                    urls.append(value)
                return
            found = re.findall(r"!\[[^\]]*\]\((https://[^\s)]+)\)", value)
            for url in found:
                if url not in urls:
                    urls.append(url)
            if key.lower() in {"msg", "message", "text", "reply", "output", "content"} or not key:
                # 不向聊天展示临时签名链接、Markdown 图像或大段原始 JSON。
                clean = re.sub(r"!\[[^\]]*\]\([^)]*\)|https?://\S+", "", value).strip()
                if clean and not clean.startswith(("{", "[")) and clean not in messages:
                    messages.append(clean[:2000])

    walk(content)
    return urls[:4], "\n".join(messages)[:3000]


class CozeProvider:
    def __init__(self):
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        self.token = os.getenv("COZE_API_TOKEN", "").strip()
        self.workflow_id = os.getenv("COZE_WORKFLOW_ID", "7687948198364037155").strip()
        self.base = "https://api.coze.cn"

    @property
    def configured(self):
        return bool(self.token and self.workflow_id.isdigit())

    def generate(self, prompt, mode, references, progress):
        if not self.configured:
            raise ImageTaskError("后端尚未配置 Coze 令牌，请配置 COZE_API_TOKEN 后重启后端。")
        # 图片参数不是浏览器 blob: 地址，也不是本机路径；Coze 只能读取上传后的 file_id。
        # 提示词留空时按产品图和 need_what 执行，仅补充四张的输出要求，不编造用户描述。
        parameters = {"input": f"{prompt.strip()}\n请一次生成 4 张图片。".strip(), "need_what": MODES[mode][0]}
        with requests.Session() as session:
            session.headers["Authorization"] = f"Bearer {self.token}"
            for slot, path in references.items():
                progress("uploading")
                with path.open("rb") as file:
                    with session.post(f"{self.base}/v1/files/upload", files={"file": (path.name, file)}, timeout=(10, 90)) as response:
                        check_http_response(response)
                        body = response.json()
                if body.get("code") != 0 or not body.get("data", {}).get("id"):
                    raise provider_error(body.get("code"), body.get("msg"))
                parameters[slot] = json.dumps({"file_id": body["data"]["id"]})

            progress("generating")
            started = time.monotonic()
            payload = {"workflow_id": self.workflow_id, "parameters": parameters}
            # 资源库工作流无需 app_id；如果以后迁入 Coze 应用，可只在后端配置此字段。
            if os.getenv("COZE_APP_ID", "").strip():
                payload["app_id"] = os.environ["COZE_APP_ID"].strip()
            with session.post(f"{self.base}/v1/workflow/stream_run", json=payload, stream=True, timeout=(10, 180)) as response:
                check_http_response(response)
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    body = response.json()
                    raise provider_error(body.get("code"), body.get("msg"))
                nodes, completed, last_event = {}, [], None
                for event, raw, event_id in sse_events(response.iter_lines()):
                    if time.monotonic() - started > 600:
                        raise ImageTaskError("工作流运行超时，请稍后查看 Coze 运行记录再重试。")
                    if event_id is not None:
                        number = int(event_id)
                        if last_event is not None and number != last_event + 1:
                            raise ImageTaskError("工作流消息传输不完整，请重试。")
                        last_event = number
                    data = json.loads(raw) if raw else {}
                    if event == "Error":
                        raise provider_error(data.get("error_code"), data.get("error_message"))
                    if event == "Interrupt":
                        raise ImageTaskError("工作流停在问答或人工输入节点，请改为直接生图并重新发布。")
                    if event == "Message":
                        key = data.get("node_execute_uuid") or data.get("node_id") or data.get("node_title", "")
                        node = nodes.setdefault(key, {"next": 0, "parts": [], "finished": False})
                        if int(data.get("node_seq_id", node["next"])) != node["next"]:
                            raise ImageTaskError("工作流图片输出不完整，请重试。")
                        node["next"] += 1
                        node["parts"].append(data.get("content", ""))
                        if data.get("node_is_finish"):
                            node["finished"] = True
                            completed.append("".join(node["parts"]))
                    if event == "Done":
                        if any(not node["finished"] for node in nodes.values()):
                            raise ImageTaskError("工作流消息尚未完成，请检查输出节点。")
                        # 结束节点通常最后到达，优先使用它，避免同时重复展示中间节点图片。
                        for content in reversed(completed):
                            urls, reply = extract_output(content)
                            if urls:
                                return urls, reply
                        raise ImageTaskError("工作流已结束，但没有返回图片链接。请把生图节点的 data 和 msg 连接到结束节点。")
        raise ImageTaskError("与 Coze 的连接提前中断，未收到完整结果；不会自动重复扣费生成。")


def public_image_url(url):
    """输出 URL 也按不可信数据处理，禁止访问本机、内网及非 HTTPS 地址。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ImageTaskError("工作流返回了不支持的图片地址。")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ImageTaskError("工作流返回的图片地址不是公开图片服务。")


def download_image(url):
    """马上下载生成图片；不把 Coze 的 Authorization 带给图片 CDN。

    限制重定向次数、大小和耗时，逐次检查目标地址，避免供应商异常拖垮后台。
    """
    started = time.monotonic()
    for _ in range(4):
        public_image_url(url)
        with requests.get(url, stream=True, allow_redirects=False, timeout=(10, 30)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise ImageTaskError("生成图片下载失败，临时链接可能已过期。")
            chunks, size = [], 0
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_IMAGE or time.monotonic() - started > 90:
                    raise ImageTaskError("生成图片过大或保存超时。")
                chunks.append(chunk)
        content = b"".join(chunks)
        extension, mime = inspect_image(content)
        return content, extension, mime
    raise ImageTaskError("图片地址重定向次数过多，无法保存。")
