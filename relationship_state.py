# relationship_state.py - Unified Longevity System
import sqlite3
import json
from datetime import datetime
from config import DB_PATH
import logging

logger = logging.getLogger(__name__)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_relationship_state():
    """Initialize unified relationship + narrative system"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Main Relationship + Emotional State
    c.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            convo_id TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            emotional_temperature INTEGER DEFAULT 5,
            relationship_phase TEXT DEFAULT 'early_flirt',
            trust_level INTEGER DEFAULT 3,
            current_mood TEXT DEFAULT 'playful',
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    ''')
    
    # Narrative Memory for Long-term Bonding
    c.execute('''
        CREATE TABLE IF NOT EXISTS narrative_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            convo_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            moment_type TEXT,
            description TEXT NOT NULL,
            emotional_tag TEXT,
            importance INTEGER DEFAULT 5
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_narrative_convo ON narrative_memories(convo_id)')
    conn.commit()
    conn.close()
    logger.info("✅ Unified relationship_state initialized")


def get_relationship_state(convo_id: str):
    """Get full current state + recent narratives"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT * FROM relationship_state WHERE convo_id = ?", (convo_id,))
    row = c.fetchone()
    
    c.execute('''
        SELECT description, moment_type, emotional_tag, timestamp
        FROM narrative_memories
        WHERE convo_id = ?
        ORDER BY importance DESC, timestamp DESC LIMIT 10
    ''', (convo_id,))
    narratives = c.fetchall()
    
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
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO relationship_state 
        (convo_id, level, pet_name, emotional_temperature, relationship_phase, 
         trust_level, current_mood, last_interaction, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(convo_id) DO UPDATE SET
            level = ?,
            pet_name = COALESCE(?, pet_name),
            emotional_temperature = ?,
            relationship_phase = ?,
            current_mood = ?,
            last_interaction = CURRENT_TIMESTAMP,
            notes = COALESCE(notes || '\n' || ?, notes)
    ''', (convo_id, new_level, pet_name, new_temp, phase, current["trust_level"], 
          mood, note or "",
          new_level, pet_name, new_temp, phase, mood, note or ""))
    
    conn.commit()
    conn.close()


def add_narrative_moment(convo_id: str, description: str, moment_type: str = "shared",
                        emotional_tag: str = None, importance: int = 5):
    """Add important shared moment or her own story"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO narrative_memories 
        (convo_id, moment_type, description, emotional_tag, importance)
        VALUES (?, ?, ?, ?, ?)
    ''', (convo_id, moment_type, description, emotional_tag, importance))
    conn.commit()
    conn.close()


# Initialize on import
init_relationship_state()