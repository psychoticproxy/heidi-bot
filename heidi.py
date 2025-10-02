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

# ------------------------
# Async message queue
# ------------------------
message_queue = asyncio.Queue()

async def message_worker():
    while True:
        channel, content, typing = await message_queue.get()
        try:
            if typing:
                async with channel.typing():
                    await asyncio.sleep(min(len(content) * 0.05, 5))  # simulate typing duration
            await channel.send(content)
        except discord.errors.HTTPException as e:
            print("⚠️ Discord rate limit / HTTP error:", e)
            await asyncio.sleep(5)  # simple retry delay
            await channel.send(content)
        message_queue.task_done()

asyncio.create_task(message_worker())

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
        print(f"🗑️ Pruned {to_delete} old messages (kept {ROW_LIMIT}).")

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

    http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0)
    asyncio.create_task(daily_random_message())
    print(f"✅ Logged in as {bot.user.name}")

async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = [
        {
            "role": "assistant",
            "content": (
                f"I am discord bot Heidi. Talking to {discord_user.display_name} ({discord_user.name}#{discord_user.discriminator}).\n"
                "I am laconic, sometimes unhinged, sometimes offensive, with split personality.\n"
            )
        }
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
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ API error:", e)
        reply = "ˣ෴ˣ"

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
            return
        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip() or "What?"
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        content = f"{message.author.mention} {reply}" if random.choice([True, False]) else reply
        typing = random.random() < 0.8  # 80% of messages will show typing

        # Push to message queue instead of sending immediately
        await message_queue.put((message.channel, content, typing))

# ------------------------
# Daily random messages
# ------------------------
ROLE_ID = 1415601057328926733
CHANNEL_ID = 1385570983062278268

async def daily_random_message():
    await bot.wait_until_ready()
    print("🕒 Daily message loop started.")
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
            reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)
            content = f"{target_user.mention} {reply}" if random.choice([True, False]) else reply
            typing = random.random() < 0.8
            await message_queue.put((channel, content, typing))
            print(f"💬 Sent daily message to {target_user.display_name}")
        except Exception as e:
            print("❌ Error in daily message loop:", e)
            await asyncio.sleep(3600)

# ------------------------
# Run bot
# ------------------------
bot.run(DISCORD_BOT_TOKEN)
