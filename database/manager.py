import aiosqlite
import logging
import os
from config import Config

log = logging.getLogger("heidi.database")

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.pool = None  # kept for compatibility with other code that expects .pool

    async def init(self):
        """Initialize SQLite connection and ensure tables exist."""
        try:
            db_path = Config.SQLITE_PATH
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            self.conn = await aiosqlite.connect(db_path)
            # Return rows as mapping so callers can use row['author'] etc.
            self.conn.row_factory = aiosqlite.Row
            self.pool = self.conn  # keep attribute name similar to previous implementation

            await self.create_tables()
            log.info("✅ SQLite database initialized and tables ready")
            return True
        except Exception as e:
            log.error(f"❌ Database connection failed: {e}")
            self.pool = None
            return False

    async def create_tables(self):
        """Create required tables (SQLite compatible)."""
        try:
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS personality (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await self.conn.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    author_id TEXT,
                    content TEXT NOT NULL,
                    is_bot INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await self.conn.commit()
            log.info("✅ Database tables created/verified")
        except Exception as e:
            log.error(f"❌ Table creation failed: {e}")
            raise

    async def execute(self, query, *args):
        """Execute a write (INSERT/UPDATE/DELETE) and commit."""
        cursor = await self.conn.execute(query, args)
        await self.conn.commit()
        return cursor

    async def fetch(self, query, *args):
        """Execute a SELECT and return rows (list of aiosqlite.Row)."""
        cursor = await self.conn.execute(query, args)
        rows = await cursor.fetchall()
        return rows

    async def fetchval(self, query, *args):
        """Fetch a single value (first column of first row)."""
        cursor = await self.conn.execute(query, args)
        row = await cursor.fetchone()
        if row is None:
            return None
        # aiosqlite.Row supports indexing
        return row[0]

    async def get_pool(self):
        """Return the underlying connection (kept for compatibility)."""
        return self.pool

    async def close(self):
        """Close SQLite connection."""
        if self.conn:
            await self.conn.close()
            log.info("✅ Database connection closed")
            self.conn = None
            self.pool = None

    async def test_connection(self):
        """Simple connectivity check."""
        try:
            await self.conn.execute("SELECT 1")
            return True
        except Exception as e:
            log.error(f"Database connection test failed: {e}")
            return False
