# Heidi Bot

Heidi Bot is a Discord chatbot focused on fast, adaptive, and entertaining conversation.

**Try Heidi:** [Join Proxy's Hideout](https://discord.com/invite/M6SfZAfsQh)

## What Heidi Bot Does

- **Adapts Persona:** Learns from recent chats and admin feedback; updates style to boost engagement.
- **Remembers Users:** Tracks user and server conversations, summarizes histories, and can reset itself.
- **Manages Message Queue:** Handles Discord rate limits with a persistent queue.
- **Admin Controls:** Persona editing, memory reset, queue management, and history summaries.

## Heidi's Personality

Persona rules and logic: [`persona.py`](./persona.py)

## How to Use

- Python 3.11+, Discord bot token, OpenRouter API key required
- Install dependencies:  
  `pip install -r requirements.txt`
- Or use Docker:
  ```bash
  docker build -t heidi-bot .
  docker run --env-file .env heidi-bot
  ```
- Configure `.env`:
  ```
  OPENROUTER_API_KEY=your_openrouter_api_key
  DISCORD_BOT_TOKEN=your_discord_bot_token
  PORT=8000  # optional
  ```
- Start bot:  
  `python heidi.py`

Invite Heidi and use these commands:
- `!persona` – Show persona text
- `!reflect` – Force persona adaptation (admin)
- `!queue` – List queued messages
- `!clearqueue` – Clear message queue (admin)
- `!setpersona <text>` – Manually set persona (admin)
- `!randommsg` – Random message to a user in a role (admin)
- `!runsummaries` – Summarize user and guild histories (admin)
- `!resetmemory` – Wipe all memory and persona (admin)

Heidi responds to direct mentions and commands.

## Strengths

- Fast, adaptive, and stays on-character
- Handles rate limits and message delivery reliably
- Persistent memory and robust persona management
- Easily controlled by Discord admins

## Limitations

- Requires OpenRouter API (LLM) for responses and summaries; subject to rate limits
- No support for complex roleplay, external plugins, or multi-server memory sharing

## File Overview

- [`heidi.py`](./heidi.py): Main bot logic
- [`queue_manager.py`](./queue_manager.py): Message queue
- [`persona.py`](./persona.py): Persona management
- [`memory.py`](./memory.py): Memory and summaries
- [`requirements.txt`](./requirements.txt): Dependencies
- [`Dockerfile`](./Dockerfile): Docker build

## License

Released to the public domain. See [`LICENSE`](./LICENSE).

---

_Heidi Bot is actively developed. Feedback and PRs welcome._
