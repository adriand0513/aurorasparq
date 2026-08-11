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

def get_history(convo_id: str, limit: int = None) -> list:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if limit is None:
            cur.execute("""
                SELECT role, content, timestamp
                FROM chat_history
                WHERE convo_id = %s
                ORDER BY timestamp ASC
            """, (convo_id,))
        else:
            cur.execute("""
                SELECT role, content, timestamp
                FROM chat_history
                WHERE convo_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (convo_id, limit))
            # reverse so oldest is first
            rows = cur.fetchall()
            rows = list(reversed(rows))
            return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]

        rows = cur.fetchall()
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]
    finally:
        cur.close()
        conn.close()


def save_message(convo_id: str, message: dict, user_id: int = None):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO chat_history (convo_id, user_id, role, content)
            VALUES (%s, %s, %s, %s)
        """, (convo_id, user_id, message["role"], message["content"]))
        conn.commit()
    except Exception as e:
        logger.error(f"save_message error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def get_recent_text_messages(convo_id: str, limit: int = 8) -> list:
    """Last N user/assistant text messages only (no voice_note URL rows)."""
    history = get_history(convo_id, limit=40) or []
    out = []
    for m in history:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content or role not in ("user", "assistant"):
            continue
        if content.startswith("[voice_note]|"):
            continue
        if content.startswith("[voice_script]|"):
            # expose as what she said out loud
            script = content.split("|", 1)[-1].strip()
            if script:
                out.append({"role": "assistant", "content": script})
            continue
        out.append({"role": role, "content": content})
    return out[-limit:]


def set_last_voice_script(convo_id: str, script: str, user_id: int = None):
    """Persist what she actually said in the last voice note."""
    if not script or len(script) < 8:
        return
    save_message(
        convo_id,
        {"role": "assistant", "content": f"[voice_script]|{script[:500]}"},
        user_id=user_id,
    )


def get_last_voice_script(convo_id: str) -> str:
    history = get_history(convo_id, limit=30) or []
    for m in reversed(history):
        content = (m.get("content") or "")
        if content.startswith("[voice_script]|"):
            return content.split("|", 1)[-1].strip()
    return ""

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
