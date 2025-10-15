# Heidi Discord Bot

A smart, adaptive Discord chatbot that engages in natural conversations while learning from user interactions and evolving her personality over time.

## Overview

Heidi is designed to be more than just a typical chatbot - she adapts her personality based on conversations, remembers user interactions, and knows when to join discussions naturally. Unlike static bots, Heidi learns from engagement patterns and evolves her response style to better suit each server's culture.

**Try Heidi:** [Join Proxy's Hideout](https://discord.com/invite/M6SfZAfsQh)

## Core Components

### Main Bot (`simple_heidi.py`)
- Handles Discord events and message processing
- Manages API calls to OpenRouter for AI responses
- Coordinates between memory, personality, and engagement systems
- Implements rate limiting and fallback responses
- Runs background web server for health monitoring

### Conversation Memory (`simplified_memory.py`)
- **Channel History**: Tracks recent conversations per channel with configurable context length
- **User Profiles**: Remembers interaction counts and user preferences
- **Persistent Storage**: Uses SQLite to maintain conversation history across restarts
- **Context Management**: Provides recent conversation context for relevant responses
- **Automatic Cleanup**: Removes old messages to prevent database bloat

### Adaptive Personality (`personality.py`)
- **Dynamic Traits**: Adjusts curiosity, playfulness, empathy, sarcasm, enthusiasm, friendliness, humor, and directness based on interactions
- **Learning Patterns**: Identifies which topics and words generate better engagement through reinforcement learning
- **Persistent Storage**: Saves personality evolution across bot restarts using SQLite
- **Tone Adaptation**: Modifies response style and creativity based on learned preferences
- **Temperature Control**: Adjusts AI response variability based on current personality state

### Engagement Engine (`engagement.py`)
- **Activity Tracking**: Monitors channel activity to determine when to engage
- **Spontaneous Messages**: Generates natural conversation starters in active channels
- **Timing Logic**: Prevents over-engagement in inactive channels (2-hour activity window)
- **Context-Aware Joining**: Only participates when recent conversation provides context

## How It Works

### 1. Message Processing
- **Direct Mentions**: Always responds when directly mentioned with context-aware replies
- **Spontaneous Engagement**: Joins active conversations naturally (3% chance in active channels)
- **Context Loading**: Automatically loads channel history when first interacting
- **Activity Tracking**: Updates engagement timestamps for smart participation decisions

### 2. Response Generation
- **System Prompt Construction**: Builds context-aware prompts including recent conversation and user interaction history
- **Personality Injection**: Uses current personality traits to influence response style and tone
- **Temperature Control**: Adjusts creativity based on playfulness and enthusiasm levels (0.7-0.9 range)
- **API Management**: Handles OpenRouter API calls with daily limits (500 requests) and fallback responses

### 3. Learning & Adaptation
- **Success Tracking**: Reinforces patterns that lead to positive interactions through engagement level scoring
- **Trait Adjustment**: Gradually evolves personality traits based on interaction success and content analysis
- **Word Association**: Learns which topics and phrases work well in different contexts through pattern strength tracking
- **Periodic Persistence**: Saves learned patterns to database every 10 interactions

### 4. Memory Management
- **User Recognition**: Tracks how many times each user has interacted for personalized responses
- **Conversation Flow**: Maintains context across multiple messages using sliding window approach
- **Database Persistence**: Ensures memory survives bot restarts with automatic history loading
- **Efficient Storage**: Uses deque structures for in-memory management with SQLite backup

## Setup & Configuration

### Prerequisites
- **Python 3.11** or higher
- **Discord Bot Token** from [Discord Developer Portal](https://discord.com/developers/applications)
- **OpenRouter API Key** from [OpenRouter](https://openrouter.ai/)
- Required permissions: `bot` with `Send Messages`, `Read Message History`, and `Use Slash Commands`

### Installation Steps

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   Required packages: `discord.py`, `aiosqlite`, `flask`, `python-dotenv`, `httpx`

2. **Environment Configuration**
   Create a `.env` file in the project root:
   ```
   OPENROUTER_API_KEY=your_openrouter_api_key_here
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   PORT=8000  # Optional: for health check server (default: 8000)
   ```

3. **Run the Bot**
   ```bash
   python simple_heidi.py
   ```

### Docker Installation (Alternative)

```bash
# Build the image
docker build -t heidi-bot .

# Run with environment file
docker run --env-file .env heidi-bot
```

### Bot Invitation

1. Create an application in Discord Developer Portal
2. Add a bot with required permissions
3. Use OAuth2 URL generator to create invite link with:
   - `bot` scope
   - Permissions: `Send Messages`, `Read Message History`
4. Invite to your server

### Usage

- **Mention Responses**: Tag Heidi with `@Heidi` or your bot's name to get responses
- **Spontaneous Engagement**: Heidi will occasionally join active conversations naturally
- **Command Support**: Use `!help` to see available commands (if implemented in your version)
- **Health Monitoring**: Access `http://localhost:8000/health` to check bot status

### Configuration Notes

- **Daily API Limits**: Set to 500 requests by default (adjustable in code)
- **Memory Retention**: Conversations are stored for 7 days before automatic cleanup
- **Personality Database**: Stored in `personality.db`, engagement patterns in `heidi_memory.db`
- **Web Server**: Runs on port 8000 for health checks (configurable via PORT env var)

## Technical Stack

- **Discord.py**: Discord bot framework with async support
- **OpenRouter API**: LLM provider using dolphin-mistral-24b model
- **SQLite**: Local database for persistent memory and personality storage
- **Flask**: Lightweight web server for health monitoring
- **Async/Await**: Non-blocking operations for better performance
- **AIOSQLite**: Async SQLite database operations

## License

This project is released into the public domain using the Unlicense. See the [LICENSE](LICENSE) file for details.

You are free to copy, modify, distribute, and use this software for any purpose without restriction.

---

_Heidi Bot is actively developed. Feedback and contributions are welcome!_

For issues, suggestions, or to contribute, please visit the project repository or join the Discord community.
