# brain/memory/facts.py  (extraction + sticky helpers)

import json
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Optional

from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL
from db.schema import get_db_connection

logger = logging.getLogger(__name__)

LIFE_TYPES = {
    "activity_now",
    "today",
    "later",
    "past",
    "people",
    "preference",
    "user",  # still capture strong user facts
}


def add_fact(convo_id: str, fact: str, importance: int = 6, fact_type: str = "general"):
    """Save one fact. fact_type helps retrieval later."""
    if not fact or not convo_id:
        return False
    fact = fact.strip()
    if len(fact) < 3:
        return False

    conn = get_db_connection()
    if conn is None:
        return False
    cur = conn.cursor()
    try:
        # Store type in the fact text prefix for simple schemas:
        # e.g. "[activity_now] editing photos at home"
        stored = f"[{fact_type}] {fact}" if fact_type else fact
        cur.execute(
            """
            INSERT INTO key_facts (convo_id, fact, importance, last_recalled)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (convo_id, fact) DO UPDATE
            SET importance = GREATEST(key_facts.importance, EXCLUDED.importance),
                last_recalled = CURRENT_TIMESTAMP
            """,
            (convo_id, stored, max(1, min(10, importance))),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_fact error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


# brain/memory/facts.py

def get_facts_for_prompt(convo_id: str, limit: int = 12) -> str:
    """
    Pretty, typed known-facts block for the system prompt.
    """
    conn = get_db_connection()
    if conn is None:
        return ""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT fact, importance
            FROM key_facts
            WHERE convo_id = %s
            ORDER BY importance DESC, last_recalled DESC NULLS LAST, timestamp DESC
            LIMIT %s
            """,
            (convo_id, limit),
        )
        rows = cur.fetchall()
        if not rows:
            return ""

        buckets = {
            "activity_now": [],
            "today": [],
            "later": [],
            "past": [],
            "people": [],
            "preference": [],
            "user": [],
            "other": [],
        }

        for fact, _imp in rows:
            text = fact or ""
            placed = False
            for key in ["activity_now", "today", "later", "past", "people", "preference", "user"]:
                prefix = f"[{key}]"
                if text.startswith(prefix):
                    buckets[key].append(text[len(prefix):].strip())
                    placed = True
                    break
            if not placed:
                buckets["other"].append(text)

        sections = []
        labels = [
            ("activity_now", "Right now"),
            ("today", "Today"),
            ("later", "Later / plans"),
            ("past", "Past"),
            ("people", "People"),
            ("preference", "Preferences"),
            ("user", "About him"),
            ("other", "Other"),
        ]
        for key, label in labels:
            items = buckets[key][:4]
            if not items:
                continue
            lines = "\n".join(f"- {x}" for x in items)
            sections.append(f"{label}:\n{lines}")

        return "\n".join(sections)
    except Exception as e:
        logger.error(f"get_facts_for_prompt error: {e}")
        return ""
    finally:
        cur.close()
        conn.close()


def get_or_set_sticky_activity(convo_id: str, candidate: Optional[str] = None) -> str:
    """
    Keep one current activity stable.
    If one exists, return it. If candidate given and none exists, save it.
    """
    conn = get_db_connection()
    if conn is None:
        return candidate or ""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT fact FROM key_facts
            WHERE convo_id = %s AND fact LIKE '[activity_now]%%'
            ORDER BY last_recalled DESC NULLS LAST, timestamp DESC
            LIMIT 1
            """,
            (convo_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            # strip prefix for clean use
            return row[0].replace("[activity_now] ", "", 1)

        if candidate:
            add_fact(convo_id, candidate, importance=8, fact_type="activity_now")
            return candidate
        return ""
    except Exception as e:
        logger.error(f"sticky activity error: {e}")
        return candidate or ""
    finally:
        cur.close()
        conn.close()


def extract_facts_from_exchange(
    convo_id: str,
    user_message: str,
    assistant_reply: str,
) -> List[str]:
    """
    Extract life facts Isabella claimed + strong user facts.
    Save them so her world grows and stays consistent.
    """
    if not assistant_reply or len(assistant_reply) < 8:
        return []

    prompt = f"""Extract durable facts from this chat exchange for a companion AI named Isabella.

Return ONLY valid JSON list. Each item:
{{"type":"activity_now|today|later|past|people|preference|user","fact":"...","importance":1-10}}

Rules:
- Prefer Isabella's life claims (what she is doing, did today, plans, past, people, preferences).
- Also capture strong user personal facts if clearly stated.
- One clear fact per item. Short. No quotes dump.
- If she states current activity, type=activity_now, importance 8.
- If plans later/tonight/tomorrow, type=later, importance 7.
- If past/family/hometown, type=past, importance 9.
- If roommate/family names, type=people, importance 9.
- Max 5 items. If nothing durable, return [].

User: {user_message[:400]}
Isabella: {assistant_reply[:600]}
"""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 350,
            },
            timeout=25,
        )
        if resp.status_code != 200:
            return []

        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # crude JSON list extract
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return []
        items = json.loads(raw[start : end + 1])
        saved = []
        for item in items[:5]:
            ftype = str(item.get("type", "general")).strip().lower()
            fact = str(item.get("fact", "")).strip()
            imp = int(item.get("importance", 6))
            if not fact:
                continue
            if ftype not in LIFE_TYPES:
                ftype = "preference" if ftype == "general" else ftype
            if add_fact(convo_id, fact, importance=imp, fact_type=ftype):
                saved.append(f"[{ftype}] {fact}")
                # sticky mirror for activity
                if ftype == "activity_now":
                    get_or_set_sticky_activity(convo_id, fact)
        return saved
    except Exception as e:
        logger.error(f"extract_facts_from_exchange error: {e}")
        return []
