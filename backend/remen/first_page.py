"""热门首屏的共享快照：所有访客读最近成功结果，不再发布写死的商品 JSON。

与每日推荐、知识库分别存储。SQLite 短事务发布整页；爬取期间不占数据库锁。
默认热门/全部品类每30分钟补充一次，其它筛选在正常首次页请求成功时保存。
"""
import asyncio
import json
import logging
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / 'runtime' / 'first-pages.sqlite3'
LOGGER = logging.getLogger(__name__)


class FirstPageStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS first_pages (category TEXT, sub_category TEXT, fetched REAL, payload TEXT, PRIMARY KEY(category, sub_category))')

    def read(self, category='hot', sub_category='all'):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            row = db.execute('SELECT payload FROM first_pages WHERE category=? AND sub_category=?',
                             (category, sub_category)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, payload):
        if (payload.get('page') != 1 or payload.get('pages_scanned') != 1
                or payload.get('partial') or not payload.get('products') or payload.get('period') != 'current'):
            return False
        fetched = datetime.fromisoformat(payload['fetched_at']).timestamp()
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            # 慢请求可能晚返回：只允许更新到更晚的抓取时间，避免旧响应倒灌。
            db.execute('''INSERT INTO first_pages VALUES (?, ?, ?, ?)
                ON CONFLICT(category, sub_category) DO UPDATE SET fetched=excluded.fetched, payload=excluded.payload
                WHERE excluded.fetched >= first_pages.fetched''',
                (payload['category'], payload['sub_category'], fetched,
                 json.dumps(payload, ensure_ascii=False, allow_nan=False)))
        return True


class FirstPageUpdater:
    def __init__(self, store, refresh, clock=time.time):
        self.store, self.refresh, self.clock = store, refresh, clock
        self.retry_after = 0
        self.stop_event = asyncio.Event()

    def tick(self):
        now = self.clock()
        if now < self.retry_after:
            return
        data = self.store.read()
        if data and now - datetime.fromisoformat(data['fetched_at']).timestamp() < 1800:
            return
        # 抓取失败不会清空首屏；五分钟后再检查。共享爬虫仍执行串行、间隔和验证码冷却。
        self.retry_after = now + 300
        try:
            self.store.save(self.refresh())
        except Exception as error:
            LOGGER.warning('first_page_refresh error=%s', getattr(error, 'code', type(error).__name__))

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception as error:
                LOGGER.warning('first_page_storage error=%s', type(error).__name__)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        # 等待有超时上限的当前网络请求收尾，不强制取消线程导致后台继续写数据。
        self.stop_event.set()
