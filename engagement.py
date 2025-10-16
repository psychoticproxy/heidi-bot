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
        last_active = self.last_activity.get(channel_id, 0)
        current_time = asyncio.get_event_loop().time()
        time_since_active = current_time - last_active
        should_engage = time_since_active < 7200  # 2 hours in seconds
        logger.debug(f"Channel {channel_id} - Time since last activity: {time_since_active:.1f}s, Should engage: {should_engage}")
        return should_engage
        
    def update_activity(self, channel_id):
        self.last_activity[channel_id] = asyncio.get_event_loop().time()
        logger.debug(f"Updated activity for channel {channel_id}")
        
    async def spontaneous_message(self, channel):
        logger.debug(f"Checking spontaneous message for channel {channel.id} ({channel.name})")
        if not await self.should_engage(channel.id):
            logger.debug(f"Channel {channel.id} not active enough for spontaneous message")
            return None

        # Get recent context
        context = await self.memory.get_recent_context(channel.id, limit=6)
        # Build a system/user prompt to ask OpenRouter for a spontaneous message
        system_prompt = self.bot.build_system_prompt(context, is_unsolicited=True)
        user_prompt = "Generate a brief, spontaneous message to join this Discord conversation naturally. Be casual and relevant, as if Heidi is chiming in."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        temperature = self.bot.personality.get_temperature_setting()
        logger.info(f"Requesting spontaneous message from OpenRouter for channel {channel.id}")
        response = await self.bot.call_openrouter(messages, temperature=temperature)
        if response and response.strip():
            logger.info(f"Generated spontaneous message for channel {channel.id}: '{response}'")
            return response.strip()
        else:
            logger.debug(f"No response from OpenRouter for spontaneous message in channel {channel.id}")
            return None
