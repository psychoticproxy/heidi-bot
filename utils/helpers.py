import random
from datetime import datetime

def get_fallback_response():
    """Get random fallback response"""
    fallbacks = [
        "🤖 *beep boop*",
        "💤 zzz...",
        "🎵 la la la...",
        "🤔 hmm...",
        "📡 connecting...",
        "⚡ processing...",
    ]
    return random.choice(fallbacks)

def format_usage_stats(current, limit):
    """Format usage statistics"""
    percent = (current / limit) * 100
    return f"{current}/{limit} ({percent:.1f}%)"

def is_administrator(ctx):
    """Check if user has administrator permissions"""
    return ctx.author.guild_permissions.administrator

