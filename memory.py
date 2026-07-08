# memory.py
#
# Core chat history layer.
# This file is being phased down in favor of the new memory system
# located in: aurorasparq_brain/brain/memory/
#
# Only core functions remain here for now:
# - Chat history (save + retrieve)
# - Database connection helper

import psycopg2
import logging
from typing import List, Dict, Optional
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_db_connection():
    """Create PostgreSQL connection."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed: {e}")
        return None


# ==================== CHAT HISTORY ====================

def get_history(convo_id: str, limit: int = 50) -> List[Dict]:
    """
    Get recent chat history.
    Only returns role + content (no timestamp) to avoid JSON issues.
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


# ==================== INITIALIZE TABLES ====================

def init_db():
    """Ensure chat_history table exists."""
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


# Initialize on import
init_db()
