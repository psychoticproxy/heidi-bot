import aiosqlite
import asyncio
import logging
from typing import Optional, Tuple

log = logging.getLogger("heidi.queue_manager")

class QueueManager:
    def __init__(self, db_path="queued_messages.db"):
        self.db_path = db_path
        self.queue = asyncio.Queue()
        self.loaded_ids = set()
        self.db: Optional[aiosqlite.Connection] = None
        self.lock: Optional[asyncio.Lock] = None

    async def init(self):
        self.db = await aiosqlite.connect(self.db_path)
        self.lock = asyncio.Lock()
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                channel_id TEXT,
                prompt TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        await self.db.commit()
        await self.load_persisted()

    async def enqueue(self, user_id, channel_id, prompt):
        async with self.lock:
            async with self.db.execute(
                "SELECT id FROM queue WHERE user_id=? AND channel_id=? AND prompt=? AND status='pending'",
                (str(user_id), str(channel_id), prompt)
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                log.info("Duplicate message detected for user=%s channel=%s, skipping enqueue.", user_id, channel_id)
                return
            await self.db.execute(
                "INSERT INTO queue (user_id, channel_id, prompt, status) VALUES (?, ?, ?, 'pending')",
                (str(user_id), str(channel_id), prompt)
            )
            await self.db.commit()
            log.info("Message enqueued for user=%s channel=%s.", user_id, channel_id)
            await self.load_persisted()

    async def load_persisted(self):
        async with self.lock:
            async with self.db.execute(
                "SELECT id, user_id, channel_id, prompt FROM queue WHERE status='pending' ORDER BY id ASC"
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                _id = row[0]
                if _id not in self.loaded_ids:
                    await self.queue.put(row)
                    self.loaded_ids.add(_id)

    async def mark_delivered(self, message_id):
        async with self.lock:
            await self.db.execute(
                "UPDATE queue SET status='delivered' WHERE id=?", (message_id,)
            )
            await self.db.commit()
            self.loaded_ids.discard(message_id)
            log.info("Message id=%s marked as delivered.", message_id)

    async def get_next(self) -> Optional[Tuple]:
        if self.queue.empty():
            await self.load_persisted()
        try:
            msg = await self.queue.get()
            return msg
        except Exception:
            return None

    async def task_done(self, message_id):
        self.queue.task_done()

    async def clear(self):
        async with self.lock:
            await self.db.execute("DELETE FROM queue WHERE status='pending'")
            await self.db.commit()
        self.loaded_ids.clear()
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        log.info("Queue cleared.")

    async def pending_count(self):
        async with self.lock:
            async with self.db.execute(
                "SELECT COUNT(*) FROM queue WHERE status='pending'"
            ) as cursor:
                row = await cursor.fetchone()
            db_count = row[0] if row else 0
        mem_count = self.queue.qsize()
        return mem_count + db_count, mem_count, db_count
