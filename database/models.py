from collections import deque

# Simple in-memory cache
conversation_cache = {}

async def add_message(db, channel_id, author, content, author_id=None, is_bot=False):
    """Add message to database and cache"""
    # Add to database
    await db.execute(
        "INSERT INTO conversations (channel_id, author, author_id, content, is_bot) VALUES ($1, $2, $3, $4, $5)",
        str(channel_id), author, str(author_id) if author_id else None, content, is_bot
    )
    
    # Add to cache
    if channel_id not in conversation_cache:
        conversation_cache[channel_id] = deque(maxlen=20)
    
    conversation_cache[channel_id].append({
        'author': author,
        'content': content,
        'is_bot': is_bot
    })

async def get_recent_context(db, channel_id, limit=10):
    """Get recent conversation context"""
    # Try cache first
    if channel_id in conversation_cache:
        return list(conversation_cache[channel_id])[-limit:]
    
    # Fallback to database
    rows = await db.fetch(
        "SELECT author, content, is_bot FROM conversations WHERE channel_id = $1 ORDER BY timestamp DESC LIMIT $2",
        str(channel_id), limit
    )
    
    messages = [
        {'author': row['author'], 'content': row['content'], 'is_bot': row['is_bot']}
        for row in rows[::-1]  # Reverse to get chronological order
    ]
    
    # Update cache
    if channel_id not in conversation_cache:
        conversation_cache[channel_id] = deque(maxlen=20)
    conversation_cache[channel_id].extend(messages)
    
    return messages

async def get_personality(db):
    """Get current personality summary"""
    return await db.fetchval("SELECT value FROM personality WHERE key = 'summary'")

async def update_personality(db, new_summary):
    """Update personality summary"""
    await db.execute(
        "INSERT INTO personality (key, value) VALUES ('summary', $1) ON CONFLICT (key) DO UPDATE SET value = $1",
        new_summary
    )

