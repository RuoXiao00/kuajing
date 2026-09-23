"""生成任务与图片持久化，完全独立于知识库数据库。

页面只负责提交任务和读取进度。耗时上传/工作流/下载在后台线程执行，刷新页面不会
重新调用工作流。每次提交带 request_id，网络重试也只会创建同一份任务。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
import uuid

import requests

from .provider import CozeProvider, ImageTaskError, download_image

DEFAULT_ROOT = Path(__file__).parent / "runtime"
ACTIVE = {"queued", "uploading", "generating", "saving"}
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


class ImageService:
    def __init__(self, root=DEFAULT_ROOT, provider=None, downloader=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "images.sqlite3"
        self.provider = provider or CozeProvider()
        self.downloader = downloader or download_image
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="coze-images")
        self.stopping = False
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(owner, request_id))")
            # 崩溃/断电时供应商可能已计费，所以重启只标记中断，不擅自重新生成。
            for row in db.execute("SELECT id, payload FROM jobs").fetchall():
                job = json.loads(row[1])
                if job["status"] in ACTIVE:
                    job.update(status="interrupted", error="上次任务因后端停止而中断。已保存的图片仍可下载；重新生成需要再次提交。", updated_at=now())
                    job["can_retry_save"] = bool(job["sources"] and len(job["images"]) < len(job["sources"]))
                    db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job, ensure_ascii=False), row[0]))

    @contextmanager
    def connect(self):
        # sqlite 的 with 只提交事务、不关闭连接；显式 close 才不会长期占住 Windows 文件。
        connection = sqlite3.connect(self.db, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, job_id, owner):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        return json.loads(row[0]) if row else None

    def history(self, owner, before=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM jobs WHERE owner=? AND created<? ORDER BY created DESC LIMIT 21", (owner, before or "9999")).fetchall()
        jobs = [json.loads(row[0]) for row in rows[:20]]
        return list(reversed(jobs)), jobs[-1]["created_at"] if len(rows) > 20 else None

    def public(self, job):
        # 源链接只供失败后的“重新保存”使用，页面始终读取本地文件。
        return {key: value for key, value in job.items() if key not in {"owner", "request_id", "sources"}}

    def save(self, job):
        job["updated_at"] = now()
        with self.connect() as db:
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job["id"]))

    def submit(self, owner, request_id, prompt, mode, uploads):
        with self.lock:
            with self.connect() as db:
                row = db.execute("SELECT payload FROM jobs WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
                if row:
                    return json.loads(row[0])
                all_jobs = db.execute("SELECT payload FROM jobs").fetchall()
            active = [json.loads(row[0]) for row in all_jobs if json.loads(row[0])["status"] in ACTIVE]
            if self.stopping or len(active) >= 5 or any(job["owner"] == owner for job in active):
                raise ImageTaskError("已有图片正在生成，请等待当前任务完成后再提交。")
            job_id = uuid.uuid4().hex
            folder = self.root / job_id
            folder.mkdir()
            references = []
            for slot, (content, extension, mime) in uploads.items():
                name = f"{slot}.{extension}"
                (folder / name).write_bytes(content)
                references.append({"slot": slot, "name": name, "mime": mime, "url": f"/api/images/jobs/{job_id}/files/{name}"})
            job = dict(id=job_id, owner=owner, request_id=request_id, prompt=prompt, mode=mode,
                       status="queued", created_at=now(), updated_at=now(), references=references,
                       images=[], sources=[], reply="", error="")
            with self.connect() as db:
                db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?)", (job_id, owner, request_id, job["created_at"], json.dumps(job, ensure_ascii=False)))
            self.pool.submit(self.run, job_id, owner, False)
            return job

    def retry_save(self, job_id, owner):
        with self.lock:
            job = self.get(job_id, owner)
            if not job or job["status"] in ACTIVE or not job["sources"] or len(job["images"]) == len(job["sources"]):
                raise ImageTaskError("当前没有需要重新保存的图片。")
            job.update(status="saving", error="")
            self.save(job)
            self.pool.submit(self.run, job_id, owner, True)
            return job

    def run(self, job_id, owner, save_only=False):
        job = self.get(job_id, owner)

        def progress(status):
            if self.stopping:
                raise ImageTaskError("后端正在停止，任务已中断；已保存图片仍可下载。")
            job["status"] = status
            self.save(job)

        try:
            if not save_only:
                refs = {item["slot"]: self.root / job_id / item["name"] for item in job["references"]}
                urls, reply = self.provider.generate(job["prompt"], job["mode"], refs, progress)
                # 先落盘源地址，后续只重试下载即可，不重复执行收费工作流。
                job.update(sources=urls, reply=reply)
                self.save(job)
            progress("saving")
            failures = 0
            for index, url in enumerate(job["sources"]):
                if any(image["index"] == index for image in job["images"]):
                    continue
                progress("saving")
                try:
                    content, extension, mime = self.downloader(url)
                    name = f"generated-{index + 1}.{extension}"
                    path = self.root / job_id / name
                    # 先写临时文件，再原子改名。接口不会读到只下载了一半的损坏图片。
                    temporary = path.with_suffix(".part")
                    temporary.write_bytes(content)
                    temporary.replace(path)
                    job["images"].append({"index": index, "name": name, "mime": mime, "url": f"/api/images/jobs/{job_id}/files/{name}"})
                    job["images"].sort(key=lambda item: item["index"])
                    self.save(job)
                except (ImageTaskError, requests.RequestException, OSError, ValueError):
                    failures += 1
            count = len(job["images"])
            job["status"] = "partial" if failures or count < 4 else "completed"
            job["error"] = (f"{failures} 张图片保存失败，可以重试保存。" if failures else
                            f"工作流本次仅返回 {count} 张图片，请检查生图节点的图片数量设置。" if count < 4 else "")
            job["can_retry_save"] = failures > 0
            if not job["reply"]:
                job["reply"] = f"已为你生成 {len(job['sources'])} 张图片。你可以点击大图查看细节，或保存原图。"
            self.save(job)
        except Exception as exc:
            # 用户只收到归类说明；日志只记类型和任务 ID，绝不输出令牌或原始异常正文。
            logger.warning("image_task_failed job=%s kind=%s", job_id, type(exc).__name__)
            job["status"] = "interrupted" if self.stopping else "failed"
            job["error"] = str(exc) if isinstance(exc, ImageTaskError) else (
                "连接 Coze 超时或网络中断，请稍后重试。" if isinstance(exc, requests.RequestException)
                else "图片任务未能完成，请检查后端配置或磁盘空间后重试。")
            job["can_retry_save"] = bool(job["sources"] and len(job["images"]) < len(job["sources"]))
            self.save(job)

    def close(self):
        self.stopping = True
        self.pool.shutdown(wait=False, cancel_futures=True)
