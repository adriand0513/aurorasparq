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


# Initialize tables when this module is imported
init_db()
