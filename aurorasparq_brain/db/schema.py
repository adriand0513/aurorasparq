# aurorasparq_brain/db/schema.py
"""
PostgreSQL schema for Isabella's Second Brain.
"""

import psycopg2
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_brain_db():
    """Initialize all Second Brain tables in PostgreSQL."""
    conn = get_db_connection()
    cur = conn.cursor()

    # RELATIONSHIP STATES
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

    # REFLECTION LOGS
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

    # NARRATIVE MEMORIES
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
    logger.info("✅ Second Brain tables initialized in PostgreSQL")


if __name__ == "__main__":
    print("Initializing Second Brain database...")
    init_brain_db()
    print("Done.")
