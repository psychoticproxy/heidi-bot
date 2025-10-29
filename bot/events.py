import discord
import logging
from database.models import add_message, get_recent_context

log = logging.getLogger("heidi.events")

def setup_events(bot):
    @bot.event
    async def on_ready():
        log.info(f"✅ {bot.user} is online! Connected to {len(bot.guilds)} guilds")
    
    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return
        
        # Process commands first
        await bot.process_commands(message)
        
        # Store message in memory
        await add_message(
            bot.db,
            message.channel.id,
            message.author.display_name,
            message.content,
            message.author.id
        )
        
        # Respond to mentions
        if bot.user in message.mentions:
            await handle_mention(bot, message)

async def handle_mention(bot, message):
    """Handle when bot is mentioned"""
    log.info(f"📨 Mention from {message.author} in {message.channel}")
    
    async with message.channel.typing():
        # Get conversation context
        context = await get_recent_context(bot.db, message.channel.id)
        
        # Generate response
        response = await bot.api.generate_response(
            context=context,
            user_message=message.content,
            user_name=message.author.display_name
        )
        
        if response:
            await message.reply(response, mention_author=False)
            # Store bot response
            await add_message(
                bot.db,
                message.channel.id,
                "Heidi",
                response,
                is_bot=True
            )
        else:
            await message.reply("https://tenor.com/view/bocchi-the-rock-bocchi-roll-rolling-rolling-on-the-floor-gif-4645200487976536632", mention_author=False)

