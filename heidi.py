import threading
from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

# Start dummy web server in background
threading.Thread(target=run_web).start()

# --- bot code starts here ---

import discord
from discord.ext import commands
import httpx
from dotenv import load_dotenv
from collections import deque
import asyncio
import random
import time

# Load environment variables
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not OPENROUTER_API_KEY:
    raise ValueError("❌ OPENROUTER_API_KEY not loaded from .env")

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Per-user conversation history (store last 5 exchanges per user)
user_histories = {}

# Per-user cooldown tracker
user_cooldowns = {}
COOLDOWN_SECONDS = 30

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")

async def ask_openrouter(user_id: int, prompt: str, discord_user) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=5)

    history = user_histories[user_id]

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
                "You prefer not to do action roleplay or asterisk actions.\n"
                "---\n"
                f"You are currently talking to **{discord_user.display_name}** "
                f"(username: {discord_user.name}#{discord_user.discriminator}).\n"
            ),
        }
    ]

    # Add history if available
    if history:
        messages.append({
            "role": "system",
            "content": "Recent conversation history:\n" + "\n".join(history)
        })

    # Add latest user input
    messages.append({"role": "user", "content": prompt})

    try:
        # Send to OpenRouter
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

    # Save conversation
    history.append(f"User: {prompt}")
    history.append(f"Heidi: {reply}")

    return reply

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        now = time.time()
        last_used = user_cooldowns.get(message.author.id, 0)

        # Apply cooldown
        if now - last_used < COOLDOWN_SECONDS:
            return
        user_cooldowns[message.author.id] = now

        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not user_input:
            user_input = "What?"

        # fetch full user object
        discord_user = await bot.fetch_user(message.author.id)

        # Add random delay (2–20 seconds for realism)
        delay = random.uniform(2, 20)
        await asyncio.sleep(delay)

        async with message.channel.typing():
            reply = await ask_openrouter(message.author.id, user_input, discord_user)

        # Occasionally mention the user (50% chance here)
        if random.choice([True, False]):
            content = f"{message.author.mention} {reply}"
        else:
            content = reply

        await message.channel.send(content)


bot.run(DISCORD_BOT_TOKEN)
