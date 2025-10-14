# Heidi

Heidi is a Discord chatbot focused on fast, adaptive, and entertaining conversation.

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

Invite Heidi and use `!help` to see all commands.

Heidi responds to direct mentions and commands.

## License

Released to the public domain. See [`LICENSE`](./LICENSE).

---

_Heidi Bot is actively developed. Feedback and PRs welcome._
