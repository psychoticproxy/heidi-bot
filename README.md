# Heidi Discord Bot

A modular Discord bot with personality, memory, and automated moderation features.

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL database
- Discord bot token
- OpenRouter API key

### Installation

1. **Clone and setup:**
```bash
git clone <your-repo>
cd heidi-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Environment variables:**
```bash
# Create .env file
DISCORD_BOT_TOKEN=your_discord_token
OPENROUTER_API_KEY=your_openrouter_key
DATABASE_HOST=your_db_host
DATABASE_USER=your_db_user  
DATABASE_PASSWORD=your_db_password
DATABASE_NAME=your_db_name
```

3. **Run the bot:**
```bash
python main.py
```

## Docker Deployment

```bash
# Build and run locally
docker build -t heidi-bot .
docker run -e DISCORD_BOT_TOKEN=your_token [...] heidi-bot

# Or deploy to Koyeb
# Connect your Git repo - Koyeb will auto-detect the Dockerfile
```

## Features

### Core Features
- **AI Conversations**: Responds to mentions using OpenRouter AI
- **Personality System**: Customizable bot personality
- **Memory**: Remembers conversation context
- **Modular Design**: Easy to extend with new features

### Sacrifice System
- **Manual Sacrifice**: `!sacrifice` - Remove random member without roles (Admin)
- **Auto Sacrifice**: `!autosacrifice on` - Daily automated purification
- **Scheduling**: `!sacrificetime 14` - Set daily time (0-23 UTC)

### Basic Commands
- `!ping` - Check bot latency
- `!usage` - API usage statistics  
- `!personality` - Show current personality
- `!memory` - Memory statistics
- `!help` - Show all commands

## Project Structure

```
heidi-bot/
├── main.py                 # Entry point
├── config.py              # Configuration
├── bot/                   # Core bot functionality
├── cogs/                  # Command modules
├── database/              # Database layer
├── api/                   # OpenRouter API client
├── utils/                 # Utility functions
└── requirements.txt       # Dependencies
```

## Configuration

Edit `config.py` to customize:
- Command prefix (`!`)
- Default AI model
- Daily API limits
- Personality settings

## Deployment

### Koyeb (Recommended)
1. Push code to GitHub
2. Connect repository in Koyeb dashboard
3. Set environment variables
4. Deploy - Koyeb handles Docker build automatically

### Manual Deployment
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISCORD_BOT_TOKEN=your_token
export OPENROUTER_API_KEY=your_key
# ... other env vars

# Run
python main.py
```

## Development

### Adding New Features
1. Create new cog in `cogs/` directory
2. Import and load in `bot/core.py`
3. That's it! The modular design handles the rest

### Example Cog Template
```python
import discord
from discord.ext import commands

class ExampleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command()
    async def example(self, ctx):
        await ctx.send("Example command!")

async def setup(bot):
    await bot.add_cog(ExampleCog(bot))
```

## API Usage

The bot tracks daily API usage and will stop responding if limits are reached. Use `!usage` to check current usage.

## Important Notes

- **Permissions**: Bot needs `Kick Members` permission for sacrifice feature
- **Database**: Requires PostgreSQL with connection details in environment variables
- **Rate Limits**: Respects OpenRouter API rate limits and daily quotas

## Troubleshooting

**Bot won't start:**
- Check all environment variables are set
- Verify Discord token has proper permissions
- Ensure database is accessible

**Commands not working:**
- Bot needs `Message Content Intent` enabled in Discord Developer Portal
- Check command prefix (default: `!`)

**Sacrifice fails:**
- Bot needs `Kick Members` permission
- Target members must have no roles (except @everyone)

## License

GNU General Public License - Everyone is permitted to copy and distribute verbatim copies of this license document, but changing it is not allowed.

---

**Need help?** Check the code comments or open an issue in the repository.
