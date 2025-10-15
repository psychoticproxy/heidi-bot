import random
import json
import aiosqlite
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("heidi.personality")

class AdaptivePersonality:
    def __init__(self, db_path="personality.db"):
        # Expanded base traits with new psychological dimensions
        self.base_traits = {
            'curiosity': 0.5,
            'playfulness': 0.5, 
            'empathy': 0.5,
            'sarcasm': 0.5,
            'enthusiasm': 0.5,
            'friendliness': 0.5,  # New: warmth and welcoming behavior
            'humor': 0.5,         # New: tendency to use humor
            'directness': 0.5     # New: straightforwardness vs. evasiveness
        }
        self.engagement_patterns = {}
        self.interaction_history = []
        self.db_path = db_path
        self.db = None
        logger.info("AdaptivePersonality initialized")

    async def init(self):
        """Initialize database for personality persistence"""
        logger.info(f"Initializing personality database: {self.db_path}")
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
        logger.info("Personality database initialized successfully")

    async def load_persisted_data(self):
        """Load personality data from database"""
        logger.debug("Loading persisted personality data")
        # Load traits
        loaded_traits = 0
        async with self.db.execute("SELECT trait, value FROM personality_traits") as cursor:
            rows = await cursor.fetchall()
            for trait, value in rows:
                if trait in self.base_traits:
                    self.base_traits[trait] = value
                    loaded_traits += 1

        # Load engagement patterns
        loaded_patterns = 0
        async with self.db.execute("SELECT pattern, strength FROM engagement_patterns") as cursor:
            rows = await cursor.fetchall()
            for pattern, strength in rows:
                self.engagement_patterns[pattern] = strength
                loaded_patterns += 1

        logger.info(f"Loaded {loaded_traits} traits and {loaded_patterns} engagement patterns from database")

    async def save_traits(self):
        """Save current traits to database"""
        logger.debug("Saving personality traits to database")
        for trait, value in self.base_traits.items():
            await self.db.execute(
                "INSERT OR REPLACE INTO personality_traits (trait, value) VALUES (?, ?)",
                (trait, value)
            )
        await self.db.commit()
        logger.debug(f"Saved {len(self.base_traits)} traits to database")

    async def save_patterns(self):
        """Save engagement patterns to database"""
        logger.debug("Saving engagement patterns to database")
        for pattern, strength in self.engagement_patterns.items():
            await self.db.execute(
                "INSERT OR REPLACE INTO engagement_patterns (pattern, strength) VALUES (?, ?)",
                (pattern, strength)
            )
        await self.db.commit()
        logger.debug(f"Saved {len(self.engagement_patterns)} engagement patterns to database")

    def adapt_from_interaction(self, message, response_success=True, engagement_level=1.0):
        """Adapt personality based on interaction success, engagement, and content"""
        logger.debug(f"Adapting personality from interaction: '{message[:50]}...', success: {response_success}, engagement: {engagement_level}")
        
        words = message.lower().split()
        updated_patterns = 0
        
        # Track engagement patterns for specific words
        for word in words:
            if len(word) > 3:  # Only track meaningful words
                if word in self.engagement_patterns:
                    if response_success:
                        # Positive reinforcement
                        self.engagement_patterns[word] = min(
                            1.0, self.engagement_patterns[word] + (0.05 * engagement_level)
                        )
                        logger.debug(f"Positive reinforcement for word '{word}': {self.engagement_patterns[word]:.3f}")
                    else:
                        # Negative reinforcement
                        self.engagement_patterns[word] = max(
                            0.0, self.engagement_patterns[word] - 0.1
                        )
                        logger.debug(f"Negative reinforcement for word '{word}': {self.engagement_patterns[word]:.3f}")
                    updated_patterns += 1
                else:
                    self.engagement_patterns[word] = 0.5
                    logger.debug(f"Added new word pattern '{word}' with initial strength 0.5")
                    updated_patterns += 1

        # Adjust base traits based on engagement and content
        if response_success:
            # Boost positive traits on successful interactions
            old_curiosity = self.base_traits['curiosity']
            old_enthusiasm = self.base_traits['enthusiasm']
            old_friendliness = self.base_traits['friendliness']
            
            self.base_traits['curiosity'] = min(1.0, self.base_traits['curiosity'] + 0.02 * engagement_level)
            self.base_traits['enthusiasm'] = min(1.0, self.base_traits['enthusiasm'] + 0.02 * engagement_level)
            self.base_traits['friendliness'] = min(1.0, self.base_traits['friendliness'] + 0.02 * engagement_level)
            
            # Humor adapts if the message contains humorous words
            humorous_words = {'lol', 'haha', 'funny', 'joke', 'lmao'}
            if any(word in humorous_words for word in words):
                old_humor = self.base_traits['humor']
                self.base_traits['humor'] = min(1.0, self.base_traits['humor'] + 0.05 * engagement_level)
                logger.debug(f"Humor increased from {old_humor:.3f} to {self.base_traits['humor']:.3f}")
            
            # Directness adapts if the message is straightforward
            direct_words = {'yes', 'no', 'direct', 'clear'}
            if any(word in direct_words for word in words):
                old_directness = self.base_traits['directness']
                self.base_traits['directness'] = min(1.0, self.base_traits['directness'] + 0.03 * engagement_level)
                logger.debug(f"Directness increased from {old_directness:.3f} to {self.base_traits['directness']:.3f}")
                
            logger.debug(f"Positive adaptation: curiosity({old_curiosity:.3f}→{self.base_traits['curiosity']:.3f}), "
                        f"enthusiasm({old_enthusiasm:.3f}→{self.base_traits['enthusiasm']:.3f}), "
                        f"friendliness({old_friendliness:.3f}→{self.base_traits['friendliness']:.3f})")
        else:
            # Slight decay on failure to encourage adaptation
            old_friendliness = self.base_traits['friendliness']
            old_humor = self.base_traits['humor']
            
            self.base_traits['friendliness'] = max(0.0, self.base_traits['friendliness'] - 0.05)
            self.base_traits['humor'] = max(0.0, self.base_traits['humor'] - 0.05)
            
            logger.debug(f"Negative adaptation: friendliness({old_friendliness:.3f}→{self.base_traits['friendliness']:.3f}), "
                        f"humor({old_humor:.3f}→{self.base_traits['humor']:.3f})")

        # Save changes periodically (every 10 interactions)
        if len(self.interaction_history) % 10 == 0:
            logger.info(f"Periodic save triggered (interaction #{len(self.interaction_history)})")
            asyncio.create_task(self.save_traits())
            asyncio.create_task(self.save_patterns())

        logger.info(f"Personality adaptation complete: updated {updated_patterns} word patterns")

    def get_engagement_boost(self, message):
        """Calculate engagement probability boost based on learned patterns"""
        boost = 1.0
        for word in message.lower().split():
            if word in self.engagement_patterns:
                # Convert 0-1 strength to -0.5 to +0.5 boost
                pattern_strength = (self.engagement_patterns[word] - 0.5) * 1.0
                boost += pattern_strength
                logger.debug(f"Word '{word}' contributes {pattern_strength:.3f} to engagement boost")
        
        final_boost = max(0.1, min(boost, 3.0))
        logger.debug(f"Final engagement boost: {final_boost:.3f}")
        return final_boost

    def get_tone_modifiers(self):
        """Get current personality tone for response generation"""
        logger.debug("Retrieving current tone modifiers")
        return self.base_traits.copy()

    def get_temperature_setting(self):
        """Get temperature setting based on personality traits"""
        base_temp = 0.7
        # Higher playfulness and enthusiasm = more creative/variable responses
        creativity_boost = (self.base_traits['playfulness'] + self.base_traits['enthusiasm']) * 0.1
        # Humor adds a bit more variability
        humor_boost = self.base_traits['humor'] * 0.05
        final_temp = min(0.9, base_temp + creativity_boost + humor_boost)
        
        logger.debug(f"Temperature setting: base={base_temp}, creativity_boost={creativity_boost:.3f}, "
                    f"humor_boost={humor_boost:.3f}, final={final_temp:.3f}")
        return final_temp

    def get_personality_summary(self):
        """Generate a simple text summary of current personality for use in prompts"""
        # Map trait values to descriptive words
        traits_desc = []
        for trait, value in self.base_traits.items():
            if value > 0.7:
                traits_desc.append(f"high {trait}")
            elif value < 0.3:
                traits_desc.append(f"low {trait}")
            else:
                traits_desc.append(f"moderate {trait}")
        
        summary = ", ".join(traits_desc)
        logger.debug(f"Personality summary: {summary}")
        return summary
