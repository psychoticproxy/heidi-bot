import threading
from flask import Flask
import os
import discord
from discord.ext import commands
from discord.ext.commands import has_permissions, CheckFailure
import httpx
from dotenv import load_dotenv
import asyncio
import random
import time
import logging
import re
from collections import Counter
from typing import Optional

from queue_manager import QueueManager
from persona import (
    get_persona, set_persona, get_model, render_system_prompt,
    render_user_mapping, reflect_and_update_persona, DEFAULT_PERSONA,
    render_summary_prompt, render_guild_summary_prompt
)
from memory import MemoryManager  # NEW IMPORT

PROXY_ID = 1248244979151671398
ROLE_ID = 1425102962556145676
CHANNEL_ID = 1385570983062278268

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("heidi")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY not loaded from .env")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
COOLDOWN_SECONDS = 15
DAILY_LIMIT = 1000

daily_usage = 0
daily_reset_timestamp = 0

async def can_make_request() -> bool:
    global daily_usage, daily_reset_timestamp
    now = time.time()
    if now > daily_reset_timestamp:
        daily_usage = 0
        daily_reset_timestamp = now + 86400
        log.info("🔄 Daily quota reset.")
    if daily_usage < DAILY_LIMIT:
        daily_usage += 1
        return True
    return False

async def safe_send(channel: discord.abc.Messageable, content: str, max_len: int = 2000):
    if not content:
        return
    for i in range(0, len(content), max_len):
        chunk = content[i:i+max_len]
        await channel.send(chunk)

queue_mgr = QueueManager("queued_messages.db")
memory_mgr = MemoryManager("heidi_memory.db")  # NEW MemoryManager instance
db_ready_event = asyncio.Event()  # Signal when DB is initialized

async def queue_worker():
    while True:
        msg = await queue_mgr.get_next()
        if not msg:
            await asyncio.sleep(2)
            continue
        _id, user_id, channel_id, prompt = msg
        try:
            reply = await ask_openrouter(user_id, channel_id, prompt, None)
            if reply:
                chan = bot.get_channel(int(channel_id))
                if chan:
                    typing = random.random() < 0.8
                    await safe_send(chan, reply)
                    await queue_mgr.mark_delivered(_id)
            else:
                await asyncio.sleep(10)
        except Exception as e:
            log.error("❌ queue_worker error: %s", e)
        finally:
            await queue_mgr.task_done(_id)

http_client: Optional[httpx.AsyncClient] = None

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
    global http_client
    log.info("🔌 on_ready triggered - initializing DBs and background tasks.")

    # INIT MEMORY MANAGER
    await memory_mgr.init()
    db_ready_event.set()  # Signal DB is ready

    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    await queue_mgr.init()
    asyncio.create_task(queue_worker())

    async def daily_reflection():
        await bot.wait_until_ready()
        await db_ready_event.wait()  # Wait for DB to be ready
        while not bot.is_closed():
            try:
                interactions = await memory_mgr.load_recent_interactions(limit=10)
                await reflect_and_update_persona(memory_mgr.db, http_client, OPENROUTER_API_KEY, interactions)
            except Exception as e:
                log.error("❌ daily_reflection task error: %s", e)
            await asyncio.sleep(86400)
    asyncio.create_task(daily_reflection())

    log.info("✅ Logged in as %s", bot.user.name)

