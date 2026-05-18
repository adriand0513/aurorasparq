# memory.py - Long-term Memory & Relationship System with Natural Name Support
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = os.path.abspath(os.getenv("DB_PATH", "users.db"))

def init_db():
    """Initialize database with safe migrations."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table for name storage
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            preferred_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Chat history
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            voice_note TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Key facts
    c.execute('''
        CREATE TABLE IF NOT EXISTS key_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            fact TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_recalled DATETIME
        )
    ''')

    # Relationship state
    c.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            user_id TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            notes TEXT,
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # === SAFE MIGRATIONS ===
    try:
        c.execute("ALTER TABLE users ADD COLUMN preferred_name TEXT")
        print("✅ Migration: Added preferred_name column")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE chat_history ADD COLUMN voice_note TEXT")
        print("✅ Migration: Added voice_note column")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE chat_history ADD COLUMN user_id TEXT")
        print("✅ Migration: Added user_id column")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE key_facts ADD COLUMN user_id TEXT")
        print("✅ Migration: Added user_id to key_facts")
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE relationship_state ADD COLUMN user_id TEXT")
        print("✅ Migration: Added user_id to relationship_state")
    except sqlite3.OperationalError:
        pass

    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON chat_history (user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_facts_user ON key_facts (user_id)')

    conn.commit()
    conn.close()
    print(f"✅ Memory system initialized successfully → {DB_PATH}")


# ── User Name Management ─────────────────────────────────────────────────────
def save_user_name(user_id: str, name: str):
    """Save user's preferred name"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO users (user_id, preferred_name, last_active)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET 
            preferred_name = ?,
            last_active = CURRENT_TIMESTAMP
    ''', (user_id, name, name))
    conn.commit()
    conn.close()


def get_user_name(user_id: str) -> Optional[str]:
    """Get saved name for user"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT preferred_name FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# ── Chat History ───────────────────────────────────────────────────────────
def get_history(user_id: str, limit: int = 50) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT role, content, voice_note, timestamp
        FROM chat_history
        WHERE user_id = ?
        ORDER BY timestamp ASC
        LIMIT ?
    ''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "voice_note": r[2], "timestamp": r[3]} for r in rows]


def save_message(user_id: str, message: Dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO chat_history (user_id, role, content, voice_note)
        VALUES (?, ?, ?, ?)
    ''', (user_id, message["role"], message["content"], message.get("voice_note")))
    conn.commit()
    conn.close()


# ── Key Facts ──────────────────────────────────────────────────────────────
def add_key_fact(user_id: str, fact: str, importance: int = 7):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO key_facts (user_id, fact, importance, last_recalled)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, fact, importance))
    conn.commit()
    conn.close()


def get_relevant_facts(user_id: str, limit: int = 8) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT fact FROM key_facts 
        WHERE user_id = ?
        ORDER BY importance DESC, last_recalled DESC 
        LIMIT ?
    ''', (user_id, limit))
    facts = [row[0] for row in c.fetchall()]
    conn.close()
    return facts


# ── Relationship ───────────────────────────────────────────────────────────
def get_relationship_level(user_id: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT level FROM relationship_state WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1


def get_pet_name(user_id: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT pet_name FROM relationship_state WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else "babe"


def update_relationship(user_id: str, delta: int = 1, pet_name: Optional[str] = None, note: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current = get_relationship_level(user_id)
    new_level = max(1, min(10, current + delta))
    
    c.execute('''
        INSERT INTO relationship_state (user_id, level, pet_name, notes, last_interaction)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            last_interaction = CURRENT_TIMESTAMP,
            level = ?,
            pet_name = COALESCE(?, pet_name),
            notes = COALESCE(notes || '\n' || ?, notes)
    ''', (user_id, new_level, pet_name, note))
    conn.commit()
    conn.close()


def summarize_recent_chat(user_id: str):
    """Placeholder for future summarization"""
    pass


# Initialize on import
init_db()
