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
import aiosqlite
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

PROXY_ID = 1248244979151671398

# ------------------------
# Logging setup
# ------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("heidi")

# ------------------------
# Dummy web server for Koyeb
# ------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ------------------------
# Environment setup
# ------------------------
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY not loaded from .env")

# ------------------------
# Discord bot setup
# ------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
COOLDOWN_SECONDS = 15
DAILY_LIMIT = 1000

# ------------------------
# Daily quota tracking
# ------------------------
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
        
# -----------------------------------------
# Helper to safely send long messages
# -----------------------------------------
async def safe_send(channel: discord.abc.Messageable, content: str, max_len: int = 2000):
    """Splits content into chunks so Discord doesn't reject it."""
    if not content:
        return
    for i in range(0, len(content), max_len):
        chunk = content[i:i+max_len]
        await channel.send(chunk)
        
# ------------------------
# Queue Manager Integration
# ------------------------
queue_mgr = QueueManager("queued_messages.db")

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

# ------------------------
# SQLite setup
# ------------------------
DB_FILE = "heidi_memory.db"
ROW_LIMIT = 500000
db: Optional[aiosqlite.Connection] = None
http_client: Optional[httpx.AsyncClient] = None

async def prune_memory():
    global db
    try:
        async with db.execute("SELECT COUNT(*) FROM memory") as cursor:
            total = (await cursor.fetchone())[0]
        if total > ROW_LIMIT:
            to_delete = total - ROW_LIMIT
            await db.execute(
                "DELETE FROM memory WHERE id IN (SELECT id FROM memory ORDER BY id ASC LIMIT ?)",
                (to_delete,)
            )
            await db.commit()
            log.info("🗑️ Pruned %s old messages (kept %s).", to_delete, ROW_LIMIT)
    except Exception as e:
        log.error("❌ prune_memory failed: %s", e)

async def save_message(user_id: int, channel_id: int, role: str, message: str):
    global db, db_lock
    try:
        if db_lock:
            async with db_lock:
                await db.execute(
                    "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
                    (str(user_id), str(channel_id), role, message)
                )
                await db.commit()
        else:
            await db.execute(
                "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
                (str(user_id), str(channel_id), role, message)
            )
            await db.commit()
        await prune_memory()
    except Exception as e:
        log.error("❌ save_message failed: %s", e)

async def load_history(user_id: int, channel_id: int, limit: int = 20):
    global db
    async with db.execute(
        "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
        (str(user_id), str(channel_id), limit)
    ) as cursor:
        rows = await cursor.fetchall()
    return rows[::-1]

