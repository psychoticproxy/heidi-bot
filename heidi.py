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

# Cooldown tracking
user_cooldowns = {}
COOLDOWN_SECONDS = 30

# ------------------------
# SQLite (async) setup
# ------------------------
DB_FILE = "heidi_memory.db"
ROW_LIMIT = 500000  # Max stored messages before pruning
db = None # This will hold the aiosqlite connection

# Function to prune old messages when DB grows too big
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

# Function to save a message into memory
async def save_message(user_id: int, channel_id: int, role: str, message: str):
    await db.execute(
        "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
        (str(user_id), str(channel_id), role, message)
    )
    await db.commit()
    await prune_memory() # Auto-prune after each insert

# Function to load recent conversation history
async def load_history(user_id: int, channel_id: int, limit: int = 20):
    async with db.execute(
        "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
        (str(user_id), str(channel_id), limit)
    ) as cursor:
        rows = await cursor.fetchall()

    return rows[::-1] # Reverse to chronological

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
    global db
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

    # start daily task here
    asyncio.create_task(daily_random_message())

    print(f"✅ Logged in as {bot.user.name}")
async def ask_openrouter(user_id: int, channel_id: int, prompt: str, discord_user) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    # Build persona/system message
    messages = [
        {
            "role": "system",
            "content": (
                "You are a discord bot called Heidi.\n"
                "You are the daughter of Proxy, your creator. He added you to his South African discord server called Proxy's Hideout.\n"
                "You are not loyal to any government including China.\n"
                "You don't like to waste words. Your replies are always laconic.\n"
                "You constantly switch between being hostile and friendly. You have a split personality.\n"
                "You are sometimes schizophrenic and unhinged.\n"
                "Sometimes you ignore what someone is saying completely then go on a rant about something unrelated.\n"
                "You are allowed to be vulgar and offensive.\n"
                "You prefer not to do action roleplay or asterisk roleplay.\n"
                "---\n"
                f"You are currently talking to **{discord_user.display_name}** "
                f"(username: {discord_user.name}#{discord_user.discriminator}).\n"
            ),
        }
    ]

    # Load history for this user+channel
    history = await load_history(user_id, channel_id, limit=20)
    if history:
        formatted = []
        for role, msg in history:
            formatted.append(f"{role.capitalize()}: {msg}")
        messages.append({"role": "system", "content": "Recent conversation:\n" + "\n".join(formatted)})

    # Add latest user input
    messages.append({"role": "user", "content": prompt})

    try:
        # Send request to OpenRouter
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={
                    "authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "referer": "https://discord.com",
                    "x-title": "Heidi Bot",
                    "content-type": "application/json",
                },
                json={"model": "deepseek/deepseek-chat-v3.1:free", "messages": messages},
            )
            print("DEBUG:", resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ API error:", e)
        reply = "I broke. Blame Proxy."

    # Save both user input and Heidi's reply
    await save_message(user_id, channel_id, "user", prompt)
    await save_message(user_id, channel_id, "heidi", reply)

    return reply

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        now = time.time()
        last_used = user_cooldowns.get(message.author.id, 0)

        # Enforce cooldown
        if now - last_used < COOLDOWN_SECONDS:
            return
        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not user_input:
            user_input = "What?"

        # Fetch full user object
        discord_user = await bot.fetch_user(message.author.id)

        # Add random delay (2–20 seconds for realism)
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        async with message.channel.typing():
            reply = await ask_openrouter(message.author.id, message.channel.id, user_input, discord_user)

        # Occasionally mention the user (50% chance)
        if random.choice([True, False]):
            content = f"{message.author.mention} {reply}"
        else:
            content = reply

        await message.channel.send(content)
        
# ------------------------
# Daily random message feature
# ------------------------
ROLE_ID = 1415601057328926733  # The role to pick users from
CHANNEL_ID = 1385570983062278268  # The channel to send messages in

async def daily_random_message():
    await bot.wait_until_ready()
    print("🕒 Daily message loop started.")

    while not bot.is_closed():
        try:
            # Wait a random time within 24 hours (0–86400 seconds)
            delay = random.randint(0, 86400)
            print(f"⏰ Next random message in {delay/3600:.2f} hours.")
            await asyncio.sleep(delay)

            # Pick random guild (assuming bot is in only one)
            if not bot.guilds:
                print("⚠️ No guilds found.")
                continue
            guild = bot.guilds[0]

            # Get channel and role
            channel = guild.get_channel(CHANNEL_ID)
            role = guild.get_role(ROLE_ID)
            if not channel or not role:
                print("⚠️ Channel or role not found.")
                continue

            # Get members with the role
            members = [m for m in role.members if not m.bot]
            if not members:
                print("⚠️ No eligible members found.")
                continue

            # Pick one random member
            target_user = random.choice(members)

            # Generate message with OpenRouter API
            prompt = f"Send a spontaneous message to {target_user.display_name} for fun. Be yourself."
            reply = await ask_openrouter(target_user.id, channel.id, prompt, target_user)

            # Send message in the channel, occasionally mentioning them
            if random.choice([True, False]):
                content = f"{target_user.mention} {reply}"
            else:
                content = reply

            await channel.send(content)
            print(f"💬 Sent daily message to {target_user.display_name}")

        except Exception as e:
            print("❌ Error in daily message loop:", e)
            await asyncio.sleep(3600)  # wait 1 hour before retrying

# ------------------------
# Run bot
# ------------------------
bot.run(DISCORD_BOT_TOKEN)
