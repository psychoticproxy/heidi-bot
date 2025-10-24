import asyncpg
import logging
from config import Config

log = logging.getLogger("heidi.database")

class DatabaseManager:
    def __init__(self):
        self.conn = None
    
    async def init(self):
        """Initialize database connection and tables"""
        try:
            self.conn = await asyncpg.connect(
                host=Config.DATABASE_HOST,
                user=Config.DATABASE_USER,
                password=Config.DATABASE_PASSWORD,
                database=Config.DATABASE_NAME,
                port=Config.DATABASE_PORT
            )
            await self.create_tables()
            log.info("✅ Database connected and tables ready")
            return True
        except Exception as e:
            log.error(f"❌ Database connection failed: {e}")
            self.conn = None
            return False
    
    async def create_tables(self):
        """Create necessary tables if they don't exist"""
        if not self.conn:
            return
            
        try:
            # Personality table
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS personality (
                    id SERIAL PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Memory table  
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Conversations table (for message history)
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_id TEXT,
                    content TEXT NOT NULL,
                    is_bot BOOLEAN DEFAULT FALSE,
                    timestamp TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            log.info("✅ Database tables created/verified")
        except Exception as e:
            log.error(f"❌ Table creation failed: {e}")
    
    async def execute(self, query, *args):
        """Execute a query"""
        if not self.conn:
            raise Exception("Database not connected")
        return await self.conn.execute(query, *args)
    
    async def fetch(self, query, *args):
        """Fetch rows from a query"""
        if not self.conn:
            raise Exception("Database not connected")
        return await self.conn.fetch(query, *args)
    
    async def fetchval(self, query, *args):
        """Fetch a single value from a query"""
        if not self.conn:
            raise Exception("Database not connected")
        return await self.conn.fetchval(query, *args)
    
    async def close(self):
        """Close database connection"""
        if self.conn:
            await self.conn.close()
            log.info("✅ Database connection closed")

    async def init(self):
        try:
            # Add pool configuration
            self.pool = await asyncpg.create_pool(
                host=Config.DATABASE_HOST,
                user=Config.DATABASE_USER,
                password=Config.DATABASE_PASSWORD,
                database=Config.DATABASE_NAME,
                port=Config.DATABASE_PORT,
                min_size=1,
                max_size=4
            )
            await self.create_tables()
            log.info("✅ Database connected and tables ready")
            return True
        except Exception as e:
            log.error(f"❌ Database connection failed: {e}")
            return False


