# memory.py - Long-term Memory & Relationship System with User Accounts
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = os.path.abspath(os.getenv("DB_PATH", "users.db"))

def init_db():
    """Initialize database with safe migrations."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Chat history table
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            voice_note TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Key facts table
    c.execute('''
        CREATE TABLE IF NOT EXISTS key_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            fact TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_recalled DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Relationship table
    c.execute('''
        CREATE TABLE IF NOT EXISTS relationship_state (
            user_email TEXT PRIMARY KEY,
            level INTEGER DEFAULT 1,
            pet_name TEXT,
            notes TEXT,
            last_interaction DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # === SAFE MIGRATIONS ===
    # Add user_email column if it doesn't exist
    try:
        c.execute("ALTER TABLE chat_history ADD COLUMN user_email TEXT")
        print("✅ Migration: Added user_email to chat_history")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        c.execute("ALTER TABLE key_facts ADD COLUMN user_email TEXT")
        print("✅ Migration: Added user_email to key_facts")
    except sqlite3.OperationalError:
        pass

    # Create indexes (only after column is guaranteed to exist)
    c.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON chat_history (user_email)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_facts_user ON key_facts (user_email)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_history_time ON chat_history (timestamp)')

    conn.commit()
    conn.close()
    print(f"✅ Memory system initialized successfully → {DB_PATH}")


# ── User Management ─────────────────────────────────────────────────────
def create_or_get_user(email: str, first_name: str, last_name: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO users (email, first_name, last_name, last_active)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(email) DO UPDATE SET
            last_active = CURRENT_TIMESTAMP,
            first_name = COALESCE(?, first_name),
            last_name = COALESCE(?, last_name)
    ''', (email, first_name, last_name, first_name, last_name))
    conn.commit()
    conn.close()


# ── Chat History ────────────────────────────────────────────────────────
def get_history(user_email: str, limit: int = 50) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT role, content, voice_note, timestamp
        FROM chat_history
        WHERE user_email = ?
        ORDER BY timestamp ASC
        LIMIT ?
    ''', (user_email, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "voice_note": r[2], "timestamp": r[3]} for r in rows]


def save_message(user_email: str, message: Dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO chat_history (user_email, role, content, voice_note)
        VALUES (?, ?, ?, ?)
    ''', (user_email, message["role"], message["content"], message.get("voice_note")))
    conn.commit()
    conn.close()


# ── Key Facts ───────────────────────────────────────────────────────────
def add_key_fact(user_email: str, fact: str, importance: int = 7):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO key_facts (user_email, fact, importance, last_recalled)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_email, fact, importance))
    conn.commit()
    conn.close()


def get_relevant_facts(user_email: str, limit: int = 8) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT fact FROM key_facts
        WHERE user_email = ?
        ORDER BY importance DESC, last_recalled DESC
        LIMIT ?
    ''', (user_email, limit))
    facts = [row[0] for row in c.fetchall()]
    conn.close()
    return facts


# ── Relationship ────────────────────────────────────────────────────────
def get_relationship_level(user_email: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT level FROM relationship_state WHERE user_email = ?', (user_email,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 1


def get_pet_name(user_email: str) -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT pet_name FROM relationship_state WHERE user_email = ?', (user_email,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else "babe"


def update_relationship(user_email: str, delta: int = 1, pet_name: Optional[str] = None, note: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    current = get_relationship_level(user_email)
    new_level = max(1, min(10, current + delta))

    c.execute('''
        INSERT INTO relationship_state (user_email, level, pet_name, notes, last_interaction)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_email) DO UPDATE SET
            last_interaction = CURRENT_TIMESTAMP,
            level = ?,
            pet_name = COALESCE(?, pet_name),
            notes = COALESCE(notes || '\n' || ?, notes)
    ''', (user_email, new_level, pet_name, note, new_level, pet_name, note))
    conn.commit()
    conn.close()


def summarize_recent_chat(user_email: str):
    pass  # Future use


# Initialize on import
init_db()
