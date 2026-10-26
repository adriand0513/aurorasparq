# database.py
"""
Single PostgreSQL access point for the whole app.

Every module (auth, chat history, analytics, Second Brain) gets its
connection here, and every table is created here, once, at startup.
There is no SQLite fallback: production runs on PostgreSQL, so local
development should too (DATABASE_URL is required).
"""

import logging
from contextlib import contextmanager

import psycopg2

from config import DATABASE_URL

logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """Raised when PostgreSQL cannot be reached."""


def get_db_connection():
    """Open a new PostgreSQL connection or raise DatabaseUnavailable."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.Error as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        raise DatabaseUnavailable("Database is unavailable") from e


@contextmanager
def db_cursor(commit: bool = False):
    """
    Yield a cursor and always close the connection.
    With commit=True the transaction is committed on success
    and rolled back on any error.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


SCHEMA = [
    # ── Accounts ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL,
        full_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        subscription_tier TEXT DEFAULT 'free',
        stripe_customer_id TEXT,
        stripe_subscription_id TEXT,
        subscription_status TEXT DEFAULT 'inactive',
        subscription_expires_at TIMESTAMP
    )
    """,
    # Older deployments may predate these columns
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_tier TEXT DEFAULT 'free'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT DEFAULT 'inactive'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP",
    "CREATE INDEX IF NOT EXISTS idx_users_stripe_sub ON users(stripe_subscription_id)",
    # ── Chat history ────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS chat_history (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        convo_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS convo_id TEXT",
    "CREATE INDEX IF NOT EXISTS idx_chat_history_convo ON chat_history(convo_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_chat_history_user_day ON chat_history(user_id, timestamp)",
    # ── Analytics ───────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS analytics_events (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        event_type TEXT NOT NULL,
        convo_id TEXT,
        user_id INTEGER,
        metadata TEXT,
        duration_ms INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_analytics_time ON analytics_events(timestamp)",
    # ── Second Brain: facts ─────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS key_facts (
        id SERIAL PRIMARY KEY,
        convo_id TEXT NOT NULL,
        fact TEXT NOT NULL,
        importance INTEGER DEFAULT 5,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_recalled TIMESTAMP,
        UNIQUE(convo_id, fact)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_key_facts_convo ON key_facts(convo_id)",
    # ── Second Brain: running summary of older conversation ─
    """
    CREATE TABLE IF NOT EXISTS conversation_memory (
        convo_id TEXT PRIMARY KEY,
        summary TEXT NOT NULL DEFAULT '',
        last_message_id INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


def init_db():
    """Create every table the app uses. Safe to run on every startup."""
    with db_cursor(commit=True) as cur:
        for statement in SCHEMA:
            cur.execute(statement)
    logger.info("✅ Database schema ready")
