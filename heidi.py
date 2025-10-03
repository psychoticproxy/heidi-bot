import threading
from flask import Flask
import os
import discord
from discord.ext import commands
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

async def message_worker():
    while True:
        channel, content, typing = await message_queue.get()

        # Defensive guard: skip empty content
        if not content:
            log.warning("⚠️ Skipping empty content in message_queue")
            message_queue.task_done()
            continue

        try:
            if typing:
                # use typing context manager; this doesn't block other tasks
                async with channel.typing():
                    await asyncio.sleep(min(len(content) * 0.05, 5))  # simulate typing duration
            await safe_send(channel, content)
        except discord.errors.HTTPException as e:
            log.warning("⚠️ Discord rate limit / HTTP error; retrying send", exc_info=e)
            await asyncio.sleep(5)  # simple retry delay
            try:
                await safe_send(channel, content)
            except Exception as e2:
                log.error("Failed to send message after retry", exc_info=e2)
        finally:
            message_queue.task_done()

#--------------------
# Retry worker
#--------------------
async def retry_worker():
    """
    Continuously processes retry_queue. For each failed request it will
    keep trying until it gets a reply (infinite retries), using exponential
    backoff (capped) so we don't hammer the API.
    """
    await bot.wait_until_ready()
    while True:
        user_id, channel_id, prompt, discord_user = await retry_queue.get()
        delay = 10  # initial retry delay (seconds)
        max_delay = 300  # 5 minutes max

        log.info("🔁 Starting retries for user=%s channel=%s prompt=%.40s...", user_id, channel_id, prompt)
        while True:
            try:
                # call ask_openrouter but DON'T allow it to re-enqueue on failure,
                # retry_worker will handle the backoff and reattempts.
                reply = await ask_openrouter(user_id, channel_id, prompt, discord_user, allow_enqueue=False)
                if reply:
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        content = f"{discord_user.mention} {reply}" if random.choice([True, False]) else reply
                        typing = random.random() < 0.8
                        await message_queue.put((channel, content, typing))
                        log.info("✅ Retry successful for user=%s channel=%s", user_id, channel_id)
                    else:
                        log.warning("⚠️ Could not find channel %s to deliver retry reply", channel_id)
                    break  # success -> stop retrying this job
                else:
                    # no reply returned (likely API still rate-limiting) -> wait then try again
                    log.info("⚠️ No reply yet; will retry after %s seconds", delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)

            except Exception as e:
                # Unexpected exception while retrying: log and back off
                log.warning("⚠️ Retry attempt raised exception; will try again", exc_info=e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        retry_queue.task_done()

# ------------------------
# SQLite (async) setup
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
        log.info("🗑️ Pruned %d old messages (kept %d).", to_delete, ROW_LIMIT)

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

# --------------------
# Persona Management
# --------------------
DEFAULT_PERSONA = (
    "You are Heidi, a laconic, sometimes unhinged, sometimes offensive, sometimes schizophrenic discord bot with split personality who is the daughter of Proxy, your creator. "
    "Stay concise. Never exceed 2000 characters in a single reply."
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
    """Ask the model to refine the persona based on recent interactions."""
    try:
        interactions = await load_recent_interactions(limit=10)
        persona = await get_persona()

        reflection_prompt = f"""
You are managing a Discord persona. Here is the current persona description:

{persona}

Here are some recent interactions:
{chr(10).join([f"{role}: {msg}" for role,msg in interactions])}

Please suggest a refined persona description that stays consistent with the character,
but improves clarity, tone, and style based on these interactions.
Always include: 'Never exceed 2000 characters in a single response.'
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

            # handle rate limiting gracefully here as well
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait_time = int(retry_after) if retry_after and retry_after.isdigit() else 30
                log.warning("⚠️ Persona reflection rate-limited. Waiting %s seconds.", wait_time)
                await asyncio.sleep(wait_time)
                # we could re-run, but let's just skip and let the scheduled loop call it again later
                return

            data = resp.json()
            new_persona = data["choices"][0]["message"]["content"].strip()

        if new_persona:
            await set_persona(new_persona)
            log.info("✨ Persona updated successfully.")
        else:
            log.info("Reflection returned empty persona, skipping.")

    except Exception as e:
        log.exception("❌ Error during persona reflection")

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
    global db, http_client
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
    
    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    # start workers
    asyncio.create_task(message_worker())
    asyncio.create_task(daily_random_message())
    asyncio.create_task(retry_worker())

    # persona reflection loop
    async def periodic_reflection():
        await bot.wait_until_ready()
        while not bot.is_closed():
            await reflect_and_update_persona()
            await asyncio.sleep(3600)  # every hour
    asyncio.create_task(periodic_reflection())

    log.info("✅ Logged in as %s", bot.user.name)

# ------------------------
# Ask OpenRouter
# ------------------------
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user, allow_enqueue: bool = True) -> str:
    """
    Attempt to call OpenRouter once.
    - If success: returns reply string.
    - If rate-limited (429) or other error:
        - if allow_enqueue is True: enqueue the request for retry_worker and return None
        - if allow_enqueue is False: just return None (caller will handle retry/backoff)
    """
    url = "https://openrouter.ai/api/v1/chat/completions"

    persona = await get_persona()

    messages = [
        {"role": "system", "content": persona},
    ]

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

        # If rate limited, do not hammer the API. Let retry_worker handle reattempts.
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            wait_time = None
            if retry_after and retry_after.isdigit():
                wait_time = int(retry_after)

            if wait_time:
                log.warning("⚠️ OpenRouter returned 429. Retry-After=%s seconds.", wait_time)
            else:
                log.warning("⚠️ OpenRouter returned 429. No Retry-After header present.")

            if allow_enqueue:
                # hand off to retry worker (which will perform backoff)
                await retry_queue.put((user_id, channel_id, prompt, discord_user))
                log.info("🔁 Enqueued request for later retry (user=%s channel=%s).", user_id, channel_id)
            return None

        # If other errors, raise so the except below handles them
        resp.raise_for_status()

        data = resp.json()
        # Be defensive - ensure structure is present
        reply = data["choices"][0]["message"]["content"]

    except httpx.HTTPStatusError as e:
        log.exception("❌ API HTTP error when calling OpenRouter")
        if allow_enqueue:
            await retry_queue.put((user_id, channel_id, prompt, discord_user))
        return None
    except Exception as e:
        log.exception("❌ API error when calling OpenRouter")
        if allow_enqueue:
            await retry_queue.put((user_id, channel_id, prompt, discord_user))
        return None

    # Save into memory and return
    try:
        await save_message(user_id, channel_id, "user", prompt)
        await save_message(user_id, channel_id, "heidi", reply)
    except Exception:
        log.exception("Failed to save messages to DB (non-fatal)")

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
            return
        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        # note: ask_openrouter will enqueue into retry_queue if the API is rate-limiting
        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        if reply:  # only enqueue if we got a real reply
            content = f"{message.author.mention} {reply}" if random.choice([True, False]) else reply
            typing = random.random() < 0.8
            await message_queue.put((message.channel, content, typing))
        else:
            log.info("⚠️ Skipped enqueuing because reply was None (it was enqueued for retry).")

# ------------------------
# Manual reflection command
# ------------------------
@bot.command()
async def reflect(ctx):
    """Manually trigger persona reflection."""
    await reflect_and_update_persona()
    await ctx.send("Persona reflection done. Check logs for updates.")

# ------------------------
# Daily random messages
# ------------------------
ROLE_ID = 1415601057328926733
CHANNEL_ID = 1385570983062278268

async def daily_random_message():
    await bot.wait_until_ready()
    log.info("🕒 Daily message loop started.")
    while not bot.is_closed():
        try:
            delay = random.randint(0, 86400)
            await asyncio.sleep(delay)

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
            # use allow_enqueue=True here (default) so the job is enqueued if rate-limited
            reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
            if reply:
                content = f"{target_user.mention} {reply}" if random.choice([True, False]) else reply
                typing = random.random() < 0.8
                await message_queue.put((channel, content, typing))
                log.info("💬 Sent daily message to %s", target_user.display_name)
            else:
                log.info("⚠️ Daily random message enqueued for retry due to rate limit or error.")
        except Exception as e:
            log.exception("❌ Error in daily message loop (sleeping 1h)")
            await asyncio.sleep(3600)

# ------------------------
# Run bot
# ------------------------
bot.run(DISCORD_BOT_TOKEN)
