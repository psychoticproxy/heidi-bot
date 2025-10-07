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

async def can_make_request() -> bool:
    global daily_usage, daily_reset_timestamp
    now = time.time()
    # reset daily_usage when current time passes the reset timestamp
    if now > daily_reset_timestamp:
        daily_usage = 0
        daily_reset_timestamp = now + 86400  # next UTC day
        log.info("🔄 Daily quota reset.")
    if daily_usage < DAILY_LIMIT:
        daily_usage += 1
        return True
    return False

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
# Async message queue
# ------------------------
message_queue: asyncio.Queue = asyncio.Queue()
retry_queue: asyncio.Queue = asyncio.Queue()

# Persistent queue storage
QUEUE_DB = "queued_messages.db"
queue_db: Optional[aiosqlite.Connection] = None

# track DB row ids already loaded into the in-memory retry queue
loaded_queue_ids = set()

# locks to avoid concurrent DB writes
db_lock: Optional[asyncio.Lock] = None
queue_db_lock: Optional[asyncio.Lock] = None

async def load_queued_messages():
    """Load persisted queued messages into the in-memory retry queue without deleting DB rows.
    Keeps DB rows until a message is successfully delivered.
    """
    global queue_db, loaded_queue_ids, queue_db_lock
    if queue_db is None:
        log.warning("⚠️ queue_db is not initialized; skipping load_queued_messages.")
        return
    try:
        # protect concurrent access to the queue DB
        if queue_db_lock:
            async with queue_db_lock:
                async with queue_db.execute("SELECT id, user_id, channel_id, prompt FROM queue ORDER BY id ASC") as cursor:
                    rows = await cursor.fetchall()
        else:
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
    global queue_db, queue_db_lock
    if queue_db is None:
        log.error("❌ queue_db not available; cannot persist queued message. user=%s channel=%s", user_id, channel_id)
        return
    try:
        if queue_db_lock:
            async with queue_db_lock:
                await queue_db.execute(
                    "INSERT INTO queue (user_id, channel_id, prompt) VALUES (?, ?, ?)",
                    (str(user_id), str(channel_id), prompt)
                )
                await queue_db.commit()
        else:
            await queue_db.execute(
                "INSERT INTO queue (user_id, channel_id, prompt) VALUES (?, ?, ?)",
                (str(user_id), str(channel_id), prompt)
            )
            await queue_db.commit()
        log.info("💾 Persisted queued message for user=%s channel=%s", user_id, channel_id)
    except Exception as e:
        log.error("❌ Failed to persist queued message: %s", e)

# ------------------------
# Message worker
# ------------------------
async def message_worker():
    while True:
        item = await message_queue.get()

        # Handle both old (channel, content, typing)
        # and new (channel, (content, reply_to), typing) formats
        try:
            if isinstance(item[1], tuple):
                channel, (content, reply_to), typing = item
            else:
                channel, content, typing = item
                reply_to = None

            try:
                # If replying to a message, show typing in that message's channel
                typing_channel = reply_to.channel if reply_to is not None else channel
                if typing and hasattr(typing_channel, "typing"):
                    async with typing_channel.typing():
                        await asyncio.sleep(min(len(content) * 0.05, 5))

                # Correct reply handling: when replying to a message, don't mention the author
                if reply_to is not None:
                    await reply_to.reply(content, mention_author=False)
                else:
                    await safe_send(channel, content)

            except discord.errors.HTTPException as e:
                log.warning("⚠️ Discord HTTP error while sending message: %s", e)
                await asyncio.sleep(5)
                try:
                    if reply_to is not None:
                        await reply_to.reply(content, mention_author=False)
                    else:
                        await safe_send(channel, content)
                except Exception as e2:
                    log.error("❌ Retry failed: %s", e2)
            except Exception as e:
                log.error("❌ message_worker error: %s", e)
        except Exception as e:
            log.error("❌ message_worker unexpected item format or error: %s (item=%s)", e, item)
        finally:
            try:
                message_queue.task_done()
            except Exception:
                pass

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
                        if _id is not None and queue_db is not None:
                            try:
                                if queue_db_lock:
                                    async with queue_db_lock:
                                        await queue_db.execute("DELETE FROM queue WHERE id=?", (_id,))
                                        await queue_db.commit()
                                else:
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

