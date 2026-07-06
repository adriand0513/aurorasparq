# aurorasparq_brain/db/schema.py
"""
PostgreSQL schema + helper functions for Isabella's Second Brain.
"""

import psycopg2
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
    print("Initializing Second Brain database...")
    init_brain_db()
    print("Done.")
