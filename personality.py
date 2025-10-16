import logging

logger = logging.getLogger("heidi.personality")

class LLMManagedPersonality:
    def __init__(self, initial_summary=None):
        self.personality_summary = initial_summary or "curious, playful, sincere, entertaining, engaging"
        logger.info("LLMManagedPersonality initialized")

    def get_personality_summary(self):
        return self.personality_summary

    def update_from_llm(self, summary):
        """Update summary received from LLM"""
        if summary:
            logger.info(f"Updating personality summary: {summary}")
            self.personality_summary = summary

    def get_temperature_setting(self):
        # Optionally: Map specific keywords in summary to temperature
        # For now, always use a moderate temperature
        return 0.8
