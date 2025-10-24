import discord
from discord.ext import commands
import logging
from database.models import get_personality, update_personality

log = logging.getLogger("heidi.cogs.personality")

class PersonalityCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="personality")
    async def show_personality(self, ctx):
        """Show current personality"""
        summary = await get_personality(self.bot.db)
        await ctx.send(f"**Current Personality:**\n{summary}")
    
    @commands.command(name="setpersonality")
    @commands.has_permissions(administrator=True)
    async def set_personality(self, ctx, *, new_summary):
        """Set new personality (Admin only)"""
        if len(new_summary) > 500:
            await ctx.send("❌ Personality summary too long (max 500 chars)")
            return
        
        await update_personality(self.bot.db, new_summary)
        await ctx.send(f"✅ Personality updated!\nNew summary: {new_summary}")

async def setup(bot):
    await bot.add_cog(PersonalityCommands(bot))

