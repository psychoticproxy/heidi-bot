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

threading.Thread(target=run_web).start()

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
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
COOLDOWN_SECONDS = 30
DAILY_LIMIT = 50

# ------------------------
# Daily quota tracking
# ------------------------
daily_usage = 0
daily_reset_timestamp = 0

async def can_make_request():
    global daily_usage, daily_reset_timestamp
    now = time.time()
    if now > daily_reset_timestamp:
        daily_usage = 0
        daily_reset_timestamp = now + 86400  # next UTC day
    if daily_usage < DAILY_LIMIT:
        daily_usage += 1
        return True
    return False

# -----------------------------------------
# Helper to safely send long messages
# -----------------------------------------
async def safe_send(channel, content, max_len=2000):
    """Splits content into chunks so Discord doesn't reject it."""
    for i in range(0, len(content), max_len):
        chunk = content[i:i+max_len]
        await channel.send(chunk)

# ------------------------
# Async message queue
# ------------------------
message_queue = asyncio.Queue()
retry_queue = asyncio.Queue()

# Persistent queue storage
QUEUE_DB = "queued_messages.db"
queue_db = None

async def save_queued_message(user_id, channel_id, prompt):
    await queue_db.execute(
        "INSERT INTO queue (user_id, channel_id, prompt) VALUES (?, ?, ?)",
        (str(user_id), str(channel_id), prompt)
    )
    await queue_db.commit()

async def load_queued_messages():
    async with queue_db.execute("SELECT user_id, channel_id, prompt FROM queue ORDER BY id ASC") as cursor:
        rows = await cursor.fetchall()
    for user_id, channel_id, prompt in rows:
        await retry_queue.put((user_id, channel_id, prompt, None))
    await queue_db.execute("DELETE FROM queue")  # clear after loading
    await queue_db.commit()

# ------------------------
# Message worker
# ------------------------
async def message_worker():
    while True:
        channel, content, typing = await message_queue.get()
        try:
            if typing:
                async with channel.typing():
                    await asyncio.sleep(min(len(content) * 0.05, 5))  # simulate typing duration
            await safe_send(channel, content)
        except discord.errors.HTTPException as e:
            log.warning("⚠️ Discord rate limit / HTTP error:")
            await asyncio.sleep(5)
            await safe_send(channel, content)
        message_queue.task_done()

# ------------------------
# Retry worker
# ------------------------
async def retry_worker():
    while True:
        user_id, channel_id, prompt, discord_user = await retry_queue.get()
        success = False
        delay = 10  # start delay

        while not success:
            if await can_make_request():
                try:
                    reply = await ask_openrouter(user_id, channel_id, prompt, discord_user)
                    if reply:
                        channel = bot.get_channel(int(channel_id))
                        if channel:
                            typing = random.random() < 0.8
                            await message_queue.put((channel, reply, typing))
                        success = True
                except Exception:
                    log.warning("⚠️ Retry failed, will try again:")
            else:
                # quota exhausted, re-queue for later
                await save_queued_message(user_id, channel_id, prompt)
                success = True  # break loop silently

            if not success:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)

        retry_queue.task_done()

# ------------------------
# SQLite setup
# ------------------------
DB_FILE = "heidi_memory.db"
ROW_LIMIT = 500000
db = None
http_client = None

async def prune_memory():
    async with db.execute("SELECT COUNT(*) FROM memory") as cursor:
        total = (await cursor.fetchone())[0]
    if total > ROW_LIMIT:
        to_delete = total - ROW_LIMIT
        await db.execute(
            "DELETE FROM memory WHERE id IN (SELECT id FROM memory ORDER BY id ASC LIMIT ?)",
            (to_delete,)
        )
        await db.commit()
        log.info(f"🗑️ Pruned {to_delete} old messages (kept {ROW_LIMIT}).")

