import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Discord
    DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    
    # Database
    DB_HOST = os.getenv("DATABASE_HOST")
    DB_USER = os.getenv("DATABASE_USER")
    DB_PASSWORD = os.getenv("DATABASE_PASSWORD")
    DB_NAME = os.getenv("DATABASE_NAME")
    DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    
    # OpenRouter
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    DEFAULT_MODEL = "tngtech/deepseek-r1t2-chimera:free"
    UNCENSORED_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    
    # Bot Settings
    COMMAND_PREFIX = "!"
    DAILY_API_LIMIT = 1000
    MAX_MEMORY_CONTEXT = 20
    
    # Personality
    DEFAULT_PERSONALITY = "emotionally complex, moody, sarcastic, empathetic, unpredictable"
    DEFAULT_TEMPERATURE = 0.7

