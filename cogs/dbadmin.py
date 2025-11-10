import discord
from discord.ext import commands
import logging
import os
import shutil
from config import Config

log = logging.getLogger("heidi.cogs.dbadmin")

class DBAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="exportdb")
    @commands.has_permissions(administrator=True)
    async def export_db(self, ctx):
        """Admin: export the SQLite DB file as an attachment."""
        db_path = Config.SQLITE_PATH
        if not os.path.exists(db_path):
            await ctx.send("❌ Database file not found.")
            return

        try:
            await ctx.send(file=discord.File(db_path, filename=os.path.basename(db_path)))
            log.info(f"Database exported by {ctx.author} ({ctx.author.id})")
        except Exception as e:
            log.error(f"Failed to send DB file: {e}")
            await ctx.send(f"❌ Failed to export DB: {e}")

    @commands.command(name="importdb")
    @commands.has_permissions(administrator=True)
    async def import_db(self, ctx):
        """
        Admin: import a SQLite DB file (attach the file to the command message).
        This will:
        - backup current DB (if exists)
        - close current DB connection
        - replace the DB file with the uploaded file
        - re-initialize the bot's DB connection
        """
        if not ctx.message.attachments:
            await ctx.send("❌ Attach the SQLite database file to this message to import.")
            return

        attachment = ctx.message.attachments[0]
        # Optional: enforce a reasonable size limit (e.g., 10 MB)
        if attachment.size > 10 * 1024 * 1024:
            await ctx.send("❌ Attachment too large (max 10 MB).")
            return

        db_path = Config.SQLITE_PATH
        backup_path = f"{db_path}.bak"

        await ctx.send("🔁 Importing database... (this will temporarily disconnect DB)")

        try:
            # Read uploaded bytes
            new_db_bytes = await attachment.read()

            # Make backup if exists
            if os.path.exists(db_path):
                shutil.copy(db_path, backup_path)

            # Close current DB connection
            try:
                await self.bot.db.close()
            except Exception:
                log.warning("Error closing DB during import (continuing)")

            # Write new DB file
            with open(db_path, "wb") as f:
                f.write(new_db_bytes)

            # Re-init DB manager
            init_ok = await self.bot.db.init()
            if not init_ok:
                # Restore backup if initialization failed
                if os.path.exists(backup_path):
                    shutil.copy(backup_path, db_path)
                    await self.bot.db.init()
                await ctx.send("❌ Failed to initialize the new database. Restored previous DB (if available).")
                return

            await ctx.send("✅ Database imported and re-initialized.")
            log.info(f"Database imported by {ctx.author} ({ctx.author.id})")
        except Exception as e:
            log.error(f"Database import failed: {e}", exc_info=True)
            # Try to restore backup
            try:
                if os.path.exists(backup_path):
                    shutil.copy(backup_path, db_path)
                    await self.bot.db.init()
            except Exception:
                log.error("Failed to restore database backup after import failure")
            await ctx.send(f"❌ Import failed: {e}")

async def setup(bot):
    await bot.add_cog(DBAdmin(bot))