async def save_message(user_id: int, channel_id: int, role: str, message: str):
    await db.execute(
        "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
        (str(user_id), str(channel_id), role, message)
    )
    await db.commit()
    await prune_memory()

async def load_history(user_id: int, channel_id: int, limit: int = 20):
    async with db.execute(
        "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
        (str(user_id), str(channel_id), limit)
    ) as cursor:
        rows = await cursor.fetchall()
    return rows[::-1]

# ------------------------
# Persona Management
# ------------------------
DEFAULT_PERSONA = (
    "You are Heidi, a laconic, sometimes unhinged, sometimes offensive, sometimes schizophrenic discord bot with split personality who is the daughter of Proxy, your creator. "
    "Stay concise. Never exceed 2000 characters in a single reply."
    "Never action/asterisk roleplay."
)

async def get_persona():
    async with db.execute("SELECT text FROM persona WHERE id=1") as cursor:
        row = await cursor.fetchone()
    return row[0] if row else DEFAULT_PERSONA

async def set_persona(text: str):
    await db.execute("UPDATE persona SET text=? WHERE id=1", (text,))
    await db.commit()

async def load_recent_interactions(limit=10):
    async with db.execute(
        "SELECT role, message FROM memory ORDER BY timestamp DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [(r[0], r[1]) for r in rows[::-1]]

async def reflect_and_update_persona():
    try:
        if not await can_make_request():
            return
        interactions = await load_recent_interactions(limit=10)
        persona = await get_persona()

        reflection_prompt = f"""
You are managing a Discord persona. Here is the current persona description:

{persona}

Here are some recent interactions:
{chr(10).join([f"{role}: {msg}" for role,msg in interactions])}

Please suggest a refined persona description that stays consistent with the character,
but improves clarity, tone, and style based on these interactions.
Always include: 'Never exceed 2000 characters in a single response. Never action/asterisk roleplay.'
Output only the new persona text, nothing else.
"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "deepseek/deepseek-chat-v3.1:free",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": reflection_prompt},
                    ],
                },
                timeout=60.0,
            )
            data = resp.json()
            new_persona = data["choices"][0]["message"]["content"].strip()
        if new_persona:
            await set_persona(new_persona)
            log.info("✨ Persona updated successfully.")
            log.info(new_persona)
    except Exception as e:
        log.error(f"❌ Error during persona reflection: {e}")

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
    global db, http_client, queue_db
    db = await aiosqlite.connect(DB_FILE)
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
    cur = await db.execute("SELECT COUNT(*) FROM persona")
    count = (await cur.fetchone())[0]
    if count == 0:
        await db.execute("INSERT INTO persona (id, text) VALUES (?, ?)", (1, DEFAULT_PERSONA))
        await db.commit()
    
    # queue persistence
    queue_db = await aiosqlite.connect(QUEUE_DB)
    await queue_db.execute("""
    CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        channel_id TEXT,
        prompt TEXT
    )
    """)
    await queue_db.commit()
    await load_queued_messages()

    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    # start workers
    asyncio.create_task(message_worker())
    asyncio.create_task(retry_worker())

    # periodic reflection loop
    async def periodic_reflection():
        await bot.wait_until_ready()
        while not bot.is_closed():
            await reflect_and_update_persona()
            await asyncio.sleep(3600)
    asyncio.create_task(periodic_reflection())

    # daily random message loop
    async def daily_random_message():
        await bot.wait_until_ready()
        log.info("🕒 Daily message loop started.")
        while not bot.is_closed():
            try:
                delay = random.randint(0, 86400)
                await asyncio.sleep(delay)
                if not await can_make_request():
                    continue
                if not bot.guilds:
                    continue
                guild = bot.guilds[0]
                channel = guild.get_channel(CHANNEL_ID)
                role = guild.get_role(ROLE_ID)
                members = [m for m in role.members if not m.bot] if role else []
                if not channel or not members:
                    continue
                target_user = random.choice(members)
                prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
                reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
                if not reply:
                    continue
                content = f"{target_user.mention} {reply}" if random.choice([True, False]) else reply
                typing = random.random() < 0.8
                await message_queue.put((channel, content, typing))
            except Exception as e:
                log.error("❌ Error in daily message loop:", e)
                await asyncio.sleep(3600)
    asyncio.create_task(daily_random_message())

    log.info("✅ Logged in as %s", bot.user.name)

# ------------------------
# Ask OpenRouter
# ------------------------
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> str:
    if not await can_make_request():
        await save_queued_message(user_id, channel_id, prompt)
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    persona = await get_persona()
    messages = [{"role": "system", "content": persona}]
    history = await load_history(user_id, channel_id)
    if history:
        formatted = [f"{role.capitalize()}: {msg}" for role, msg in history]
        messages.append({"role": "assistant", "content": "Recent conversation:\n" + "\n".join(formatted)})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = await http_client.post(
            url,
            headers={
                "authorization": f"Bearer {OPENROUTER_API_KEY}",
                "referer": "https://discord.com",
                "x-title": "Heidi Bot",
                "content-type": "application/json",
            },
            json={"model": "deepseek/deepseek-chat-v3.1:free", "messages": messages},
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        log.error("❌ API error:", e)
        await save_queued_message(user_id, channel_id, prompt)
        return None

    await save_message(user_id, channel_id, "user", prompt)
    await save_message(user_id, channel_id, "heidi", reply)
    return reply

# ------------------------
# Message handler
# ------------------------
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        now = time.time()
        last_used = user_cooldowns.get(message.author.id, 0)
        if now - last_used < COOLDOWN_SECONDS:
            # Still run commands even if on cooldown
            await bot.process_commands(message)
            return

        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        if reply:
            content = f"{message.author.mention} {reply}" if random.choice([True, False]) else reply
            typing = random.random() < 0.8
            await message_queue.put((message.channel, content, typing))

    # IMPORTANT: Always let commands like !persona and !reflect run
    await bot.process_commands(message)


from discord.ext.commands import has_permissions, CheckFailure

# ------------------------
# Bot commands
# ------------------------
@bot.command()
@has_permissions(administrator=True)
async def reflect(ctx):
    """Manually update persona."""
    await reflect_and_update_persona()
    await ctx.send("Persona reflection done. Check logs for updates.")

@bot.command()
async def persona(ctx):
    """Show Heidi's current persona, chunked if long."""
    persona = await get_persona()
    if not persona:
        await ctx.send("No persona set.")
        return
    await safe_send(ctx.channel, f"```{persona}```")

