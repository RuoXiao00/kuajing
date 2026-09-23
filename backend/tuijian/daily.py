"""每日推荐的时钟、存储和调度；不依赖前端访问，也不使用知识库数据库。

单实例部署：FastAPI lifespan 创建一个 DailyRecommendations。同步抓取/模型调用
放在线程里，事件循环继续响应知识库。SQLite 只在短事务里读写，不在抓取期间持锁。
测试可注入时钟、生成器和临时数据库，默认测试绝不访问真实模型或正式存储。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_DB = Path(__file__).parent / "runtime" / "recommendations.sqlite3"
LOGGER = logging.getLogger(__name__)


def beijing_now():
    return datetime.now(BEIJING)


def schedule_slot(now):
    """当前应有的那一期：05:00 前仍属于昨天 05:00，错过多天只补最近一期。"""
    local = now.astimezone(BEIJING)
    slot = local.replace(hour=5, minute=0, second=0, microsecond=0)
    return slot if local >= slot else slot - timedelta(days=1)


def is_complete(payload):
    categories = payload.get("categories", [])
    # 有效商品少于五件可如实发布；真实抓取中断或缺少分析不能冒充完整成功。
    return len(categories) == 10 and all(
        c.get("products") and c.get("fetch_complete") and c.get("analysis_status") == "success"
        for c in categories
    )


def snapshot_payload(candidate):
    """阶段检查点也能构成部分结果，但不能把类别发现的模型 JSON 当成最终分析。"""
    categories = candidate.get("categories", [])
    return {"categories": categories, "product_names": [c["keyword"] for c in categories],
            "products": [p for c in categories for p in c.get("products", [])],
            "answer": "\n\n".join(c.get("answer", "") for c in categories
                                   if c.get("analysis_status") == "success"),
            "step_num": candidate.get("step_num", 0), "pipeline_version": candidate.get("pipeline_version", 1),
            "evidence": candidate.get("evidence", {})}


def data_failure_message(candidate):
    """兼容已经保存的旧错误：全池抓取失败不能继续向用户谎报AI格式错误。"""
    pool = candidate.get('candidate_pool', [])
    if not pool or any(c.get('products') for c in pool):
        return ''
    codes = {c.get('fetch_error') for c in pool}
    if codes & {'browser_unavailable', 'browser_missing', 'browser_dependency_missing'}:
        return '商品采集浏览器未能启动或连接，尚无数据可供AI分析；已保留上期结果。'
    if codes & {'amazon_blocked', 'amazon_cooldown'}:
        return '商品来源暂时限制访问，尚无数据可供AI分析；已保留上期结果。'
    return '本期未取得可用商品数据，尚未进行AI分析；已保留上期结果。'


class RecommendationStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    slot TEXT PRIMARY KEY, attempts INTEGER NOT NULL,
                    status TEXT NOT NULL, retry_at TEXT, error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL, candidate TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, slot TEXT NOT NULL,
                    generated_at TEXT NOT NULL, complete INTEGER NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        # 每次操作独立连接，避免 FastAPI 读取线程与生成线程共用 SQLite connection。
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self, now):
        """仅服务启动时调用。上次进程已退出的 running 视为中断，沿用已用重试次数。"""
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='interrupted', retry_at=?, error=?, updated_at=? WHERE status='running'",
                       (now.isoformat(), "上次更新被中断，等待后台恢复。", now.isoformat()))

    def claim(self, slot, now):
        """先原子领取再抓取。同一期成功不重跑，失败最多两次，GET 永远不领取任务。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE slot=?", (slot,)).fetchone()
            if row:
                if row["status"] in {"running", "complete"} or row["attempts"] >= 2:
                    return None
                if row["retry_at"] and datetime.fromisoformat(row["retry_at"]) > now:
                    return None
                attempt, prior = row["attempts"] + 1, json.loads(row["candidate"])
                db.execute("UPDATE jobs SET attempts=?, status='running', retry_at=NULL, updated_at=? WHERE slot=?",
                           (attempt, now.isoformat(), slot))
            else:
                attempt, prior = 1, {}
                db.execute("INSERT INTO jobs(slot,attempts,status,updated_at) VALUES (?,1,'running',?)",
                           (slot, now.isoformat()))
            return attempt, prior

    def checkpoint(self, slot, candidate):
        with self.connection() as db:
            db.execute("UPDATE jobs SET candidate=? WHERE slot=? AND status='running'",
                       (json.dumps(candidate, ensure_ascii=False, allow_nan=False), slot))

    def candidate(self, slot):
        with self.connection() as db:
            row = db.execute("SELECT candidate FROM jobs WHERE slot=?", (slot,)).fetchone()
            return json.loads(row["candidate"]) if row else {}

    def finish(self, slot, candidate, now, error="", interrupted=False):
        payload = snapshot_payload(candidate)
        complete = is_complete(payload) and not interrupted
        if not complete and not error:
            good = sum(bool(c.get("fetch_complete") and c.get("analysis_status") == "success")
                       for c in payload["categories"])
            error = f"本次仅 {good}/10 个类别完成抓取和分析，未发布为完整更新。"
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempts FROM jobs WHERE slot=?", (slot,)).fetchone()
            retry_at = (now + timedelta(minutes=15)).isoformat() if not complete and row[0] < 2 else None
            # 发布与任务完成在同一个事务中。读者看到旧整份或新整份，不会看到写到一半。
            has_complete = db.execute("SELECT 1 FROM snapshots WHERE complete=1 LIMIT 1").fetchone()
            if complete or (payload["products"] and not has_complete and not interrupted):
                db.execute("INSERT INTO snapshots(slot,generated_at,complete,payload) VALUES (?,?,?,?)",
                           (slot, now.isoformat(), int(complete), json.dumps(payload, ensure_ascii=False, allow_nan=False)))
            db.execute("UPDATE jobs SET status=?, retry_at=?, error=?, updated_at=?, candidate=? WHERE slot=?",
                       ("complete" if complete else "interrupted" if interrupted else "failed", retry_at,
                        "" if complete else error, now.isoformat(), json.dumps(candidate, ensure_ascii=False, allow_nan=False), slot))
            cutoff = (now - timedelta(days=30)).isoformat()
            # 保留最近30天；长期故障时额外保留最后一份可展示结果，避免把用户页面清空。
            db.execute("DELETE FROM snapshots WHERE generated_at<? AND id<>(SELECT MAX(id) FROM snapshots)", (cutoff,))
            db.execute("DELETE FROM jobs WHERE slot<?", (cutoff,))
        return complete

    def history(self, now, slot):
        with self.connection() as db:
            rows = db.execute("SELECT slot,generated_at,payload FROM snapshots WHERE generated_at>=? AND slot<>? ORDER BY id DESC",
                              ((now - timedelta(days=7)).isoformat(), slot)).fetchall()
        seen, result = set(), []
        for row in rows:
            if row["slot"] not in seen:
                seen.add(row["slot"])
                result.append({"generated_at": row["generated_at"], **json.loads(row["payload"])})
        return result

    def latest(self, now):
        slot = schedule_slot(now)
        with self.connection() as db:
            # 同一只读事务内取得快照和任务状态，避免恰好发布时两个查询跨版本。
            db.execute("BEGIN")
            snapshot = db.execute("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            job = db.execute("SELECT * FROM jobs WHERE slot=?", (slot.isoformat(),)).fetchone()
        payload = json.loads(snapshot["payload"]) if snapshot else snapshot_payload({})
        status = {"running": "updating", "complete": "ready", "failed": "update_failed",
                  "interrupted": "update_failed"}.get(job["status"] if job else None, "pending")
        return {**payload, "snapshot_id": str(snapshot["id"]) if snapshot else None,
                "generated_at": snapshot["generated_at"] if snapshot else None,
                "snapshot_date": snapshot["slot"][:10] if snapshot else None,
                "scheduled_for": slot.isoformat(), "next_update_at": (slot + timedelta(days=1)).isoformat(),
                "update_status": status, "is_stale": bool(snapshot and snapshot["slot"] != slot.isoformat()),
                "partial": bool(snapshot and not snapshot["complete"]),
                "last_error": (data_failure_message(json.loads(job['candidate'])) or job['error'])
                    if job and job['status'] in {'failed', 'interrupted'} else '',
                "retry_at": job["retry_at"] if job and job["attempts"] < 2 else None}


class DailyRecommendations:
    def __init__(self, path=DEFAULT_DB, *, clock=beijing_now, generator=None):
        self.store = RecommendationStore(path)
        self.clock = clock
        self.generator = generator
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.wake = None
        self.task = None

    def latest(self):
        return self.store.latest(self.clock().astimezone(BEIJING))

    def tick(self):
        """一次检查至多生成一期；时钟和生成器可替换，因此无需等到凌晨做测试。"""
        if self.stop_event.is_set() or not self.lock.acquire(blocking=False):
            return False
        try:
            now = self.clock().astimezone(BEIJING)
            slot = schedule_slot(now).isoformat()
            claimed = self.store.claim(slot, now)
            if claimed is None:
                return False
            attempt, prior = claimed
            started = time.monotonic()
            LOGGER.info("recommendation daily=start slot=%s attempt=%s", slot, attempt)
            # 延迟导入避免存储/调度单元测试依赖模型配置，也避免模块循环导入。
            from backend.tuijian.agent import generate_recommendations, GenerationInterrupted, _classify_model_error
            try:
                candidate = (self.generator or generate_recommendations)(
                    self.store.history(now, slot), prior, now,
                    lambda value: self.store.checkpoint(slot, value), self.stop_event)
                complete = self.store.finish(slot, candidate, self.clock().astimezone(BEIJING))
            except Exception as error:
                interrupted = isinstance(error, GenerationInterrupted)
                code, message, _ = _classify_model_error(error)
                LOGGER.warning("recommendation daily=failed error=%s type=%s", code, type(error).__name__)
                complete = self.store.finish(slot, self.store.candidate(slot), self.clock().astimezone(BEIJING),
                                             "更新被中断，等待后台恢复。" if interrupted else message, interrupted)
            saved = self.store.candidate(slot).get("categories", [])
            good = sum(bool(c.get("fetch_complete") and c.get("analysis_status") == "success") for c in saved)
            LOGGER.info("recommendation daily=finished slot=%s complete=%s categories_ok=%d elapsed=%.1fs",
                        slot, complete, good, time.monotonic() - started)
            return True
        finally:
            self.lock.release()

    async def start(self):
        # Uvicorn 默认只配置自己的日志，业务 INFO 可能被丢掉。只给本模块安装处理器，
        # 不把所有第三方库调成 DEBUG，也不记录带凭据的请求正文或完整异常。
        if not LOGGER.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
        self.store.recover(self.clock().astimezone(BEIJING))
        self.wake = asyncio.Event()
        self.task = asyncio.create_task(self._loop())

    async def _loop(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception as error:
                # 存储故障不能让整个定时协程永久消失，也不应把异常正文中的路径/凭据外泄。
                LOGGER.error("recommendation scheduler_error type=%s", type(error).__name__)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=30)
            except TimeoutError:
                pass

    async def stop(self):
        # 不直接 cancel(to_thread)：取消等待不等于线程停止，可能留下并行的旧任务。
        # 通知节点在下一安全边界退出，等待当前有超时限制的网络调用结束并保存检查点。
        self.stop_event.set()
        if self.wake:
            self.wake.set()
        if self.task:
            await self.task
