# internal_state.py - Improved Narrative Memory & Emotional Continuity System
import sqlite3
import json
from datetime import datetime, timedelta
from config import DB_PATH

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_internal_state():
    """Initialize tables with proper schema"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Main emotional + relationship state
    c.execute('''
        CREATE TABLE IF NOT EXISTS internal_state (
            convo_id TEXT PRIMARY KEY,
            emotional_temperature INTEGER DEFAULT 5,   -- 1-10 how close she feels
            relationship_phase TEXT DEFAULT 'early_flirt',
            trust_level INTEGER DEFAULT 3,             -- 1-10
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP,
            current_mood TEXT DEFAULT 'playful',
            notes TEXT
        )
    ''')
    
    # Narrative memory - Shared moments and her own stories
    c.execute('''
        CREATE TABLE IF NOT EXISTS narrative_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            convo_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            moment_type TEXT,           -- 'user_shared', 'her_story', 'milestone', 'flirty_moment', 'joke'
            description TEXT NOT NULL,
            emotional_tag TEXT,         -- 'laugh', 'vulnerable', 'turned_on', 'close', 'teasing'
            importance INTEGER DEFAULT 5
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_narrative_convo ON narrative_memories(convo_id)')
    conn.commit()
    conn.close()

def get_internal_state(convo_id: str):
    """Get full current state + recent narratives"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT * FROM internal_state WHERE convo_id = ?", (convo_id,))
    row = c.fetchone()
    
    # Get recent important narratives
    c.execute('''
        SELECT description, moment_type, emotional_tag, timestamp 
        FROM narrative_memories 
        WHERE convo_id = ?
        ORDER BY importance DESC, timestamp DESC 
        LIMIT 10
    ''', (convo_id,))
    narratives = c.fetchall()
    
    conn.close()

    if row:
        return {
            "emotional_temperature": row[1],
            "relationship_phase": row[2],
            "trust_level": row[3],
            "last_interaction": row[4],
            "current_mood": row[5],
            "notes": row[6] or "",
            "recent_narratives": [
                {"desc": n[0], "type": n[1], "tag": n[2], "time": n[3]} 
                for n in narratives
            ]
        }
    return None  # New conversation


def add_narrative_moment(convo_id: str, description: str, moment_type: str = "shared",
                        emotional_tag: str = None, importance: int = 5):
    """Add important moment or story"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO narrative_memories 
        (convo_id, moment_type, description, emotional_tag, importance)
        VALUES (?, ?, ?, ?, ?)
    ''', (convo_id, moment_type, description, emotional_tag, importance))
    conn.commit()
    conn.close()


def update_internal_state(convo_id: str, emotional_delta=0, new_phase=None, 
                         new_mood=None, new_note=None):
    """Safely update emotional state"""
    current = get_internal_state(convo_id) or {
        "emotional_temperature": 5,
        "relationship_phase": "early_flirt",
        "trust_level": 3,
        "current_mood": "playful",
        "notes": ""
    }

    new_temp = max(1, min(10, current["emotional_temperature"] + emotional_delta))
    phase = new_phase or current["relationship_phase"]
    mood = new_mood or current["current_mood"]

    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO internal_state 
        (convo_id, emotional_temperature, relationship_phase, trust_level, 
         last_interaction, current_mood, notes)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
        ON CONFLICT(convo_id) DO UPDATE SET
            emotional_temperature = ?,
            relationship_phase = ?,
            last_interaction = CURRENT_TIMESTAMP,
            current_mood = ?,
            notes = COALESCE(notes || '\n' || ?, notes)
    ''', (convo_id, new_temp, phase, current["trust_level"], 
          mood, new_note or "",
          new_temp, phase, mood, new_note or ""))
    
    conn.commit()
    conn.close()