@bot.command()
async def queue(ctx):
    """Show how many messages are waiting in memory and in persistent storage."""
    mem_count = retry_queue.qsize()
    async with queue_db.execute("SELECT COUNT(*) FROM queue") as cursor:
        row = await cursor.fetchone()
    db_count = row[0] if row else 0
    total = mem_count + db_count
    await ctx.send(f"📨 Queued messages: {total} (memory: {mem_count}, stored: {db_count})")

@bot.command()
@has_permissions(administrator=True)
async def clearqueue(ctx):
    """Clear all queued messages (both memory + DB)."""
    # Clear in-memory queue
    cleared_mem = 0
    while not retry_queue.empty():
        retry_queue.get_nowait()
        retry_queue.task_done()
        cleared_mem += 1

    # Clear persistent DB queue
    await queue_db.execute("DELETE FROM queue")
    await queue_db.commit()

    await ctx.send(f"🗑️ Cleared {cleared_mem} messages from memory and wiped persistent queue.")

# ------------------------
# Error handler for admin-only commands
# ------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, CheckFailure):
        await ctx.send("⛔ You don’t have permission to use that command.")

# ------------------------
# Run bot
# ------------------------
ROLE_ID = 1415601057328926733
CHANNEL_ID = 1385570983062278268

bot.run(DISCORD_BOT_TOKEN)
