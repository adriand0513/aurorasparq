# memory.py - Improved with User ID Linking
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional
from analytics import log_event

DB_PATH = os.path.abspath(os.getenv("DB_PATH", "isabella.db"))


def init_db():
    """Safe initialization and migration"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Chat History with user_id
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            convo_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
   
    # Safe migrations
    c.execute("PRAGMA table_info(chat_history)")
    columns = [row[1] for row in c.fetchall()]
    
    if "user_id" not in columns:
        c.execute("ALTER TABLE chat_history ADD COLUMN user_id INTEGER")
        print("Migration: Added user_id column to chat_history")
    
    if "convo_id" not in columns:
        c.execute("ALTER TABLE chat_history ADD COLUMN convo_id TEXT")
        print("Migration: Added convo_id column to chat_history")
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_convo_id ON chat_history (convo_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history (user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON chat_history (timestamp)')
    
    # Key Facts
    c.execute('''
        CREATE TABLE IF NOT EXISTS key_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            convo_id TEXT NOT NULL,
            fact TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_recalled DATETIME
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_facts_convo ON key_facts (convo_id)')
    
    # Relationship State
    c.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            convo_id TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            notes TEXT,
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Memory system initialized at: {DB_PATH}")


# ── History Functions ───────────────────────────────────────────────
def get_history(convo_id: str, limit: int = 50) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT role, content, timestamp
        FROM chat_history
        WHERE convo_id = ?
        ORDER BY timestamp ASC
        LIMIT ?
    ''', (convo_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


def save_message(convo_id: str, message: Dict, user_id: Optional[int] = None):
    """Save message with optional user_id linking"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO chat_history (convo_id, user_id, role, content)
        VALUES (?, ?, ?, ?)
    ''', (convo_id, user_id, message["role"], message["content"]))
    conn.commit()
    conn.close()
    
    event_type = "message_sent" if message["role"] == "user" else "message_received"
    log_event(event_type, convo_id, user_id=user_id, metadata={"length": len(message["content"])})


# ── Key Facts & Relationship (unchanged) ─────────────────────────────────
def add_key_fact(convo_id: str, fact: str, importance: int = 7):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO key_facts (convo_id, fact, importance, last_recalled)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (convo_id, fact, importance))
    conn.commit()
    conn.close()


def get_relevant_facts(convo_id: str, limit: int = 8) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT fact
        FROM key_facts
        WHERE convo_id = ?
        ORDER BY importance DESC, last_recalled DESC
        LIMIT ?
    ''', (convo_id, limit))
    facts = [row[0] for row in c.fetchall()]
    conn.close()
    return facts


def get_relationship_level(convo_id: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT level FROM relationship_state WHERE convo_id = ?', (convo_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1


def get_pet_name(convo_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT pet_name FROM relationship_state WHERE convo_id = ?', (convo_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else "babe"


def update_relationship(convo_id: str, delta: int = 1, pet_name: Optional[str] = None, note: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current = get_relationship_level(convo_id)
    new_level = max(1, min(10, current + delta))
   
    c.execute('''
        INSERT INTO relationship_state (convo_id, level, pet_name, notes, last_interaction)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(convo_id) DO UPDATE SET
            last_interaction = CURRENT_TIMESTAMP,
            level = ?,
            pet_name = COALESCE(?, pet_name),
            notes = COALESCE(notes || '\n' || ?, notes)
    ''', (convo_id, new_level, pet_name, note, new_level, pet_name, note))
    conn.commit()
    conn.close()


# Initialize
init_db()