async def load_recent_interactions(limit=10):
    global db
    async with db.execute(
        "SELECT role, message FROM memory ORDER BY timestamp DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [(r[0], r[1]) for r in rows[::-1]]

# ------------------------
# User profile helpers (store latest names)
# ------------------------
async def upsert_user_profile(member: discord.Member):
    global db, db_lock
    try:
        if member is None:
            return
        if db_lock:
            async with db_lock:
                await db.execute(
                    "INSERT INTO user_profiles (user_id, username, display_name, discriminator, nick, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id) DO UPDATE SET username=?, display_name=?, discriminator=?, nick=?, last_seen=CURRENT_TIMESTAMP",
                    (
                        str(member.id),
                        str(member.name),
                        str(getattr(member, "display_name", member.name)),
                        str(getattr(member, "discriminator", "")),
                        str(getattr(member, "nick", "")),
                        str(member.name),
                        str(getattr(member, "display_name", member.name)),
                        str(getattr(member, "discriminator", "")),
                        str(getattr(member, "nick", "")),
                    )
                )
                await db.commit()
        else:
            await db.execute(
                "INSERT INTO user_profiles (user_id, username, display_name, discriminator, nick, last_seen) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET username=?, display_name=?, discriminator=?, nick=?, last_seen=CURRENT_TIMESTAMP",
                (
                    str(member.id),
                    str(member.name),
                    str(getattr(member, "display_name", member.name)),
                    str(getattr(member, "discriminator", "")),
                    str(getattr(member, "nick", "")),
                    str(member.name),
                    str(getattr(member, "display_name", member.name)),
                    str(getattr(member, "discriminator", "")),
                    str(getattr(member, "nick", "")),
                )
            )
            await db.commit()
    except Exception as e:
        log.debug("⚠️ upsert_user_profile failed: %s", e)

async def fetch_profile_from_db(user_id: int):
    global db
    try:
        async with db.execute("SELECT username, display_name, discriminator, nick FROM user_profiles WHERE user_id=? LIMIT 1", (str(user_id),)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"username": row[0], "display_name": row[1], "discriminator": row[2], "nick": row[3]}
    except Exception as e:
        log.debug("⚠️ fetch_profile_from_db failed: %s", e)
        return None

# ------------------------
# Long-term summary and short-term context cache
# ------------------------
async def summarize_user_history(user_id, channel_id):
    try:
        log.info("🟡 Starting summarization for user=%s channel=%s", user_id, channel_id)
        async with db.execute(
            "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT 50",
            (str(user_id), str(channel_id))
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            log.info("ℹ️ No messages found to summarize for user=%s channel=%s", user_id, channel_id)
            return

        prompt = render_summary_prompt(rows[::-1])
        model = get_model("summary")

        if not await can_make_request():
            log.info("⏳ Skipping summary for %s/%s due to quota.", user_id, channel_id)
            return

        log.info("📡 Sending summarization request for user=%s channel=%s", user_id, channel_id)

        resp = await http_client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                "X-Title": "Heidi Discord Bot",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a concise uncensored summarizer."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60.0,
        )

        if resp.status_code == 429:
            log.warning("⚠️ Rate limited while summarizing %s/%s.", user_id, channel_id)
            return

        resp.raise_for_status()
        data = resp.json()
        summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        if not summary:
            log.info("ℹ️ Empty summary returned for user=%s channel=%s", user_id, channel_id)
            return

        try:
            if db_lock:
                async with db_lock:
                    await db.execute(
                        "INSERT INTO memory_summary (user_id, channel_id, summary) VALUES (?, ?, ?) "
                        "ON CONFLICT(user_id, channel_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                        (str(user_id), str(channel_id), summary, summary)
                    )
                    await db.commit()
            else:
                await db.execute(
                    "INSERT INTO memory_summary (user_id, channel_id, summary) VALUES (?, ?, ?)"
                    "ON CONFLICT(user_id, channel_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                    (str(user_id), str(channel_id), summary, summary)
                )
                await db.commit()
        except Exception as e:
            log.error("❌ Failed to upsert memory_summary: %s", e)
            return

        log.info("✅ Summary updated successfully for user=%s channel=%s", user_id, channel_id)
        log.debug("🧠 Summary content: %s", summary)

    except Exception as e:
        log.error("❌ Error summarizing user history for %s/%s: %s", user_id, channel_id, e)

async def summarize_guild_history(guild_id):
    try:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            log.info("ℹ️ Guild %s not found in cache; skipping global summary.", guild_id)
            return

        channel_ids = [str(c.id) for c in guild.text_channels if c.permissions_for(guild.me).read_messages]
        if not channel_ids:
            log.info("ℹ️ No accessible text channels for guild %s; skipping.", guild_id)
            return

        placeholders = ",".join("?" for _ in channel_ids)
        query = f"""
            SELECT role, message FROM memory
            WHERE channel_id IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT 200
        """
        async with db.execute(query, channel_ids) as cursor:
            rows = await cursor.fetchall()
        if not rows:
            log.info("ℹ️ No messages to summarize for guild %s", guild_id)
            return

        prompt = render_guild_summary_prompt(rows[::-1])
        model = get_model("summary")

        if not await can_make_request():
            log.info("⏳ Skipping guild summary for %s due to quota.", guild_id)
            return

        log.info("📡 Sending guild summarization request for guild=%s", guild_id)

        resp = await http_client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                "X-Title": "Heidi Discord Bot",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a concise uncensored summarizer."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60.0,
        )

        if resp.status_code == 429:
            log.warning("⚠️ Rate limited while summarizing guild %s.", guild_id)
            return
        resp.raise_for_status()
        data = resp.json()
        summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not summary:
            log.info("ℹ️ Empty guild summary for %s", guild_id)
            return

        if db_lock:
            async with db_lock:
                await db.execute(
                    "INSERT INTO memory_summary_global (guild_id, summary) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                    (str(guild_id), summary, summary)
                )
                await db.commit()
        else:
            await db.execute(
                "INSERT INTO memory_summary_global (guild_id, summary) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                (str(guild_id), summary, summary)
            )
            await db.commit()
            
        log.info("✅ Guild summary updated for %s", guild_id)
    except Exception as e:
        log.error("❌ Error summarizing guild %s: %s", guild_id, e)

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
    global db, http_client, db_lock, queue_db_lock
    log.info("🔌 on_ready triggered - initializing DBs and background tasks.")
    db = await aiosqlite.connect(DB_FILE)
    db_lock = asyncio.Lock()
    queue_db_lock = asyncio.Lock()

    await db.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        role TEXT,
        message TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    await db.commit()

    await db.execute("""
    CREATE TABLE IF NOT EXISTS persona (
        id INTEGER PRIMARY KEY,
        text TEXT
    )
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS memory_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        summary TEXT,
        last_update DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, channel_id)
    )
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS context_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        context TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS memory_summary_global (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT UNIQUE,
        summary TEXT,
        last_update DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    await db.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        display_name TEXT,
        discriminator TEXT,
        nick TEXT,
        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur = await db.execute("SELECT COUNT(*) FROM persona")
    count = (await cur.fetchone())[0]
    if count == 0:
        await db.execute("INSERT INTO persona (id, text) VALUES (?, ?)", (1, DEFAULT_PERSONA))
        await db.commit()

    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    await queue_mgr.init()
    asyncio.create_task(queue_worker())

    async def daily_reflection():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                interactions = await load_recent_interactions(limit=10)
                await reflect_and_update_persona(db, http_client, OPENROUTER_API_KEY, interactions)
            except Exception as e:
                log.error("❌ daily_reflection task error: %s", e)
            await asyncio.sleep(86400)
    asyncio.create_task(daily_reflection())

    log.info("✅ Logged in as %s", bot.user.name)

# ------------------------
# Ask OpenRouter
# ------------------------
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> Optional[str]:
    if not await can_make_request():
        await queue_mgr.enqueue(user_id, channel_id, prompt)
        return None

    persona = await get_persona(db)
    messages = []
    messages += render_system_prompt(persona, PROXY_ID)

    profile = None
    if discord_user:
        display = getattr(discord_user, "display_name", None) or getattr(discord_user, "name", str(discord_user))
        username = getattr(discord_user, "name", display)
        profile = {"username": username, "display_name": display, "id": str(discord_user.id)}
        try:
            await upsert_user_profile(discord_user)
        except Exception:
            pass
    else:
        prof = await fetch_profile_from_db(user_id)
        if prof:
            profile = {"username": prof.get("username"), "display_name": prof.get("display_name"), "id": str(user_id)}
    messages += render_user_mapping(profile)

    # Load long-term summary if present (per-user/channel)
    try:
        async with db.execute(
            "SELECT summary FROM memory_summary WHERE user_id=? AND channel_id=? ORDER BY last_update DESC LIMIT 1",
            (str(user_id), str(channel_id))
        ) as cursor:
            row = await cursor.fetchone()
        if row and row[0]:
            messages.append({"role": "system", "content": f"Long-term memory summary: {row[0]}"})
    except Exception as e:
        log.error("❌ Failed to load memory_summary: %s", e)

    # Load global guild summary if possible
    try:
        chan = bot.get_channel(int(channel_id))
        if chan and chan.guild:
            gid = str(chan.guild.id)
            async with db.execute(
                "SELECT summary FROM memory_summary_global WHERE guild_id=? LIMIT 1", (gid,)
            ) as cursor:
                row = await cursor.fetchone()
            if row and row[0]:
                messages.append({"role": "system", "content": f"Server-wide memory: {row[0]}"})
            messages.append({"role": "system", "content": f"Channel: {getattr(chan, 'name', str(channel_id))}, Guild: {getattr(chan.guild, 'name', '')}, guild_id: {gid}"})
    except Exception as e:
        log.error("❌ Failed to load memory_summary_global: %s", e)

    # Load short-term context cache entries
    try:
        async with db.execute(
            "SELECT context FROM context_cache WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT 2",
            (str(user_id), str(channel_id))
        ) as cursor:
            context_rows = await cursor.fetchall()
        if context_rows:
            joined_context = "\n".join([r[0] for r in context_rows])
            messages.append({"role": "system", "content": f"Recent context: {joined_context}"})
    except Exception as e:
        log.error("❌ Failed to load context_cache: %s", e)

    history = await load_history(user_id, channel_id)
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
        await save_message(user_id, channel_id, "user", prompt)
        await save_message(user_id, channel_id, "heidi", reply)
    except Exception as e:
        log.error("❌ Failed to save messages to DB: %s", e)

    return reply

# ------------------------
# Message handler
# ------------------------
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    try:
        await upsert_user_profile(message.author)
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
    interactions = await load_recent_interactions(limit=10)
    await reflect_and_update_persona(db, http_client, OPENROUTER_API_KEY, interactions)
    await ctx.send("Persona reflection done. Check logs for updates.")

@bot.command()
async def persona(ctx):
    persona = await get_persona(db)
    if not persona:
        await ctx.send("No persona set.")
        return
    await safe_send(ctx.channel, f"```{persona}```")

@bot.command()
async def queue(ctx):
    total, mem_count, db_count = await queue_mgr.pending_count()
    await ctx.send(f"📨 Queued messages: {total} (memory: {mem_count}, stored: {db_count})")

@bot.command()
@has_permissions(administrator=True)
async def clearqueue(ctx):
    await queue_mgr.clear()
    await ctx.send(f"🗑️ Cleared queued messages from memory and persistent queue.")

@bot.command()
@has_permissions(administrator=True)
async def setpersona(ctx, *, text: str):
    try:
        await set_persona(db, text)
        await ctx.send("✅ Persona updated successfully.")
        log.info("📝 Persona manually updated by admin %s.", ctx.author)
    except Exception as e:
        log.error("❌ Failed to update persona: %s", e)
        await ctx.send("❌ Error updating persona. Check logs.")

@bot.command()
@has_permissions(administrator=True)
async def randommsg(ctx):
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
        await upsert_user_profile(target_user)
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
    await ctx.send("Starting manual summarization pass...")
    try:
        async with db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cur:
            rows = await cur.fetchall()
        for user_id, channel_id in rows:
            await summarize_user_history(user_id, channel_id)
            await asyncio.sleep(1)

        async with db.execute("SELECT DISTINCT channel_id FROM memory") as cur:
            chan_rows = await cur.fetchall()
        guild_ids = set()
        for (chid,) in chan_rows:
            ch = bot.get_channel(int(chid))
            if ch and getattr(ch, "guild", None):
                guild_ids.add(str(ch.guild.id))
        for gid in guild_ids:
            await summarize_guild_history(gid)
            await asyncio.sleep(1)

        await ctx.send("Manual summarization complete.")
    except Exception as e:
        log.exception("Error in manual summarization: %s", e)
        await ctx.send(f"Error while running summaries: {e}")

@bot.command()
@has_permissions(administrator=True)
async def resetmemory(ctx):
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
        if db_lock:
            async with db_lock:
                await db.execute("DELETE FROM memory")
                await db.execute("DELETE FROM memory_summary")
                await db.execute("DELETE FROM memory_summary_global")
                await db.execute("DELETE FROM context_cache")
                await db.execute("DELETE FROM persona")
                await db.commit()
                await db.execute("INSERT INTO persona (id, text) VALUES (?, ?)", (1, DEFAULT_PERSONA))
                await db.commit()
        else:
            await db.execute("DELETE FROM memory")
            await db.execute("DELETE FROM memory_summary")
            await db.execute("DELETE FROM memory_summary_global")
            await db.execute("DELETE FROM context_cache")
            await db.execute("DELETE FROM persona")
            await db.commit()
            await db.execute("INSERT INTO persona (id, text) VALUES (?, ?)", (1, DEFAULT_PERSONA))
            await db.commit()

        await ctx.send("🧠 All memories, summaries, and persona wiped. Heidi has been fully reset.")
        log.warning("🧨 Heidi's memory and persona have been reset by %s.", ctx.author)
    except Exception as e:
        await ctx.send(f"❌ Error during reset: {e}")
        log.error("❌ Error wiping memory: %s", e)

# ------------------------
# Error handler
# ------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CheckFailure):
        await ctx.send("⛔ You don’t have permission to use that command.")

ROLE_ID = 1425102962556145676
CHANNEL_ID = 1385570983062278268

if not DISCORD_BOT_TOKEN:
    log.error("❌ DISCORD_BOT_TOKEN not configured in environment. Exiting.")
else:
    bot.run(DISCORD_BOT_TOKEN)
