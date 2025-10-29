import discord
from discord.ext import commands
import logging
from config import Config
from database.manager import DatabaseManager
from api.openrouter import OpenRouterClient
from bot.events import setup_events

log = logging.getLogger("heidi.bot")

class SimpleHeidi(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix=Config.COMMAND_PREFIX,
            intents=intents,
            help_command=None
        )
        
        self.config = Config
        self.db = DatabaseManager()
        self.api = OpenRouterClient(self)
        
        # Simple state
        self.daily_usage = 0
        
        setup_events(self)
    
    async def setup_hook(self):
        """Initialize bot components"""
        log.info("Starting bot setup...")
        
        # Initialize database
        await self.db.init()
        
        # Load cogs
        await self.load_extension("cogs.basic")
        await self.load_extension("cogs.personality")
        await self.load_extension("cogs.sacrifice")  # This starts the background task
        await self.load_extension("cogs.memory")
        await self.load_extension("cogs.summarize")
        
        log.info("✅ Bot setup complete!")
    
    async def close(self):
        """Clean shutdown - properly stop all background tasks"""
        log.info("Shutting down bot...")
        
        # Get all cogs and stop their background tasks
        for cog_name, cog in self.cogs.items():
            if hasattr(cog, 'cog_unload'):
                cog.cog_unload()
        
        await self.db.close()
        await self.api.close()
        await super().close()

