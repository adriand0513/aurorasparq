# aurorasparq_brain/db/schema.py
"""
PostgreSQL schema + helper functions for Isabella's Second Brain.
"""

import psycopg2
import json
from psycopg2.extras import RealDictCursor
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_brain_db():
    """Initialize all Second Brain tables."""
    conn = get_db_connection()
    cur = conn.cursor()

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS narrative_memories (
            id SERIAL PRIMARY KEY,
            convo_id TEXT NOT NULL,
            moment_type TEXT,
            description TEXT NOT NULL,
            emotional_tag TEXT,
            importance INTEGER DEFAULT 5,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Second Brain tables initialized")


# ===================== HELPER FUNCTIONS USED BY state.py =====================

def get_relationship_state(convo_id: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM relationship_states WHERE convo_id = %s", (convo_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def upsert_relationship_state(state: dict):
    """Insert or update relationship state (fixed for PostgreSQL + json import)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO relationship_states (
                user_id, convo_id, phase, relationship_level, 
                emotional_state, user_model, last_interaction, 
                total_messages, key_milestones, notes, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(convo_id) DO UPDATE SET
                phase = excluded.phase,
                relationship_level = excluded.relationship_level,
                emotional_state = excluded.emotional_state,
                user_model = excluded.user_model,
                last_interaction = excluded.last_interaction,
                total_messages = excluded.total_messages,
                key_milestones = excluded.key_milestones,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
        """, (
            state["user_id"],
            state["convo_id"],
            state.get("phase", "early_flirt"),
            state.get("relationship_level", 1),
            json.dumps(state.get("emotional_state", {})),      # Now works
            json.dumps(state.get("user_model", {})),            # Now works
            state.get("last_interaction"),
            state.get("total_messages", 0),
            json.dumps(state.get("key_milestones", [])),        # Now works
            state.get("notes", "")
        ))
        
        conn.commit()
        logger.info(f"✅ RelationshipState saved for convo_id={state['convo_id']}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"upsert_relationship_state error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    print("Initializing Second Brain database...")
    init_brain_db()
    print("Done.")
