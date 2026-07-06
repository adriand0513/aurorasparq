# memory.py - PostgreSQL Version (Cleaned & Updated)
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
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.warning(f"⚠️ PostgreSQL connection failed: {e}")
        return None


def get_embedding(text: str) -> list:
    """Generate embedding using OpenAI's text-embedding-3-small."""
    if not text or not OPENAI_API_KEY:
        return []
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
    """Initialize core tables (chat_history + key_facts)."""
    conn = get_db_connection()
    if conn is None:
        logger.warning("⚠️ Skipping init_db() — no database connection")
        return

    cur = conn.cursor()
    try:
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
        logger.info("✅ Core memory tables initialized (PostgreSQL)")
    except Exception as e:
        logger.error(f"init_db error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def init_conversation_summaries():
    """Initialize conversation_summaries table."""
    conn = get_db_connection()
    if conn is None:
        return

    cur = conn.cursor()
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id SERIAL PRIMARY KEY,
                convo_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                start_message_id INTEGER,
                end_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                importance INTEGER DEFAULT 5
            )
        ''')

        # Try to add vector support (safe if pgvector is missing)
        try:
            cur.execute("""
                ALTER TABLE conversation_summaries 
                ADD COLUMN IF NOT EXISTS embedding VECTOR(1536);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_summary_embedding 
                ON conversation_summaries USING ivfflat (embedding vector_cosine_ops);
            """)
        except Exception:
            pass

        cur.execute('CREATE INDEX IF NOT EXISTS idx_summary_convo ON conversation_summaries(convo_id)')
        conn.commit()
        logger.info("✅ conversation_summaries table ready")
    except Exception as e:
        logger.error(f"init_conversation_summaries error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ==================== HISTORY & FACTS ====================
def get_history(convo_id: str, limit: int = 50) -> List[Dict]:
    """
    Get chat history. 
    IMPORTANT: We do NOT include 'timestamp' here to avoid 
    JSON serialization errors when sending to xAI.
    """
    conn = get_db_connection()
    if conn is None:
        return []

    cur = conn.cursor()
    cur.execute('''
        SELECT role, content
        FROM chat_history
        WHERE convo_id = %s
        ORDER BY timestamp ASC
        LIMIT %s
    ''', (convo_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # Only return role + content (no timestamp)
    return [{"role": r[0], "content": r[1]} for r in rows]


def save_message(convo_id: str, message: Dict, user_id: Optional[int] = None):
    conn = get_db_connection()
    if conn is None:
        return

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
    if conn is None:
        return []

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
    if conn is None:
        return

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
    conversation_text = "\n".join([
        f"{msg['role']}: {msg['content']}" for msg in recent_messages
    ])

    summary_prompt = f"""You are creating a memory summary for an AI girlfriend chatbot named Isabella.
Extract the most important information from this conversation so Isabella can remember it later.

Focus on:
- Key things the user shared about himself
- Emotional tone
- Important or recurring topics
- Relationship progression moments
- Things Isabella should remember

Be concise but specific (4-8 sentences max).

Conversation:
{conversation_text}

Structured Memory Summary:"""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": summary_prompt}],
                "temperature": 0.35,
                "max_tokens": 450
            },
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Summarization error: {e}")
    return ""


def store_conversation_summary(convo_id: str, summary: str, start_id: int = None, end_id: int = None):
    if not summary or len(summary) < 30:
        return

    embedding = get_embedding(summary)
    conn = get_db_connection()
    if conn is None:
        return

    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO conversation_summaries
            (convo_id, summary, embedding, start_message_id, end_message_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (convo_id, summary, embedding if embedding else None, start_id, end_id))
        conn.commit()
        logger.info(f"✅ Stored conversation summary for {convo_id}")
    except Exception as e:
        logger.error(f"store_conversation_summary error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ==================== LEGACY COMPATIBILITY ====================
def get_relationship_level(convo_id: str) -> int:
    return 1


def get_pet_name(convo_id: str) -> str:
    return "papi"


# ==================== INITIALIZE ON IMPORT ====================
init_db()
init_conversation_summaries()
