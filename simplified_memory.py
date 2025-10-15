import asyncio
from collections import deque
import json
import aiosqlite

class ConversationMemory:
    def __init__(self, max_context=30, db_path="heidi_memory.db"):
        self.max_context = max_context
        self.db_path = db_path
        self.conversations = {}  # channel_id -> deque of messages
        self.db = None
        self.user_profiles = {} # Add user awareness

    async def init(self):
        """Initialize database connection"""
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                channel_id TEXT,
                author TEXT,
                author_id TEXT,
                content TEXT,
                is_bot BOOLEAN,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add user profiles table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                interaction_count INTEGER DEFAULT 0,
                last_interaction DATETIME,
                preferences TEXT
            )
        """)
        await self.db.commit()

    async def add_message(self, channel_id, author, content, is_bot=False, author_id=None):
        """Add message to memory"""
        if channel_id not in self.conversations:
            self.conversations[channel_id] = deque(maxlen=self.max_context)
        
        message_data = {
            'author': author,
            'content': content,
            'is_bot': is_bot
        }
        
        self.conversations[channel_id].append(message_data)
        
        # Update user profile
        if author_id and not is_bot:
            await self.update_user_profile(author_id, author)

        # Save to database
        if self.db:
            await self.db.execute(
                "INSERT INTO conversations (channel_id, author, author_id, content, is_bot) VALUES (?, ?, ?, ?, ?)",
                (str(channel_id), author, str(author_id) if author_id else None, content, is_bot)
            )
            await self.db.commit()
            
    async def update_user_profile(self, user_id, username):
        """Update or create user profile"""
        await self.db.execute("""
            INSERT OR REPLACE INTO user_profiles (user_id, username, interaction_count, last_interaction)
            VALUES (?, ?, COALESCE((SELECT interaction_count + 1 FROM user_profiles WHERE user_id = ?), 1), CURRENT_TIMESTAMP)
        """, (user_id, username, user_id))
        await self.db.commit()

    async def get_user_interaction_count(self, user_id):
        """Get how many times a user has interacted with the bot"""
        async with self.db.execute(
            "SELECT interaction_count FROM user_profiles WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

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
        
    async def cleanup_old_messages(self, days_old=7):
        """Clean up old messages to prevent database bloat"""
        if self.db:
            await self.db.execute(
                "DELETE FROM conversations WHERE timestamp < datetime('now', ?)",
                (f'-{days_old} days',)
            )
            await self.db.commit()
