import discord
from discord.ext import commands
import logging
from utils.helpers import format_usage_stats

log = logging.getLogger("heidi.cogs.basic")

class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name="ping")
    async def ping(self, ctx):
        """Check bot latency"""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! {latency}ms")
    
    @commands.command(name="usage")
    async def usage(self, ctx):
        """Check API usage"""
        usage_text = format_usage_stats(
            self.bot.daily_usage, 
            self.bot.config.DAILY_API_LIMIT
        )
        await ctx.send(f"**API Usage Today:** {usage_text}")
    
    @commands.command(name="help")
    async def help_command(self, ctx):
        """Show available commands"""
        embed = discord.Embed(
            title="Heidi Help",
            description="Available commands:",
            color=0x00ff00
        )
        
        commands_list = [
            ("!ping", "Check bot latency"),
            ("!usage", "Check API usage"),
            ("!personality", "Show current personality"),
            ("!memory", "Show memory stats"),
            ("!sacrifice", "Manual sacrifice (Admin)"),
            ("!autosacrifice on/off", "Toggle auto-sacrifice (Admin)"),
            ("!sacrificetime [hour]", "Set sacrifice time 0-23 UTC (Admin)"),
            ("!sacrificestatus", "Check sacrifice status"),
            ("!help", "This message")
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=cmd, value=desc, inline=False)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BasicCommands(bot))