# ------------------------
# Ask OpenRouter
# ------------------------
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> Optional[str]:
    await db_ready_event.wait()  # Ensure DB is initialized
    if not await can_make_request():
        await queue_mgr.enqueue(user_id, channel_id, prompt)
        return None

    persona = await get_persona(memory_mgr.db)
    messages = []
    messages += render_system_prompt(persona, PROXY_ID)

    profile = None
    if discord_user:
        display = getattr(discord_user, "display_name", None) or getattr(discord_user, "name", str(discord_user))
        username = getattr(discord_user, "name", display)
        profile = {"username": username, "display_name": display, "id": str(discord_user.id)}
        try:
            await memory_mgr.upsert_user_profile(discord_user)
        except Exception:
            pass
    else:
        prof = await memory_mgr.fetch_profile_from_db(user_id)
        if prof:
            profile = {"username": prof.get("username"), "display_name": prof.get("display_name"), "id": str(user_id)}
    messages += render_user_mapping(profile)

    # Long-term summary
    try:
        summary = await memory_mgr.get_summary(user_id, channel_id)
        if summary:
            messages.append({"role": "system", "content": f"Long-term memory summary: {summary}"})
    except Exception as e:
        log.error("❌ Failed to load memory_summary: %s", e)

    # Global guild summary
    try:
        chan = bot.get_channel(int(channel_id))
        if chan and chan.guild:
            gid = str(chan.guild.id)
            guild_summary = await memory_mgr.get_guild_summary(gid)
            if guild_summary:
                messages.append({"role": "system", "content": f"Server-wide memory: {guild_summary}"})
            messages.append({"role": "system", "content": f"Channel: {getattr(chan, 'name', str(channel_id))}, Guild: {getattr(chan.guild, 'name', '')}, guild_id: {gid}"})
    except Exception as e:
        log.error("❌ Failed to load memory_summary_global: %s", e)

    # Short-term context cache
    try:
        context_rows = await memory_mgr.get_context(user_id, channel_id, limit=2)
        if context_rows:
            joined_context = "\n".join(context_rows)
            messages.append({"role": "system", "content": f"Recent context: {joined_context}"})
    except Exception as e:
        log.error("❌ Failed to load context_cache: %s", e)

    history = await memory_mgr.load_history(user_id, channel_id)
    if history:
        formatted = [f"{role.capitalize()}: {msg}" for role, msg in history]
        messages.append({"role": "assistant", "content": "Recent conversation:\n" + "\n".join(formatted)})
    messages.append({"role": "user", "content": prompt})

    model = get_model("main")
    client_to_use = http_client
    try:
        resp = await client_to_use.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "authorization": f"Bearer {OPENROUTER_API_KEY}",
                "referer": "https://discord.com",
                "x-title": "Heidi Bot",
                "content-type": "application/json",
            },
            json={"model": model, "messages": messages},
        )
        if resp.status_code == 429:
            log.warning("⚠️ Rate limited by OpenRouter.")
            await asyncio.sleep(30)
            return None
        resp.raise_for_status()
        data = resp.json()
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if reply is None:
            reply = ""
    except Exception as e:
        log.error("❌ API error: %s", e)
        return None

    try:
        await memory_mgr.save_message(user_id, channel_id, "user", prompt)
        await memory_mgr.save_message(user_id, channel_id, "heidi", reply)
    except Exception as e:
        log.error("❌ Failed to save messages to DB: %s", e)

    return reply

# ------------------------
# Message handler
# ------------------------
@bot.event
async def on_message(message):
    await db_ready_event.wait()  # Ensure DB is initialized
    if message.author == bot.user:
        return
    try:
        await memory_mgr.upsert_user_profile(message.author)
    except Exception:
        pass
    if bot.user in message.mentions:
        now = time.time()
        last_used = user_cooldowns.get(message.author.id, 0)
        if now - last_used < COOLDOWN_SECONDS:
            await bot.process_commands(message)
            return
        user_cooldowns[message.author.id] = now
        user_input = re.sub(rf"<@!?\s*{bot.user.id}\s*>", "", message.content).strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)
        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)
        if reply:
            typing = random.random() < 0.8
            await safe_send(message.channel, reply)
    await bot.process_commands(message)

# ------------------------
# Bot commands
# ------------------------
@bot.command()
@has_permissions(administrator=True)
async def reflect(ctx):
    await db_ready_event.wait()
    interactions = await memory_mgr.load_recent_interactions(limit=10)
    await reflect_and_update_persona(memory_mgr.db, http_client, OPENROUTER_API_KEY, interactions)
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
    
    await ctx.send(f"✅ Sent random message to {target_user.display_name} in {channel.mention}.")
    log.info("🎲 Manual random message triggered by admin %s -> %s", ctx.author, target_user)

@bot.command()
@has_permissions(administrator=True)
async def runsummaries(ctx):
    await db_ready_event.wait()
    await ctx.send("Starting manual summarization pass...")
    try:
        async with memory_mgr.db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cur:
            rows = await cur.fetchall()
        for user_id, channel_id in rows:
            await memory_mgr.summarize_user_history(user_id, channel_id, http_client, OPENROUTER_API_KEY)
            await asyncio.sleep(1)

        async with memory_mgr.db.execute("SELECT DISTINCT channel_id FROM memory") as cur:
            chan_rows = await cur.fetchall()
        guild_ids = set()
        for (chid,) in chan_rows:
            ch = bot.get_channel(int(chid))
            if ch and getattr(ch, "guild", None):
                guild_ids.add(str(ch.guild.id))
        for gid in guild_ids:
            await memory_mgr.summarize_guild_history(gid, bot, http_client, OPENROUTER_API_KEY)
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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CheckFailure):
        await ctx.send("⛔ You don’t have permission to use that command.")

if not DISCORD_BOT_TOKEN:
    log.error("❌ DISCORD_BOT_TOKEN not configured in environment. Exiting.")
else:
    bot.run(DISCORD_BOT_TOKEN)
