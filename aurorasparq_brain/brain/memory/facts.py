# brain/memory/facts.py
"""
Fact extraction and storage module for Isabella's memory system.
Uses structured JSON output for reliability.
"""

import json
import logging
import requests
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL
from db.schema import get_db_connection  # We'll update this later to support PostgreSQL

logger = logging.getLogger(__name__)


def extract_and_save_facts(convo_id: str, user_message: str, tier: str = "free"):
    """
    Extract important facts about the user from their message using JSON output.
    Stores them in PostgreSQL.
    """
    if not user_message or len(user_message) < 12:
        return

    prompt = f"""Extract clear, useful personal facts the user shared about themselves.
Only extract facts that are specific and meaningful (name, job, hobbies, family, preferences, location, goals, personality traits, etc).

Respond ONLY with valid JSON in this exact format:
{{
  "facts": [
    {{"fact": "short clear fact here", "importance": 1-10}}
  ]
}}

If there are no meaningful facts, return exactly: {{"facts": []}}

User message:
{user_message}
"""

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
                "temperature": 0.25,
                "max_tokens": 700
            },
            timeout=30
        )

        if resp.status_code != 200:
            logger.warning(f"Fact extraction API failed with status {resp.status_code}")
            return

        content = resp.json()["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()

        data = json.loads(content)
        facts = data.get("facts", [])

        if not facts:
            return

        conn = get_db_connection()
        cur = conn.cursor()

        for item in facts:
            fact_text = item.get("fact", "").strip()
            importance = int(item.get("importance", 5))

            if fact_text and len(fact_text) > 4:
                cur.execute("""
                    INSERT INTO key_facts (convo_id, fact, importance, last_recalled)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (convo_id, fact) DO NOTHING
                """, (convo_id, fact_text, importance))

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"✅ Extracted and saved {len(facts)} facts for convo {convo_id}")

    except json.JSONDecodeError:
        logger.warning("Fact extraction returned invalid JSON")
    except Exception as e:
        logger.error(f"Fact extraction error: {e}")


def get_relevant_facts(convo_id: str, limit: int = 8) -> list:
    """Retrieve most important facts for a conversation."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT fact
        FROM key_facts
        WHERE convo_id = %s
        ORDER BY importance DESC, last_recalled DESC
        LIMIT %s
    """, (convo_id, limit))

    facts = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return facts
