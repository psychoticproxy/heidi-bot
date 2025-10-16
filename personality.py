import logging

logger = logging.getLogger("heidi.personality")

class LLMManagedPersonality:
    def __init__(self, personality_db):
        self.personality_db = personality_db
        logger.info("LLMManagedPersonality initialized")

    async def get_personality_summary(self):
        """Get current personality summary from database"""
        return await self.personality_db.get_personality()

    async def update_from_llm(self, summary):
        """Update personality summary in database"""
        if summary and len(summary.strip()) > 10:  # Basic validation
            await self.personality_db.update_personality(summary.strip())
            logger.info(f"Personality updated: {summary}")

    def get_temperature_setting(self):
        """Get temperature setting for API calls"""
        # Optionally: Map specific keywords in summary to temperature
        # For now, always use a moderate temperature
        return 0.8
