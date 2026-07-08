# brain/memory/summaries.py
"""
Conversation summarization module.
Creates and stores summaries of conversations for long-term memory.
"""

import logging
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL
from db.schema import get_db_connection

logger = logging.getLogger(__name__)


def generate_and_save_summary(convo_id: str, tier: str = "free"):
    """
    Generate a summary of the recent conversation and store it.
    This helps with long-term memory.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # Get recent messages
    cur.execute("""
        SELECT role, content 
        FROM chat_history 
        WHERE convo_id = %s 
        ORDER BY timestamp DESC 
        LIMIT 40
    """, (convo_id,))

    messages = cur.fetchall()
    cur.close()
    conn.close()

    if len(messages) < 10:
        return  # Not enough messages to summarize

    # Format conversation
    conversation_text = "\n".join([
        f"{role}: {content}" for role, content in reversed(messages)
    ])

    prompt = f"""Summarize the key points, emotional tone, and important details from this conversation.
Focus on what the user shared about themselves, how the relationship is developing, and any recurring topics.

Keep the summary concise but informative (5-8 sentences max).

Conversation:
{conversation_text}

Summary:"""

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
                "temperature": 0.4,
                "max_tokens": 500
            },
            timeout=35
        )

        if resp.status_code != 200:
            return

        summary = resp.json()["choices"][0]["message"]["content"].strip()

        if len(summary) < 30:
            return

        # Save summary to database
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO conversation_summaries 
            (convo_id, summary, created_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
        """, (convo_id, summary))

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ Summary saved for convo {convo_id}")

    except Exception as e:
        logger.error(f"Summary generation error: {e}")


def get_recent_summaries(convo_id: str, limit: int = 3) -> list:
    """Retrieve recent conversation summaries."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT summary 
        FROM conversation_summaries 
        WHERE convo_id = %s 
        ORDER BY created_at DESC 
        LIMIT %s
    """, (convo_id, limit))

    summaries = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return summaries
