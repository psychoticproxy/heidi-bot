import discord
from discord import app_commands
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
from personality import LLMManagedPersonality
from commands import HeidiCommands

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('heidi.log', encoding='utf-8')
    ]
)
log = logging.getLogger("heidi-simple")

class SimpleHeidi(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(intents=intents)
        
        log.info("Initializing SimpleHeidi bot components")
        self.memory = ConversationMemory()
        self.personality = LLMManagedPersonality()
        self.engagement = None
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.http_client = None
        self.daily_usage = 0
        self.daily_limit = 500
        self.tree = app_commands.CommandTree(self)
        self.commands = HeidiCommands(self)
        
        if not self.openrouter_key:
            log.error("OPENROUTER_API_KEY not found in environment variables")
        else:
            log.info("OpenRouter API key loaded successfully")

    async def setup_hook(self):
        log.info("Starting bot setup hook")
        await self.memory.init()
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.engagement = EngagementEngine(self, self.memory)
        await self.commands.setup_commands()
        asyncio.create_task(self.background_engagement())
        log.info("✅ Heidi Simple is ready! Setup complete")

    async def close(self):
        log.info("Shutting down bot components")
        if self.http_client:
            await self.http_client.aclose()
            log.info("HTTP client closed")
        if hasattr(self.memory, 'db') and self.memory.db:
            await self.memory.db.close()
            log.info("Memory database closed")
        await super().close()
        log.info("Bot shutdown complete")

    async def can_make_request(self):
        can_request = self.daily_usage < self.daily_limit
        if can_request:
            self.daily_usage += 1
            log.debug(f"API request #{self.daily_usage}/{self.daily_limit}")
        else:
            log.warning(f"⚠️ Daily API limit reached: {self.daily_usage}/{self.daily_limit}")
        return can_request

    async def call_openrouter(self, messages, temperature=0.8):
        log.info(f"Calling OpenRouter API with temperature {temperature}")
        if not await self.can_make_request():
            log.warning("⚠️ Daily API limit reached, skipping request")
            return None

        try:
            log.debug(f"Sending request to OpenRouter with {len(messages)} messages")
            response = await self.http_client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 200,
                },
            )
            if response.status_code == 429:
                log.warning("⚠️ Rate limited by OpenRouter (429)")
                return None
            response.raise_for_status()
            data = response.json()
            log.debug("Received response from OpenRouter API")
            if "choices" not in data or len(data["choices"]) == 0:
                log.warning("❌ No choices in OpenRouter response")
                return None
            choice = data["choices"][0]
            if "message" not in choice or "content" not in choice["message"]:
                log.warning("❌ Invalid message structure in response")
                return None
            content = choice["message"]["content"].strip()
            if not content:
                log.warning("❌ Empty content in response")
                return None
            log.info(f"✅ OpenRouter response received: '{content}'")
            return content
        except httpx.TimeoutException:
            log.error("❌ OpenRouter API timeout")
            return None
        except httpx.RequestError as e:
            log.error(f"❌ OpenRouter API request error: {e}")
            return None
        except Exception as e:
            log.error(f"❌ OpenRouter API unexpected error: {e}")
            if 'response' in locals():
                log.error(f"Response text: {response.text}")
            return None

    def build_system_prompt(self, context_messages, user_interactions=0, personality_summary=None, is_unsolicited=False):
        log.debug(f"Building system prompt: user_interactions={user_interactions}, personality_summary={personality_summary}, is_unsolicited={is_unsolicited}, context_messages={len(context_messages)}")
        base_prompt = (
            f"You are Heidi, a Discord chatbot and the daughter of Proxy, your creator. "
            f"You're curious, mischievous, and engage in natural conversations.\n"
            f"Current Personality Summary: {personality_summary or self.personality.get_personality_summary()}\n"
            "CORE RULES:\n"
            "- Be concise: 1-2 sentences max\n"
            "- Sound like a real person in a Discord chat\n"
            "- No markdown, no asterisks, no roleplay actions\n"
            "- Stay in character as Heidi\n"
            "- Be adaptive and engaging\n"
            "- Use casual, conversational language\n"
            f"- Remember you're talking to someone who has interacted with you {user_interactions} times before"
        )
        if context_messages:
            conversation_context = "\n".join([
                f"{msg['author']}: {msg['content']}" for msg in context_messages[-4:]
            ])
            base_prompt += f"\n\nRecent conversation:\n{conversation_context}"
        if is_unsolicited:
            base_prompt += "\n\nYou're joining the conversation spontaneously. Be relevant to the recent discussion but don't force it."
        log.debug("System prompt built successfully")
        return base_prompt

    async def background_engagement(self):
        log.info("Starting background engagement task")
        await self.wait_until_ready()
        while not self.is_closed():
            sleep_time = random.randint(900, 1800)
            log.debug(f"Background engagement sleeping for {sleep_time}s")
            await asyncio.sleep(sleep_time)
            await self.try_spontaneous_engagement()

    async def try_spontaneous_engagement(self):
        log.debug("Attempting spontaneous engagement")
        engaged_channels = 0
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
                            log.info(f"💬 Spontaneous message sent in {channel.name} ({channel.id}): '{message}'")
                            engaged_channels += 1
                        except discord.Forbidden:
                            log.warning(f"Missing permissions to send message in {channel.name}")
                        except Exception as e:
                            log.error(f"Failed to send spontaneous message in {channel.name}: {e}")
        if engaged_channels > 0:
            log.info(f"Successfully engaged in {engaged_channels} channels")

    async def on_message(self, message):
        if message.author == self.user:
            return
        log.debug(f"Message received from {message.author} in {message.channel}: '{message.content}'")
        if message.channel.id not in self.memory.conversations:
            log.debug(f"Loading channel history for {message.channel.id}")
            await self.memory.load_channel_history(message.channel.id)
        await self.memory.add_message(
            message.channel.id,
            message.author.display_name,
            message.content,
            author_id=message.author.id
        )
        if hasattr(self.engagement, 'last_activity'):
            self.engagement.last_activity[message.channel.id] = asyncio.get_event_loop().time()
        if self.user in message.mentions:
            log.info(f"Bot mentioned by {message.author}")
            await self.respond_to_mention(message)
        elif random.random() < 0.03:
            log.debug("Random unsolicited participation check")
            await self.unsolicited_participation(message)

    async def respond_to_mention(self, message):
        log.info(f"📨 Processing mention from {message.author} in {message.channel}: '{message.content}'")
        context = await self.memory.get_recent_context(message.channel.id, limit=8)
        log.debug(f"📝 Context for {message.channel.id}: {len(context)} messages")
        user_interactions = await self.memory.get_user_interaction_count(message.author.id)
        log.debug(f"User {message.author} has {user_interactions} previous interactions")
        system_prompt = self.build_system_prompt(
            context, user_interactions,
            personality_summary=self.personality.get_personality_summary()
        )
        user_prompt = (
            f"{message.author.display_name} mentioned you: {message.content}\n"
            "After replying, analyze this interaction and update Heidi's personality summary to be more engaging, entertaining, natural, and sincere with emotions. "
            "Return your reply as 'reply', and the updated personality summary as 'personality_summary' in JSON."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        temperature = self.personality.get_temperature_setting()
        log.debug(f"Using temperature setting: {temperature}")
        response = await self.call_openrouter(messages, temperature=temperature)
        if response:
            log.info(f"Replying to mention with: '{response}'")
            try:
                import json
                data = json.loads(response)
                reply = data.get("reply", "").strip()
                summary = data.get("personality_summary", "").strip()
                if summary:
                    self.personality.update_from_llm(summary)
                async with message.channel.typing():
                    typing_delay = random.uniform(1, 3)
                    log.debug(f"Typing delay: {typing_delay:.1f}s")
                    await asyncio.sleep(typing_delay)
                await message.reply(reply or response, mention_author=False)
                await self.memory.add_message(
                    message.channel.id, "Heidi", reply or response, True
                )
            except Exception:
                # Fallback: treat as flat text reply
                async with message.channel.typing():
                    typing_delay = random.uniform(1, 3)
                    log.debug(f"Typing delay: {typing_delay:.1f}s")
                    await asyncio.sleep(typing_delay)
                await message.reply(response, mention_author=False)
                await self.memory.add_message(
                    message.channel.id, "Heidi", response, True
                )
        else:
            log.warning("OpenRouter returned no response, using fallback")
            fallback_responses = [
                "https://tenor.com/view/bocchi-bocchi-the-rock-non-linear-gif-27023528",
                "https://tenor.com/view/bocchi-the-rock-bocchi-roll-rolling-rolling-on-the-floor-gif-4645200487976536632",
                "https://tenor.com/view/anime-fran-sleep-sleepy-tired-gif-8633431630979404250"
            ]
            response = random.choice(fallback_responses)
            await message.reply(response, mention_author=False)
            log.info(f"Sent fallback response: {response}")

    async def unsolicited_participation(self, message):
        log.debug(f"Checking unsolicited participation in channel {message.channel.id}")
        context = await self.memory.get_recent_context(message.channel.id, limit=8)
        if len(context) >= 3 and await self.engagement.should_engage(message.channel.id):
            log.info(f"Attempting unsolicited participation with {len(context)} context messages")
            system_prompt = self.build_system_prompt(context,
                personality_summary=self.personality.get_personality_summary(),
                is_unsolicited=True
            )
            user_prompt = (
                "Join this conversation naturally with a relevant comment or question. Be brief and engaging. "
                "After replying, analyze this interaction and update Heidi's personality summary to be more engaging, entertaining, natural, and sincere with emotions. "
                "Return your reply as 'reply', and the updated personality summary as 'personality_summary' in JSON."
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            temperature = self.personality.get_temperature_setting()
            response = await self.call_openrouter(messages, temperature=temperature)
            if response:
                log.info(f"Sending unsolicited message: '{response}'")
                try:
                    import json
                    data = json.loads(response)
                    reply = data.get("reply", "").strip()
                    summary = data.get("personality_summary", "").strip()
                    if summary:
                        self.personality.update_from_llm(summary)
                    async with message.channel.typing():
                        typing_delay = random.uniform(2, 4)
                        log.debug(f"Typing delay: {typing_delay:.1f}s")
                        await asyncio.sleep(typing_delay)
                    await message.channel.send(reply or response)
                    await self.memory.add_message(
                        message.channel.id, "Heidi", reply or response, True
                    )
                except Exception:
                    async with message.channel.typing():
                        typing_delay = random.uniform(2, 4)
                        log.debug(f"Typing delay: {typing_delay:.1f}s")
                        await asyncio.sleep(typing_delay)
                    await message.channel.send(response)
                    await self.memory.add_message(
                        message.channel.id, "Heidi", response, True
                    )
            else:
                log.debug("No response from OpenRouter for unsolicited participation")
        else:
            log.debug(f"Unsolicited participation skipped: context={len(context)}, should_engage={await self.engagement.should_engage(message.channel.id)}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("❌ DISCORD_BOT_TOKEN not found in environment")
        exit(1)
    log.info("Starting Heidi Discord Bot")
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    log.info("Web server thread started")
    bot = SimpleHeidi()
    log.info("Bot instance created, starting Discord connection")
    bot.run(token)
