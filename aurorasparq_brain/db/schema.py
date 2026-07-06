# db/schema.py
"""
PostgreSQL schema for Isabella's Second Brain.
This file defines all tables needed for relationship modeling, memory, 
and the Reflection Engine. Uses the main app's PostgreSQL database.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from typing import Optional
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_db_connection():
    """Create a connection to PostgreSQL using the main app's DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)


def init_brain_db():   :
    """Initialize all tables required for Isabella's Second Brain in PostgreSQL."""
    conn = get_db_connection()
    cur = conn.cursor()

    # ===================== RELATIONSHIP STATES =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS relationship_states (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            convo_id TEXT NOT NULL UNIQUE,
            
            phase TEXT DEFAULT 'early_flirt',
            relationship_level INTEGER DEFAULT 1,
            
            emotional_state JSONB,
            user_model JSONB,
            
            last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_messages INTEGER DEFAULT 0,
            key_milestones JSONB,
            notes TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===================== KEY FACTS =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS key_facts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            convo_id TEXT,
            fact TEXT NOT NULL,
            importance INTEGER DEFAULT 5,
            category TEXT,
            last_recalled TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===================== NARRATIVE MEMORIES =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS narrative_memories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            convo_id TEXT,
            moment_type TEXT,
            description TEXT NOT NULL,
            emotional_impact INTEGER DEFAULT 5,
            importance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===================== CONVERSATION SUMMARIES =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            convo_id TEXT,
            summary TEXT NOT NULL,
            start_message_id INTEGER,
            end_message_id INTEGER,
            importance INTEGER DEFAULT 5,
            embedding JSONB,                    -- Changed from BLOB to JSONB (easier + future vector ready)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===================== REFLECTION LOGS =====================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reflection_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            convo_id TEXT NOT NULL,
            tier TEXT DEFAULT 'free',
            
            before_emotional_state JSONB,
            after_emotional_state JSONB,
            
            reasoning TEXT,
            emotional_changes JSONB,
            new_milestones JSONB,
            phase_change TEXT,
            internal_narrative TEXT,
            
            trigger_type TEXT,
            messages_since_last_reflection INTEGER,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database schema initialized successfully (PostgreSQL)")


def get_relationship_state(convo_id: str) -> Optional[dict]:
    """Fetch the current relationship state for a specific conversation."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT * FROM relationship_states 
        WHERE convo_id = %s
    """, (convo_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def upsert_relationship_state(state: dict):
    """Insert or update relationship state (used by the Reflection Engine)."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO relationship_states (
            user_id, convo_id, phase, relationship_level, 
            emotional_state, user_model, last_interaction, 
            total_messages, key_milestones, notes, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (convo_id) DO UPDATE SET
            phase = EXCLUDED.phase,
            relationship_level = EXCLUDED.relationship_level,
            emotional_state = EXCLUDED.emotional_state,
            user_model = EXCLUDED.user_model,
            last_interaction = EXCLUDED.last_interaction,
            total_messages = EXCLUDED.total_messages,
            key_milestones = EXCLUDED.key_milestones,
            notes = EXCLUDED.notes,
            updated_at = CURRENT_TIMESTAMP
    """, (
        state["user_id"],
        state["convo_id"],
        state.get("phase", "early_flirt"),
        state.get("relationship_level", 1),
        state.get("emotional_state"),
        state.get("user_model"),
        state.get("last_interaction"),
        state.get("total_messages", 0),
        state.get("key_milestones"),
        state.get("notes")
    ))
    
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    print("Initializing database schema (PostgreSQL)...")
    init_brain_db()
