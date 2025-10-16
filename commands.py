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

    @bot.command(name="summarize")
    async def summarize(ctx, limit: int = 100):
        """
        Summarize recent messages in this channel.
        
        Usage: !summarize [limit]
        - limit: Number of messages to summarize (default: 100, max: 500)
        """
        logger.info(f"Summarize command used by {ctx.author} in {ctx.channel}")
        
        # Validate limit
        if limit <= 0:
            await ctx.send("❌ Please specify a positive number of messages to summarize.")
            return
        if limit > 500:
            await ctx.send("⚠️ Limit too high! Using maximum of 500 messages.")
            limit = 500
        
        async with ctx.typing():
            try:
                # Fetch message history
                messages = []
                async for message in ctx.channel.history(limit=limit + 1):  # +1 to exclude the command itself
                    if message.id == ctx.message.id:
                        continue  # Skip the summarize command message
                    if message.content.startswith('!'):
                        continue  # Skip other command messages
                    
                    # Format message with author and content
                    author_name = message.author.display_name
                    content = message.content.replace('\n', ' ')  # Clean up newlines
                    messages.append(f"{author_name}: {content}")
                
                if not messages:
                    await ctx.send("🤷 No recent messages found to summarize.")
                    return
                
                # Reverse to get chronological order (newest first in history)
                messages.reverse()
                conversation_text = "\n".join(messages[-limit:])  # Ensure we don't exceed limit
                
                # Prepare prompts for summarization
                system_prompt = (
                    "You are Heidi, a Discord chatbot. Your task is to summarize the recent conversation in this channel. "
                    "Provide a concise, engaging summary that captures the main topics, key points, and any interesting discussions. "
                    "Keep it natural and conversational, as if you're briefly catching someone up on what they missed. "
                    "Aim for 2-4 sentences maximum, and maintain your playful personality."
                )
                
                user_prompt = f"Here are the recent messages from this channel. Please summarize them:\n\n{conversation_text}"
                
                api_messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                # Call OpenRouter API with lower temperature for more consistent summarization
                summary = await bot.call_openrouter(api_messages, temperature=0.3, max_tokens=200)
                
                if summary:
                    # Add some context about the summary
                    message_count = len(messages)
                    await ctx.send(
                        f"**📝 Summary of recent conversation** ({message_count} messages):\n"
                        f"{summary}"
                    )
                    logger.info(f"Successfully summarized {message_count} messages in {ctx.channel}")
                else:
                    await ctx.send("❌ Sorry, I couldn't generate a summary right now. The API might be unavailable or I've hit my daily limit.")
                    
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to read message history in this channel.")
            except Exception as e:
                logger.error(f"Error in summarize command: {e}")
                await ctx.send("❌ An error occurred while trying to summarize messages. Please try again later.")
