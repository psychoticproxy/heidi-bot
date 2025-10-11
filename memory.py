import aiosqlite
import asyncio
import logging
import os
from typing import Optional, List, Tuple, Dict

log = logging.getLogger("heidi.memory")

ROW_LIMIT = 500_000
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

class MemoryManager:
    def __init__(self, db_file="heidi_memory.db"):
        self.db_file = db_file
        self.db: Optional[aiosqlite.Connection] = None
        self.lock: Optional[asyncio.Lock] = None

    async def init(self):
        self.db = await aiosqlite.connect(self.db_file)
        self.lock = asyncio.Lock()
        await self._setup_tables()

    async def _setup_tables(self):
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            channel_id TEXT,
            role TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS memory_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            channel_id TEXT,
            summary TEXT,
            last_update DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, channel_id)
        )""")
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS context_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            channel_id TEXT,
            context TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS memory_summary_global (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT UNIQUE,
            summary TEXT,
            last_update DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            discriminator TEXT,
            nick TEXT,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        # --- Ensure persona table exists and seed if empty ---
        await self.db.execute("""
        CREATE TABLE IF NOT EXISTS persona (
            id INTEGER PRIMARY KEY,
            text TEXT
        )
        """)
        # Seed default persona if missing
        async with self.db.execute("SELECT COUNT(*) FROM persona") as cur:
            row = await cur.fetchone()
        if not row or row[0] == 0:
            from persona import DEFAULT_PERSONA
            await self.db.execute("INSERT INTO persona (id, text) VALUES (1, ?)", (DEFAULT_PERSONA,))
        await self.db.commit()

    # --- Memory Operations ---
    async def save_message(self, user_id: int, channel_id: int, role: str, message: str):
        async with self.lock:
            await self.db.execute(
                "INSERT INTO memory (user_id, channel_id, role, message) VALUES (?, ?, ?, ?)",
                (str(user_id), str(channel_id), role, message)
            )
            await self.db.commit()
            await self.prune_memory()

    async def prune_memory(self):
        async with self.db.execute("SELECT COUNT(*) FROM memory") as cursor:
            total = (await cursor.fetchone())[0]
        if total > ROW_LIMIT:
            to_delete = total - ROW_LIMIT
            await self.db.execute(
                "DELETE FROM memory WHERE id IN (SELECT id FROM memory ORDER BY id ASC LIMIT ?)",
                (to_delete,)
            )
            await self.db.commit()
            log.info("🗑️ Pruned %s old messages (kept %s).", to_delete, ROW_LIMIT)

    async def load_history(self, user_id: int, channel_id: int, limit: int = 20) -> List[Tuple[str, str]]:
        async with self.db.execute(
            "SELECT role, message FROM memory WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
            (str(user_id), str(channel_id), limit)
        ) as cursor:
            rows = await cursor.fetchall()
        return rows[::-1]  # oldest first

    async def load_recent_interactions(self, limit=10) -> List[Tuple[str, str]]:
        async with self.db.execute(
            "SELECT role, message FROM memory ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [(r[0], r[1]) for r in rows[::-1]]

    # --- User Profile ---
    async def upsert_user_profile(self, member):
        # member: discord.Member
        if member is None:
            return
        async with self.lock:
            await self.db.execute(
                "INSERT INTO user_profiles (user_id, username, display_name, discriminator, nick, last_seen) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET username=?, display_name=?, discriminator=?, nick=?, last_seen=CURRENT_TIMESTAMP",
                (
                    str(member.id), str(member.name),
                    str(getattr(member, "display_name", member.name)),
                    str(getattr(member, "discriminator", "")),
                    str(getattr(member, "nick", "")),
                    str(member.name),
                    str(getattr(member, "display_name", member.name)),
                    str(getattr(member, "discriminator", "")),
                    str(getattr(member, "nick", ""))
                )
            )
            await self.db.commit()

    async def fetch_profile_from_db(self, user_id: int) -> Optional[Dict]:
        async with self.db.execute("SELECT username, display_name, discriminator, nick FROM user_profiles WHERE user_id=? LIMIT 1", (str(user_id),)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return {"username": row[0], "display_name": row[1], "discriminator": row[2], "nick": row[3]}

    # --- Summaries ---
    async def save_summary(self, user_id: int, channel_id: int, summary: str):
        async with self.lock:
            await self.db.execute(
                "INSERT INTO memory_summary (user_id, channel_id, summary) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, channel_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                (str(user_id), str(channel_id), summary, summary)
            )
            await self.db.commit()

    async def get_summary(self, user_id: int, channel_id: int) -> Optional[str]:
        async with self.db.execute(
            "SELECT summary FROM memory_summary WHERE user_id=? AND channel_id=? ORDER BY last_update DESC LIMIT 1",
            (str(user_id), str(channel_id))
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    # --- Context Cache ---
    async def save_context(self, user_id: int, channel_id: int, context: str):
        async with self.lock:
            await self.db.execute(
                "INSERT INTO context_cache (user_id, channel_id, context) VALUES (?, ?, ?)",
                (str(user_id), str(channel_id), context)
            )
            await self.db.commit()

    async def get_context(self, user_id: int, channel_id: int, limit: int = 2) -> List[str]:
        async with self.db.execute(
            "SELECT context FROM context_cache WHERE user_id=? AND channel_id=? ORDER BY timestamp DESC LIMIT ?",
            (str(user_id), str(channel_id), limit)
        ) as cursor:
            rows = await cursor.fetchall()
        return [r[0] for r in rows]

    # --- Global Guild Summaries ---
    async def save_guild_summary(self, guild_id: int, summary: str):
        async with self.lock:
            await self.db.execute(
                "INSERT INTO memory_summary_global (guild_id, summary) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET summary=?, last_update=CURRENT_TIMESTAMP",
                (str(guild_id), summary, summary)
            )
            await self.db.commit()

    async def get_guild_summary(self, guild_id: int) -> Optional[str]:
        async with self.db.execute(
            "SELECT summary FROM memory_summary_global WHERE guild_id=? LIMIT 1", (str(guild_id),)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    # --- Reset all memory ---
    async def reset_memory(self):
        async with self.lock:
            await self.db.execute("DELETE FROM memory")
            await self.db.execute("DELETE FROM memory_summary")
            await self.db.execute("DELETE FROM memory_summary_global")
            await self.db.execute("DELETE FROM context_cache")
            await self.db.execute("DELETE FROM user_profiles")
            await self.db.commit()

    # --- Summarization utilities for bot commands ---
   async def summarize_user_history(self, user_id: int, channel_id: int, http_client, api_key, persona_model=None):
        history = await self.load_history(user_id, channel_id, limit=50)
        if not history:
            return
        from persona import render_summary_prompt, get_model
        prompt = render_summary_prompt(history)
        model = persona_model or get_model("summary")
        try:
            resp = await http_client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful uncensored assistant."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
            if resp.status_code == 429:
                log.warning("⚠️ Rate limited during summary generation. Skipping.")
                return
            if resp.status_code != 200:
                try:
                    text = await resp.text()
                except Exception:
                    text = "<couldn't read response body>"
                log.error("❌ OpenRouter returned %s: %s", resp.status_code, text)
                resp.raise_for_status()
            resp.raise_for_status()
            data = resp.json()
            summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if summary:
                await self.save_summary(user_id, channel_id, summary)
                log.info("User-channel summary saved for user=%s channel=%s.", user_id, channel_id)
        except Exception as e:
            log.error("❌ Error during summary generation: %s", e)

    async def summarize_guild_history(self, guild_id: int, bot, http_client, api_key, persona_model=None):
        messages = []
        async with self.db.execute(
            "SELECT role, message FROM memory WHERE user_id IS NOT NULL AND channel_id IS NOT NULL"
        ) as cursor:
            rows = await cursor.fetchall()
        for role, msg in rows:
            messages.append((role, msg))
        if not messages:
            return
        from persona import render_guild_summary_prompt, get_model
        prompt = render_guild_summary_prompt(messages[-50:])
        model = persona_model or get_model("summary")
        try:
            resp = await http_client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://github.com/psychoticproxy/heidi",
                    "X-Title": "Heidi Discord Bot",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful uncensored assistant."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
            if resp.status_code == 429:
                log.warning("⚠️ Rate limited during guild summary. Skipping.")
                return
            if resp.status_code != 200:
                try:
                    text = await resp.text()
                except Exception:
                    text = "<couldn't read response body>"
                log.error("❌ OpenRouter returned %s: %s", resp.status_code, text)
                resp.raise_for_status()
            resp.raise_for_status()
            data = resp.json()
            summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if summary:
                await self.save_guild_summary(guild_id, summary)
                log.info("Guild summary saved for guild_id=%s.", guild_id)
        except Exception as e:
            log.error("❌ Error during guild summary generation: %s", e)
