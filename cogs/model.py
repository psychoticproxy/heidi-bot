import discord
from discord.ext import commands
import logging

log = logging.getLogger("heidi.cogs.model")

class ModelCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="model")
    async def show_model(self, ctx):
        """Show current AI model"""
        await ctx.send(f"🤖 **Current Model:** `{self.bot.current_model}`")

    @commands.command(name="setmodel")
    @commands.has_permissions(administrator=True)
    async def set_model(self, ctx, *, model_name: str):
        """Change AI model (Admin)"""
        try:
            # Simple validation
            if '/' not in model_name:
                await ctx.send("❌ Invalid model format. Use `provider/model:tag`")
                return
            
            await self.bot.db.execute(
                "INSERT INTO personality (key, value) VALUES ('current_model', $1) "
                "ON CONFLICT (key) DO UPDATE SET value = $1",
                model_name
            )
            self.bot.current_model = model_name
            await ctx.send(f"✅ Model updated to `{model_name}`")
        except Exception as e:
            await ctx.send(f"❌ Error updating model: {str(e)}")
            log.error(f"Model update error: {str(e)}")

async def setup(bot):
    await bot.add_cog(ModelCommands(bot))
