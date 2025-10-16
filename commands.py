import discord
from discord.ext import commands
import logging

logger = logging.getLogger("heidi.commands")

def setup_legacy_commands(bot):
    @bot.command(name="ping")
    async def ping(ctx):
        """Check bot responsiveness."""
        logger.info(f"Ping command used by {ctx.author} in {ctx.channel}")
        latency = round(bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latency: {latency}ms")

    @bot.command(name="usage")
    async def usage(ctx):
        """Check current API usage statistics."""
        logger.info(f"Usage command used by {ctx.author}")
        usage_percent = (bot.daily_usage / bot.daily_limit) * 100
        await ctx.send(
            f"**API Usage Today:**\n"
            f"• Used: {bot.daily_usage}/{bot.daily_limit}\n"
            f"• Remaining: {bot.daily_limit - bot.daily_usage}\n"
            f"• Usage: {usage_percent:.1f}%"
        )

    @bot.command(name="personality")
    async def personality(ctx):
        """Display current personality summary."""
        logger.info(f"Personality command used by {ctx.author}")
        summary = bot.personality.get_personality_summary()
        await ctx.send(
            f"**Current Personality Summary:**\n{summary}"
        )

    @bot.command(name="memory")
    async def memory(ctx):
        """Display memory usage statistics."""
        logger.info(f"Memory command used by {ctx.author}")
        channel_count = len(bot.memory.conversations)
        total_messages = sum(len(conv) for conv in bot.memory.conversations.values())
        await ctx.send(
            f"**Memory Stats:**\n"
            f"• Active channels: {channel_count}\n"
            f"• Total messages: {total_messages}"
        )

    @bot.command(name="help")
    async def help_command(ctx):
        """Show help information."""
        logger.info(f"Help command used by {ctx.author}")
        help_text = """
**Available Commands:**
• `!ping` - Check if I'm responsive
• `!usage` - Check current API usage
• `!personality` - See my current personality summary
• `!memory` - Check memory statistics
• `!help` - Show this message

**Regular Usage:**
• Mention me (@Heidi) to chat directly
• I'll sometimes join conversations naturally
        """
        await ctx.send(help_text)
