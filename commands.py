import discord
from discord import app_commands
import logging
import asyncio
import os

logger = logging.getLogger("heidi.commands")

class HeidiCommands:
    def __init__(self, bot):
        self.bot = bot
        logger.info("HeidiCommands initialized")

    async def setup_commands(self):
        """Setup slash commands for the bot"""
        try:
            # Add commands to the tree
            self.bot.tree.add_command(self.ping)
            self.bot.tree.add_command(self.usage)
            self.bot.tree.add_command(self.personality)
            self.bot.tree.add_command(self.memory)
            self.bot.tree.add_command(self.help_command)
            
            # Sync commands to a specific guild if GUILD_ID is set
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                await self.bot.tree.sync(guild=guild)
                logger.info(f"Slash commands synced to guild {guild_id}")
            else:
                await self.bot.tree.sync()  # Global sync
                logger.info("Slash commands synced globally")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    @app_commands.command(name="ping", description="Check if the bot is responsive")
    async def ping(self, interaction: discord.Interaction):
        """Simple ping command to check bot responsiveness"""
        logger.info(f"Ping command used by {interaction.user} in {interaction.channel}")
        
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"Pong! 🏓 Latency: {latency}ms",
            ephemeral=True
        )

    @app_commands.command(name="usage", description="Check current API usage")
    async def usage(self, interaction: discord.Interaction):
        """Check current API usage statistics"""
        logger.info(f"Usage command used by {interaction.user}")
        
        usage_percent = (self.bot.daily_usage / self.bot.daily_limit) * 100
        await interaction.response.send_message(
            f"**API Usage Today:**\n"
            f"• Used: {self.bot.daily_usage}/{self.bot.daily_limit}\n"
            f"• Remaining: {self.bot.daily_limit - self.bot.daily_usage}\n"
            f"• Usage: {usage_percent:.1f}%",
            ephemeral=True
        )

    @app_commands.command(name="personality", description="Check Heidi's current personality traits")
    async def personality(self, interaction: discord.Interaction):
        """Display current personality traits"""
        logger.info(f"Personality command used by {interaction.user}")
        
        traits = self.bot.personality.base_traits
        trait_text = "\n".join([f"• **{trait}**: {value:.2f}" for trait, value in traits.items()])
        
        await interaction.response.send_message(
            f"**Current Personality Traits:**\n{trait_text}",
            ephemeral=True
        )

    @app_commands.command(name="memory", description="Check memory statistics")
    async def memory(self, interaction: discord.Interaction):
        """Display memory usage statistics"""
        logger.info(f"Memory command used by {interaction.user}")
        
        channel_count = len(self.bot.memory.conversations)
        total_messages = sum(len(conv) for conv in self.bot.memory.conversations.values())
        
        await interaction.response.send_message(
            f"**Memory Stats:**\n"
            f"• Active channels: {channel_count}\n"
            f"• Total messages: {total_messages}",
            ephemeral=True
        )

    @app_commands.command(name="help", description="Show available commands")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information"""
        logger.info(f"Help command used by {interaction.user}")
        
        help_text = """
**Available Commands:**

• `/ping` - Check if I'm responsive
• `/usage` - Check current API usage
• `/personality` - See my current personality traits  
• `/memory` - Check memory statistics
• `/help` - Show this message

**Regular Usage:**
• Mention me (@Heidi) to chat directly
• I'll sometimes join conversations naturally
        """
        
        await interaction.response.send_message(help_text, ephemeral=True)
