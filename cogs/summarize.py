import discord
from discord.ext import commands
import logging
from datetime import timedelta
from database.models import get_message_history
from utils.helpers import is_administrator

log = logging.getLogger("heidi.cogs.summarize")

class SummarizeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    @commands.command(name="summary")
    async def summarize(self, ctx, user: discord.Member = None):
        """Summarize recent channel messages (500 max)"""
        # Cooldown check (1 hour for non-admins)
        try:
            if not is_administrator(ctx):
                last_used = self.cooldowns.get(ctx.author.id)
                if last_used and (ctx.message.created_at - last_used) < timedelta(hours=1):
                    remaining = timedelta(hours=1) - (ctx.message.created_at - last_used)
                    await ctx.send(f"⏳ Please wait {remaining.seconds//60} minutes before using this command again")
                    return
        
            await ctx.send("📚 Gathering messages for summary...")
        
            # Get message history
            messages = await get_message_history(
                self.bot.db,
                ctx.channel.id,
                user.id if user else None,
                500
            )
        
            if not messages:
                await ctx.send("❌ No messages found to summarize")
                return
        
            await ctx.send("🧠 Analyzing conversation (this may take a moment)...")
        
        
            # Build summary prompt
            conversation = "\n".join([f"{m['author']}: {m['content']}" for m in messages])
            prompt = f"Create a concise bullet-point summary focusing on key topics and interactions:\n\n{conversation[-8000:]}"

            # Log the API call parameters
            log.debug(f"Calling API with system_prompt and prompt length: {len(prompt)}")
            
            # Generate summary
            response = await self.bot.api.generate_response(
                context=[],
                user_message=prompt,
                user_name="Summary Request",
                system_prompt="""You're a professional summarization AI. For the given Discord chat:
                1. Create bullet points with clear topic headings
                2. Keep each bullet 1-2 sentences
                3. Never truncate mid-sentence
                4. Focus on recurring themes and key interactions"""
            )
            
            
            # Send results
            if response:
                summary_content = response
                if len(response) > 1900:
                    last_period = response[:1900].rfind('. ')
                    if last_period != -1:
                        summary_content = response[:last_period+1] + " [...]"
                    else:
                        summary_content = response[:1900] + "..."
                await ctx.send(summary)
                
                # Update cooldown only if non-admin
                if not is_administrator(ctx):
                    self.cooldowns[ctx.author.id] = ctx.message.created_at
            else:
                 await ctx.send("❌ Failed to generate summary")
                
        except Exception as e:
            log.error(f"Summary error: {str(e)}", exc_info=True)
            await ctx.send("❌ Error generating summary")

async def setup(bot):
    await bot.add_cog(SummarizeCommands(bot))
