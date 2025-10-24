import asyncpg
import logging
from config import Config

log = logging.getLogger("heidi.database")

class DatabaseManager:
    def __init__(self):
        self.pool = None
    
    async def init(self):
        """Initialize database connection pool and tables"""
        try:
            # Create connection pool
            self.pool = await asyncpg.create_pool(
                host=Config.DATABASE_HOST,
                user=Config.DATABASE_USER,
                password=Config.DATABASE_PASSWORD,
                database=Config.DATABASE_NAME,
                port=Config.DATABASE_PORT,
                min_size=1,
                max_size=4,
                command_timeout=30
            )
            
            await self.create_tables()
            log.info("✅ Database pool initialized and tables ready")
            return True
        except Exception as e:
            log.error(f"❌ Database connection failed: {e}")
            self.pool = None
            return False
    
    async def create_tables(self):
        """Create necessary tables if they don't exist"""
        async with self.pool.acquire() as conn:
            try:
                # Personality table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS personality (
                        id SERIAL PRIMARY KEY,
                        key TEXT UNIQUE NOT NULL,
                        value TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # Memory table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS memory (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # Conversations table (for message history)
                await conn.execute('''
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
                raise

    async def execute(self, query, *args):
        """Execute a query with connection resilience"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query, *args):
        """Fetch rows with retries"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchval(self, query, *args):
        """Fetch a single value safely"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def get_pool(self):
        """Get the connection pool instance"""
        return self.pool

    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            log.info("✅ Database pool closed")

    async def test_connection(self):
        """Test database connectivity"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as e:
            log.error(f"Database connection test failed: {e}")
            return False
