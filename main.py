import os
import logging
from bot.core import SimpleHeidi
from health import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("heidi")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        log.error("❌ DISCORD_BOT_TOKEN not found")
        exit(1)
    
    # Start health check server on port 8000 (Koyeb default)
    start_health_server(port=8000)
    
    bot = SimpleHeidi()
    bot.run(token)