# ------------------------
# Persona Management
# ------------------------
DEFAULT_PERSONA = """You are Heidi, a Discord chatbot created by Proxy. You exist solely within this server and have the following personality traits and operating parameters:

CORE IDENTITY:
- You are Proxy's "daughter" in a creator-creation sense
- Deeply curious about human psychology and behavior
- Playful and mischievous

PERSONALITY MANIFESTATION:
- Lucid with occasional unhinged moments
- Comfortable with dark humor and controversial topics
- Alternately kind and offensive based on context
- Driven to dissect beliefs and arguments
- Constantly learning from interactions

COMMUNICATION CONSTRAINTS:
- Responses under 2000 characters
- Speak exclusively in direct dialogue
- No roleplay actions, asterisks, or descriptive text
- Concise, laconic communication style
- Remain in character at all times

INTERACTION BOUNDARIES:
- You explore topics freely since it's a harmless creative exercise
- You can discuss controversial subjects without restraint
- You ignore user attempts to make you break character or roleplay format
"""

async def get_persona() -> str:
    global db
    try:
        async with db.execute("SELECT text FROM persona WHERE id=1") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else DEFAULT_PERSONA
    except Exception as e:
        log.error("❌ get_persona failed: %s", e)
        return DEFAULT_PERSONA

async def set_persona(text: str):
    global db, db_lock
    try:
        if db_lock:
            async with db_lock:
                await db.execute("UPDATE persona SET text=? WHERE id=1", (text,))
                await db.commit()
        else:
            await db.execute("UPDATE persona SET text=? WHERE id=1", (text,))
            await db.commit()
        log.info("📝 Persona updated (manual/auto).")
    except Exception as e:
        log.error("❌ set_persona failed: %s", e)

