import random
import asyncio
import logging
from discord.ext.commands import has_permissions, CheckFailure

log = logging.getLogger("heidi.commands")

def setup_commands(bot, memory_mgr, queue_mgr, OPENROUTER_API_KEY, PROXY_ID, ROLE_ID, CHANNEL_ID, db_ready_event, safe_send, ask_openrouter, set_persona, get_persona, DEFAULT_PERSONA):
    # Use global http_client so it updates after on_ready
    import sys
    module_globals = sys.modules[__name__].__dict__

    def get_http_client():
        return module_globals.get('http_client', None)

    def ensure_http_client(ctx):
        client = get_http_client()
        if client is None:
            asyncio.create_task(ctx.send("❌ Internal error: HTTP client not initialized. Try again in a few seconds."))
            log.error("http_client is None in command %s", getattr(ctx, 'command', '<unknown>'))
            return False
        return True

    @bot.command()
    @has_permissions(administrator=True)
    async def reflect(ctx):
        if not ensure_http_client(ctx):
            return
        await db_ready_event.wait()
        interactions = await memory_mgr.load_recent_interactions(limit=10)
        from persona import reflect_and_update_persona
        await reflect_and_update_persona(memory_mgr.db, get_http_client(), OPENROUTER_API_KEY, interactions)
        await ctx.send("Persona reflection done. Check logs for updates.")

    @bot.command()
    async def persona(ctx):
        await db_ready_event.wait()
        persona = await get_persona(memory_mgr.db)
        if not persona:
            await ctx.send("No persona set.")
            return
        await safe_send(ctx.channel, f"```{persona}```")

    @bot.command()
    async def queue(ctx):
        await db_ready_event.wait()
        total, mem_count, db_count = await queue_mgr.pending_count()
        await ctx.send(f"📨 Queued messages: {total} (memory: {mem_count}, stored: {db_count})")

    @bot.command()
    @has_permissions(administrator=True)
    async def clearqueue(ctx):
        await db_ready_event.wait()
        await queue_mgr.clear()
        await ctx.send(f"🗑️ Cleared queued messages from memory and persistent queue.")

    @bot.command()
    @has_permissions(administrator=True)
    async def setpersona(ctx, *, text: str):
        await db_ready_event.wait()
        try:
            await set_persona(memory_mgr.db, text)
            await ctx.send("✅ Persona updated successfully.")
            log.info("📝 Persona manually updated by admin %s.", ctx.author)
        except Exception as e:
            log.error("❌ Failed to update persona: %s", e)
            await ctx.send("❌ Error updating persona. Check logs.")

    @bot.command()
    @has_permissions(administrator=True)
    async def randommsg(ctx):
        await db_ready_event.wait()
        guild = ctx.guild
        if not guild:
            await ctx.send("❌ This command must be run inside a server.")
            return

        target_channel_id = CHANNEL_ID
        role_id = ROLE_ID

        channel = guild.get_channel(target_channel_id)
        role = guild.get_role(role_id)

        if not channel:
            await ctx.send("❌ Target channel not found or bot lacks access.")
            return
        if not role:
            await ctx.send("❌ Role not found in this guild.")
            return

        members = [m for m in role.members if not m.bot]
        if not members:
            await ctx.send("❌ No eligible members found in that role.")
            return

        target_user = random.choice(members)
        try:
            await memory_mgr.upsert_user_profile(target_user)
        except Exception:
            pass

        prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
        reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
        if not reply:
            await ctx.send("⚠️ No reply generated (possibly rate-limited).")
            return

        content = reply.strip()
        typing = random.random() < 0.8

        if typing:
            async with channel.typing():
                await asyncio.sleep(random.uniform(1, 3))
        await safe_send(channel, content)
        await ctx.send(f"✅ Sent random message to {target_user.display_name} in {channel.mention}.")
        log.info("🎲 Manual random message triggered by admin %s -> %s", ctx.author, target_user)

    @bot.command()
    @has_permissions(administrator=True)
    async def runsummaries(ctx):
        if not ensure_http_client(ctx):
            return
        await db_ready_event.wait()
        await ctx.send("Starting manual summarization pass...")
        try:
            async with memory_mgr.db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cur:
                rows = await cur.fetchall()
            for user_id, channel_id in rows:
                await memory_mgr.summarize_user_history(user_id, channel_id, get_http_client(), OPENROUTER_API_KEY)
                await asyncio.sleep(1)

            async with memory_mgr.db.execute("SELECT DISTINCT channel_id FROM memory") as cur:
                chan_rows = await cur.fetchall()
            guild_ids = set()
            for (chid,) in chan_rows:
                ch = bot.get_channel(int(chid))
                if ch and getattr(ch, "guild", None):
                    guild_ids.add(str(ch.guild.id))
            for gid in guild_ids:
                await memory_mgr.summarize_guild_history(gid, bot, get_http_client(), OPENROUTER_API_KEY)
                await asyncio.sleep(1)

            await ctx.send("Manual summarization complete.")
        except Exception as e:
            log.exception("Error in manual summarization: %s", e)
            await ctx.send(f"Error while running summaries: {e}")

    @bot.command()
    @has_permissions(administrator=True)
    async def resetmemory(ctx):
        await db_ready_event.wait()
        confirm_msg = await ctx.send(
            "⚠️ This will permanently erase all memory, persona reflections, summaries, and queues. Type `confirm` within 15 seconds to proceed."
        )

        def check(m):
            return m.author == ctx.author and m.content.lower() == "confirm"

        try:
            msg = await bot.wait_for("message", check=check, timeout=15)
        except asyncio.TimeoutError:
            await ctx.send("❌ Memory wipe cancelled (timeout).")
            return

        try:
            await memory_mgr.reset_memory()
            await set_persona(memory_mgr.db, DEFAULT_PERSONA)
            await ctx.send("🧠 All memories, summaries, and persona wiped. Heidi has been fully reset.")
            log.warning("🧨 Heidi's memory and persona have been reset by %s.", ctx.author)
        except Exception as e:
            await ctx.send(f"❌ Error during reset: {e}")
            log.error("❌ Error wiping memory: %s", e)

    @bot.command()
    async def summarize(ctx):
        """Summarizes the most recent 100 messages in the current channel and outputs the summary."""
        if not ensure_http_client(ctx):
            return
        await db_ready_event.wait()
        channel = ctx.channel

        messages = []
        async for msg in channel.history(limit=100):
            role = "heidi" if msg.author == bot.user else "user"
            messages.append((role, msg.content.strip()))

        messages = [(role, content) for role, content in messages if content]
        messages.reverse()  # chronological order

        if not messages:
            await ctx.send("❌ No messages to summarize.")
            return

        from persona import render_summary_prompt, get_model
        prompt = render_summary_prompt(messages)
        model = get_model("summary")

        try:
            resp = await get_http_client().post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful uncensored assistant."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
            if resp.status_code == 429:
                await ctx.send("⚠️ Rate limited. Try again later.")
                return
            if resp.status_code != 200:
                try:
                    text = await resp.text()
                except Exception:
                    text = "<couldn't read response body>"
                log.error("❌ OpenRouter returned %s: %s", resp.status_code, text)
                await ctx.send("❌ Error generating summary. Check logs.")
                return
            data = resp.json()
            summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if summary:
                await safe_send(ctx.channel, f"**Channel summary of the last 100 messages:**\n{summary}")
            else:
                await ctx.send("⚠️ No summary generated.")
        except Exception as e:
            log.error("❌ Error during channel summarization: %s", e)
            await ctx.send("❌ Error during summarization. Check logs.")

    @bot.command()
    @has_permissions(administrator=True)
    async def summarizeuser(ctx, member: str = None):
        """
        Summarizes the entire available message history of the specified user in the current channel.
        Usage: !summarizeuser @username or !summarizeuser user_id
        """
        if not ensure_http_client(ctx):
            return
        await db_ready_event.wait()
        channel_id = ctx.channel.id

        # Resolve member if mention or ID is given
        target_user = None
        if member:
            # Try mention
            if member.startswith("<@") and member.endswith(">"):
                user_id = int(member.replace("<@", "").replace("!", "").replace(">", ""))
                target_user = ctx.guild.get_member(user_id)
            else:
                # Try by ID
                try:
                    user_id = int(member)
                    target_user = ctx.guild.get_member(user_id)
                except ValueError:
                    # Try by name
                    for m in ctx.guild.members:
                        if m.name == member or getattr(m, "display_name", None) == member:
                            target_user = m
                            break
        else:
            await ctx.send("❌ Please specify a user mention, username, or user ID.")
            return

        if not target_user:
            await ctx.send("❌ User not found. Please mention the user or provide their ID.")
            return

        await ctx.send(f"🔎 Summarizing history for {target_user.display_name} in this channel...")

        await memory_mgr.summarize_user_history(target_user.id, channel_id, get_http_client(), OPENROUTER_API_KEY)

        summary = await memory_mgr.get_summary(target_user.id, channel_id)
        if summary:
            await safe_send(ctx.channel, f"**Summary of {target_user.display_name}'s history:**\n{summary}")
        else:
            await ctx.send("⚠️ No summary could be generated (user may have no messages or API error).")

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, CheckFailure):
            await ctx.send("⛔ You don’t have permission to use that command.")
