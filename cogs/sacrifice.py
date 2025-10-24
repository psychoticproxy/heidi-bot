import discord
from discord.ext import commands, tasks
import random
import logging
from datetime import datetime, time, timedelta
from utils.helpers import is_administrator

log = logging.getLogger("heidi.cogs.sacrifice")

class SacrificeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_enabled = False
        self.last_sacrifice_date = None
        self.sacrifice_time = time(0, 0)  # Midnight UTC
        
        # Start the background task when cog loads
        self.daily_sacrifice_task.start()
    
    async def find_sacrifice_targets(self, guild):
        """Find members with no roles (excluding @everyone)"""
        targets = []
        for member in guild.members:
            if member.bot:
                continue
            if len(member.roles) == 1:  # Only @everyone
                targets.append(member)
        return targets
    
    @tasks.loop(minutes=30)  # Check every 30 minutes
    async def daily_sacrifice_task(self):
        """Background task to perform daily sacrifice"""
        # Skip if auto-sacrifice is disabled or already performed today
        if not self.auto_enabled:
            return
            
        current_date = datetime.utcnow().date()
        if self.last_sacrifice_date == current_date:
            return
            
        current_time = datetime.utcnow().time()
        if current_time < self.sacrifice_time:
            return
        
        log.info(f"🔄 Attempting daily sacrifice for {current_date}...")
        sacrifice_performed = False
        
        for guild in self.bot.guilds:
            try:
                targets = await self.find_sacrifice_targets(guild)
                if not targets:
                    continue
                
                target = random.choice(targets)
                log.info(f"🔪 Auto-sacrifice: Kicking {target.display_name} from {guild.name}")
                
                await target.kick(reason="Daily auto-sacrifice")
                
                # Notify in first available channel
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send(
                            f"🔪 **Daily Sacrifice Complete**\n"
                            f"*{target.display_name} has been chosen for today's purification ritual.*"
                        )
                        break
                
                self.last_sacrifice_date = current_date
                sacrifice_performed = True
                log.info(f"✅ Daily sacrifice completed for {current_date}")
                break  # Only one sacrifice per day
                
            except discord.Forbidden:
                log.error(f"Missing permissions to kick in {guild.name}")
            except Exception as e:
                log.error(f"Error in auto-sacrifice for {guild.name}: {e}")
        
        if not sacrifice_performed:
            log.info("No auto-sacrifice performed - no targets or errors")
    
    @daily_sacrifice_task.before_loop
    async def before_daily_task(self):
        """Wait until bot is ready before starting task"""
        await self.bot.wait_until_ready()
        log.info("✅ Daily sacrifice task started")
    
    @commands.command(name="sacrifice")
    async def sacrifice_command(self, ctx):
        """Manual sacrifice (Admin only)"""
        if not is_administrator(ctx):
            await ctx.send("❌ Only administrators can perform sacrifices.")
            return
        
        targets = await self.find_sacrifice_targets(ctx.guild)
        if not targets:
            await ctx.send("🤷 No members without roles found.")
            return
        
        target = random.choice(targets)
        
        try:
            await target.kick(reason="Manual sacrifice command")
            await ctx.send(
                f"🔪 **Sacrifice Complete**\n"
                f"*{target.display_name} has been chosen for purification.*"
            )
            log.info(f"Manual sacrifice: Kicked {target.display_name}")
        except discord.Forbidden:
            await ctx.send("❌ Missing permissions to kick members.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
    
    @commands.command(name="autosacrifice")
    async def toggle_auto_sacrifice(self, ctx, mode: str):
        """Toggle auto-sacrifice (Admin only)"""
        if not is_administrator(ctx):
            await ctx.send("❌ Administrator only.")
            return
        
        if mode.lower() == "on":
            self.auto_enabled = True
            await ctx.send("✅ Auto-sacrifice enabled")
            log.info("Auto-sacrifice enabled")
        elif mode.lower() == "off":
            self.auto_enabled = False
            await ctx.send("✅ Auto-sacrifice disabled")
            log.info("Auto-sacrifice disabled")
        else:
            await ctx.send("❌ Use `!autosacrifice on` or `!autosacrifice off`")
    
    @commands.command(name="sacrificetime")
    @commands.has_permissions(administrator=True)
    async def set_sacrifice_time(self, ctx, hour: int):
        """Set sacrifice time (0-23 UTC) (Admin only)"""
        if not 0 <= hour <= 23:
            await ctx.send("❌ Hour must be between 0 and 23")
            return
        
        self.sacrifice_time = time(hour, 0)
        await ctx.send(f"✅ Sacrifice time set to {hour:02d}:00 UTC")
        log.info(f"Sacrifice time set to {hour:02d}:00 UTC")
    
    @commands.command(name="sacrificestatus")
    async def sacrifice_status(self, ctx):
        """Check sacrifice status"""
        status = "🟢 **ENABLED**" if self.auto_enabled else "🔴 **DISABLED**"
        last_date = self.last_sacrifice_date or "Never"
        
        await ctx.send(
            f"**Daily Sacrifice Status:**\n"
            f"• Auto-sacrifice: {status}\n"
            f"• Last sacrifice: {last_date}\n"
            f"• Scheduled time: {self.sacrifice_time.strftime('%H:%M')} UTC"
        )
    
    def cog_unload(self):
        """Clean up when cog is unloaded"""
        self.daily_sacrifice_task.cancel()
        log.info("Daily sacrifice task stopped")

async def setup(bot):
    await bot.add_cog(SacrificeCommands(bot))