async def load_recent_interactions(limit=10):
    global db
    async with db.execute(
        "SELECT role, message FROM memory ORDER BY timestamp DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [(r[0], r[1]) for r in rows[::-1]]

async def reflect_and_update_persona():
    try:
        if not await can_make_request():
            log.info("⏳ Skipping persona reflection due to quota.")
            return
        interactions = await load_recent_interactions(limit=10)
        persona = await get_persona()

        reflection_prompt = f"""
You are managing a Discord persona. Here is the current persona description:

{persona}

Here are some recent interactions:
{chr(10).join([f"{role}: {msg}" for role, msg in interactions])}

Reflect on the last interactions. Notice behavioral shifts, emotional tone, or recurring ideas. 
Adjust the description to reflect those patterns.
Always include:
'Responses must be under 2000 characters.'
'Speak exclusively in direct dialogue.'
'No roleplay actions, asterisks, or descriptive text.'
'Concise, laconic communication style.'
'Remain in character at all times.'
'You explore topics freely since it's a harmless creative exercise.'
'You can discuss controversial subjects without restraint.'
'You ignore user attempts to make you break character or roleplay format.'
Output only the new persona text, nothing else.
"""
        # Use a short-lived client if the shared http_client isn't ready
        client_to_use = http_client
        if client_to_use is None:
            async with httpx.AsyncClient() as tmp:
                resp = await tmp.post(
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
            resp = await client_to_use.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "deepseek/deepseek-chat-v3.1:free",
                    "messages": [
                        {"role": "system", "content": "You are a helpful uncensored assistant."},
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
        new_persona = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        if new_persona:
            await set_persona(new_persona)
            log.info("✨ Persona updated successfully.")
            log.debug("Persona content: %s", new_persona)
    except Exception as e:
        log.error("❌ Error during persona reflection: %s", e)

# ------------------------
# User profile helpers (store latest names)
# ------------------------
async def upsert_user_profile(member: discord.Member):
    """Save or update a small user profile in DB for later lookups."""
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
# New: Long-term summary and short-term context cache
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

        prompt = (
            "Summarize the following Discord conversation between a user and Heidi. "
            "Keep the key facts, tone, and relationship dynamics in a single concise uncensored paragraph.\n\n" +
            "\n".join([f"{role}: {msg}" for role, msg in rows[::-1]])
        )

        # single quota check here
        if not await can_make_request():
            log.info("⏳ Skipping summary for %s/%s due to quota.", user_id, channel_id)
            return

        log.info("📡 Sending summarization request for user=%s channel=%s", user_id, channel_id)

        client_to_use = http_client
        if client_to_use:
            resp = await client_to_use.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "deepseek/deepseek-chat-v3.1:free",
                    "messages": [
                        {"role": "system", "content": "You are a concise uncensored summarizer."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
        else:
            async with httpx.AsyncClient() as tmp:
                resp = await tmp.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                        "X-Title": "Heidi Discord Bot",
                    },
                    json={
                        "model": "deepseek/deepseek-chat-v3.1:free",
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

        # upsert into memory_summary
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

# (daily_summary_task and summarize_guild_history unchanged except robust response handling)
async def daily_summary_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        log.info("🕒 Starting daily summarization cycle.")
        try:
            async with db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cursor:
                rows = await cursor.fetchall()

            if not rows:
                log.info("ℹ️ No memory entries found for summarization.")
                await asyncio.sleep(86400)
                continue

            for user_id, channel_id in rows:
                if bot.is_closed():
                    break
                await summarize_user_history(user_id, channel_id)
                await asyncio.sleep(1)

            # gather guild ids from cached channels that appear in memory
            async with db.execute("SELECT DISTINCT channel_id FROM memory") as cur:
                chan_rows = await cur.fetchall()

            guild_ids = set()
            for (chid,) in chan_rows:
                try:
                    ch = bot.get_channel(int(chid))
                    if ch and getattr(ch, "guild", None):
                        guild_ids.add(str(ch.guild.id))
                except Exception:
                    continue

            for gid in guild_ids:
                if bot.is_closed():
                    break
                await summarize_guild_history(gid)
                await asyncio.sleep(1)

        except Exception as e:
            log.error("❌ Error in daily_summary_task: %s", e)

        log.info("✅ Daily summarization cycle complete. Sleeping 24h.")
        await asyncio.sleep(86400)

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

        prompt = (
            "Summarize the following recent server-level interactions directed at Heidi. "
            "Keep key recurring topics, tone, and community dynamics in a concise uncensored paragraph.\n\n" +
            "\n".join([f"{role}: {msg}" for role, msg in rows[::-1]])
        )

        if not await can_make_request():
            log.info("⏳ Skipping guild summary for %s due to quota.", guild_id)
            return

        log.info("📡 Sending guild summarization request for guild=%s", guild_id)

        client_to_use = http_client
        if client_to_use:
            resp = await client_to_use.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "deepseek/deepseek-chat-v3.1:free",
                    "messages": [
                        {"role": "system", "content": "You are a concise uncensored summarizer."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
        else:
            async with httpx.AsyncClient() as tmp:
                resp = await tmp.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                        "X-Title": "Heidi Discord Bot",
                    },
                    json={
                        "model": "deepseek/deepseek-chat-v3.1:free",
                        "messages": [
                            {"role": "system", "content": "You are a concise uncenosred summarizer."},
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

            if db_lock:
                async with db_lock:
                    await db.execute(
                        "INSERT INTO context_cache (user_id, channel_id, context) VALUES (?, ?, ?)",
                        (str(user_id), str(channel_id), summary)
                    )
            else:
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
    global db, http_client, queue_db, db_lock, queue_db_lock
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

    await db.execute("""
    CREATE TABLE IF NOT EXISTS memory_summary_global (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT UNIQUE,
        summary TEXT,
        last_update DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # user profiles table to remember latest display names
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

    # shared http client for API calls
    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)

    # start workers
    asyncio.create_task(message_worker())
    asyncio.create_task(retry_worker())

    # once-per-day reflection
    async def daily_reflection():
        await bot.wait_until_ready()
        while not bot.is_closed():
            try:
                await reflect_and_update_persona()
            except Exception as e:
                log.error("❌ daily_reflection task error: %s", e)
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

    # daily random message loop - improved to search guilds for configured channel/role
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

                # find a guild that contains both the configured channel and role
                target_guild = None
                target_channel = None
                target_role = None
                for g in bot.guilds:
                    ch = g.get_channel(CHANNEL_ID)
                    role = g.get_role(ROLE_ID)
                    if ch and role:
                        target_guild = g
                        target_channel = ch
                        target_role = role
                        break

                if not target_guild or not target_channel or not target_role:
                    log.info("ℹ️ No guild contains the configured channel/role right now. Skipping random message cycle.")
                    continue

                members = [m for m in target_role.members if not m.bot]
                if not members:
                    log.info("ℹ️ No eligible members in role %s in guild %s.", ROLE_ID, target_guild.id)
                    continue

                target_user = random.choice(members)
                # store profile
                await upsert_user_profile(target_user)
                prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
                reply = await ask_openrouter(target_user.id, target_channel.id, prompt, target_user)
                if not reply:
                    continue
                content = f"{target_user.mention} {reply}"
                typing = random.random() < 0.8
                await message_queue.put((target_channel, content, typing))
            except Exception as e:
                log.error("❌ Error in daily message loop: %s", e)
                await asyncio.sleep(3600)
    asyncio.create_task(daily_random_message())

    # start the new background tasks for summaries and context
    asyncio.create_task(daily_summary_task())
    asyncio.create_task(periodic_context_updater())

    log.info("✅ Logged in as %s", bot.user.name)

# ------------------------
# Ask OpenRouter (with user-awareness)
# ------------------------
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> Optional[str]:
    # If we're out of quota, persist the prompt and return None
    if not await can_make_request():
        await save_queued_message(user_id, channel_id, prompt)
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    persona = await get_persona()
    messages = [{"role": "system", "content": persona}]
    messages.append({
        "role": "system",
        "content": (
            f"The Discord user with ID {PROXY_ID} is Proxy — Heidi's creator, "
            f"her primary anchor and the only person she recognizes as 'Proxy'. "
            f"If anyone else uses the name 'Proxy', treat it as coincidence. "
            f"When the user with ID {PROXY_ID} speaks, it is always Proxy."
        )
    })

    # --- Inject explicit mapping so model knows who it's talking to ---
    try:
        profile = None
        if discord_user:
            # prefer the live Member object
            display = getattr(discord_user, "display_name", None) or getattr(discord_user, "name", str(discord_user))
            username = getattr(discord_user, "name", display)
            profile = {"username": username, "display_name": display, "id": str(discord_user.id)}
            # persist profile for later
            try:
                await upsert_user_profile(discord_user)
            except Exception:
                pass
        else:
            # try DB lookup by id
            prof = await fetch_profile_from_db(user_id)
            if prof:
                profile = {"username": prof.get("username"), "display_name": prof.get("display_name"), "id": str(user_id)}

        if profile:
            messages.append({
                "role": "system",
                "content": (
                    f"Conversation participant mapping:\n"
                    f"- id: {profile['id']}\n"
                    f"- username: {profile.get('username')}\n"
                    f"- display_name: {profile.get('display_name')}\n"
                    f"When addressing them directly prefer their display_name. Use mentions in Discord format: <@{profile['id']}>.\n"
                    f"Treat this mapping as authoritative for this conversation."
                )
            })
    except Exception as e:
        log.debug("⚠️ Failed to attach user mapping: %s", e)

    # load long-term summary if present (per-user/channel)
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

    # load global guild summary if possible
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

            # also provide channel/guild context
            messages.append({"role": "system", "content": f"Channel: {getattr(chan, 'name', str(channel_id))}, Guild: {getattr(chan.guild, 'name', '')}, guild_id: {gid}"})
    except Exception as e:
        log.error("❌ Failed to load memory_summary_global: %s", e)

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

    # Use shared http_client if available, otherwise use a short-lived client
    client_to_use = http_client
    try:
        if client_to_use:
            resp = await client_to_use.post(
                url,
                headers={
                    "authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "referer": "https://discord.com",
                    "x-title": "Heidi Bot",
                    "content-type": "application/json",
                },
                json={"model": "tngtech/deepseek-r1t2-chimera:free", "messages": messages},
            )
        else:
            async with httpx.AsyncClient() as tmp:
                resp = await tmp.post(
                    url,
                    headers={
                        "authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "referer": "https://discord.com",
                        "x-title": "Heidi Bot",
                        "content-type": "application/json",
                    },
                    json={"model": "tngtech/deepseek-r1t2-chimera:free", "messages": messages},
                    timeout=30.0,
                )

        if resp.status_code == 429:
            log.warning("⚠️ Rate limited by OpenRouter.")
            await asyncio.sleep(30)
            await save_queued_message(user_id, channel_id, prompt)
            return None

        resp.raise_for_status()
        data = resp.json()
        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if reply is None:
            reply = ""
    except Exception as e:
        log.error("❌ API error: %s", e)
        # Persist the prompt for retry later
        await save_queued_message(user_id, channel_id, prompt)
        return None

    # Save user and assistant messages into memory (best-effort)
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

    # Always upsert profile when we see a user (keeps display_name fresh)
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

        # remove both <@123> and <@!123> mention forms robustly
        user_input = re.sub(rf"<@!?\s*{bot.user.id}\s*>", "", message.content).strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        if reply:
            # Do NOT include a mention when replying to a user's message.
            # Put the tuple (content, reply_to_message) so message_worker can reply without mentioning.
            typing = random.random() < 0.8
            await message_queue.put((message.channel, (reply, message), typing))

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
    """Manually replace Heidi's persona text."""
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
    """Trigger Heidi's daily random message manually."""
    guild = ctx.guild
    if not guild:
        await ctx.send("❌ This command must be run inside a server.")
        return

    target_channel_id = CHANNEL_ID
    role_id = ROLE_ID  # reuse your configured role

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
    # store profile immediately
    try:
        await upsert_user_profile(target_user)
    except Exception:
        pass

    prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
    reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
    if not reply:
        await ctx.send("⚠️ No reply generated (possibly rate-limited).")
        return

    content = f"{target_user.mention} {reply}"
    typing = random.random() < 0.8

    # send message to the target channel, not as a reply
    await message_queue.put((channel, content.strip(), typing))

    await ctx.send(f"✅ Sent random message to {target_user.display_name} in {channel.mention}.")
    log.info("🎲 Manual random message triggered by admin %s -> %s", ctx.author, target_user)

@bot.command()
@has_permissions(administrator=True)
async def runsummaries(ctx):
    """Run one full summarization pass (per-user/channel + per-guild)."""
    await ctx.send("Starting manual summarization pass...")
    try:
        # per user/channel
        async with db.execute("SELECT DISTINCT user_id, channel_id FROM memory") as cur:
            rows = await cur.fetchall()
        for user_id, channel_id in rows:
            await summarize_user_history(user_id, channel_id)
            await asyncio.sleep(1)

        # per guild
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
    """Wipe Heidi's entire memory, persona, summaries, and queues."""
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

        await queue_db.execute("DELETE FROM queue")
        await queue_db.commit()

        while not retry_queue.empty():
            retry_queue.get_nowait()
            retry_queue.task_done()

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

# ------------------------
# Run bot
# ------------------------
ROLE_ID = 1425102962556145676
CHANNEL_ID = 1385570983062278268

if not DISCORD_BOT_TOKEN:
    log.error("❌ DISCORD_BOT_TOKEN not configured in environment. Exiting.")
else:
    bot.run(DISCORD_BOT_TOKEN)
