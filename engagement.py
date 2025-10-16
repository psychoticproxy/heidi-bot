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
        
        # Get current personality for the system prompt
        current_personality = await self.bot.personality.get_personality_summary()
        
        system_prompt = await self.bot.build_system_prompt(
            context,
            personality_summary=current_personality,
            is_unsolicited=True
        )
        
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

    async def update_personality_from_spontaneous(self, context, response):
        """Update personality based on spontaneous interaction (called by bot)"""
        try:
            current_personality = await self.bot.personality.get_personality_summary()
            
            personality_prompt = (
                f"Based on Heidi's spontaneous message: '{response}'\n"
                f"and the conversation context, update her personality summary.\n"
                f"Current personality: {current_personality}\n\n"
                f"Provide ONLY the updated personality summary as a brief comma-separated list of traits. "
                f"Keep it concise (max 100 characters). Focus on making her more engaging, entertaining, natural, and sincere."
            )
            
            messages = [
                {"role": "system", "content": "You are a personality analyzer. Provide only the updated personality summary based on the interaction."},
                {"role": "user", "content": personality_prompt}
            ]
            
            new_summary = await self.bot.call_openrouter(messages, temperature=0.3)  # Lower temp for consistency
            if new_summary and len(new_summary.strip()) > 10:
                await self.bot.personality.update_from_llm(new_summary.strip())
                logger.info(f"✅ Personality updated from spontaneous interaction: {new_summary}")
                
        except Exception as e:
            logger.error(f"Failed to update personality from spontaneous: {e}")
