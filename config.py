import os

class Config:
    # Discord and API settings
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    COMMAND_PREFIX = "!"
    DAILY_API_LIMIT = 500
    DEFAULT_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
    DEFAULT_TEMPERATURE = 0.7
    
    # Database configuration (PostgreSQL)
    DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
    DATABASE_USER = os.getenv("DATABASE_USER", "postgres")
    DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
    DATABASE_NAME = os.getenv("DATABASE_NAME", "heidi")
    DATABASE_PORT = int(os.getenv("DATABASE_PORT", 5432))

