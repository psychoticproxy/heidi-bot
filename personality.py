import random
import json
import aiosqlite
import asyncio
from datetime import datetime

class AdaptivePersonality:
    def __init__(self, db_path="personality.db"):
        self.base_traits = {
            'curiosity': 0.7,
            'playfulness': 0.6, 
            'empathy': 0.5,
            'sarcasm': 0.3,
            'enthusiasm': 0.8
        }
        self.engagement_patterns = {}
        self.interaction_history = []
        self.db_path = db_path
        self.db = None

    async def init(self):
        """Initialize database for personality persistence"""
        self.db = await aiosqlite.connect(self.db_path)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS personality_traits (
                trait TEXT PRIMARY KEY,
                value REAL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS engagement_patterns (
                pattern TEXT PRIMARY KEY,
                strength REAL,
                last_used DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.db.commit()
        await self.load_persisted_data()

    async def load_persisted_data(self):
        """Load personality data from database"""
        # Load traits
        async with self.db.execute("SELECT trait, value FROM personality_traits") as cursor:
            rows = await cursor.fetchall()
            for trait, value in rows:
                if trait in self.base_traits:
                    self.base_traits[trait] = value

        # Load engagement patterns
        async with self.db.execute("SELECT pattern, strength FROM engagement_patterns") as cursor:
            rows = await cursor.fetchall()
            for pattern, strength in rows:
                self.engagement_patterns[pattern] = strength

    async def save_traits(self):
        """Save current traits to database"""
        for trait, value in self.base_traits.items():
            await self.db.execute(
                "INSERT OR REPLACE INTO personality_traits (trait, value) VALUES (?, ?)",
                (trait, value)
            )
        await self.db.commit()

    async def save_patterns(self):
        """Save engagement patterns to database"""
        for pattern, strength in self.engagement_patterns.items():
            await self.db.execute(
                "INSERT OR REPLACE INTO engagement_patterns (pattern, strength) VALUES (?, ?)",
                (pattern, strength)
            )
        await self.db.commit()

    def adapt_from_interaction(self, message, response_success=True, engagement_level=1.0):
        """Adapt personality based on interaction success and engagement"""
        words = message.lower().split()
        
        for word in words:
            if len(word) > 3:  # Only track meaningful words
                if word in self.engagement_patterns:
                    if response_success:
                        # Positive reinforcement
                        self.engagement_patterns[word] = min(
                            1.0, self.engagement_patterns[word] + (0.05 * engagement_level)
                        )
                    else:
                        # Negative reinforcement
                        self.engagement_patterns[word] = max(
                            0.0, self.engagement_patterns[word] - 0.1
                        )
                else:
                    self.engagement_patterns[word] = 0.5

        # Adjust base traits based on engagement
        if response_success and engagement_level > 0.7:
            self.base_traits['curiosity'] = min(1.0, self.base_traits['curiosity'] + 0.02)
            self.base_traits['enthusiasm'] = min(1.0, self.base_traits['enthusiasm'] + 0.02)

        # Save changes periodically (every 10 interactions)
        if len(self.interaction_history) % 10 == 0:
            asyncio.create_task(self.save_traits())
            asyncio.create_task(self.save_patterns())

    def get_engagement_boost(self, message):
        """Calculate engagement probability boost based on learned patterns"""
        boost = 1.0
        for word in message.lower().split():
            if word in self.engagement_patterns:
                # Convert 0-1 strength to -0.5 to +0.5 boost
                pattern_strength = (self.engagement_patterns[word] - 0.5) * 1.0
                boost += pattern_strength
        return max(0.1, min(boost, 3.0))

    def get_tone_modifiers(self):
        """Get current personality tone for response generation"""
        return self.base_traits.copy()

    def get_temperature_setting(self):
        """Get temperature setting based on personality traits"""
        base_temp = 0.7
        # Higher playfulness and enthusiasm = more creative/variable responses
        creativity_boost = (self.base_traits['playfulness'] + self.base_traits['enthusiasm']) * 0.1
        return min(0.9, base_temp + creativity_boost)

