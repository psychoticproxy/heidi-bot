import random
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("heidi.engagement")

class EngagementEngine:
    def __init__(self, bot, memory):
        self.bot = bot
        self.memory = memory
        self.last_activity = {}
        logger.info("EngagementEngine initialized")
        
    async def should_engage(self, channel_id):
        # Check if channel has been active recently (within last 2 hours)
        last_active = self.last_activity.get(channel_id, 0)
        current_time = asyncio.get_event_loop().time()
        time_since_active = current_time - last_active
        should_engage = time_since_active < 7200  # 2 hours in seconds
        
        logger.debug(f"Channel {channel_id} - Time since last activity: {time_since_active:.1f}s, Should engage: {should_engage}")
        return should_engage
        
    def update_activity(self, channel_id):
        """Update last activity time for a channel"""
        self.last_activity[channel_id] = asyncio.get_event_loop().time()
        logger.debug(f"Updated activity for channel {channel_id}")
        
    async def spontaneous_message(self, channel):
        logger.debug(f"Checking spontaneous message for channel {channel.id} ({channel.name})")
        
        if not await self.should_engage(channel.id):
            logger.debug(f"Channel {channel.id} not active enough for spontaneous message")
            return None
            
        prompts = [
            "What's everyone talking about?",
            "I was just thinking about something...",
            "Anyone else find this interesting?",
            "What do you all think about this?",
            "I've been wondering about something..."
        ]
        
        selected_prompt = random.choice(prompts)
        logger.info(f"Generated spontaneous message for channel {channel.id}: '{selected_prompt}'")
        return selected_prompt
