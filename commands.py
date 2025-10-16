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
        summary = await bot.personality.get_personality_summary()
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

    @bot.command(name="temperature")
    async def temperature(ctx):
        """Display current temperature setting and pattern info."""
        logger.info(f"Temperature command used by {ctx.author}")
        temp_info = bot.personality.get_temperature_info()
        current_temp = temp_info["current_temperature"]
        hour_index = temp_info["current_hour_index"]
        next_temp = temp_info["next_temperature"]
        
        # Create a simple visual representation of the temperature pattern
        pattern_display = []
        for i, temp in enumerate(temp_info["full_pattern"]):
            marker = "🟢" if i == hour_index else "⚪"
            pattern_display.append(f"{marker} {i:02d}:00 - {temp:.2f}")
        
        # Show current segment and next few hours
        current_segment = "\n".join(pattern_display[hour_index:hour_index+4])
        
        await ctx.send(
            f"**Temperature Settings:**\n"
            f"• Current: **{current_temp:.2f}** (Hour {hour_index}:00)\n"
            f"• Next: {next_temp:.2f} (Hour {(hour_index + 1) % 24}:00)\n\n"
            f"**Next Hours:**\n{current_segment}"
        )

    @bot.command(name="resettemp")
    @commands.has_permissions(administrator=True)
    async def reset_temp(ctx):
        """Reset the temperature pattern (Admin only)."""
        logger.info(f"Reset temperature command used by {ctx.author}")
        new_pattern = ctx.bot.personality.reset_temperature_pattern()
        await ctx.send(
            f"✅ Temperature pattern reset!\n"
            f"New pattern: {new_pattern}"
        )
