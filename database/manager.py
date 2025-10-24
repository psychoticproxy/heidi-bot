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
            # Don't crash - bot can run without database
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
            
            log.info("✅ Database tables created/verified")
        except Exception as e:
            log.error(f"❌ Table creation failed: {e}")
            # Don't crash - bot can run without proper tables
    
    async def close(self):
        """Close database connection"""
        if self.conn:
            await self.conn.close()
            log.info("✅ Database connection closed")

