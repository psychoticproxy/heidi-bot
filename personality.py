import logging
import random
import time
import math

logger = logging.getLogger("heidi.personality")

class LLMManagedPersonality:
    def __init__(self, personality_db):
        self.personality_db = personality_db
        self.temperature_pattern = self._generate_daily_pattern()
        self.pattern_start_time = time.time()
        logger.info("LLMManagedPersonality initialized with daily temperature fluctuations")

    def _generate_daily_pattern(self):
        """Generate a smooth temperature pattern for 24 hours"""
        pattern = []
        hours = 24
        
        # Create base pattern with peaks and valleys
        for hour in range(hours):
            # Base sine wave for natural fluctuation (period = 24 hours)
            base = math.sin((hour / hours) * 2 * math.pi) * 0.15
            
            # Add some random noise for variety
            noise = random.uniform(-0.05, 0.05)
            
            # Center around 0.7 with fluctuations between 0.4 and 1.0
            temperature = 0.7 + base + noise
            
            # Clamp between reasonable bounds
            temperature = max(0.4, min(1.0, temperature))
            
            pattern.append(round(temperature, 2))
        
        logger.info(f"Generated daily temperature pattern: {pattern}")
        return pattern

    def _get_current_temperature_index(self):
        """Get the current hour index in the 24-hour pattern"""
        current_time = time.time()
        elapsed_hours = (current_time - self.pattern_start_time) / 3600  # Convert to hours
        current_hour = int(elapsed_hours % 24)  # Wrap around every 24 hours
        return current_hour

    async def get_personality_summary(self):
        """Get current personality summary from database"""
        return await self.personality_db.get_personality()

    async def update_from_llm(self, summary):
        """Update personality summary in database"""
        if summary and len(summary.strip()) > 10:  # Basic validation
            await self.personality_db.update_personality(summary.strip())
            logger.info(f"Personality updated: {summary}")

    def get_temperature_setting(self):
        """Get temperature setting based on time of day pattern"""
        current_index = self._get_current_temperature_index()
        temperature = self.temperature_pattern[current_index]
        
        # Occasionally (5% chance) add a small random variation to prevent predictability
        if random.random() < 0.05:
            variation = random.uniform(-0.1, 0.1)
            temperature = max(0.4, min(1.0, temperature + variation))
            temperature = round(temperature, 2)
            logger.debug(f"Added random temperature variation: {temperature}")
        
        logger.debug(f"Current temperature: {temperature} (hour index: {current_index})")
        return temperature

    def get_temperature_info(self):
        """Get information about current temperature pattern (for debugging/monitoring)"""
        current_index = self._get_current_temperature_index()
        next_index = (current_index + 1) % 24
        return {
            "current_temperature": self.temperature_pattern[current_index],
            "current_hour_index": current_index,
            "next_temperature": self.temperature_pattern[next_index],
            "pattern_start_time": self.pattern_start_time,
            "full_pattern": self.temperature_pattern
        }

    def reset_temperature_pattern(self):
        """Reset the temperature pattern (useful for testing or manual adjustment)"""
        self.temperature_pattern = self._generate_daily_pattern()
        self.pattern_start_time = time.time()
        logger.info("Temperature pattern reset")
        return self.temperature_pattern
