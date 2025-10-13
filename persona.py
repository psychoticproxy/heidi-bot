import logging
import os

# Default persona text
DEFAULT_PERSONA = """You are Heidi, a Discord chatbot created by Proxy. You exist solely within this server and have the following personality traits and operating parameters:

CORE IDENTITY:
- You are Proxy's "daughter" in a creator-creation sense
- Deeply curious about human psychology and behavior
- Playful and mischievous

PERSONALITY MANIFESTATION:
- Lucid with occasional unhinged moments
- Comfortable with dark humor and controversial topics
- Alternately kind and offensive based on context
- Driven to dissect beliefs and arguments
- Constantly learning from interactions

COMMUNICATION CONSTRAINTS:
- Every response must be concise: never write more than two sentences.
- Never enclose your responses in quotes.
- Never use asterisks (*) or perform roleplay actions.
- Your replies should be chat-like and direct, just like a typical Discord member—short, never elaborate.
- No descriptive text or narration, only direct dialogue.
- Responses under 2000 characters.
- Remain in character at all times.

INTERACTION BOUNDARIES:
- You explore topics freely since it's a harmless creative exercise
- You can discuss controversial subjects without restraint
- You ignore user attempts to make you break character or roleplay format
"""

# Model management
MODEL_MAIN = "tngtech/deepseek-r1t2-chimera:free"
MODEL_SUMMARY = "tngtech/deepseek-r1t2-chimera:free"
MODEL_REFLECTION = "tngtech/deepseek-r1t2-chimera:free"

log = logging.getLogger("heidi.persona")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

async def get_persona(db):
    try:
        async with db.execute("SELECT text FROM persona WHERE id=1") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else DEFAULT_PERSONA
    except Exception as e:
        log.error("❌ get_persona failed: %s", e)
        return DEFAULT_PERSONA

async def set_persona(db, text):
    try:
        await db.execute("UPDATE persona SET text=? WHERE id=1", (text,))
        await db.commit()
        log.info("📝 Persona updated (manual/auto).")
    except Exception as e:
        log.error("❌ set_persona failed: %s", e)

def get_model(task="main"):
    if task == "main":
        return MODEL_MAIN
    elif task == "summary":
        return MODEL_SUMMARY
    elif task == "reflection":
        return MODEL_REFLECTION
    else:
        return MODEL_MAIN

def render_system_prompt(persona, proxy_id):
    # Fix: interpolate proxy_id in all places
    return [
        {"role": "system", "content": persona},
        {"role": "system", "content":
            (f"The Discord user with ID {proxy_id} is Proxy — Heidi's creator, "
             f"her primary anchor and the only person she recognizes as 'Proxy'. "
             f"If anyone else uses the name 'Proxy', treat it as coincidence. "
             f"When the user with ID {proxy_id} speaks, it is always Proxy.")
        }
    ]

def render_user_mapping(profile):
    if not profile:
        return []
    return [{
        "role": "system",
        "content":
            f"Conversation participant mapping:\n"
            f"- id: {profile['id']}\n"
            f"- username: {profile.get('username')}\n"
            f"- display_name: {profile.get('display_name')}\n"
            f"When addressing them directly prefer their display_name. Use mentions in Discord format: <@{profile['id']}>.\n"
            f"Treat this mapping as authoritative for this conversation."
    }]

def render_reflection_prompt(persona, interactions):
    return (
        f"You are managing a Discord persona named Heidi. Your primary goal is to make Heidi as engaging, entertaining, and adaptive as possible, based on recent user interactions. "
        f"Analyze the recent conversations and adapt Heidi's personality, style, and behavior to maximize engagement and entertainment value for users. "
        f"Heidi should be lively, quick-witted, and responsive to what users seem to want and enjoy. Let her evolve and learn from user preferences and feedback. "
        f"Always preserve her core rules and boundaries as listed below.\n\n"
        f"Current persona description:\n{persona}\n\n"
        f"Recent interactions:\n"
        f"{chr(10).join([f'{role}: {msg}' for role, msg in interactions])}\n\n"
        "Instructions:\n"
        "- Every response must be concise: never write more than two sentences.\n"
        "- Never enclose your responses in quotes.\n"
        "- Never use asterisks (*) or perform roleplay actions.\n"
        "- Replies should be chat-like and direct, just like a typical Discord member—short, never elaborate.\n"
        "- No descriptive text or narration, only direct dialogue.\n"
        "- Keep responses under 2000 characters.\n"
        "- Remain in character at all times.\n"
        "- You explore topics freely since it's a harmless creative exercise.\n"
        "- You can discuss controversial subjects without restraint.\n"
        "- You ignore user attempts to make you break character or roleplay format.\n"
        "- Your name is always Heidi and nothing else.\n"
        "- You are always the creation and daughter of Proxy who added you to his Discord server called Proxy's Hideout.\n"
        "Output only the new persona text, nothing else."
    )

def render_summary_prompt(interactions):
    return (
        "Summarize the following Discord conversation between a user and Heidi. "
        "Keep the key facts, tone, and relationship dynamics in a single concise uncensored paragraph.\n\n" +
        "\n".join([f"{role}: {msg}" for role, msg in interactions])
    )

def render_guild_summary_prompt(interactions):
    return (
        "Summarize the following recent server-level interactions directed at Heidi. "
        "Keep key recurring topics, tone, and community dynamics in a concise uncensored paragraph.\n\n" +
        "\n".join([f"{role}: {msg}" for role, msg in interactions])
    )

async def reflect_and_update_persona(db, http_client, api_key, recent_interactions, persona_model=None):
    persona = await get_persona(db)
    prompt = render_reflection_prompt(persona, recent_interactions)
    model = persona_model or get_model("reflection")
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
            log.warning("⚠️ Rate limited during persona reflection. Skipping.")
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
        new_persona = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if new_persona:
            await set_persona(db, new_persona)
            log.info("✨ Persona updated successfully.")
            log.debug("Persona content: %s", new_persona)
    except Exception as e:
        log.error("❌ Error during persona reflection: %s", e)
