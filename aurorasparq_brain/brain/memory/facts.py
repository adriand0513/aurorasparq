# aurorasparq_brain/brain/memory/facts.py  (minimal)

import logging
from typing import List
from db.schema import get_db_connection
import os

logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")

def add_fact(convo_id: str, fact: str, importance: int = 6) -> None:
    if not fact or len(fact) < 8:
        return
    fact = fact.strip()
    conn = get_db_connection()
    if conn is None:
        return
    cur = conn.cursor()
    try:
        if DATABASE_URL:
            cur.execute("""
                INSERT INTO key_facts (convo_id, fact, importance, last_recalled)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (convo_id, fact) DO UPDATE
                SET last_recalled = CURRENT_TIMESTAMP,
                    importance = GREATEST(key_facts.importance, EXCLUDED.importance)
            """, (convo_id, fact, importance))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO key_facts (convo_id, fact, importance, last_recalled)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (convo_id, fact, importance))
        conn.commit()
    except Exception as e:
        logger.error(f"add_fact error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()


def get_facts_for_prompt(convo_id: str, limit: int = 10) -> str:
    conn = get_db_connection()
    if conn is None:
        return ""
    cur = conn.cursor()
    try:
        if DATABASE_URL:
            cur.execute("""
                SELECT fact FROM key_facts
                WHERE convo_id = %s
                ORDER BY importance DESC, last_recalled DESC NULLS LAST, timestamp DESC
                LIMIT %s
            """, (convo_id, limit))
        else:
            cur.execute("""
                SELECT fact FROM key_facts
                WHERE convo_id = ?
                ORDER BY importance DESC, timestamp DESC
                LIMIT ?
            """, (convo_id, limit))
        rows = cur.fetchall()
        facts = [r[0] for r in rows if r and r[0]]
        if not facts:
            return ""
        return "\n".join(f"- {f}" for f in facts)
    except Exception as e:
        logger.error(f"get_facts_for_prompt error: {e}")
        return ""
    finally:
        cur.close()
        conn.close()


def extract_facts_from_exchange(convo_id: str, user_message: str, assistant_reply: str) -> None:
    """
    Lightweight extraction via LLM. Saves only durable facts.
    Call AFTER the reply is generated (does not affect speech style).
    """
    import requests
    from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

    if not user_message and not assistant_reply:
        return

    prompt = f"""Extract durable facts from this exchange for long-term memory.
Only keep stable personal facts (location, job, interests, relationship status, preferences, important life details).
Skip temporary mood, greetings, and one-off compliments.
Write each fact as a short line starting with "He" or "She".
Max 5 facts. If none, return NONE.

User: {user_message[:400]}
Isabella: {assistant_reply[:400]}

Facts:"""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 200
            },
            timeout=20
        )
        if resp.status_code != 200:
            return
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if not text or text.upper() == "NONE":
            return
        for line in text.splitlines():
            line = line.strip(" -•\t")
            if len(line) < 8:
                continue
            if line.lower().startswith(("he ", "she ", "user ", "isabella ")):
                add_fact(convo_id, line, importance=7)
    except Exception as e:
        logger.error(f"extract_facts_from_exchange error: {e}")
