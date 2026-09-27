"""商品发现的每日共享数据集。

只有后台更新器调用收费数据源；HTTP GET 只读 SQLite，滚动分页不触发采集。
每个品类只保留最近一份成功数据，新数据完整写入后原子替换旧数据。
当天已成功取得的源页面也落盘，任务重试和进程重启都可复用，避免重复收费。
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import sqlite3
import threading
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

BEIJING = timezone(timedelta(hours=8))
DEFAULT_PATH = Path(__file__).parent / "runtime" / "shared-products.sqlite3"
LOGGER = logging.getLogger(__name__)
_PAGE_LOCK = threading.RLock()


def now_beijing():
    return datetime.now(BEIJING)


def daily_slot(now, hour=5):
    local = now.astimezone(BEIJING)
    slot = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return slot if local >= slot else slot - timedelta(days=1)


def valid_product(item):
    price = item.get("price")
    return (isinstance(price, (int, float)) and not isinstance(price, bool)
            and math.isfinite(price) and price > 0 and bool(item.get("currency"))
            and not item.get("sponsored") and bool(item.get("asin")) and bool(item.get("title")))


class CatalogStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_pages (
                    cache_key TEXT PRIMARY KEY, slot TEXT NOT NULL, fetched_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalog (
                    sub_category TEXT PRIMARY KEY, slot TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                    fetched_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalog_jobs (
                    sub_category TEXT NOT NULL, slot TEXT NOT NULL, attempts INTEGER NOT NULL,
                    status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', retry_at TEXT,
                    lease_until TEXT NOT NULL, claim_id TEXT NOT NULL,
                    PRIMARY KEY (sub_category, slot)
                );
            """)

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def cached_page(self, cache_key, slot, fetch):
        """同进程的热门/推荐共用读后写锁；网络期间不持有 SQLite 写事务。

        部署保持一个 API worker；跨主机应换集中任务队列，不能靠此进程锁协调。
        fetch 返回 JSON 可序列化内容，异常绝不缓存，也不记录包含令牌的异常正文。
        """
        with _PAGE_LOCK:
            with self.connection() as db:
                row = db.execute("SELECT * FROM source_pages WHERE cache_key=? AND slot=?",
                                 (cache_key, slot)).fetchone()
            if row:
                return json.loads(row["payload"]), row["fetched_at"], True
            data = fetch()
            fetched_at = now_beijing().isoformat()
            encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
            with self.connection() as db:
                db.execute("DELETE FROM source_pages WHERE slot<?", (slot,))
                db.execute("INSERT OR REPLACE INTO source_pages VALUES (?,?,?,?)",
                           (cache_key, slot, fetched_at, encoded))
            return data, fetched_at, False

    def claim(self, sub_category, slot, now):
        """数据库领取保证同一天只成功更新一次；失败最多两次，重试间隔十五分钟。"""
        at = now.isoformat()
        claim_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM catalog_jobs WHERE sub_category=? AND slot=?",
                             (sub_category, slot)).fetchone()
            if row and row["status"] == "running" and row["lease_until"] <= at and row["attempts"] >= 2:
                db.execute("UPDATE catalog_jobs SET status='failed',error='update_interrupted',retry_at=NULL "
                           "WHERE sub_category=? AND slot=?", (sub_category, slot))
                return None
            if row and (row["status"] == "complete" or row["attempts"] >= 2
                        or (row["status"] == "running" and row["lease_until"] > at)
                        or (row["retry_at"] and row["retry_at"] > at)):
                return None
            attempts = row["attempts"] + 1 if row else 1
            db.execute("INSERT OR REPLACE INTO catalog_jobs VALUES (?,?,?,'running','',NULL,?,?)",
                       (sub_category, slot, attempts, (now + timedelta(minutes=30)).isoformat(), claim_id))
            db.execute("DELETE FROM catalog_jobs WHERE slot<?", (slot,))
        return claim_id

    def publish(self, sub_category, slot, claim_id, payload):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT claim_id,status FROM catalog_jobs WHERE sub_category=? AND slot=?",
                             (sub_category, slot)).fetchone()
            if not row or row["claim_id"] != claim_id or row["status"] != "running":
                return False
            # 更新这一个主键即删除其旧版商品集合；不会把不同日期的商品越积越多。
            db.execute("INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?)",
                       (sub_category, slot, uuid.uuid4().hex, payload["fetched_at"],
                        json.dumps(payload, ensure_ascii=False, allow_nan=False)))
            db.execute("UPDATE catalog_jobs SET status='complete',error='',retry_at=NULL WHERE sub_category=? AND slot=?",
                       (sub_category, slot))
        return True

    def fail(self, sub_category, slot, claim_id, now, code):
        with self.connection() as db:
            # 仅保存程序定义的错误码，不保存供应商响应或带 token 的 URL。
            db.execute("UPDATE catalog_jobs SET status='failed',error=?,retry_at=? "
                       "WHERE sub_category=? AND slot=? AND claim_id=?",
                       (code, (now + timedelta(minutes=15)).isoformat(), sub_category, slot, claim_id))

    def read(self, sub_category, slot):
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM catalog WHERE sub_category=?", (sub_category,)).fetchone()
            job = db.execute("SELECT * FROM catalog_jobs WHERE sub_category=? AND slot=?", (sub_category, slot)).fetchone()
        return (dict(row) if row else None), (dict(job) if job else None)


