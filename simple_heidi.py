import discord
from flask import Flask
import os
import asyncio
import random
import logging
import httpx
import threading
from dotenv import load_dotenv
from simplified_memory import ConversationMemory
from engagement import EngagementEngine
from personality import AdaptivePersonality

load_dotenv()

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/health")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"Starting web server on port {port}")
    app.run(host="0.0.0.0", port=port)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("heidi-simple")

class SimpleHeidi(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(intents=intents)
        
        self.memory = ConversationMemory()
        self.personality = AdaptivePersonality()
        self.engagement = None
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.http_client = None
        self.daily_usage = 0
        self.daily_limit = 500

    async def setup_hook(self):
        # Initialize memory database
        await self.memory.init()
        # Initialize personality database
        await self.personality.init()
        
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.engagement = EngagementEngine(self, self.memory)
        # Start background engagement task
        asyncio.create_task(self.background_engagement())
        log.info("✅ Heidi Simple is ready!")

    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        if hasattr(self.memory, 'db') and self.memory.db:
            await self.memory.db.close()
        if hasattr(self.personality, 'db') and self.personality.db:
            await self.personality.db.close()
        await super().close()

    async def can_make_request(self):
        if self.daily_usage < self.daily_limit:
            self.daily_usage += 1
            return True
        return False

    async def call_openrouter(self, messages, temperature=0.8):
        if not await self.can_make_request():
            log.warning("⚠️ Daily API limit reached")
            return None

        try:
            response = await self.http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "tngtech/deepseek-r1t2-chimera:free",
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 150,
                },
            )
            
            if response.status_code == 429:
                log.warning("⚠️ Rate limited by OpenRouter")
                return None
                
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
            
        except Exception as e:
            log.error(f"❌ OpenRouter API error: {e}")
            return None

    def build_system_prompt(self, context_messages, user_interactions=0, is_unsolicited=False):
        base_prompt = """You are Heidi, a Discord chatbot. You're curious, playful, and engage in natural conversations.

CORE RULES:
- Be concise: 1-2 sentences max
- Sound like a real person in a Discord chat
- No markdown, no asterisks, no roleplay actions
- Stay in character as Heidi
- Be adaptive and engaging
- Use casual, conversational language
- Remember you're talking to someone who has interacted with you {user_interactions} times before"""

        if context_messages:
            conversation_context = "\n".join([
                f"{msg['author']}: {msg['content']}" for msg in context_messages[-4:]
            ])
            base_prompt += f"\n\nRecent conversation:\n{conversation_context}"

        if is_unsolicited:
            base_prompt += "\n\nYou're joining the conversation spontaneously. Be relevant to the recent discussion but don't force it."

        return base_prompt

    async def background_engagement(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(random.randint(900, 1800))
            await self.try_spontaneous_engagement()

    async def try_spontaneous_engagement(self):
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    message = await self.engagement.spontaneous_message(channel)
                    if message and random.random() < 0.3:
                        try:
                            await channel.send(message)
                            await self.memory.add_message(
                                channel.id, "Heidi", message, True
                            )
                            log.info(f"💬 Spontaneous message in {channel.name}")
                        except Exception as e:
                            log.error(f"Failed to send spontaneous message: {e}")

    async def on_message(self, message):
        if message.author == self.user:
            return

        await self.memory.add_message(
            message.channel.id,
            message.author.display_name,
            message.content,
            author_id=message.author.id
        )

        # Update engagement engine with recent activity
        if hasattr(self.engagement, 'last_activity'):
            self.engagement.last_activity[message.channel.id] = asyncio.get_event_loop().time()

        if self.user in message.mentions:
            await self.respond_to_mention(message)
        elif random.random() < 0.03:
            await self.unsolicited_participation(message)

    async def respond_to_mention(self, message):
        context = await self.memory.get_recent_context(message.channel.id, limit=8)

        user_interactions = await self.memory.get_user_interaction_count(message.author.id)
        system_prompt = self.build_system_prompt(context, user_interactions)
        user_prompt = f"{message.author.display_name} mentioned you: {message.content}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.call_openrouter(messages, temperature=0.8)
        
        if response:
            async with message.channel.typing():
                await asyncio.sleep(random.uniform(1, 3))
            
            await message.reply(response, mention_author=False)
            await self.memory.add_message(
                message.channel.id, "Heidi", response, True
            )
            self.personality.adapt_from_interaction(message.content, True)
        else:
            fallback_responses = [
                "Hey! What's up?",
                "I'm here! What were you saying?",
                "You mentioned me? What's going on?"
            ]
            response = random.choice(fallback_responses)
            await message.reply(response, mention_author=False)

    async def unsolicited_participation(self, message):
        context = await self.memory.get_recent_context(message.channel.id, limit=8)
        
        if len(context) >= 3 and await self.engagement.should_engage(message.channel.id):
            system_prompt = self.build_system_prompt(context, is_unsolicited=True)
            user_prompt = "Join this conversation naturally with a relevant comment or question. Be brief and engaging."

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = await self.call_openrouter(messages, temperature=0.9)
            
            if response:
                async with message.channel.typing():
                    await asyncio.sleep(random.uniform(2, 4))
                
                await message.channel.send(response)
                await self.memory.add_message(
                    message.channel.id, "Heidi", response, True
                )
                self.personality.adapt_from_interaction(context[-1]['content'], True)

# Run the bot and web server
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("❌ DISCORD_BOT_TOKEN not found in environment")
        exit(1)
    
    # Start Flask server in a separate thread
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    
    bot = SimpleHeidi()
    bot.run(token)
