import random
import asyncio
import logging

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
        should_engage = time_since_active < 7200
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

        context = await self.memory.get_recent_context(channel.id, limit=6)
        system_prompt = self.bot.build_system_prompt(
            context,
            personality_summary=self.bot.personality.get_personality_summary(),
            is_unsolicited=True
        )
        user_prompt = (
            "Generate a brief, spontaneous message to join this Discord conversation naturally. "
            "Be casual and relevant, as if Heidi is chiming in. "
            "After replying, analyze this interaction and update Heidi's personality summary to be more engaging, entertaining, natural, and sincere with emotions. "
            "Return your reply as 'reply', and the updated personality summary as 'personality_summary' in JSON."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        temperature = self.bot.personality.get_temperature_setting()
        logger.info(f"Requesting spontaneous message from OpenRouter for channel {channel.id}")
        response = await self.bot.call_openrouter(messages, temperature=temperature)
        if response and response.strip():
            logger.info(f"Generated spontaneous message for channel {channel.id}: '{response}'")
            try:
                import json
                data = json.loads(response)
                reply = data.get("reply", "").strip()
                summary = data.get("personality_summary", "").strip()
                if summary:
                    self.bot.personality.update_from_llm(summary)
                return reply or response.strip()
            except Exception:
                return response.strip()
        else:
            logger.debug(f"No response from OpenRouter for spontaneous message in channel {channel.id}")
            return None