class DailyCatalog:
    def __init__(self, crawler, path=DEFAULT_PATH, *, pages=3, hour=5, clock=now_beijing, categories=None):
        from .pachon import CATEGORIES
        if not 1 <= pages <= 10 or not 0 <= hour <= 23:
            raise ValueError("热门采集页数必须为1到10，更新时间为0到23小时")
        self.crawler, self.store, self.clock = crawler, CatalogStore(path), clock
        self.pages, self.hour = pages, hour
        self.categories = categories if categories is not None else CATEGORIES
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self.task = None

    def _collect(self, keyword):
        from .pachon import CrawlError
        products, records, seen_raw = {}, [], set()
        no_progress = 0
        stop_reason = "page_limit"
        for page in range(1, self.pages + 1):
            if self.stop_event.is_set():
                raise CrawlError("update_interrupted", "商品更新中断，已保留上期结果。", 503)
            items, fetched, cached = self.crawler.fetch(keyword, page, wait_for_interval=True)
            raw = {item.asin for item in items}
            no_progress = no_progress + 1 if not (raw - seen_raw) else 0
            seen_raw.update(raw)
            before = len(products)
            for item in items:
                data = item.model_dump(mode="json")
                if valid_product(data):
                    products.setdefault(item.asin, data)
            records.append(dict(page=page, count=len(items), added_count=len(products)-before,
                                from_cache=cached, fetched_at=fetched))
            if not items or no_progress >= 2:
                stop_reason = "empty_page" if not items else "no_progress"
                break
        # 所有页都失败/没有有效价格时保留上一份，不能用空数组清空正常数据。
        if not products:
            raise CrawlError("no_valid_products", "本期没有取得有效价格商品，已保留上期结果。", 503)
        return dict(products=list(products.values()), page_results=records, stop_reason=stop_reason,
                    fetched_at=min(record["fetched_at"] for record in records))

    def tick(self):
        if self.stop_event.is_set() or not self._lock.acquire(blocking=False):
            return
        try:
            for sub_category, (_, keyword) in self.categories.items():
                if self.stop_event.is_set():
                    break
                now = self.clock().astimezone(BEIJING)
                slot = daily_slot(now, self.hour).isoformat()
                claim = self.store.claim(sub_category, slot, now)
                if not claim:
                    continue
                try:
                    data = self._collect(keyword)
                    self.store.publish(sub_category, slot, claim, data)
                except Exception as error:
                    from .pachon import CrawlError
                    code = error.code if isinstance(error, CrawlError) else "catalog_update_failed"
                    self.store.fail(sub_category, slot, claim, self.clock(), code)
                    LOGGER.warning("catalog_update category=%s error=%s", sub_category, code)
                    # 配置/账号错误不会因换品类好转，本轮不继续消耗请求。
                    if code in {"scrape_do_not_configured", "scrape_do_auth_or_credits", "scrape_do_rate_limited"}:
                        break
        finally:
            self._lock.release()

    def envelope(self, category="hot", sub_category="all"):
        from .pachon import CATEGORIES
        now = self.clock().astimezone(BEIJING)
        slot = daily_slot(now, self.hour)
        row, job = self.store.read(sub_category, slot.isoformat())
        status = {"running": "updating", "complete": "ready", "failed": "update_failed"}.get(
            job["status"] if job else None, "pending")
        last_error = "本期商品更新暂未成功，已保留最近一次数据。" if status == "update_failed" else ""
        result = dict(snapshot=None, update_status=status, last_error=last_error,
                      next_update_at=(slot + timedelta(days=1)).isoformat(),
                      snapshot_date=row["slot"][:10] if row else None)
        if not row:
            return result
        stored = json.loads(row["payload"])
        products = [p for p in stored["products"] if valid_product(p)]
        if category == "niche":
            products = [p for p in products if p.get("review_count") is not None and p["review_count"] <= 100]
            products.sort(key=lambda p: p["review_count"])
        else:
            products.sort(key=lambda p: (p.get("sales_count_min") is not None, p.get("sales_count_min") or 0,
                                         p.get("review_count") or 0), reverse=True)
        name, keyword = CATEGORIES[sub_category]
        stale = row["slot"] != slot.isoformat()
        warnings = ["来自 Scrape.do 采集的 Amazon 公开搜索数据，每日共享更新，不代表全站榜单。",
                    "仅包含本轮采样取得的有效价格商品；近月购买提示不等于精确销量。"]
        if stale:
            warnings.append("当前显示上一次成功保存的数据，请以快照时间和商品页价格为准。")
        result["snapshot"] = dict(
            products=products, category=category, sub_category=sub_category, sub_category_name=name,
            keyword=keyword, period="current", period_applied=False, data_period="daily_snapshot",
            page=1, limit=len(products), count=len(products), fetched_at=row["fetched_at"],
            from_cache=True, provider=self.crawler.provider, source="Amazon.com",
            source_url="https://www.amazon.com/s?" + urlencode({"k": keyword, "language": "en_US", "currency": "USD"}),
            selection_rule="低评论候选，评论数不超过100。" if category == "niche" else "按公开近月购买提示与评论热度排序。",
            warnings=warnings, max_pages=self.pages, pages_scanned=len(stored["page_results"]),
            page_results=stored["page_results"], candidate_count=len(products), target_reached=True,
            partial=False, stop_reason=stored["stop_reason"], error_code=None, next_page=None,
            snapshot_id=row["snapshot_id"], snapshot_date=row["slot"][:10], is_stale=stale,
            next_update_at=result["next_update_at"], pagination_type="snapshot", dataset_count=len(products))
        return result

    def page(self, category, sub_category, page, limit):
        from .pachon import CrawlError
        envelope = self.envelope(category, sub_category)
        if envelope["snapshot"] is None:
            raise CrawlError("snapshot_not_ready", "共享商品数据正在准备，请稍后刷新展示。", 503)
        payload = copy.deepcopy(envelope["snapshot"])
        start = (page - 1) * limit
        payload["products"] = payload["products"][start:start + limit]
        payload.update(page=page, limit=limit, count=len(payload["products"]),
                       next_page=page + 1 if start + limit < payload["dataset_count"] else None)
        return payload

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception as error:
                LOGGER.warning("catalog_storage error=%s", type(error).__name__)
            for _ in range(60):
                if self.stop_event.is_set():
                    return
                await asyncio.sleep(1)

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await self.task
