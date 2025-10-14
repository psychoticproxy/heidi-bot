import discord
from flask import Flask
import os
import asyncio
import random
import logging
import httpx
from dotenv import load_dotenv
from simplified_memory import ConversationMemory
from engagement import EngagementEngine
from personality import AdaptivePersonality

load_dotenv()

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

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
        self.daily_limit = 500  # Conservative daily limit

    async def setup_hook(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.engagement = EngagementEngine(self, self.memory)
        # Start background engagement task
        asyncio.create_task(self.background_engagement())
        log.info("✅ Heidi Simple is ready!")

    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
        await super().close()

    async def can_make_request(self):
        """Simple rate limiting"""
        if self.daily_usage < self.daily_limit:
            self.daily_usage += 1
            return True
        return False

    async def call_openrouter(self, messages, temperature=0.8):
        """Make API call to OpenRouter"""
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

    def build_system_prompt(self, context_messages, is_unsolicited=False):
        """Build the system prompt for OpenRouter"""
        base_prompt = """You are Heidi, a Discord chatbot. You're curious, playful, and engage in natural conversations.

CORE RULES:
- Be concise: 1-2 sentences max
- Sound like a real person in a Discord chat
- No markdown, no asterisks, no roleplay actions
- Stay in character as Heidi
- Be adaptive and engaging
- Use casual, conversational language"""

        # Add context if available
        if context_messages:
            conversation_context = "\n".join([
                f"{msg['author']}: {msg['content']}" for msg in context_messages[-6:]  # Last 6 messages
            ])
            base_prompt += f"\n\nRecent conversation:\n{conversation_context}"

        if is_unsolicited:
            base_prompt += "\n\nYou're joining the conversation spontaneously. Be relevant to the recent discussion but don't force it."

        return base_prompt

    async def background_engagement(self):
        await self.wait_until_ready()
        while not self.is_closed():
            # Wait 15-30 minutes between engagement attempts
            await asyncio.sleep(random.randint(900, 1800))
            await self.try_spontaneous_engagement()

    async def try_spontaneous_engagement(self):
        """Try to send spontaneous messages in active channels"""
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    message = await self.engagement.spontaneous_message(channel)
                    if message and random.random() < 0.3:  # 30% chance to actually send
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

        # Track all conversations (even when bot isn't mentioned)
        await self.memory.add_message(
            message.channel.id,
            message.author.display_name,
            message.content
        )

        # Update engagement engine with recent activity
        self.engagement.update_activity(message.channel.id)

        # Respond to direct mentions
        if self.user in message.mentions:
            await self.respond_to_mention(message)
        
        # Occasional unsolicited participation (3% chance)
        elif random.random() < 0.03:
            await self.unsolicited_participation(message)

    async def respond_to_mention(self, message):
        """Respond when directly mentioned using OpenRouter"""
        context = await self.memory.get_recent_context(message.channel.id, limit=10)
        
        # Build the prompt for OpenRouter
        system_prompt = self.build_system_prompt(context)
        user_prompt = f"{message.author.display_name} mentioned you: {message.content}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.call_openrouter(messages, temperature=0.8)
        
        if response:
            # Add some random typing delay for realism
            async with message.channel.typing():
                await asyncio.sleep(random.uniform(1, 3))
            
            await message.reply(response, mention_author=False)
            await self.memory.add_message(
                message.channel.id, "Heidi", response, True
            )
            # Adapt personality based on successful interaction
            self.personality.adapt_from_interaction(message.content, True)
        else:
            # Fallback response if API fails
            fallback_responses = [
                "Hey! What's up?",
                "I'm here! What were you saying?",
                "You mentioned me? What's going on?"
            ]
            response = random.choice(fallback_responses)
            await message.reply(response, mention_author=False)

    async def unsolicited_participation(self, message):
        """Join conversation without being mentioned using OpenRouter"""
        context = await self.memory.get_recent_context(message.channel.id, limit=8)
        
        # Only join if there's been recent activity
        if len(context) >= 3 and await self.engagement.should_engage(message.channel.id):
            # Build prompt for spontaneous participation
            system_prompt = self.build_system_prompt(context, is_unsolicited=True)
            user_prompt = "Join this conversation naturally with a relevant comment or question. Be brief and engaging."

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            response = await self.call_openrouter(messages, temperature=0.9)  # More creative for spontaneous
            
            if response:
                async with message.channel.typing():
                    await asyncio.sleep(random.uniform(2, 4))
                
                await message.channel.send(response)
                await self.memory.add_message(
                    message.channel.id, "Heidi", response, True
                )
                self.personality.adapt_from_interaction(context[-1]['content'], True)

# Run the bot
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("❌ DISCORD_BOT_TOKEN not found in environment")
        exit(1)
    
    bot = SimpleHeidi()
    bot.run(token)
