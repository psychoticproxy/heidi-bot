import asyncpg
import logging
from config import Config

log = logging.getLogger("heidi.database")

class DatabaseManager:
    def __init__(self):
        self.pool = None
    
    async def init(self):
        """Initialize database connection pool"""
        try:
            self.pool = await asyncpg.create_pool(Config.DB_URL)
            await self._create_tables()
            log.info("✅ Database connection established")
            return True
        except Exception as e:
            log.error(f"❌ Database connection failed: {e}")
            return False
    
    async def _create_tables(self):
        """Create necessary tables"""
        async with self.pool.acquire() as conn:
            # Conversations table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_id TEXT,
                    content TEXT NOT NULL,
                    is_bot BOOLEAN DEFAULT FALSE,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Personality table (simple key-value)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS personality (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            # Insert default personality if not exists
            await conn.execute("""
                INSERT INTO personality (key, value) 
                VALUES ('summary', $1)
                ON CONFLICT (key) DO NOTHING
            """, Config.DEFAULT_PERSONALITY)
    
    async def execute(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    
    async def close(self):
        if self.pool:
            await self.pool.close()
            log.info("Database connection closed")

