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
import sqlite3

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
# SQLite setup
# ------------------------
DB_FILE = "heidi_memory.db"
ROW_LIMIT = 500000  # Max stored messages before pruning

# Connect to SQLite (creates file if missing)
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# Create table for memory (per user, per channel)
cursor.execute("""
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    channel_id TEXT,
    role TEXT,
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Function to prune old messages when DB grows too big
def prune_memory():
    cursor.execute("SELECT COUNT(*) FROM memory")
    total = cursor.fetchone()[0]
    if total > ROW_LIMIT:
        # Delete oldest rows beyond the limit
        to_delete = total - ROW_LIMIT
        cursor.execute("DELETE FROM memory WHERE id IN (SELECT id FROM memory ORDER BY id ASC LIMIT ?)", (to_delete,))
        conn.commit()
        print(f"🗑️ Pruned {to_delete} old messages (kept {ROW_LIMIT}).")

# Function to save a message into memory
def save_message(user_id: int, channel_id: int, role: str, message: str):
    cursor.execute(
        "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
        (str(user_id), str(channel_id), role, message)
    )
    conn.commit()
    prune_memory()  # Auto-prune after each insert

# Function to load recent conversation history
def load_history(user_id: int, channel_id: int, limit: int = 20):
    cursor.execute(
        "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
        (str(user_id), str(channel_id), limit)
    )
    rows = cursor.fetchall()
    # Reverse to chronological order
    return rows[::-1]

# ------------------------
# Bot events
# ------------------------
@bot.event
async def on_ready():
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
    history = load_history(user_id, channel_id, limit=20)
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
    save_message(user_id, channel_id, "user", prompt)
    save_message(user_id, channel_id, "heidi", reply)

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
# Run bot
# ------------------------
bot.run(DISCORD_BOT_TOKEN)
