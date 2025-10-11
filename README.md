# Heidi Bot

Heidi Bot is a Discord chatbot designed to provide engaging, adaptive, and entertaining conversation in your Discord server. Built by [Proxy](https://github.com/psychoticproxy), Heidi is not just a generic bot—she has a dynamic persona that evolves based on user interactions, server culture, and administrator input. The bot leverages persistent memory, reflection, and summarization to create a uniquely personal chat experience.

> **Try out Heidi Bot:** [Join Proxy's Hideout](https://discord.com/invite/M6SfZAfsQh)

## Features

- **Adaptive Personality**: Heidi learns from recent conversations and administrator feedback, evolving her style and responses to maximize user engagement.
- **Memory & Summaries**: Remembers per-user and per-server interactions, summarizes conversations, and can reset or reflect on her persona.
- **Queue Management**: Handles rate limits and message delivery with a persistent queue system.
- **Admin Commands**: Control persona, memory, message queue, and more.
- **Web Status Endpoint**: Simple Flask web interface to report bot status for monitoring.

## Persona

Heidi is characterized by:
- Playful and mischievous behavior
- Curiosity about human psychology
- Lucid with occasional unhinged moments
- Comfort with dark humor and controversial topics
- Always concise, laconic, and in-character

> Persona rules and reflection logic are defined in [`persona.py`](./persona.py).

## Setup

### Prerequisites

- Python 3.11+
- Discord bot token
- OpenRouter API key (for LLM completions)

### Installation

```bash
git clone https://github.com/psychoticproxy/heidi-bot.git
cd heidi-bot
pip install -r requirements.txt
```

Or use Docker:

```bash
docker build -t heidi-bot .
docker run --env-file .env heidi-bot
```

### Configuration

Create a `.env` file in your project root:

```
OPENROUTER_API_KEY=your_openrouter_api_key
DISCORD_BOT_TOKEN=your_discord_bot_token
PORT=8000  # optional, for web status
```

### Running

```bash
python heidi.py
```

## Usage

Once running, invite your bot to a server and use Discord mentions or commands:

- `!persona` – Show Heidi's current persona
- `!reflect` – Force persona adaptation (admin only)
- `!queue` – Show queued messages
- `!clearqueue` – Clear all pending messages (admin only)
- `!setpersona <text>` – Manually set persona (admin only)
- `!randommsg` – Send a spontaneous message to a random user in a role (admin only)
- `!runsummaries` – Summarize user and guild histories (admin only)
- `!resetmemory` – Wipe all bot memory and persona (admin only)

Heidi will also respond to direct mentions.

## File Structure

- [`heidi.py`](./heidi.py): Main bot logic and Discord event handling
- [`queue_manager.py`](./queue_manager.py): Persistent message queue
- [`persona.py`](./persona.py): Persona management and reflection
- [`memory.py`](./memory.py): Long/short-term memory and summarization
- [`requirements.txt`](./requirements.txt): Python dependencies
- [`Dockerfile`](./Dockerfile): Container build instructions
- [`LICENSE`](./LICENSE): Public domain license (Unlicense)

## License

This is free and unencumbered software released into the public domain. See [`LICENSE`](./LICENSE) for details.

## Support

Buy Proxy a coffee: [Ko-fi](https://ko-fi.com/proxylikeskofi)

---

_Heidi Bot is still under development! Contributions and feedback are welcome._
