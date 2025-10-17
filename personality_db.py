import aiosqlite
import logging
import os

logger = logging.getLogger("heidi.personality_db")

class PersonalityDB:
    def __init__(self):
        self.db_path = "personality.db"
        self.db = None
        logger.info("PersonalityDB initialized")

    async def init(self):
        """Initialize the database and create table if needed"""
        try:
            self.db = await aiosqlite.connect(self.db_path)
            await self._create_table()
            await self._ensure_default_personality()
            logger.info("✅ Personality database initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize personality database: {e}")
            raise

    async def _create_table(self):
        """Create the personality table if it doesn't exist"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS personality (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            summary TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        await self.db.execute(create_table_sql)
        await self.db.commit()
        logger.debug("Personality table created/verified")

    async def _ensure_default_personality(self):
        """Ensure there's a default personality entry"""
        check_sql = "SELECT COUNT(*) FROM personality WHERE id = 1"
        cursor = await self.db.execute(check_sql)
        count = (await cursor.fetchone())[0]
        await cursor.close()

        if count == 0:
            default_personality = "emotionally complex, moody, sarcastic, empathetic, unpredictable, introspective, easily distracted"
            insert_sql = "INSERT INTO personality (id, summary) VALUES (1, ?)"
            await self.db.execute(insert_sql, (default_personality,))
            await self.db.commit()
            logger.info(f"Created default personality: {default_personality}")

    async def get_personality(self):
        """Get the current personality summary"""
        try:
            sql = "SELECT summary FROM personality WHERE id = 1"
            cursor = await self.db.execute(sql)
            result = await cursor.fetchone()
            await cursor.close()
            
            if result:
                personality = result[0]
                logger.debug(f"Retrieved personality: {personality}")
                return personality
            else:
                logger.warning("No personality found, returning default")
                return "curious, playful, friendly"
                
        except Exception as e:
            logger.error(f"Error getting personality: {e}")
            return "curious, playful, friendly"

    async def update_personality(self, new_summary):
        """Update the personality summary"""
        try:
            if len(new_summary) > 500:
                new_summary = new_summary[:500]
                logger.warning(f"Personality summary truncated to 500 characters")

            sql = "UPDATE personality SET summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
            await self.db.execute(sql, (new_summary,))
            await self.db.commit()
            logger.info(f"✅ Personality updated: {new_summary}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update personality: {e}")
            return False

    async def get_personality_history(self, limit=10):
        """Get recent personality changes (if we want to add history tracking later)"""
        try:
            # This would require a different table structure with version history
            # For now, just return current personality
            current = await self.get_personality()
            return [{"summary": current, "timestamp": "current"}]
        except Exception as e:
            logger.error(f"Error getting personality history: {e}")
            return []

    async def close(self):
        """Close the database connection"""
        if self.db:
            await self.db.close()
            logger.info("Personality database connection closed")
