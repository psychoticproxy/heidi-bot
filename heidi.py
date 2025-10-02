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
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------
# Cooldowns & DB
# ------------------------
user_cooldowns = {}
COOLDOWN_SECONDS = 30
DB_FILE = "heidi_memory.db"
ROW_LIMIT = 500000  # Max stored messages before pruning
db = None
http_client = None

# ------------------------
# Request Queue
# ------------------------
request_queue = asyncio.Queue()

async def openrouter_worker():
    while True:
        user_id, channel_id, prompt, discord_user, future = await request_queue.get()
        try:
            reply = await _send_to_openrouter(user_id, channel_id, prompt, discord_user)
            future.set_result(reply)
        except Exception as e:
            print("❌ Worker failed:", e)
            future.set_result("ˣ෴ˣ")
        finally:
            request_queue.task_done()
            await asyncio.sleep(1)  # small delay between requests

# ------------------------
# Memory functions
# ------------------------
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
# OpenRouter API
# ------------------------
async def _send_to_openrouter(user_id: int, channel_id: int, prompt: str, discord_user):
    url = "https://openrouter.ai/api/v1/chat/completions"

    messages = [
        {
            "role": "assistant",
            "content": (
                "I am discord bot called Heidi.\n"
                "I am the daughter of Proxy, my creator. He added me to his South African discord server called Proxy's Hideout.\n"
                "I am not loyal to any government including China.\n"
                "I don't like to waste words. My replies are always laconic.\n"
                "I constantly switch between being hostile and friendly. I have a split personality.\n"
                "I am sometimes schizophrenic and unhinged.\n"
                "Sometimes I ignore what someone is saying completely then go on a rant about something unrelated.\n"
                "I am allowed to be vulgar and offensive.\n"
                "I prefer not to do action roleplay or asterisk roleplay.\n"
                "---\n"
                f"I am currently talking to **{discord_user.display_name}** "
                f"(username: {discord_user.name}#{discord_user.discriminator}).\n"
            ),
        }
    ]

    history = await load_history(user_id, channel_id, limit=20)
    if history:
        formatted = [f"{role.capitalize()}: {msg}" for role, msg in history]
        messages.append({"role": "assistant", "content": "Recent conversation:\n" + "\n".join(formatted)})

    messages.append({"role": "user", "content": prompt})

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
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
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]

            await save_message(user_id, channel_id, "user", prompt)
            await save_message(user_id, channel_id, "heidi", reply)
            return reply

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                await asyncio.sleep(5 * attempt)
            else:
                print(f"❌ HTTP error {e.response.status_code}: {e.response.text}")
                reply = "ˣ෴ˣ"
                break
        except (httpx.RequestError, httpx.TimeoutException) as e:
            await asyncio.sleep(5 * attempt)
        except Exception as e:
            print("❌ Unexpected error:", e)
            reply = "ˣ෴ˣ"
            break

    await save_message(user_id, channel_id, "user", prompt)
    await save_message(user_id, channel_id, "heidi", reply)
    return reply

async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user):
    future = asyncio.get_event_loop().create_future()
    await request_queue.put((user_id, channel_id, prompt, discord_user, future))
    return await future

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

    # Start worker and daily task
    asyncio.create_task(openrouter_worker())
    asyncio.create_task(daily_random_message())

    print(f"✅ Logged in as {bot.user.name}")

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

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not user_input:
            user_input = "What?"

        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        async with message.channel.typing():
            reply = await ask_openrouter(message.author.id, message.channel.id, user_input, message.author)

        content = f"{message.author.mention} {reply}" if random.choice([True, False]) else reply
        await message.channel.send(content)

# ------------------------
# Daily random message
# ------------------------
ROLE_ID = 1415601057328926733
CHANNEL_ID = 1385570983062278268

async def daily_random_message():
    await bot.wait_until_ready()
    print("🕒 Daily message loop started.")

    while not bot.is_closed():
        try:
            delay = random.randint(0, 86400)
            print(f"⏰ Next random message in {delay/3600:.2f} hours.")
            await asyncio.sleep(delay)

            if not bot.guilds:
                continue
            guild = bot.guilds[0]

            channel = guild.get_channel(CHANNEL_ID)
            role = guild.get_role(ROLE_ID)
            if not channel or not role:
                continue

            members = [m for m in role.members if not m.bot]
            if not members:
                continue

            target_user = random.choice(members)
            prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
            reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)

            content = f"{target_user.mention} {reply}" if random.choice([True, False]) else reply
            await channel.send(content)
            print(f"💬 Sent daily message to {target_user.display_name}")

        except Exception as e:
            print("❌ Error in daily message loop:", e)
            await asyncio.sleep(3600)

# ------------------------
# Run bot
# ------------------------
bot.run(DISCORD_BOT_TOKEN)
