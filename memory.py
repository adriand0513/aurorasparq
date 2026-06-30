# memory.py - PostgreSQL Version with OpenAI Embeddings
import psycopg2
import requests
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from config import DATABASE_URL, XAI_API_KEY, XAI_API_BASE, XAI_MODEL, OPENAI_API_KEY
import openai

logger = logging.getLogger(__name__)

# OpenAI Configuration
openai.api_key = OPENAI_API_KEY


def get_db_connection():
    """Create PostgreSQL connection"""
    return psycopg2.connect(DATABASE_URL)


def get_embedding(text: str) -> list:
    """Generate embedding using OpenAI's text-embedding-3-small."""
    try:
        response = openai.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"OpenAI embedding error: {e}")
        return []


# ==================== INITIALIZATION ====================

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            convo_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS key_facts (
            id SERIAL PRIMARY KEY,
            convo_id TEXT NOT NULL,
            fact TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_recalled TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Core memory system initialized (PostgreSQL)")


def init_relationship_state():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            convo_id TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            emotional_temperature INTEGER DEFAULT 5,
            relationship_phase TEXT DEFAULT 'early_flirt',
            trust_level INTEGER DEFAULT 3,
            current_mood TEXT DEFAULT 'playful',
            last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS narrative_memories (
            id SERIAL PRIMARY KEY,
            convo_id TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            moment_type TEXT,
            description TEXT NOT NULL,
            emotional_tag TEXT,
            importance INTEGER DEFAULT 5
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Relationship state initialized")


def init_conversation_summaries():
    """Initialize with OpenAI embedding dimension (1536)"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id SERIAL PRIMARY KEY,
            convo_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            embedding VECTOR(1536),
            start_message_id INTEGER,
            end_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            importance INTEGER DEFAULT 5
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_summary_convo ON conversation_summaries(convo_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_summary_embedding ON conversation_summaries USING ivfflat (embedding vector_cosine_ops)')
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Conversation summaries table initialized with vector support")


# ==================== RELATIONSHIP STATE ====================

def get_relationship_state(convo_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM relationship_state WHERE convo_id = %s", (convo_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {
            "convo_id": row[0],
            "level": row[1],
            "pet_name": row[2],
            "emotional_temperature": row[3],
            "relationship_phase": row[4],
            "trust_level": row[5],
            "current_mood": row[6],
            "last_interaction": row[7],
            "notes": row[8]
        }
    return None


def update_relationship_state(convo_id: str, level_delta=0, emotional_delta=0,
                              new_phase=None, new_mood=None, pet_name=None, note=None):
    current = get_relationship_state(convo_id) or {
        "level": 1, "emotional_temperature": 5, "relationship_phase": "early_flirt",
        "trust_level": 3, "current_mood": "playful", "pet_name": None, "notes": ""
    }
    new_level = max(1, min(10, current["level"] + level_delta))
    nou_temp = max(1, min(10, current["emotional_temperature"] + emotional_delta))
    phase = new_phase or current["relationship_phase"]
    mood = new_mood or current["current_mood"]

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO relationship_state
        (convo_id, level, pet_name, emotional_temperature, relationship_phase,
         trust_level, current_mood, last_interaction, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT(convo_id) DO UPDATE SET
            level = %s,
            pet_name = COALESCE(%s, pet_name),
            emotional_temperature = %s,
            relationship_phase = %s,
            current_mood = %s,
            last_interaction = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || '\n' || %s, notes)
    ''', (convo_id, new_level, pet_name, new_temp, phase, current["trust_level"],
          mood, note or "",
          new_level, pet_name, new_temp, phase, mood, note or ""))
    conn.commit()
    cur.close()
    conn.close()


# ==================== HISTORY & FACTS ====================

def get_history(convo_id: str, limit: int = 50) -> List[Dict]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT role, content, timestamp
        FROM chat_history
        WHERE convo_id = %s
        ORDER BY timestamp ASC
        LIMIT %s
    ''', (convo_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


def save_message(convo_id: str, message: Dict, user_id: Optional[int] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO chat_history (convo_id, user_id, role, content)
        VALUES (%s, %s, %s, %s)
    ''', (convo_id, user_id, message["role"], message["content"]))
    conn.commit()
    cur.close()
    conn.close()


def get_relevant_facts(convo_id: str, limit: int = 8) -> List[str]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT fact
        FROM key_facts
        WHERE convo_id = %s
        ORDER BY importance DESC, last_recalled DESC
        LIMIT %s
    ''', (convo_id, limit))
    facts = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return facts


def add_key_fact(convo_id: str, fact: str, importance: int = 7):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO key_facts (convo_id, fact, importance, last_recalled)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
    ''', (convo_id, fact, importance))
    conn.commit()
    cur.close()
    conn.close()


# ==================== AUTOMATIC FACT EXTRACTION ====================

def extract_and_save_facts(convo_id: str, user_message: str, tier: str = "free"):
    if tier == "free":
        return
    if not user_message or len(user_message.strip()) < 10:
        return

    extraction_prompt = f"""Extract any important personal facts about the user from this message.
Only extract clear, useful, and specific information such as preferences, habits, life details,
strong opinions, background, or things he mentioned about himself.
If nothing meaningful is mentioned, return nothing.
User message: "{user_message}"
Return facts in this format (one per line):
fact: [fact here]
importance: [6-10]
Only include facts with importance 6 or higher."""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": extraction_prompt}],
                "temperature": 0.3,
                "max_tokens": 300
            },
            timeout=12
        )
        if resp.status_code != 200:
            return

        content = resp.json()["choices"][0]["message"]["content"].strip()
        if not content or "nothing" in content.lower():
            return

        facts = []
        for line in content.split("\n"):
            line = line.strip()
            if line.lower().startswith("fact:"):
                fact_text = line.split("fact:", 1)[1].strip()
                facts.append({"fact": fact_text, "importance": 6})
            elif line.lower().startswith("importance:") and facts:
                try:
                    facts[-1]["importance"] = int(line.split("importance:", 1)[1].strip())
                except:
                    pass

        for fact in facts:
            if fact.get("fact") and fact.get("importance", 0) >= 6:
                add_key_fact(convo_id, fact["fact"], fact["importance"])
    except Exception as e:
        logger.error(f"Fact extraction error: {e}")


# ==================== CONVERSATION SUMMARIZATION ====================

def summarize_conversation(convo_id: str, recent_messages: list) -> str:
    """Generate a concise summary of recent conversation messages."""
    conversation_text = "\n".join([
        f"{msg['role']}: {msg['content']}" for msg in recent_messages
    ])

    summary_prompt = f"""Summarize the following conversation between a user and Isabella in 4-8 sentences.
Focus on key topics discussed, important things the user shared, and the overall emotional tone.
Be concise and factual.
Conversation:
{conversation_text}
Summary:"""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": summary_prompt}],
                "temperature": 0.4,
                "max_tokens": 400
            },
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Summarization error: {e}")

    return ""


def store_conversation_summary(convo_id: str, summary: str, start_id: int = None, end_id: int = None):
    """Generate embedding using OpenAI and store the summary."""
    if not summary or len(summary) < 30:
        return

    embedding = get_embedding(summary)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO conversation_summaries
        (convo_id, summary, embedding, start_message_id, end_message_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (convo_id, summary, embedding, start_id, end_id))

    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"✅ Stored conversation summary for {convo_id}")


# ==================== LEGACY COMPATIBILITY ====================

def get_relationship_level(convo_id: str) -> int:
    state = get_relationship_state(convo_id)
    return state["level"] if state else 1


def get_pet_name(convo_id: str) -> str:
    state = get_relationship_state(convo_id)
    return state.get("pet_name") or "papi"


# ==================== INITIALIZE ON IMPORT ====================

init_db()
init_relationship_state()
init_conversation_summaries()
