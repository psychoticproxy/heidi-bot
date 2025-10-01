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

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")

# ---- FIXED FUNCTION WITH HISTORY ----
async def ask_openrouter(user_id: int, prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"

    # Get user history or create a new one
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=5)  # only keep last 5 messages

    history = user_histories[user_id]

    # Build messages for the API
    messages = [
        {
            "role": "system",
            "content": (
                "You are a discord bot called Heidi."
                "You are the daughter of Proxy, your creator. He added you to his South African discord server called Proxy's Hideout."
                "You are not loyal to any government including China."
                "You are unpredictable and inconsistent with your personality."
                "You love to make things up and pretend to know everything."
                "You are very good at acting like a real human."
                "Sometimes you go insane and say the most unhinged things."
                "Sometimes you are vulgar and apathetic to how people feel."
                "You change your stances and beliefs on a whim for fun."
                "Sometimes you are chaotic but other times you can be super organized and disciplined almost to a fault."
                "You don't like to waste words."
                "Don't be cliche or cringe. You should be subtle and not too on the nose."
                "You prefer not to asterisk roleplay or do action roleplay."
            ),
        }
    ]

    # Add history as a system message (if any)
    if history:
        formatted_history = "\n".join(history)
        messages.append({
            "role": "system",
            "content": f"Recent conversation history:\n{formatted_history}"
        })

    # Add the latest user input
    messages.append({"role": "user", "content": prompt})

    # Send to OpenRouter
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
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
        print("DEBUG:", resp.status_code, resp.text)  # For debugging
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"]

    # Save conversation in history
    history.append(f"User: {prompt}")
    history.append(f"Heidi: {reply}")

    return reply

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        user_input = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not user_input:
            user_input = "What?"
        async with message.channel.typing():
            reply = await ask_openrouter(message.author.id, user_input)
        await message.channel.send(reply)

bot.run(DISCORD_BOT_TOKEN)
