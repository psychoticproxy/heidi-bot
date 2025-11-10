import os

class Config:
    # Discord and API settings
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    COMMAND_PREFIX = "!"
    DAILY_API_LIMIT = 500
    DEFAULT_MODEL = "tngtech/deepseek-r1t2-chimera:free"
    DEFAULT_TEMPERATURE = 0.7

    # SQLite configuration (local file used when deploying as a single service)
    # Default path inside the container; change via env var if needed.
    SQLITE_PATH = os.getenv("SQLITE_PATH", "heidi.db")
