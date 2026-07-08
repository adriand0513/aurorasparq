# memory.py - Core Chat History + Embedding Layer
#
# NOTE: This file is being phased down in favor of the new memory system
# located in aurorasparq_brain/brain/memory/
#
# What remains here:
# - Chat history (save_message / get_history)
# - Embedding generation (used by summaries)
# - Table initialization for chat_history and conversation_summaries
#
# New fact extraction, smart retrieval, and summarization now live in:
# → brain/memory/facts.py
# → brain/memory/retrieval.py
# → brain/memory/summaries.py

import psycopg2
import logging
from typing import List, Dict, Optional
from config import DATABASE_URL, OPENAI_API_KEY
import openai

logger = logging.getLogger(__name__)

# OpenAI Configuration
openai.api_key = OPENAI_API_KEY


def get_db_connection():
    """Create PostgreSQL connection."""
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


# ==================== TABLE INITIALIZATION ====================

def init_db():
    """Initialize core tables."""
    conn = get_db_connection()
    if conn is None:
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
        conn.commit()
    except Exception as e:
        logger.error(f"init_db error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def init_conversation_summaries():
    """Initialize conversation_summaries table (with optional vector support)."""
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
        # Optional pgvector support
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
    except Exception as e:
        logger.error(f"init_conversation_summaries error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


# ==================== CHAT HISTORY ====================

def get_history(convo_id: str, limit: int = 50) -> List[Dict]:
    """
    Get chat history.
    Only returns role + content to avoid JSON serialization issues.
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


# ==================== LEGACY STUBS (REMOVED) ====================
# get_relationship_level() and get_pet_name() have been removed.
# Relationship state is now handled by the Second Brain.


# ==================== INITIALIZE ON IMPORT ====================
init_db()
init_conversation_summaries()
