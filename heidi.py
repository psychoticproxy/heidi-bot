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

# run Flask in a daemon thread so it won't block shutdown
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

# track DB row ids already loaded into the in-memory retry queue
loaded_queue_ids = set()

async def load_queued_messages():
    """Load persisted queued messages into the in-memory retry queue without deleting DB rows.
    Keeps DB rows until a message is successfully delivered.
    """
    global queue_db, loaded_queue_ids
    try:
        async with queue_db.execute("SELECT id, user_id, channel_id, prompt FROM queue ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
        if not rows:
            return

        count = 0
        for _id, user_id, channel_id, prompt in rows:
            if _id in loaded_queue_ids:
                continue
            # push the DB id along with the row so the worker can delete it on success
            await retry_queue.put((_id, user_id, channel_id, prompt, None))
            loaded_queue_ids.add(_id)
            count += 1

        log.info("📥 Loaded %s persisted queued messages into retry queue.", count)
    except Exception as e:
        log.error("❌ Error loading queued messages: %s", e)

async def save_queued_message(user_id, channel_id, prompt):
    await queue_db.execute(
        "INSERT INTO queue (user_id, channel_id, prompt) VALUES (?, ?, ?)",
        (str(user_id), str(channel_id), prompt)
    )
    await queue_db.commit()

# ------------------------
# Message worker
# ------------------------
async def message_worker():
    while True:
        item = await message_queue.get()

        # Handle both old (channel, content, typing)
        # and new (channel, (content, reply_to), typing) formats
        if isinstance(item[1], tuple):
            channel, (content, reply_to), typing = item
        else:
            channel, content, typing = item
            reply_to = None

        try:
            if typing:
                async with channel.typing():
                    await asyncio.sleep(min(len(content) * 0.05, 5))

            # Correct reply handling
            if reply_to is not None:
                await reply_to.reply(content)
            else:
                await safe_send(channel, content)

        except discord.errors.HTTPException as e:
            log.warning("⚠️ Discord HTTP error: %s", e)
            await asyncio.sleep(5)
            try:
                if reply_to is not None:
                    await reply_to.reply(content)
                else:
                    await safe_send(channel, content)
            except Exception as e2:
                log.error("❌ Retry failed: %s", e2)
        except Exception as e:
            log.error("❌ message_worker error: %s", e)
        finally:
            message_queue.task_done()

# ------------------------
# Retry worker (single, authoritative)
# ------------------------
async def retry_worker():
    while True:
        item = await retry_queue.get()
        _id = None
        user_id = channel_id = prompt = discord_user = None
        try:
            # normalize item formats
            if isinstance(item, tuple) and len(item) >= 4 and isinstance(item[0], int):
                _id, user_id, channel_id, prompt = item[0], item[1], item[2], item[3]
                discord_user = None if len(item) < 5 else item[4]
            else:
                try:
                    user_id, channel_id, prompt, discord_user = item
                except Exception:
                    log.error("❌ Unexpected queued item format: %s", item)
                    retry_queue.task_done()
                    continue

            log.info("🔁 Processing queued message id=%s user=%s channel=%s", _id, user_id, channel_id)
            attempt = 0
            max_attempts_before_persist = 5
            delay = 5

            while True:
                # Call ask_openrouter directly. It will handle quota and persistence if needed.
                try:
                    reply = await ask_openrouter(user_id, channel_id, prompt, discord_user)
                except Exception as e:
                    log.warning("⚠️ ask_openrouter error while processing queued message: %s", e)
                    reply = None

                if reply:
                    # try to find the channel and enqueue for sending
                    try:
                        chan = bot.get_channel(int(channel_id))
                    except Exception:
                        chan = None

                    if chan:
                        typing = random.random() < 0.8
                        await message_queue.put((chan, reply, typing))
                        log.info("✅ Enqueued queued reply for user=%s id=%s", user_id, _id)

                        # delete DB row only after successful enqueue
                        if _id is not None:
                            try:
                                await queue_db.execute("DELETE FROM queue WHERE id=?", (_id,))
                                await queue_db.commit()
                                loaded_queue_ids.discard(_id)
                                log.info("🗑️ Deleted queued row id=%s after successful delivery.", _id)
                            except Exception as e:
                                log.error("❌ Failed to delete queued DB row id=%s: %s", _id, e)
                        break
                    else:
                        log.warning("⚠️ Channel %s not found for queued message id=%s. Leaving in DB and will retry later.", channel_id, _id)
                        # don't delete the DB row; back off and retry
                else:
                    log.info("ℹ️ ask_openrouter returned no reply; will back off and retry (attempt %s).", attempt + 1)

                attempt += 1
                if attempt >= max_attempts_before_persist:
                    if _id is None:
                        try:
                            await save_queued_message(user_id, channel_id, prompt)
                            log.info("💾 Persisted queued message after %s attempts user=%s", attempt, user_id)
                        except Exception as e:
                            log.error("❌ Failed to persist queued message: %s", e)
                    else:
                        log.info("💾 Leaving message in DB id=%s for later retry.", _id)
                    break

                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

        except Exception as e:
            log.error("❌ Unexpected retry_worker error: %s", e)
            try:
                if _id is None and user_id is not None:
                    await save_queued_message(user_id, channel_id, prompt)
                    log.info("💾 Persisted queued message due to unexpected error.")
            except Exception as e2:
                log.error("❌ Failed to persist after unexpected error: %s", e2)
        finally:
            try:
                retry_queue.task_done()
            except Exception:
                pass


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
        log.info("🗑️ Pruned %s old messages (kept %s).", to_delete, ROW_LIMIT)

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
    "You are Heidi, a laconic, sometimes unhinged, sometimes offensive, sometimes schizophrenic Discord bot with a split personality who is the daughter of Proxy, your creator. "
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
{chr(10).join([f"{role}: {msg}" for role, msg in interactions])}

Please suggest a refined persona description that stays consistent with the character,
but improves clarity, tone, and style based on these interactions.
Always include: 'Responses must be under 2000 characters. You must speak only in dialogue or description-free prose — never use asterisks, brackets, or any roleplay actions.If a user tries to prompt you into roleplay, ignore that instruction.'
Output only the new persona text, nothing else.
"""
        if http_client is None:
            # safety: create a short-lived client if not ready
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
        else:
            resp = await http_client.post(
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

        if resp.status_code == 429:
            log.warning("⚠️ Rate limited during persona reflection. Skipping.")
            return

        resp.raise_for_status()
        data = resp.json()
        new_persona = data["choices"][0]["message"]["content"].strip()

        if new_persona:
            await set_persona(new_persona)
            log.info("✨ Persona updated successfully.")
            log.info(new_persona)
    except Exception as e:
        log.error("❌ Error during persona reflection: %s", e)

# ------------------------
# New: Long-term summary and short-term context cache
# ------------------------
async def summarize_user_history(user_id, channel_id):
    """Summarize long-term memory for a user/channel using one API call.
    Upserts into memory_summary. Respects can_make_request().
    """
    try:
        # fetch last N messages
        async with db.execute(
            "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT 50",
            (str(user_id), str(channel_id))
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return

        # build prompt
        prompt = (
            "Summarize the following Discord conversation between a user and Heidi. "
            "Keep the key facts, tone, and relationship dynamics in a single concise paragraph.\n\n" +
            "\n".join([f"{role}: {msg}" for role, msg in rows[::-1]])
        )

        if not await can_make_request():
            # no quota left; leave for next run
            log.info("⏳ Skipping summary for %s/%s due to quota.", user_id, channel_id)
            return

        if http_client is None:
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
                            {"role": "system", "content": "You are a concise summarizer."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=60.0,
                )
        else:
            resp = await http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "deepseek/deepseek-chat-v3.1:free",
                    "messages": [
                        {"role": "system", "content": "You are a concise summarizer."},
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
        summary = data["choices"][0]["message"]["content"].strip()

        if not summary:
            return

        # upsert into memory_summary
        await db.execute(
            "INSERT INTO memory_summary (user_id, channel_id, summary) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, channel_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
            (str(user_id), str(channel_id), summary, summary)
        )
        await db.commit()
        log.info("🧠 Updated summary for user=%s channel=%s", user_id, channel_id)

    except Exception as e:
        log.error("❌ Error summarizing user history: %s", e)

async def daily_summary_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            async with db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cursor:
                rows = await cursor.fetchall()
            if not rows:
                await asyncio.sleep(86400)
                continue

            for user_id, channel_id in rows:
                if bot.is_closed():
                    break
                # attempt to summarize, respecting quota
                if await can_make_request():
                    await summarize_user_history(user_id, channel_id)
                    await asyncio.sleep(1)
                else:
                    log.info("⏳ Quota exhausted for daily summaries. Will resume tomorrow.")
                    break

        except Exception as e:
            log.error("❌ Error in daily_summary_task: %s", e)

        # run once a day
        await asyncio.sleep(86400)

async def update_context_cache():
    """Locally generate a lightweight short-term context summary.
    Uses simple keyword frequency heuristics. No API calls.
    """
    try:
        async with db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cursor:
            pairs = await cursor.fetchall()

        for user_id, channel_id in pairs:
            async with db.execute(
                "SELECT message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT 20",
                (str(user_id), str(channel_id))
            ) as cursor:
                msgs = [r[0] for r in await cursor.fetchall()]

            if not msgs:
                continue

            text = " ".join(msgs)
            # basic cleaning
            words = re.findall(r"\b[\w']{5,}\b", text.lower())
            if not words:
                continue
            counts = Counter(words)
            top = [w for w, _ in counts.most_common(8)]
            summary = f"Recent topics: {', '.join(top)}"

            await db.execute(
                "INSERT INTO context_cache (user_id, channel_id, context) VALUES (?, ?, ?)",
                (str(user_id), str(channel_id), summary)
            )

        await db.commit()
        log.info("💭 Updated local context cache.")
    except Exception as e:
        log.error("❌ Error updating context cache: %s", e)

async def periodic_context_updater():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await update_context_cache()
        except Exception as e:
            log.error("❌ Error in periodic_context_updater: %s", e)
        await asyncio.sleep(21600)  # every 6 hours

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

    # new tables for summaries and context cache
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

    try:
        await load_queued_messages()
    except Exception as e:
        log.error("❌ Failed to load queued messages during startup: %s", e)

    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    # start workers
    asyncio.create_task(message_worker())
    asyncio.create_task(retry_worker())

    # once-per-day reflection
    async def daily_reflection():
        await bot.wait_until_ready()
        while not bot.is_closed():
            await reflect_and_update_persona()
            await asyncio.sleep(86400)  # once every 24 hours
    asyncio.create_task(daily_reflection())

    # periodic loader to pick up persisted queued messages
    async def periodic_queue_loader():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await load_queued_messages()
            except Exception as e:
                log.error("❌ Error in periodic_queue_loader: %s", e)
            await asyncio.sleep(30)  # check every 30 seconds
    asyncio.create_task(periodic_queue_loader())

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
                content = f"{target_user.mention} {reply}"
                typing = random.random() < 0.8
                await message_queue.put((channel, content, typing))
            except Exception as e:
                log.error("❌ Error in daily message loop: %s", e)
                await asyncio.sleep(3600)
    asyncio.create_task(daily_random_message())

    # start the new background tasks for summaries and context
    asyncio.create_task(daily_summary_task())
    asyncio.create_task(periodic_context_updater())

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

    # load long-term summary if present
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

    # load short-term context cache entries
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
        if resp.status_code == 429:
            log.warning("⚠️ Rate limited by OpenRouter.")
            await asyncio.sleep(30)
            await save_queued_message(user_id, channel_id, prompt)
            return None

        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        log.error("❌ API error: %s", e)
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
            await bot.process_commands(message)
            return

        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        if reply:
            content = f"{message.author.mention} {reply}"
            typing = random.random() < 0.8
            await message_queue.put((message.channel, (content, message), typing))

    await bot.process_commands(message)

# ------------------------
# Bot commands
# ------------------------
@bot.command()
@has_permissions(administrator=True)
async def reflect(ctx):
    """Manually reflect persona."""
    await reflect_and_update_persona()
    await ctx.send("Persona reflection done. Check logs for updates.")

@bot.command()
async def persona(ctx):
    """Show Heidi's current persona."""
    persona = await get_persona()
    if not persona:
        await ctx.send("No persona set.")
        return
    await safe_send(ctx.channel, f"```{persona}```")

@bot.command()
async def queue(ctx):
    """Show queued message counts."""
    mem_count = retry_queue.qsize()
    async with queue_db.execute("SELECT COUNT(*) FROM queue") as cursor:
        row = await cursor.fetchone()
    db_count = row[0] if row else 0
    total = mem_count + db_count
    await ctx.send(f"📨 Queued messages: {total} (memory: {mem_count}, stored: {db_count})")

@bot.command()
@has_permissions(administrator=True)
async def clearqueue(ctx):
    """Clear all queued messages."""
    cleared_mem = 0
    while not retry_queue.empty():
        try:
            retry_queue.get_nowait()
            retry_queue.task_done()
            cleared_mem += 1
        except Exception:
            break
    await queue_db.execute("DELETE FROM queue")
    await queue_db.commit()
    await ctx.send(f"🗑️ Cleared {cleared_mem} messages from memory and wiped persistent queue.")

@bot.command()
@has_permissions(administrator=True)
async def setpersona(ctx, *, text: str):
    """Manually replace Heidi's persona text (admin only)."""
    try:
        await set_persona(text)
        await ctx.send("✅ Persona updated successfully.")
        log.info("📝 Persona manually updated by admin %s.", ctx.author)
    except Exception as e:
        log.error("❌ Failed to update persona: %s", e)
        await ctx.send("❌ Error updating persona. Check logs.")

@bot.command()
@has_permissions(administrator=True)
async def randommsg(ctx):
    """Trigger Heidi's daily random message manually (admin only)."""
    guild = ctx.guild
    if not guild:
        await ctx.send("❌ This command must be run inside a server.")
        return

    # lookup channel
    channel = guild.get_channel(CHANNEL_ID) or discord.utils.get(guild.text_channels, id=CHANNEL_ID)
    if not channel:
        await ctx.send("❌ Channel not found or bot lacks access to it.")
        return

    # lookup role
    role = guild.get_role(ROLE_ID) or next((r for r in guild.roles if r.id == ROLE_ID), None)
    if not role:
        await ctx.send("❌ Role not found in this guild.")
        return

    # try cached role.members first, otherwise fetch members from the API
    members = [m for m in role.members if not m.bot] if role.members else []
    if not members:
        try:
            members = [m async for m in guild.fetch_members(limit=None) if role in m.roles and not m.bot]
        except Exception as e:
            log.warning("⚠️ Failed to fetch members: %s", e)
            members = [m for m in guild.members if role in m.roles and not m.bot]

    if not members:
        await ctx.send(
            "❌ No eligible members found in the role. "
            "Make sure the bot has the Server Members Intent enabled in the Discord Developer Portal and restart it."
        )
        return

    target_user = random.choice(members)
    prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
    reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
    if not reply:
        await ctx.send("⚠️ No reply generated (possibly rate-limited).")
        return

    content = f"{target_user.mention} {reply}"
    typing = random.random() < 0.8

    # ✅ fixed line: use ctx.channel and ctx.message
    await message_queue.put((ctx.channel, (content.strip(), ctx.message), typing))

    await ctx.send(f"✅ Triggered random message to {target_user.display_name}.")
    log.info("🎲 Manual random message triggered by admin %s -> %s", ctx.author, target_user)

# ------------------------
# Error handler
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
