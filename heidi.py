import threading
from flask import Flask
import os

# ----------------------------
# Dummy web server (keeps Koyeb deployment alive)
# ----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

# Start dummy web server in background
threading.Thread(target=run_web).start()

# ----------------------------
# Discord + API imports
# ----------------------------
import discord
from discord.ext import commands
import httpx
from dotenv import load_dotenv
import asyncio
import random
import time
import sqlite3
import atexit

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY not loaded from .env")

# ----------------------------
# SQLite setup (long-term memory)
# ----------------------------
DB_FILE = "heidi_memory.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute("""
CREATE TABLE IF NOT EXISTS conversations (
    user_id INTEGER,
    role TEXT,
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Ensure DB closes properly when bot exits
atexit.register(lambda: conn.close())

def save_message(user_id: int, role: str, message: str):
    """Save a message into the SQLite DB"""
    cursor.execute(
        "INSERT INTO conversations (user_id, role, message) VALUES (?, ?, ?)",
        (user_id, role, message)
    )
    conn.commit()

def load_history(user_id: int, limit: int = 10):
    """Load the last N messages for a user from SQLite"""
    cursor.execute(
        "SELECT role, message FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cursor.fetchall()
    # Reverse so oldest is first (important for conversation flow)
    return list(reversed(rows))

# ----------------------------
# Discord bot setup
# ----------------------------
intents = discord.Intents.default()
intents.message_content = True  # Needed to read message text
bot = commands.Bot(command_prefix="!", intents=intents)

# Per-user cooldown tracker
user_cooldowns = {}
COOLDOWN_SECONDS = 30  # Prevent spam

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")

# ----------------------------
# Function to ask OpenRouter API
# ----------------------------
async def ask_openrouter(user_id: int, prompt: str, discord_user) -> str:
    """Send conversation (with history) to OpenRouter and get Heidi's reply"""
    url = "https://openrouter.ai/api/v1/chat/completions"

    # Build system prompt (Heidi's persona)
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

    # Load last 10 messages from DB and inject into context
    history = load_history(user_id, limit=10)
    if history:
        messages.append({
            "role": "system",
            "content": "Recent conversation history:\n" +
                       "\n".join([f"{role}: {msg}" for role, msg in history])
        })

    # Add latest user input
    messages.append({"role": "user", "content": prompt})

    try:
        # Send to OpenRouter API
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
            print("DEBUG:", resp.status_code, resp.text[:200])  # log first 200 chars
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        print("❌ API error:", e)
        reply = "I broke. Blame Proxy."

    # Save conversation into DB
    save_message(user_id, "User", prompt)
    save_message(user_id, "Heidi", reply)

    return reply

# ----------------------------
# Handle Discord messages
# ----------------------------
@bot.event
async def on_message(message):
    # Ignore own messages
    if message.author == bot.user:
        return

    # Only respond when Heidi is mentioned
    if bot.user in message.mentions:
        now = time.time()
        last_used = user_cooldowns.get(message.author.id, 0)

        # Enforce cooldown
        if now - last_used < COOLDOWN_SECONDS:
            return
        user_cooldowns[message.author.id] = now

        # Extract the text after mentioning Heidi
        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not user_input:
            user_input = "What?"

        # Get full user object (to access display name)
        discord_user = await bot.fetch_user(message.author.id)

        # Random delay for realism (2–20s)
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        async with message.channel.typing():
            reply = await ask_openrouter(message.author.id, user_input, discord_user)

        # Occasionally mention the user (50% chance)
        if random.choice([True, False]):
            content = f"{message.author.mention} {reply}"
        else:
            content = reply

        await message.channel.send(content)

# ----------------------------
# Run the bot
# ----------------------------
bot.run(DISCORD_BOT_TOKEN)
