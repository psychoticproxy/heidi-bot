import httpx
import logging
from config import Config

log = logging.getLogger("heidi.api")

class OpenRouterClient:
    def __init__(self, bot):
        self.bot = bot
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def generate_response(self, context, user_message, user_name, system_prompt=None):
        """Generate AI response with optional system prompt override"""
        if self.bot.daily_usage >= Config.DAILY_API_LIMIT:
            log.warning("Daily API limit reached")
            return None
        
        # Build messages
        if system_prompt is None:
            personality = await self.bot.db.fetchval("SELECT value FROM personality WHERE key = 'summary'")
            system_prompt = f"""You are Heidi, a Discord bot. 
Personality: {personality}
Respond naturally and concisely in 1-3 sentences without it being enclosed in quotation marks or anything else."""
        
        # Build conversation context
        conversation_text = "\n".join([
            f"{msg['author']}: {msg['content']}" for msg in context[-5:]  # Last 5 messages
        ])
        
        user_prompt = f"Recent conversation:\n{conversation_text}\n\n{user_name} mentioned you: {user_message}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # API call
        try:
            model = self.bot.current_model
            
            response = await self.client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": Config.DEFAULT_TEMPERATURE,
                    "max_tokens": 600,
                },
            )
            
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            # Update usage
            self.bot.daily_usage += 1
            
            log.info(f"✅ API response: {content[:50]}...")
            return content
            
        except Exception as e:
            log.error(f"❌ API error: {e}")
            return None
    
    async def close(self):
        await self.client.aclose()

