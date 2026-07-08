# aurorasparq_brain/db/schema.py
"""
Database schema and connection handler for Isabella's Second Brain.
Supports both PostgreSQL (production) and SQLite (local testing).
"""

import os
import logging
import psycopg2
import sqlite3
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Use PostgreSQL if DATABASE_URL is set, otherwise fallback to SQLite
DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.getenv("DB_PATH", "isabella_brain.db")  # Fallback SQLite path


def get_db_connection():
    """Returns a database connection (PostgreSQL or SQLite)."""
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            raise
    else:
        # Fallback to SQLite for local development
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    """Initialize all required tables for the Second Brain + Memory system."""
    conn = get_db_connection()
    cur = conn.cursor()

    if DATABASE_URL:
        # ===================== PostgreSQL =====================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS key_facts (
                id SERIAL PRIMARY KEY,
                convo_id TEXT NOT NULL,
                fact TEXT NOT NULL,
                importance INTEGER DEFAULT 5,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_recalled TIMESTAMP,
                UNIQUE(convo_id, fact)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id SERIAL PRIMARY KEY,
                convo_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Relationship state tables (for future full migration)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS relationship_states (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                convo_id TEXT UNIQUE NOT NULL,
                phase TEXT DEFAULT 'early_flirt',
                relationship_level INTEGER DEFAULT 1,
                emotional_state JSONB,
                user_model JSONB,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_messages INTEGER DEFAULT 0,
                key_milestones JSONB,
                notes TEXT
            )
        """)

    else:
        # ===================== SQLite =====================
        cur.execute("""
            CREATE TABLE IF NOT EXISTS key_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                convo_id TEXT NOT NULL,
                fact TEXT NOT NULL,
                importance INTEGER DEFAULT 5,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_recalled DATETIME,
                UNIQUE(convo_id, fact)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                convo_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database schema initialized successfully")


# ==================== RELATIONSHIP STATE HELPERS ====================

def get_relationship_state(convo_id: str):
    """Load relationship state from database."""
    conn = get_db_connection()
    if conn is None:
        return None
    cur = conn.cursor()
    try:
        if DATABASE_URL:  # PostgreSQL
            cur.execute("""
                SELECT user_id, convo_id, phase, relationship_level, 
                       emotional_state, user_model, last_interaction,
                       total_messages, key_milestones, notes
                FROM relationship_states 
                WHERE convo_id = %s
            """, (convo_id,))
        else:  # SQLite
            cur.execute("""
                SELECT user_id, convo_id, phase, relationship_level, 
                       emotional_state, user_model, last_interaction,
                       total_messages, key_milestones, notes
                FROM relationship_states 
                WHERE convo_id = ?
            """, (convo_id,))

        row = cur.fetchone()
        if row:
            return {
                "user_id": row[0],
                "convo_id": row[1],
                "phase": row[2],
                "relationship_level": row[3],
                "emotional_state": row[4],
                "user_model": row[5],
                "last_interaction": row[6],
                "total_messages": row[7],
                "key_milestones": row[8],
                "notes": row[9],
            }
        return None
    finally:
        cur.close()
        conn.close()


def upsert_relationship_state(state: dict):
    """Insert or update relationship state."""
    conn = get_db_connection()
    if conn is None:
        return False
    cur = conn.cursor()
    try:
        if DATABASE_URL:  # PostgreSQL
            cur.execute("""
                INSERT INTO relationship_states 
                (user_id, convo_id, phase, relationship_level, emotional_state, 
                 user_model, last_interaction, total_messages, key_milestones, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (convo_id) 
                DO UPDATE SET
                    phase = EXCLUDED.phase,
                    relationship_level = EXCLUDED.relationship_level,
                    emotional_state = EXCLUDED.emotional_state,
                    user_model = EXCLUDED.user_model,
                    last_interaction = EXCLUDED.last_interaction,
                    total_messages = EXCLUDED.total_messages,
                    key_milestones = EXCLUDED.key_milestones,
                    notes = EXCLUDED.notes
            """, (
                state.get("user_id"),
                state.get("convo_id"),
                state.get("phase", "early_flirt"),
                state.get("relationship_level", 1),
                json.dumps(state.get("emotional_state")) if state.get("emotional_state") else None,
                json.dumps(state.get("user_model")) if state.get("user_model") else None,
                state.get("last_interaction"),
                state.get("total_messages", 0),
                json.dumps(state.get("key_milestones")) if state.get("key_milestones") else None,
                state.get("notes")
            ))
        else:  # SQLite fallback
            cur.execute("""
                INSERT OR REPLACE INTO relationship_states 
                (user_id, convo_id, phase, relationship_level, emotional_state, 
                 user_model, last_interaction, total_messages, key_milestones, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.get("user_id"),
                state.get("convo_id"),
                state.get("phase", "early_flirt"),
                state.get("relationship_level", 1),
                json.dumps(state.get("emotional_state")) if state.get("emotional_state") else None,
                json.dumps(state.get("user_model")) if state.get("user_model") else None,
                state.get("last_interaction"),
                state.get("total_messages", 0),
                json.dumps(state.get("key_milestones")) if state.get("key_milestones") else None,
                state.get("notes")
            ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"upsert_relationship_state error: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


# Initialize tables when this module is imported
init_db()
