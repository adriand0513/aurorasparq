# memory.py - PostgreSQL Version with Unified Relationship State
import psycopg2
import json
from datetime import datetime
from typing import List, Dict, Optional
from analytics import log_event
from config import DATABASE_URL

def get_db_connection():
    """Create PostgreSQL connection"""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Safe initialization and migration for PostgreSQL"""
    conn = get_db_connection()
    cur = conn.cursor()
  
    # Chat History with user_id
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

# ==================== UNIFIED RELATIONSHIP STATE ====================

def init_relationship_state():
    """Initialize unified relationship + narrative memory"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Unified Relationship + Emotional State
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
    
    # Narrative Memory for Longevity
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
    
    cur.execute('CREATE INDEX IF NOT EXISTS idx_narrative_convo ON narrative_memories(convo_id)')
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Unified relationship_state initialized")

def get_relationship_state(convo_id: str):
    """Get full current state + recent narratives"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM relationship_state WHERE convo_id = %s", (convo_id,))
    row = cur.fetchone()
    
    cur.execute('''
        SELECT description, moment_type, emotional_tag, timestamp
        FROM narrative_memories
        WHERE convo_id = %s
        ORDER BY importance DESC, timestamp DESC LIMIT 10
    ''', (convo_id,))
    narratives = cur.fetchall()
    
    cur.close()
    conn.close()

    if row:
        return {
            "level": row[1],
            "pet_name": row[2],
            "emotional_temperature": row[3],
            "relationship_phase": row[4],
            "trust_level": row[5],
            "current_mood": row[6],
            "last_interaction": row[7],
            "notes": row[8] or "",
            "recent_narratives": [
                {"desc": n[0], "type": n[1], "tag": n[2], "time": n[3]} 
                for n in narratives
            ]
        }
    return None  # New user

def update_relationship_state(convo_id: str, level_delta=0, emotional_delta=0, 
                            new_phase=None, new_mood=None, pet_name=None, note=None):
    """Update relationship with decay + emotional state"""
    current = get_relationship_state(convo_id) or {
        "level": 1, 
        "emotional_temperature": 5, 
        "relationship_phase": "early_flirt",
        "trust_level": 3, 
        "current_mood": "playful", 
        "pet_name": None, 
        "notes": ""
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

def add_narrative_moment(convo_id: str, description: str, moment_type: str = "shared",
                        emotional_tag: str = None, importance: int = 5):
    """Add important shared moment or her own story"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO narrative_memories 
        (convo_id, moment_type, description, emotional_tag, importance)
        VALUES (%s, %s, %s, %s, %s)
    ''', (convo_id, moment_type, description, emotional_tag, importance))
    conn.commit()
    cur.close()
    conn.close()

# ── History Functions ───────────────────────────────────────────────
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
    """Save message with user_id linking"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO chat_history (convo_id, user_id, role, content)
        VALUES (%s, %s, %s, %s)
    ''', (convo_id, user_id, message["role"], message["content"]))
    conn.commit()
    cur.close()
    conn.close()
  
    event_type = "message_sent" if message["role"] == "user" else "message_received"
    log_event(event_type, convo_id, user_id=user_id, metadata={"length": len(message["content"])})

# ── Key Facts ───────────────────────────────────────────────────────
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

# ── Legacy Compatibility (Optional) ─────────────────────────────────
def get_relationship_level(convo_id: str) -> int:
    state = get_relationship_state(convo_id)
    return state["level"] if state else 1

def get_pet_name(convo_id: str) -> str:
    state = get_relationship_state(convo_id)
    return state.get("pet_name") or "papi"

# Initialize everything
init_db()
init_relationship_state()
