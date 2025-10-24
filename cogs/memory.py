import discord
from discord.ext import commands
import logging
from database.models import get_recent_context

log = logging.getLogger("heidi.cogs.memory")

class MemoryCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="memory")
    async def memory_stats(self, ctx):
        """Show memory statistics"""
        # Simple stats - in a real implementation, you might want more detailed stats
        context = await get_recent_context(self.bot.db, ctx.channel.id)
        await ctx.send(f"📊 **Memory Stats**\n• Recent messages in channel: {len(context)}")

async def setup(bot):
    await bot.add_cog(MemoryCommands(bot))

