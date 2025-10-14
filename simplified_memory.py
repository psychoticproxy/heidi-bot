import asyncio
from collections import deque
import json
import aiosqlite

class ConversationMemory:
    def __init__(self, max_context=50, db_path="heidi_memory.db"):
        self.max_context = max_context
        self.db_path = db_path
        self.conversations = {}  # channel_id -> deque of messages
        self.db = None

    async def init(self):
        """Initialize database connection"""
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                channel_id TEXT,
                author TEXT,
                content TEXT,
                is_bot BOOLEAN,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.db.commit()

    async def add_message(self, channel_id, author, content, is_bot=False):
        """Add message to memory"""
        if channel_id not in self.conversations:
            self.conversations[channel_id] = deque(maxlen=self.max_context)
        
        message_data = {
            'author': author,
            'content': content,
            'is_bot': is_bot
        }
        
        self.conversations[channel_id].append(message_data)
        
        # Also save to database for persistence
        if self.db:
            await self.db.execute(
                "INSERT INTO conversations (channel_id, author, content, is_bot) VALUES (?, ?, ?, ?)",
                (str(channel_id), author, content, is_bot)
            )
            await self.db.commit()

    async def get_recent_context(self, channel_id, limit=10):
        """Get recent messages from a channel"""
        if channel_id in self.conversations:
            return list(self.conversations[channel_id])[-limit:]
        return []

    async def load_channel_history(self, channel_id, limit=20):
        """Load recent history from database"""
        if self.db:
            async with self.db.execute(
                "SELECT author, content, is_bot FROM conversations WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?",
                (str(channel_id), limit)
            ) as cursor:
                rows = await cursor.fetchall()
            
            # Convert to list and reverse for chronological order
            messages = [
                {'author': row[0], 'content': row[1], 'is_bot': bool(row[2])}
                for row in rows[::-1]
            ]
            
            if channel_id not in self.conversations:
                self.conversations[channel_id] = deque(maxlen=self.max_context)
            
            self.conversations[channel_id].extend(messages)
            return messages
        return []

