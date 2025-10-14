import random
import asyncio
from datetime import datetime, timedelta

class EngagementEngine:
    def __init__(self, bot, memory):
        self.bot = bot
        self.memory = memory
        self.last_activity = {}
        
    async def should_engage(self, channel_id):
        # Check if channel has been active recently (within last 2 hours)
        last_active = self.last_activity.get(channel_id, 0)
        current_time = asyncio.get_event_loop().time()
        return current_time - last_active < 7200  # 2 hours in seconds
    
    def update_activity(self, channel_id):
        """Update last activity time for a channel"""
        self.last_activity[channel_id] = asyncio.get_event_loop().time()
        
    async def spontaneous_message(self, channel):
        if not await self.should_engage(channel.id):
            return None
            
        prompts = [
            "What's everyone talking about?",
            "I was just thinking about something...",
            "Anyone else find this interesting?",
            "What do you all think about this?",
            "I've been wondering about something..."
        ]
        
        return random.choice(prompts)
