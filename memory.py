# memory.py - Complete PostgreSQL Version
import psycopg2
import os
import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
from config import DATABASE_URL
from config import XAI_API_KEY, XAI_API_BASE, XAI_MODEL

logger = logging.getLogger(__name__)

def get_db_connection():
    """Create PostgreSQL connection"""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Safe initialization"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Chat History
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
    
    # Key Facts
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

# ==================== RELATIONSHIP STATE ====================
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
    print("✅ Unified relationship_state initialized")

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
    new_temp = max(1, min(10, current["emotional_temperature"] + emotional_delta))
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

# ==================== HISTORY FUNCTIONS ====================
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

# Legacy compatibility
def get_relationship_level(convo_id: str) -> int:
    state = get_relationship_state(convo_id)
    return state["level"] if state else 1

def get_pet_name(convo_id: str) -> str:
    state = get_relationship_state(convo_id)
    return state.get("pet_name") or "papi"


def extract_and_save_facts(convo_id: str, user_message: str, tier: str = "free"):
    """
    Automatically extracts important facts from the user's message and saves them.
    - Runs on every message for Ultimate
    - Runs every 3-5 messages for Premium (controlled from main.py)
    - Skips Free tier
    """
    if tier == "free":
        return  # Don't waste tokens on Free users

    if not user_message or len(user_message.strip()) < 10:
        return

    extraction_prompt = f"""Extract any important personal facts about the user from this message.
Only extract clear, useful, and specific information such as:
- Preferences, habits, or dislikes
- Life details, job, location, family, or background
- Strong opinions or values
- Things he mentioned about his past or current life

If nothing meaningful is mentioned, return nothing.

User message: "{user_message}"

Return the facts in this exact format (one fact per line):
fact: [the fact here]
importance: [number from 1 to 10]

Only return facts with importance 6 or higher. If there are none, return nothing."""

    try:
        resp = requests.post(
            XAI_API_BASE,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": [{"role": "user", "content": extraction_prompt}],
                "temperature": 0.3,
                "max_tokens": 300
            },
            timeout=12
        )

        if resp.status_code != 200:
            logger.warning(f"Fact extraction failed with status {resp.status_code}")
            return

        content = resp.json()["choices"][0]["message"]["content"].strip()

        if not content or "nothing" in content.lower():
            return

        # Parse the response
        facts = []
        current_fact = {}
        for line in content.split("\n"):
            line = line.strip()
            if line.lower().startswith("fact:"):
                if current_fact:
                    facts.append(current_fact)
                current_fact = {"fact": line.split("fact:", 1)[1].strip()}
            elif line.lower().startswith("importance:"):
                try:
                    current_fact["importance"] = int(line.split("importance:", 1)[1].strip())
                except:
                    current_fact["importance"] = 6

        if current_fact:
            facts.append(current_fact)

        # Save high-quality facts
        for fact in facts:
            if fact.get("fact") and fact.get("importance", 0) >= 6:
                add_key_fact(convo_id, fact["fact"], fact["importance"])

    except Exception as e:
        logger.error(f"Fact extraction error: {e}")

# Initialize on import
init_db()
init_relationship_state()
