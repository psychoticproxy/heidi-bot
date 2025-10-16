# Heidi Discord Bot

A Discord bot that uses AI to engage in conversations, adapts its personality, and remembers interactions.

## Features

- Responds to mentions and joins conversations spontaneously
- Maintains conversation memory with SQLite
- Adapts personality based on interactions
- Uses OpenRouter API for AI responses
- Includes basic commands and health monitoring

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file:**
   ```
   DISCORD_BOT_TOKEN=your_discord_token
   OPENROUTER_API_KEY=your_openrouter_key
   PORT=8000  # Optional
   ```

3. **Run the bot:**
   ```bash
   python simple_heidi.py
   ```

### Docker
```bash
docker build -t heidi-bot .
docker run --env-file .env heidi-bot
```

## Usage

- Mention the bot (`@Heidi`) for direct responses
- Bot occasionally joins active conversations (3% chance)
- Commands: `!ping`, `!usage`, `!personality`, `!memory`, `!help`
- Health check: `http://localhost:8000/health`

## Configuration

- Daily API limit: 500 requests
- Memory retention: 7 days
- Databases: `heidi_memory.db` and `personality.db`

## License

Public Domain (Unlicense)
